"""Workflow rules and exact INR validation; no HTTP or persistence dependencies."""

from decimal import Decimal, InvalidOperation
import re


class ValidationError(ValueError):
    pass


class ConflictError(ValueError):
    pass


class PermissionError(ValueError):
    pass


PERSONAS = {
    "desk": {"name": "Meera Shah", "role": "desk", "label": "Front desk"},
    "tech-amit": {"name": "Amit Patel", "role": "technician", "label": "Technician"},
    "tech-neha": {"name": "Neha Desai", "role": "technician", "label": "Technician"},
    "customer": {"name": "Customer response", "role": "customer", "label": "Simulated customer"},
}
STATUSES = ("intake", "diagnosis", "awaiting_approval", "repair", "ready", "collected", "cancelled")
STATUS_LABELS = {
    "intake": "New intake", "diagnosis": "Diagnosis", "awaiting_approval": "Awaiting approval",
    "repair": "In repair", "ready": "Ready to collect", "collected": "Collected", "cancelled": "Cancelled",
}
CLOSED = {"collected", "cancelled"}


def text(value, name, maximum=200, required=True):
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be text.")
    value = value.strip()
    if (required and not value) or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ValidationError(f"{name} must contain {'1' if required else '0'}–{maximum} printable characters.")
    return value


def money(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 24:
        raise ValidationError(f"{name} must be an INR amount.")
    # Explicit decimal notation prevents tiny scientific values from silently
    # underflowing to zero when Decimal applies its arithmetic context.
    literal = str(value).strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", literal):
        raise ValidationError(f"{name} must use a plain amount with at most two decimal places.")
    try:
        number = Decimal(literal)
    except InvalidOperation as error:
        raise ValidationError(f"{name} must be an INR amount.") from error
    if not number.is_finite() or number < 0 or number > 100000 or number * 100 != (number * 100).to_integral_value():
        raise ValidationError(f"{name} must be ₹0–₹1,00,000 with at most two decimal places.")
    return int(number * 100)


def rupees(paise):
    return f"{Decimal(paise) / 100:.2f}"


def revision(value):
    if type(value) is not int or value < 1:
        raise ValidationError("A positive integer revision is required.")
    return value


def intake(data):
    if data.get("consent") is not True:
        raise ValidationError("Record the customer's permission to inspect the device.")
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
        raise ValidationError("An 8–80 character request ID is required.")
    return {
        "customer_name": text(data.get("customer_name"), "Customer name", 80),
        "customer_ref": text(data.get("customer_ref", ""), "Customer reference", 40, required=False),
        "device": text(data.get("device"), "Device", 100),
        "issue": text(data.get("issue"), "Reported issue", 500),
        "accessories": text(data.get("accessories", "None"), "Accessories", 200),
        "consent": True,
        "request_id": request_id,
    }


def transition(job, action, data, persona_id):
    """Return an explicit change set. SQLite applies this inside a write lock."""
    persona = PERSONAS[persona_id]
    if job["status"] in CLOSED:
        raise ConflictError("This ticket is closed; its history cannot be changed.")

    def role(required):
        if persona["role"] != required:
            raise PermissionError(f"This action requires the {required} demo persona.")

    def state(*allowed):
        if job["status"] not in allowed:
            raise ConflictError("This action is not available at the current workflow stage.")

    def owner():
        role("technician")
        if job["assigned_to"] != persona_id:
            raise PermissionError("Only the assigned technician can change this repair.")

    if action == "claim":
        role("technician")
        state("intake")
        if job["assigned_to"]:
            raise ConflictError("Another technician has already claimed this ticket.")
        return {"assigned_to": persona_id, "status": "diagnosis"}, {}
    if action == "estimate":
        owner()
        state("diagnosis", "awaiting_approval")
        diagnosis = text(data.get("diagnosis"), "Diagnosis", 600)
        parts = money(data.get("parts"), "Parts cost")
        labour = money(data.get("labour"), "Labour cost")
        if not 0 < parts + labour <= 10000000:
            raise ValidationError("The estimate total must be greater than zero and at most ₹1,00,000.")
        changes = {"diagnosis": diagnosis, "parts_paise": parts, "labour_paise": labour, "status": "awaiting_approval"}
        return changes, {"estimate_total": rupees(parts + labour)}
    if action in {"approve", "decline"}:
        role("customer")
        state("awaiting_approval")
        if data.get("confirmed") is not True:
            raise ValidationError("Confirm that this is a simulated customer decision.")
        changes = {"status": "repair" if action == "approve" else "cancelled", "customer_decision": action}
        details = {"simulated": True, "estimate_total": rupees(job["parts_paise"] + job["labour_paise"])}
        if action == "decline":
            changes["cancel_reason"] = text(data.get("reason"), "Decline reason", 300)
        return changes, details
    if action == "ready":
        owner()
        state("repair")
        if data.get("tested") is not True:
            raise ValidationError("Confirm the functional check before marking the device ready.")
        return {"status": "ready", "completion_note": text(data.get("completion_note"), "Completion note", 600)}, {"functional_check": True}
    if action == "collect":
        role("desk")
        state("ready")
        if data.get("confirmed") is not True:
            raise ValidationError("Confirm the handover with the customer.")
        name = text(data.get("collected_by"), "Collected by", 80)
        return {"status": "collected", "collected_by": name}, {"handover_confirmed": True, "payment_recorded": False}
    if action == "cancel":
        role("desk")
        state("intake", "diagnosis", "awaiting_approval")
        return {"status": "cancelled", "cancel_reason": text(data.get("reason"), "Cancellation reason", 300)}, {}
    raise ValidationError("Unknown workflow action.")
