# Local validation

The latest local validation used Python 3.12.14, Flask 3.1.3 and SQLite through the Python standard library. Exact installed development packages are recorded in `requirements-tested.txt`.

## Automated checks

```bash
python -m pytest --cov=workshop --cov-report=term-missing --cov-fail-under=90
python -m pip check
```

Result: **67 passed**, **98% Python statement coverage**, and **no broken requirements**. These tests are offline and each uses a temporary database or a factory-specific temporary directory. They do not mutate the running demo's tickets.

| Area | Evidence |
|---|---|
| Full service path | Intake → diagnosis → approval → repair → functional check → collection |
| Estimate decision | Explicit simulation acknowledgement; decline reason; no unapproved repair |
| Ownership | A second technician cannot estimate or complete someone else's job |
| Quote changes | Old quote revision cannot be approved; prior accepted quote values remain in events |
| Closed ticket | No accepted mutation after collection or cancellation |
| Concurrent claim | Two real SQLite connections synchronize at a barrier; exactly one claims |
| Concurrent creation | Identical request IDs create one ticket and return one retry result |
| Transaction rollback | Injected event-insert failure leaves the job and audit count unchanged |
| SQL constraints | Direct unapproved repair, missing assignment and negative price writes fail |
| Validation | Field limits, exact paise, invalid decimal notation, required flags and revisions |
| Request protections | Session-bound CSRF, same origin, trusted hosts, 32 KiB cap and security headers |
| Local integration | Separate `repair_session` cookie and persistent key/session across restarts |
| Fixtures | Seed repeat safety; empty start; every fixture created through normal domain functions |

Statement coverage is a useful regression signal, not proof that every browser behavior or security case is covered. The suite includes meaningful concurrency and failure tests instead of depending solely on a coverage percentage.

## Browser validation

Working screenshots are stored in `docs/screenshots/` and embedded in the README. The browser review is performed against the actual loopback server, including a narrow mobile layout. The final screenshot/documentation commit records captures after the interface is tested. Screenshots demonstrate UI behavior; they do not substitute for the separate-connection concurrency tests.

On 1 October 2026 the running browser completed Pooja Rao's fictional Motorola G32 ticket: Amit claimed it, recorded parts ₹650.50 plus labour ₹250.00, a simulated customer approved the ₹900.50 estimate, Amit recorded a functional check, and Meera recorded collection. Every accepted stage appeared in the service timeline. Closed-ticket history remained available.

The captured workflow image shows the estimate awaiting approval; the overview/mobile images show the board after collection. The 1280-pixel desktop and 390-pixel mobile boards had no horizontal document overflow. The final browser console contained no warnings or errors. A shared-browser API check also verified this app's session remained independent of Sutra and Nirikshak running on neighbouring localhost ports.

## Practical limits

- Roles are explicitly simulated. Anyone at the local demo can switch persona. There is no user authentication or customer identity verification.
- The app is intended for one fictional shop on a trusted local machine. All demo personas can view the store's tickets.
- Estimates include any tax in the entered amount; no GST breakdown, payment, invoice, deposit, refund or finance accounting is implemented.
- There is no SMS, email, customer upload, file attachment or external API integration.
- Active repairs cannot be cancelled; handling abandoned or disputed work is deliberately outside the small workflow.
- Dates and timestamps are real UTC server times shown in the browser's locale. The app does not fabricate historical work dates.
- There is no pagination. The board is sized for a small demonstration dataset.
- Audit events are immutable through the API, but the local database owner can edit the file. This is not a tamper-evident audit system.
- No schema migration system is implemented in this initial release. Preserve real data before any future schema change; practice with a separate fresh `--data-dir`.
- The repository is public; [GitHub Actions](https://github.com/Siddh-sys-rgb/repair-works/actions/workflows/tests.yml) records Linux matrix results separately from these original local checks.
