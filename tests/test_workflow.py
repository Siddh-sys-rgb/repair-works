import pytest

from conftest import act, estimate, persona


def test_full_workflow_requires_correct_personas_consent_and_check(client, headers, job):
    assert job["status"] == "intake"
    job = estimate(client, headers, job)
    assert job["status"] == "awaiting_approval"
    assert job["estimate_total"] == "690.75"
    assert act(client, headers, job, "ready", completion_note="Fixed", tested=True).status_code == 409
    assert act(client, headers, job, "approve", confirmed=True).status_code == 403
    persona(client, headers, "customer")
    assert act(client, headers, job, "approve", confirmed=False).status_code == 422
    job = act(client, headers, job, "approve", confirmed=True).json["job"]
    assert job["status"] == "repair"
    persona(client, headers, "tech-neha")
    assert act(client, headers, job, "ready", tested=True, completion_note="Fixed").status_code == 403
    persona(client, headers, "tech-amit")
    assert act(client, headers, job, "ready", tested=False, completion_note="Fixed").status_code == 422
    job = act(client, headers, job, "ready", tested=True, completion_note="Port replaced; charging tested").json["job"]
    assert job["status"] == "ready"
    assert act(client, headers, job, "collect", confirmed=True, collected_by="Dev Patel").status_code == 403
    persona(client, headers, "desk")
    assert act(client, headers, job, "collect", confirmed=False, collected_by="Dev Patel").status_code == 422
    job = act(client, headers, job, "collect", confirmed=True, collected_by="Dev Patel").json["job"]
    assert job["status"] == "collected"
    assert job["revision"] == 6
    detail = client.get(f"/api/jobs/{job['id']}").json
    assert [event["action"] for event in detail["events"]] == ["collect", "ready", "approve", "estimate", "claim", "intake"]
    assert detail["events"][2]["details"]["simulated"] is True
    assert detail["events"][2]["actor"] == "Dev Patel (simulated response)"
    assert detail["events"][0]["details"]["payment_recorded"] is False
    assert act(client, headers, job, "cancel", reason="Changed mind").status_code == 409
    assert client.get("/api/jobs?status=active").json["jobs"] == []
    summary = client.get("/api/jobs?status=all").json["summary"]
    assert summary["counts"]["collected"] == 1
    assert summary["approved_estimates"] == "690.75"


def test_revised_quote_invalidates_customer_old_revision(client, headers, job):
    old = estimate(client, headers, job)
    updated = act(client, headers, old, "estimate", diagnosis="Port and flex cable replacement", parts="500", labour="250").json["job"]
    persona(client, headers, "customer")
    assert act(client, headers, old, "approve", confirmed=True).status_code == 409
    current = act(client, headers, updated, "approve", confirmed=True).json["job"]
    assert current["estimate_total"] == "750.00"
    persona(client, headers, "tech-amit")
    assert act(client, headers, current, "estimate", diagnosis="Increase price", parts="999", labour="250").status_code == 409


def test_customer_decline_records_reason_and_closes_ticket(client, headers, job):
    job = estimate(client, headers, job)
    persona(client, headers, "customer")
    assert act(client, headers, job, "decline", confirmed=True, reason="").status_code == 422
    job = act(client, headers, job, "decline", confirmed=True, reason="Customer prefers a replacement phone").json["job"]
    assert job["status"] == "cancelled"
    assert job["customer_decision"] == "decline"
    assert job["cancel_reason"] == "Customer prefers a replacement phone"
    assert client.get("/api/jobs?status=all").json["summary"]["approved_estimates"] == "0.00"
    assert act(client, headers, job, "approve", confirmed=True).status_code == 409


@pytest.mark.parametrize("stage", ["intake", "diagnosis", "awaiting_approval"])
def test_front_desk_can_cancel_only_before_repair(client, headers, job, stage):
    if stage == "diagnosis":
        persona(client, headers, "tech-amit")
        job = act(client, headers, job, "claim").json["job"]
    elif stage == "awaiting_approval":
        job = estimate(client, headers, job)
    persona(client, headers, "desk")
    job = act(client, headers, job, "cancel", reason="Customer collected without repair").json["job"]
    assert job["status"] == "cancelled"
    assert act(client, headers, job, "claim").status_code == 409


def test_active_repair_cannot_be_cancelled_or_collected(client, headers, job):
    job = estimate(client, headers, job)
    persona(client, headers, "customer")
    job = act(client, headers, job, "approve", confirmed=True).json["job"]
    persona(client, headers, "desk")
    assert act(client, headers, job, "cancel", reason="Skip steps").status_code == 409
    assert act(client, headers, job, "collect", confirmed=True, collected_by="Dev").status_code == 409


def test_technician_cannot_take_over_assigned_ticket(client, headers, job):
    persona(client, headers, "tech-amit")
    claimed = act(client, headers, job, "claim").json["job"]
    persona(client, headers, "tech-neha")
    assert act(client, headers, job, "claim").status_code == 409
    assert act(client, headers, claimed, "claim").status_code == 409
    assert act(client, headers, claimed, "estimate", diagnosis="Forged", parts="1", labour="1").status_code == 403
    assert client.get(f"/api/jobs/{job['id']}").json["job"]["assigned_to"] == "tech-amit"


@pytest.mark.parametrize("identity", ["tech-amit", "tech-neha", "customer"])
def test_only_front_desk_creates_intake(client, headers, intake_data, identity):
    persona(client, headers, identity)
    assert client.post("/api/jobs", json=intake_data, headers=headers).status_code == 403


def test_failed_transition_preserves_revision_and_audit_history(client, headers, job):
    before = client.get(f"/api/jobs/{job['id']}").json
    assert act(client, headers, job, "unknown").status_code == 422
    after = client.get(f"/api/jobs/{job['id']}").json
    assert before == after


def test_create_retries_return_same_ticket_but_changed_body_conflicts(client, headers, intake_data):
    first = client.post("/api/jobs", json=intake_data, headers=headers)
    retry = client.post("/api/jobs", json=intake_data, headers=headers)
    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json["created"] is False
    assert first.json["job"]["id"] == retry.json["job"]["id"]
    changed = {**intake_data, "issue": "Different issue"}
    assert client.post("/api/jobs", json=changed, headers=headers).status_code == 409
    detail = client.get(f"/api/jobs/{first.json['job']['id']}").json
    assert len(detail["events"]) == 1


@pytest.mark.parametrize("revision", [None, 0, -1, True, "1", 1.1])
def test_revisions_are_required_positive_integers(client, headers, job, revision):
    persona(client, headers, "tech-amit")
    assert act(client, headers, {**job, "revision": revision}, "claim").status_code == 422


def test_actor_and_price_cannot_be_spoofed_via_extra_fields(client, headers, job):
    persona(client, headers, "tech-neha")
    job = act(client, headers, job, "claim", assigned_to="tech-amit", status="collected", actor="Meera Shah").json["job"]
    assert job["assigned_to"] == "tech-neha"
    assert job["status"] == "diagnosis"
    history = client.get(f"/api/jobs/{job['id']}").json["events"]
    assert history[0]["actor"] == "Neha Desai"
