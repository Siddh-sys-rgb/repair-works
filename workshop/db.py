"""SQLite transactions keep assignment, job versions, and audit events consistent."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from .domain import ConflictError, PERSONAS, PermissionError, STATUS_LABELS, intake, revision, rupees, transition


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def connect(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as database:
        database.execute("PRAGMA journal_mode = WAL")
        database.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                ticket TEXT NOT NULL UNIQUE,
                request_id TEXT NOT NULL UNIQUE,
                request_hash TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                customer_ref TEXT NOT NULL DEFAULT '',
                device TEXT NOT NULL,
                issue TEXT NOT NULL,
                accessories TEXT NOT NULL,
                consent INTEGER NOT NULL CHECK (consent = 1),
                status TEXT NOT NULL DEFAULT 'intake' CHECK (status IN ('intake','diagnosis','awaiting_approval','repair','ready','collected','cancelled')),
                assigned_to TEXT CHECK (assigned_to IN ('tech-amit','tech-neha')),
                diagnosis TEXT NOT NULL DEFAULT '',
                parts_paise INTEGER NOT NULL DEFAULT 0 CHECK (parts_paise >= 0),
                labour_paise INTEGER NOT NULL DEFAULT 0 CHECK (labour_paise >= 0),
                customer_decision TEXT CHECK (customer_decision IN ('approve','decline')),
                completion_note TEXT NOT NULL DEFAULT '',
                collected_by TEXT NOT NULL DEFAULT '',
                cancel_reason TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (status IN ('intake','cancelled') OR assigned_to IS NOT NULL),
                CHECK (status NOT IN ('repair','ready','collected') OR customer_decision = 'approve')
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id),
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                revision INTEGER NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS events_job ON events(job_id, id);
        """)


def serialize(row):
    job = dict(row)
    job.pop("request_hash", None)
    job.pop("request_id", None)
    job["consent"] = bool(job["consent"])
    job["status_label"] = STATUS_LABELS[job["status"]]
    job["assigned_name"] = PERSONAS[job["assigned_to"]]["name"] if job["assigned_to"] else None
    job["parts"] = rupees(job["parts_paise"])
    job["labour"] = rupees(job["labour_paise"])
    job["estimate_total"] = rupees(job["parts_paise"] + job["labour_paise"])
    return job


def get_job(database, job_id):
    job = database.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise LookupError("This repair ticket does not exist.")
    return serialize(job)


def create(database, data, persona_id):
    if PERSONAS[persona_id]["role"] != "desk":
        raise PermissionError("Only the front desk demo persona can create a ticket.")
    values = intake(data)
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    database.execute("BEGIN IMMEDIATE")
    try:
        existing = database.execute("SELECT * FROM jobs WHERE request_id = ?", (values["request_id"],)).fetchone()
        if existing:
            if existing["request_hash"] != fingerprint:
                raise ConflictError("This request ID was already used for different intake details.")
            database.commit()
            return serialize(existing), False
        job_id = uuid.uuid4().hex
        sequence = database.execute("SELECT COALESCE(MAX(rowid), 0) + 1 FROM jobs").fetchone()[0]
        timestamp = now()
        database.execute("""
            INSERT INTO jobs (id, ticket, request_id, request_hash, customer_name, customer_ref,
                              device, issue, accessories, consent, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (job_id, f"RW-{sequence:04d}", values["request_id"], fingerprint,
              values["customer_name"], values["customer_ref"], values["device"], values["issue"],
              values["accessories"], timestamp, timestamp))
        database.execute("""
            INSERT INTO events (job_id, action, actor, from_status, to_status, revision, details, created_at)
            VALUES (?, 'intake', ?, NULL, 'intake', 1, ?, ?)
        """, (job_id, PERSONAS[persona_id]["name"], json.dumps({"inspection_consent": True, "accessories": values["accessories"]}), timestamp))
        database.commit()
        return get_job(database, job_id), True
    except Exception:
        database.rollback()
        raise


def act(database, job_id, action, data, persona_id):
    expected_revision = revision(data.get("revision"))
    database.execute("BEGIN IMMEDIATE")
    try:
        stored = database.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if stored is None:
            raise LookupError("This repair ticket does not exist.")
        job = dict(stored)
        if job["revision"] != expected_revision:
            raise ConflictError("This ticket changed in another session. Reload it before trying again.")
        changes, details = transition(job, action, data, persona_id)
        new_revision = expected_revision + 1
        timestamp = now()
        changes.update(revision=new_revision, updated_at=timestamp)
        # Column names are exclusively from transition(), never from incoming JSON.
        assignments = ", ".join(f"{column} = ?" for column in changes)
        changed = database.execute(f"UPDATE jobs SET {assignments} WHERE id = ? AND revision = ?",
                                   (*changes.values(), job_id, expected_revision)).rowcount
        if changed != 1:
            raise ConflictError("This ticket changed in another session.")
        actor = PERSONAS[persona_id]["name"]
        if persona_id == "customer":
            actor = f"{job['customer_name']} (simulated response)"
        database.execute("""
            INSERT INTO events (job_id, action, actor, from_status, to_status, revision, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_id, action, actor, job["status"], changes.get("status", job["status"]),
              new_revision, json.dumps(details), timestamp))
        database.commit()
        return get_job(database, job_id)
    except Exception:
        database.rollback()
        raise


def events(database, job_id):
    get_job(database, job_id)
    records = database.execute("SELECT * FROM events WHERE job_id = ? ORDER BY id DESC", (job_id,)).fetchall()
    return [{**dict(record), "details": json.loads(record["details"])} for record in records]
