from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

from workshop import create_app, db
from workshop.domain import ConflictError


def test_two_technicians_claiming_same_revision_have_one_winner(app, job):
    barrier = threading.Barrier(2)

    def claim(identity):
        connection = db.connect(app.config["DATABASE"])
        try:
            barrier.wait(timeout=5)
            try:
                result = db.act(connection, job["id"], "claim", {"revision": 1}, identity)
                return "claimed", result["assigned_to"]
            except ConflictError:
                return "conflict", identity
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["tech-amit", "tech-neha"]))
    assert sorted(result[0] for result in results) == ["claimed", "conflict"]
    connection = db.connect(app.config["DATABASE"])
    try:
        final = db.get_job(connection, job["id"])
        assert final["revision"] == 2
        assert final["assigned_to"] == next(identity for outcome, identity in results if outcome == "claimed")
        assert [event["action"] for event in db.events(connection, job["id"])] == ["claim", "intake"]
    finally:
        connection.close()


def test_two_identical_intake_requests_commit_only_one_ticket(app, intake_data):
    barrier = threading.Barrier(2)

    def create(_):
        connection = db.connect(app.config["DATABASE"])
        try:
            barrier.wait(timeout=5)
            return db.create(connection, intake_data, "desk")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert results[0][0]["id"] == results[1][0]["id"]
    assert sorted(created for _, created in results) == [False, True]


def test_database_itself_rejects_unapproved_repair_even_with_null_decision(app, job):
    connection = db.connect(app.config["DATABASE"])
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE jobs SET status='repair', assigned_to='tech-amit', customer_decision=NULL WHERE id=?", (job["id"],))
        connection.rollback()
        assert db.get_job(connection, job["id"])["status"] == "intake"
    finally:
        connection.close()


def test_database_itself_rejects_unassigned_diagnosis_and_negative_cost(app, job):
    connection = db.connect(app.config["DATABASE"])
    try:
        for statement in ["UPDATE jobs SET status='diagnosis' WHERE id=?", "UPDATE jobs SET parts_paise=-1 WHERE id=?"]:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement, (job["id"],))
            connection.rollback()
    finally:
        connection.close()


def test_failed_event_insert_rolls_back_job_transition(app, job):
    connection = db.connect(app.config["DATABASE"])
    try:
        connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'simulated disk write failure'); END")
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.act(connection, job["id"], "claim", {"revision": 1}, "tech-amit")
        assert db.get_job(connection, job["id"])["status"] == "intake"
        assert len(db.events(connection, job["id"])) == 1
    finally:
        connection.close()


def test_seed_is_repeat_safe_and_empty_mode_stays_empty(tmp_path):
    config = {"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"}
    first = create_app(config).test_client().get("/api/jobs?status=all").json
    assert first["summary"]["total"] == 5
    assert first["summary"]["counts"]["intake"] == 1
    assert first["summary"]["counts"]["awaiting_approval"] == 1
    assert first["summary"]["approved_estimates"] == "2310.00"
    second = create_app(config).test_client().get("/api/jobs?status=all").json
    assert second == first
    empty = create_app({**config, "DATA_DIR": tmp_path / "empty", "SEED_DEMO": False})
    assert empty.test_client().get("/api/jobs?status=all").json["summary"]["total"] == 0


def test_secret_key_and_session_persona_persist_across_factory_restart(tmp_path):
    config = {"DATA_DIR": tmp_path, "SEED_DEMO": False}
    first = create_app(config)
    client = first.test_client()
    headers = {"X-CSRF-Token": client.get("/api/bootstrap").json["csrf"]}
    client.post("/api/persona", json={"persona": "tech-neha"}, headers=headers)
    cookie = client.get_cookie("repair_session").value
    second = create_app(config)
    assert first.config["SECRET_KEY"] == second.config["SECRET_KEY"]
    assert (tmp_path / "session.key").stat().st_mode & 0o777 == 0o600
    restart_client = second.test_client()
    restart_client.set_cookie("repair_session", cookie)
    assert restart_client.get("/api/bootstrap").json["persona"] == "tech-neha"


def test_health_checks_database_and_home_loads(client):
    assert client.get("/api/health").json["status"] == "ok"
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
