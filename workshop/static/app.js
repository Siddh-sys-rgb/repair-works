"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));
const inr = (amount) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(Number(amount));
const stages = [
  ["intake", "New intake", "Fresh tickets land here."],
  ["diagnosis", "Diagnosis", "A closer look comes first."],
  ["awaiting_approval", "Approval", "Waiting for a clear yes."],
  ["repair", "In repair", "Approved work in progress."],
  ["ready", "Ready", "Checked and ready to go."],
];
const actionLabels = {
  intake: "Device received", claim: "Technician claimed ticket", estimate: "Estimate recorded",
  approve: "Estimate approved", decline: "Estimate declined", ready: "Functional check complete",
  collect: "Device handed over", cancel: "Ticket cancelled",
};
const state = { csrf: "", persona: "desk", personas: {}, job: null, busy: false, routeVersion: 0 };
let toastTimeout;
let searchTimeout;

async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = state.csrf;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body.error || "The request could not be completed.");
    error.status = response.status;
    throw error;
  }
  return body;
}

function toast(message) {
  clearTimeout(toastTimeout);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimeout = setTimeout(() => { $("#toast").hidden = true; }, 4500);
}

function card(job) {
  const initials = job.assigned_name ? job.assigned_name.split(" ").map((part) => part[0]).join("") : "—";
  return `<a class="ticket-card" href="#ticket/${encodeURIComponent(job.id)}" aria-label="Open ${escapeHtml(job.ticket)}, ${escapeHtml(job.customer_name)}, ${escapeHtml(job.device)}">
    <div class="card-ticket"><span>${escapeHtml(job.ticket)}</span><span class="card-arrow" aria-hidden="true">↗</span></div>
    <h3>${escapeHtml(job.device)}</h3><p class="card-customer">${escapeHtml(job.customer_name)}</p>
    <p class="card-issue">${escapeHtml(job.issue)}</p><div class="card-bottom"><span class="avatar-dot">${escapeHtml(initials)}</span>
    <span>${job.assigned_name ? escapeHtml(job.assigned_name.split(" ")[0]) : "Unassigned"}</span>
    ${job.diagnosis ? `<strong>${escapeHtml(inr(job.estimate_total))}</strong>` : ""}</div></a>`;
}

function renderBoard(body) {
  const { jobs, summary } = body;
  $("#active-count").textContent = summary.active;
  $("#metric-active").textContent = summary.active;
  $("#metric-approval").textContent = summary.counts.awaiting_approval;
  $("#metric-ready").textContent = summary.counts.ready;
  $("#metric-estimate").textContent = inr(summary.approved_estimates);
  $("#service-board").innerHTML = stages.map(([status, label, empty]) => {
    const matching = jobs.filter((job) => job.status === status);
    return `<section class="board-column ${status}" aria-label="${label}"><h3 class="column-heading"><span class="stage-dot"></span>${label}<span class="column-count">${matching.length}</span></h3>
      ${matching.length ? matching.map(card).join("") : `<div class="column-empty"><span aria-hidden="true">＋</span>${empty}</div>`}</section>`;
  }).join("");
  $("#board-empty").hidden = jobs.length > 0;
  const help = {
    desk: "Front desk takes intake and records handovers. Switch persona to see technician or customer actions.",
    "tech-amit": "Amit can claim a new ticket or work on tickets assigned to Amit. Neha's tickets remain read-only.",
    "tech-neha": "Neha can claim a new ticket or work on tickets assigned to Neha. Amit's tickets remain read-only.",
    customer: "Customer simulation can approve or decline an estimate. This demo does not authenticate customers or send messages.",
  };
  $("#board-help").textContent = help[state.persona];
  $$('[data-new-job]').forEach((button) => { button.disabled = state.persona !== "desk"; });
}

function renderArchive(jobs) {
  const closed = jobs.filter((job) => ["collected", "cancelled"].includes(job.status));
  $("#archive-rows").innerHTML = closed.map((job) => `<tr><td><strong>${escapeHtml(job.ticket)}</strong><small>${escapeHtml(job.customer_name)}</small></td><td>${escapeHtml(job.device)}</td><td><span class="status-badge ${job.status}">${escapeHtml(job.status_label)}</span></td><td>${job.diagnosis ? escapeHtml(inr(job.estimate_total)) : "—"}</td><td><a href="#ticket/${encodeURIComponent(job.id)}">View ticket ↗</a></td></tr>`).join("");
  $("#archive-empty").hidden = closed.length > 0;
}

