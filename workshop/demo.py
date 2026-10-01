"""Original fictional tickets. No real customers, contact data, or remote services."""

from . import db


TICKETS = [
    {"customer_name": "Riya Patel", "customer_ref": "DEMO-RIYA", "device": "Samsung Galaxy M34", "issue": "Charging cable connects intermittently; phone only charges at an angle.", "accessories": "Blue case; no charger", "stage": "intake"},
    {"customer_name": "Dhruv Shah", "customer_ref": "DEMO-DHRUV", "device": "OnePlus Nord CE 3", "issue": "Display cracked after a drop. Touch works but flickers near the bottom.", "accessories": "Black case", "stage": "awaiting_approval", "technician": "tech-amit", "diagnosis": "Display assembly damaged. Replacement assembly and adhesive required; data does not need to be erased.", "parts": "2450.00", "labour": "450.00"},
    {"customer_name": "Kavya Desai", "customer_ref": "DEMO-KAVYA", "device": "Redmi Note 12", "issue": "Call audio is very quiet even at maximum volume.", "accessories": "None", "stage": "repair", "technician": "tech-neha", "diagnosis": "Earpiece speaker mesh cleaned; speaker remains weak and requires replacement.", "parts": "380.00", "labour": "250.00"},
    {"customer_name": "Arjun Mehta", "customer_ref": "DEMO-ARJUN", "device": "Motorola G54", "issue": "Battery drains quickly and phone heats up during light use.", "accessories": "Clear case", "stage": "ready", "technician": "tech-amit", "diagnosis": "Battery health below expected range. Replace battery and inspect charging behaviour.", "parts": "950.00", "labour": "350.00"},
    {"customer_name": "Ishita Joshi", "customer_ref": "DEMO-ISHITA", "device": "Realme 10", "issue": "Rear camera lens cover is cracked.", "accessories": "None", "stage": "collected", "technician": "tech-neha", "diagnosis": "Replace external camera lens cover; camera sensor and focus tested normally.", "parts": "180.00", "labour": "200.00"},
]


def seed(path):
    database = db.connect(path)
    try:
        if database.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]:
            return
        for index, sample in enumerate(TICKETS):
            details = {key: value for key, value in sample.items() if key in {"customer_name", "customer_ref", "device", "issue", "accessories"}}
            details.update(consent=True, request_id=f"fictional-intake-{index + 1}")
            job, _ = db.create(database, details, "desk")
            if sample["stage"] == "intake":
                continue
            technician = sample["technician"]
            job = db.act(database, job["id"], "claim", {"revision": job["revision"]}, technician)
            job = db.act(database, job["id"], "estimate", {"revision": job["revision"], "diagnosis": sample["diagnosis"], "parts": sample["parts"], "labour": sample["labour"]}, technician)
            if sample["stage"] == "awaiting_approval":
                continue
            job = db.act(database, job["id"], "approve", {"revision": job["revision"], "confirmed": True}, "customer")
            if sample["stage"] == "repair":
                continue
            job = db.act(database, job["id"], "ready", {"revision": job["revision"], "tested": True, "completion_note": "Replacement completed. Charging, audio, touch and camera functions checked; accessories retained."}, technician)
            if sample["stage"] == "collected":
                db.act(database, job["id"], "collect", {"revision": job["revision"], "confirmed": True, "collected_by": sample["customer_name"]}, "desk")
    finally:
        database.close()
