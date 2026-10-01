import pytest

from conftest import act, estimate, persona
from workshop.domain import ValidationError, money


@pytest.mark.parametrize("value", [True, None, [], {}, "NaN", "Infinity", "-1", "0.001", "100000.01", "9" * 30, "banana", "1e-999999999"])
def test_invalid_money(value):
    with pytest.raises(ValidationError):
        money(value, "Cost")


@pytest.mark.parametrize("value,expected", [("0", 0), ("0.01", 1), ("480.25", 48025), ("100000", 10000000), (10.5, 1050)])
def test_exact_rupee_conversion(value, expected):
    assert money(value, "Cost") == expected


@pytest.mark.parametrize("field,value", [
    ("customer_name", ""), ("customer_name", "x" * 81), ("customer_name", 1),
    ("customer_ref", "x" * 41), ("device", "x" * 101), ("issue", "x" * 501),
    ("accessories", "x" * 201), ("issue", "Invalid\x00control character"),
    ("consent", False), ("consent", "true"), ("request_id", "short"), ("request_id", "space not allowed"),
])
def test_intake_validation_rejects_bad_inputs(client, headers, intake_data, field, value):
    response = client.post("/api/jobs", json={**intake_data, field: value}, headers=headers)
    assert response.status_code == 422
    assert client.get("/api/jobs?status=all").json["summary"]["total"] == 0


def test_missing_consent_and_missing_request_id(client, headers, intake_data):
    for field in ("consent", "request_id"):
        data = {key: value for key, value in intake_data.items() if key != field}
        assert client.post("/api/jobs", json=data, headers=headers).status_code == 422


def test_estimate_limits_and_owner_rules(client, headers, job):
    persona(client, headers, "tech-amit")
    job = act(client, headers, job, "claim").json["job"]
    for parts, labour, diagnosis in [("0", "0", "No repair"), ("100000", "1", "Too much"), ("-1", "100", "Invalid"), ("1", "1", "")]:
        assert act(client, headers, job, "estimate", parts=parts, labour=labour, diagnosis=diagnosis).status_code == 422
    assert client.get(f"/api/jobs/{job['id']}").json["job"]["revision"] == 2


def test_csrf_token_and_same_origin_are_required(client, headers, intake_data):
    assert client.post("/api/jobs", json=intake_data).status_code == 403
    assert client.post("/api/jobs", json=intake_data, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/jobs", json=intake_data, headers={"X-CSRF-Token": "invalid✕"}).status_code == 403
    foreign = {**headers, "Origin": "https://other.example"}
    assert client.post("/api/jobs", json=intake_data, headers=foreign).status_code == 403
    same = {**headers, "Origin": "http://localhost"}
    assert client.post("/api/jobs", json=intake_data, headers=same).status_code == 201


def test_another_browser_cannot_reuse_csrf_token(app, headers, intake_data):
    second = app.test_client()
    second.get("/api/bootstrap")
    assert second.post("/api/jobs", json=intake_data, headers=headers).status_code == 403


def test_host_headers_response_headers_cookie_isolation_and_no_auth_claim(client):
    response = client.get("/api/bootstrap")
    assert response.json["simulated_personas"] is True
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith("repair_session=")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400


def test_malformed_nonobject_oversized_and_nonjson_requests(client, headers):
    assert client.post("/api/jobs", json=[], headers=headers).status_code == 422
    assert client.post("/api/jobs", data="{invalid", content_type="application/json", headers=headers).status_code == 400
    assert client.post("/api/jobs", data="x", headers=headers).status_code == 415
    assert client.post("/api/jobs", data='{"issue":"' + "x" * 34000 + '"}', content_type="application/json", headers=headers).status_code == 413


def test_invalid_filters_personas_and_missing_records(client, headers):
    assert client.get("/api/jobs?status=unknown").status_code == 422
    assert client.get("/api/jobs?q=" + "a" * 101).status_code == 422
    assert client.post("/api/persona", json={"persona": "admin"}, headers=headers).status_code == 422
    assert client.post("/api/persona", json={"persona": []}, headers=headers).status_code == 422
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.post("/api/jobs/missing/actions/claim", json={"revision": 1}, headers=headers).status_code == 404
    assert client.get("/not-a-route").status_code == 404


def test_search_is_literal_and_does_not_expand_sql(client, headers, intake_data):
    client.post("/api/jobs", json=intake_data, headers=headers)
    assert len(client.get("/api/jobs?q=DEV").json["jobs"]) == 1
    assert len(client.get("/api/jobs?q=Samsung").json["jobs"]) == 1
    assert client.get("/api/jobs?q=%25").json["jobs"] == []
    assert client.get("/api/jobs?q=' OR 1=1 --").json["jobs"] == []


def test_user_markup_stays_data_in_api_and_is_not_in_initial_html(client, headers, intake_data):
    markup = '<img src=x onerror=alert(1)>'
    created = client.post("/api/jobs", json={**intake_data, "customer_name": markup}, headers=headers).json["job"]
    assert created["customer_name"] == markup
    assert markup.encode() not in client.get("/").data
    assert b"Persona switching simulates roles; it is not a login" in client.get("/").data
    assert "request_hash" not in created and "request_id" not in created


def test_multiline_service_notes_are_preserved_but_names_stay_single_line(client, headers, intake_data):
    response = client.post("/api/jobs", json={**intake_data, "issue": "Loose port.\r\nCharging disconnects."}, headers=headers)
    assert response.status_code == 201
    assert response.json["job"]["issue"] == "Loose port.\nCharging disconnects."
    persona(client, headers, "tech-amit")
    job = act(client, headers, response.json["job"], "claim").json["job"]
    job = act(client, headers, job, "estimate", diagnosis="Port damaged.\nReplace assembly.", parts="480", labour="210").json["job"]
    assert job["diagnosis"] == "Port damaged.\nReplace assembly."
    persona(client, headers, "desk")
    bad_name = {**intake_data, "request_id": "test-multiline-name", "customer_name": "Dev\nPatel"}
    assert client.post("/api/jobs", json=bad_name, headers=headers).status_code == 422