function switchButtons(identities) {
  return `<div class="action-buttons">${identities.map((identity) => `<button class="button" type="button" data-persona="${identity}">Switch to ${escapeHtml(state.personas[identity].name)}</button>`).join("")}</div>`;
}

function estimateForm(job) {
  return `<p class="action-intro">Inspect the device and explain the repair. An estimate does not authorize the repair.</p>
    <form data-action="estimate"><label>Diagnosis<textarea name="diagnosis" required maxlength="600" rows="3" placeholder="What did you find? What repair is needed?">${escapeHtml(job.diagnosis)}</textarea></label>
      <div class="form-grid"><label>Parts cost (INR)<input name="parts" type="number" min="0" max="100000" step="0.01" required value="${escapeHtml(job.parts)}"></label><label>Labour cost (INR)<input name="labour" type="number" min="0" max="100000" step="0.01" required value="${escapeHtml(job.labour)}"></label></div>
      <button class="button primary" type="submit">${job.diagnosis ? "Revise estimate" : "Save estimate for approval"}</button></form>`;
}

function nextAction(job) {
  const persona = state.personas[state.persona];
  if (["collected", "cancelled"].includes(job.status)) {
    return `<div class="closed-info">${job.status === "collected" ? "Handover complete. This ticket is closed and its service history is retained." : `This ticket was cancelled. ${escapeHtml(job.cancel_reason)}`}<br>No further changes are allowed.</div>`;
  }
  if (job.status === "intake") {
    if (persona.role === "technician") return `<p class="action-intro">Claim this ticket to start diagnosis. A ticket can have only one technician.</p><button class="button primary" type="button" data-action-button="claim">Claim ticket as ${escapeHtml(persona.name)}</button>`;
    return `<p class="action-intro">A technician needs to claim this ticket before diagnosis starts.</p>${switchButtons(["tech-amit", "tech-neha"])}`;
  }
  if (job.status === "diagnosis") {
    if (job.assigned_to === state.persona) return estimateForm(job);
    return `<p class="action-intro">${escapeHtml(job.assigned_name)} is diagnosing this device. Only the assigned technician can record its estimate.</p>${switchButtons([job.assigned_to])}`;
  }
  if (job.status === "awaiting_approval") {
    if (persona.role === "customer") return `<p class="action-intro">Simulate ${escapeHtml(job.customer_name)} reviewing the <strong>${escapeHtml(inr(job.estimate_total))}</strong> estimate. Declining closes the ticket.</p>
      <form data-action="decision"><label class="check-label"><input name="confirmed" type="checkbox" required><span>I understand this is a fictional customer decision; no message or payment will be sent.</span></label>
      <label>Reason if declining<input name="reason" maxlength="300" placeholder="e.g. Customer prefers to replace the device"></label>
      <div class="action-buttons"><button class="button primary" type="submit" name="decision" value="approve">Approve estimate</button><button class="button danger-outline" type="submit" name="decision" value="decline">Decline estimate</button></div></form>`;
    if (job.assigned_to === state.persona) return `<p class="action-intro">Awaiting the customer's decision. You may revise the estimate before approval; the latest ticket version must be reviewed.</p>${switchButtons(["customer"])}<details class="estimate-revision"><summary>Revise this estimate</summary>${estimateForm(job)}</details>`;
    return `<p class="action-intro">The estimate is waiting for a customer decision. Repair cannot start until approval is recorded.</p>${switchButtons(["customer"])}`;
  }
  if (job.status === "repair") {
    if (job.assigned_to === state.persona) return `<p class="action-intro">Approval is recorded. Complete the repair and confirm the functional check before handover.</p><form data-action="ready"><label>Completion note<textarea name="completion_note" required maxlength="600" rows="3" placeholder="What was repaired and what did you check?"></textarea></label><label class="check-label"><input name="tested" type="checkbox" required><span>I completed the functional check and verified the reported issue.</span></label><button class="button primary" type="submit">Mark ready for collection</button></form>`;
    return `<p class="action-intro">${escapeHtml(job.assigned_name)} is carrying out the approved repair. Only the assigned technician can mark it ready.</p>${switchButtons([job.assigned_to])}`;
  }
  if (job.status === "ready") {
    if (persona.role === "desk") return `<p class="action-intro">Record the handover at the front desk. Payment collection is outside this demo.</p><form data-action="collect"><label>Collected by<input name="collected_by" required maxlength="80" value="${escapeHtml(job.customer_name)}"></label><label class="check-label"><input name="confirmed" type="checkbox" required><span>I confirmed the device and accessories were handed over to this person.</span></label><button class="button primary" type="submit">Record collection & close ticket</button></form>`;
    return `<p class="action-intro">The repair has passed its functional check. Front desk records the customer handover.</p>${switchButtons(["desk"])}`;
  }
  return "";
}

