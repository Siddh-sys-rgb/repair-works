import pytest

from workshop import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "local-test-secret", "SEED_DEMO": False})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def headers(client):
    token = client.get("/api/bootstrap").json["csrf"]
    return {"X-CSRF-Token": token}


@pytest.fixture
def intake_data():
    return {
        "customer_name": "Dev Patel", "customer_ref": "DEMO-DEV", "device": "Samsung Galaxy A35",
        "issue": "Charging port is loose", "accessories": "Clear case", "consent": True,
        "request_id": "test-intake-001",
    }


@pytest.fixture
def job(client, headers, intake_data):
    response = client.post("/api/jobs", json=intake_data, headers=headers)
    assert response.status_code == 201
    return response.json["job"]


def persona(client, headers, identity):
    response = client.post("/api/persona", json={"persona": identity}, headers=headers)
    assert response.status_code == 200


def act(client, headers, job, action, **details):
    return client.post(f"/api/jobs/{job['id']}/actions/{action}", json={"revision": job["revision"], **details}, headers=headers)


def estimate(client, headers, job):
    persona(client, headers, "tech-amit")
    job = act(client, headers, job, "claim").json["job"]
    return act(client, headers, job, "estimate", diagnosis="Replace charging port assembly", parts="480.25", labour="210.50").json["job"]
