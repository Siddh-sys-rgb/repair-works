"""Local-only Flask application factory and JSON boundary."""

import hmac
import os
from pathlib import Path
import secrets

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from . import db
from .domain import ConflictError, PERSONAS, PermissionError, STATUSES, ValidationError


def create_app(config=None):
    root = Path(__file__).resolve().parent.parent
    config = config or {}
    instance = Path(config.get("DATA_DIR", root / "instance")).resolve()
    app = Flask(__name__, instance_path=str(instance))
    app.config.update(
        DATABASE=str(instance / "workshop.sqlite3"),
        DATA_DIR=str(instance),
        MAX_CONTENT_LENGTH=32 * 1024,
        SESSION_COOKIE_NAME="repair_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        TRUSTED_HOSTS=["127.0.0.1", "localhost", "[::1]"],
        SEED_DEMO=True,
    )
    app.config.update(config)
    instance.mkdir(parents=True, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        secret_file = instance / "session.key"
        try:
            descriptor = os.open(secret_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w") as destination:
                destination.write(secrets.token_hex(32))
        app.config["SECRET_KEY"] = secret_file.read_text()
    db.initialize(app.config["DATABASE"])
    if app.config["SEED_DEMO"]:
        from .demo import seed
        seed(app.config["DATABASE"])

    def database():
        if "database" not in g:
            g.database = db.connect(app.config["DATABASE"])
        return g.database

    def actor():
        return session.get("persona", "desk")

    def payload():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValidationError("Send a JSON object.")
        return data

    @app.teardown_appcontext
    def close_database(_error):
        connection = g.pop("database", None)
        if connection is not None:
            connection.close()

    @app.before_request
    def protect_mutations():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            return jsonify(error="Cross-origin changes are not allowed."), 403
        token = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf", "")
        if not token or not token.isascii() or not expected or not hmac.compare_digest(token, expected):
            return jsonify(error="Reload this page to obtain a valid CSRF token."), 403
        return None

    @app.after_request
    def headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "font-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException):
            status, message = error.code, error.description
        elif isinstance(error, ValidationError):
            status, message = 422, str(error)
        elif isinstance(error, ConflictError):
            status, message = 409, str(error)
        elif isinstance(error, PermissionError):
            status, message = 403, str(error)
        elif isinstance(error, LookupError):
            status, message = 404, str(error)
        else:
            app.logger.exception("Unexpected workshop error")
            status, message = 500, "Something went wrong. Your ticket has not been changed."
        return jsonify(error=message), status

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        database().execute("SELECT 1").fetchone()
        return jsonify(status="ok", app="Repair Works", mode="local demo", database="sqlite")

    @app.get("/api/bootstrap")
    def bootstrap():
        session.setdefault("csrf", secrets.token_hex(24))
        return jsonify(
            csrf=session["csrf"], persona=actor(), personas=PERSONAS,
            shop={"name": "Repair Works", "location": "Navrangpura, Ahmedabad", "owner": "Meera Shah"},
            simulated_personas=True,
        )

    @app.post("/api/persona")
    def persona():
        identity = payload().get("persona")
        if not isinstance(identity, str) or identity not in PERSONAS:
            raise ValidationError("Choose a known demo persona.")
        session["persona"] = identity
        return jsonify(persona=identity, profile=PERSONAS[identity], simulated=True)

    @app.get("/api/jobs")
    def jobs():
        status = request.args.get("status", "active")
        if status not in {*STATUSES, "active", "all"}:
            raise ValidationError("Unknown status filter.")
        search = request.args.get("q", "").strip()
        if len(search) > 100:
            raise ValidationError("Search must be 100 characters or fewer.")
        query, parameters = "SELECT * FROM jobs", []
        conditions = []
        if status == "active":
            conditions.append("status NOT IN ('collected','cancelled')")
        elif status != "all":
            conditions.append("status = ?")
            parameters.append(status)
        if search:
            conditions.append("(instr(lower(customer_name), lower(?)) > 0 OR instr(lower(device), lower(?)) > 0 OR instr(lower(ticket), lower(?)) > 0)")
            parameters.extend([search] * 3)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        rows = database().execute(query + " ORDER BY rowid DESC", parameters).fetchall()
        all_jobs = database().execute("SELECT status, parts_paise, labour_paise FROM jobs").fetchall()
        counts = {status: sum(row["status"] == status for row in all_jobs) for status in STATUSES}
        approved = sum(row["parts_paise"] + row["labour_paise"] for row in all_jobs if row["status"] in {"repair", "ready", "collected"})
        return jsonify(jobs=[db.serialize(row) for row in rows], summary={
            "counts": counts, "active": len(all_jobs) - counts["collected"] - counts["cancelled"],
            "approved_estimates": db.rupees(approved), "total": len(all_jobs),
        })

    @app.post("/api/jobs")
    def create_job():
        job, created = db.create(database(), payload(), actor())
        return jsonify(job=job, created=created), 201 if created else 200

    @app.get("/api/jobs/<job_id>")
    def detail(job_id):
        return jsonify(job=db.get_job(database(), job_id), events=db.events(database(), job_id))

    @app.post("/api/jobs/<job_id>/actions/<action>")
    def action(job_id, action):
        return jsonify(job=db.act(database(), job_id, action, payload(), actor()))

    return app