function renderTicket(body) {
  const { job, events } = body;
  state.job = job;
  $("#ticket-number").textContent = `${job.ticket} / SERVICE TICKET`;
  $("#ticket-device").textContent = job.device;
  $("#ticket-customer").textContent = `${job.customer_name} · Device inspection consent recorded`;
  $("#ticket-status").textContent = job.status_label;
  $("#ticket-status").hidden = false;
  $("#ticket-status").className = `status-badge ${job.status}`;
  $("#ticket-content").hidden = false;
  $("#ticket-issue").textContent = job.issue;
  $("#ticket-accessories").textContent = job.accessories;
  $("#ticket-ref").textContent = job.customer_ref || "Not provided";
  $("#ticket-technician").textContent = job.assigned_name || "Not yet assigned";
  $("#estimate-panel").hidden = !job.diagnosis;
  $("#diagnosis-note").textContent = job.diagnosis;
  $("#estimate-parts").textContent = inr(job.parts);
  $("#estimate-labour").textContent = inr(job.labour);
  $("#estimate-total").textContent = inr(job.estimate_total);
  $("#estimate-state").textContent = job.customer_decision === "approve" ? "CUSTOMER APPROVED" : job.customer_decision === "decline" ? "CUSTOMER DECLINED" : "ESTIMATE ONLY";
  $("#completion-panel").hidden = !job.completion_note;
  $("#completion-note").textContent = job.completion_note;
  $("#handover-note").textContent = job.collected_by ? `Collected by ${job.collected_by}. Handover confirmation recorded; no payment recorded.` : "Functional check recorded. Awaiting front desk handover.";
  $("#action-persona").textContent = state.personas[state.persona].label.toUpperCase();
  $("#ticket-action").innerHTML = nextAction(job);
  $("#action-error").hidden = true;
  $("#reload-ticket").hidden = true;
  $("#cancel-panel").hidden = state.persona !== "desk" || !["intake", "diagnosis", "awaiting_approval"].includes(job.status);
  $("#cancel-form").reset();
  $("#ticket-revision").textContent = job.revision;
  $("#timeline").innerHTML = events.map((event) => {
    const details = event.details;
    const note = details.estimate_total ? `Estimate ${inr(details.estimate_total)}${details.simulated ? " · Simulated customer response" : ""}` : details.functional_check ? "Functional check recorded" : details.handover_confirmed ? "Handover confirmed · No payment recorded" : details.inspection_consent ? "Permission to inspect recorded" : "";
    const date = new Date(event.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    return `<li><strong>${escapeHtml(actionLabels[event.action] || event.action)}</strong><span class="event-actor">${escapeHtml(event.actor)}</span>${note ? `<p class="event-detail">${escapeHtml(note)}</p>` : ""}<small>${escapeHtml(date)} · Version ${event.revision}</small></li>`;
  }).join("");
}

async function route() {
  const version = ++state.routeVersion;
  const hash = location.hash.slice(1) || "board";
  const view = hash.startsWith("ticket/") ? "ticket" : hash === "archive" ? "archive" : "board";
  $$(".view").forEach((element) => { element.hidden = element.id !== `${view}-view`; });
  $$("[data-nav]").forEach((element) => element.classList.toggle("active", element.dataset.nav === (view === "archive" ? "archive" : "board")));
  $("#breadcrumb").textContent = `WORKSHOP / ${view === "ticket" ? "SERVICE TICKET" : view === "archive" ? "CLOSED TICKETS" : "SERVICE BOARD"}`;
  try {
    if (view === "ticket") {
      state.job = null;
      $("#ticket-content").hidden = true;
      $("#ticket-number").textContent = "";
      $("#ticket-customer").textContent = "";
      $("#ticket-status").hidden = true;
      $("#ticket-device").textContent = "Loading ticket…";
      const body = await api(`/api/jobs/${encodeURIComponent(hash.slice(7))}`);
      if (version !== state.routeVersion) return;
      renderTicket(body);
    } else {
      const filter = view === "archive" ? "all" : "active";
      const search = view === "board" ? $("#search").value : "";
      const body = await api(`/api/jobs?status=${filter}&q=${encodeURIComponent(search)}`);
      if (version !== state.routeVersion) return;
      $("#active-count").textContent = body.summary.active;
      if (view === "board") renderBoard(body);
      else renderArchive(body.jobs);
    }
  } catch (error) {
    if (version !== state.routeVersion) return;
    if (view === "ticket") {
      $("#ticket-device").textContent = "Ticket could not be loaded";
      $("#ticket-customer").textContent = error.message;
    }
    toast(error.message);
  }
}

function setBusy(value) {
  state.busy = value;
  $$("#ticket-action button, #ticket-action input, #ticket-action textarea, #cancel-form button, #persona").forEach((element) => { element.disabled = value; });
}

async function switchPersona(identity) {
  if (state.busy) return;
  setBusy(true);
  try {
    await api("/api/persona", { method: "POST", body: JSON.stringify({ persona: identity }) });
    state.persona = identity;
    $("#persona").value = identity;
    await route();
    toast(`Demo persona: ${state.personas[identity].name}`);
  } catch (error) {
    $("#persona").value = state.persona;
    toast(error.message);
  } finally { setBusy(false); }
}

async function perform(action, details) {
  if (state.busy || !state.job) return;
  const snapshot = { id: state.job.id, revision: state.job.revision };
  const startedRoute = state.routeVersion;
  setBusy(true);
  try {
    await api(`/api/jobs/${encodeURIComponent(snapshot.id)}/actions/${action}`, {
      method: "POST", body: JSON.stringify({ ...details, revision: snapshot.revision }),
    });
    toast(actionLabels[action] || "Ticket updated");
    if (startedRoute === state.routeVersion) await route();
  } catch (error) {
    if (startedRoute === state.routeVersion) {
      $("#action-error").textContent = error.message;
      $("#action-error").hidden = false;
      $("#reload-ticket").hidden = error.status !== 409;
    } else toast(error.message);
  } finally { setBusy(false); }
}

document.addEventListener("click", (event) => {
  const newJob = event.target.closest("[data-new-job]");
  if (newJob) {
    if (state.persona !== "desk") { toast("Switch to the front desk persona to create a ticket."); return; }
    $("#intake-error").hidden = true;
    $("#intake-dialog").showModal();
  }
  const persona = event.target.closest("[data-persona]");
  if (persona) switchPersona(persona.dataset.persona);
  const action = event.target.closest("[data-action-button]");
  if (action) perform(action.dataset.actionButton, {});
});
$("#persona").addEventListener("change", (event) => switchPersona(event.target.value));
$("#close-intake").addEventListener("click", () => $("#intake-dialog").close());
$("#reload-ticket").addEventListener("click", route);
$("#search").addEventListener("input", () => { clearTimeout(searchTimeout); searchTimeout = setTimeout(route, 200); });
$("#ticket-action").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form).entries());
  let action = form.dataset.action;
  if (action === "decision") action = event.submitter.value;
  for (const name of ["tested", "confirmed"]) if (form.elements[name]) data[name] = form.elements[name].checked;
  perform(action, data);
});
$("#cancel-form").addEventListener("submit", (event) => {
  event.preventDefault();
  perform("cancel", { reason: event.target.elements.reason.value });
});
$("#intake-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const form = event.target;
  const data = Object.fromEntries(new FormData(form).entries());
  data.consent = form.elements.consent.checked;
  form.dataset.requestId ||= crypto.randomUUID();
  data.request_id = form.dataset.requestId;
  setBusy(true);
  $("#create-ticket").disabled = true;
  $("#intake-error").hidden = true;
  try {
    const body = await api("/api/jobs", { method: "POST", body: JSON.stringify(data) });
    $("#intake-dialog").close();
    form.reset();
    delete form.dataset.requestId;
    location.hash = `ticket/${body.job.id}`;
    toast("Device received. Ticket created with inspection consent.");
  } catch (error) {
    $("#intake-error").textContent = error.message;
    $("#intake-error").hidden = false;
    // A changed body needs a new idempotency key after a conflicting retry.
    if (error.status === 409) delete form.dataset.requestId;
  } finally {
    setBusy(false);
    $("#create-ticket").disabled = false;
  }
});
window.addEventListener("hashchange", route);

(async () => {
  try {
    const body = await api("/api/bootstrap");
    state.csrf = body.csrf;
    state.persona = body.persona;
    state.personas = body.personas;
    $("#persona").value = state.persona;
    await route();
  } catch (error) { toast(error.message); }
})();
