# gym-payments-service-python

Python/Flask baseline that owns charging and refunding payments for members of
`gym-membership-service-python`. Kept as a separate service so membership logic and payment logic
can evolve independently, matching the Express pair and the other cross-service baselines in this
workspace.

## Domain model

- **Payment** — memberId (reference to a member in `gym-membership-service-python`, no local
  foreign key), type (`CHARGE` / `REFUND`), amount, status (`SUCCESS` / `FAILED` / `PENDING`,
  defaults to `SUCCESS`), reason (optional), relatedPaymentId (optional — links a refund back to
  the charge it reverses)

## Stack

- Flask 3 with an application factory and one blueprint per resource
- Flask-SQLAlchemy 3 / SQLAlchemy 2, SQLite for local dev
- pytest + Flask test client; ruff for linting

## Project structure

```
app/
  __init__.py        # create_app factory, blueprint and error-handler wiring
  config.py          # environment-backed config
  extensions.py      # SQLAlchemy instance
  errors.py          # ApiError and JSON error handlers
  models/            # SQLAlchemy models
  services/          # business logic, DB access
  routes/            # Flask blueprints
tests/               # pytest suite
wsgi.py              # WSGI entrypoint
```

## Run

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
flask run
```

`flask run` reads `.flaskenv` and listens on `http://localhost:3001` so it can run alongside
`gym-membership-service-python` (port 3000) during local testing. The SQLite file is created at
`data/dev.sqlite` on first run. Set `DATABASE_URL` to point elsewhere and `FLASK_RUN_PORT` to
change the port.

## Endpoints

- `GET /api/health` — liveness check
- `POST /api/payments/charge` — `{ "memberId", "amount", "reason" }` — records a successful charge
- `POST /api/payments/refund` — `{ "memberId", "amount", "reason", "relatedPaymentId" }` — records
  a refund; if `relatedPaymentId` is given it must reference an existing `CHARGE` for that same
  member, or `422`
- `GET /api/payments/member/:memberId` — full payment history for a member, most recent first
- `GET /api/payments/:id` — get one payment (`404` if missing)

## Relationship to gym-membership-service-python

This service doesn't know about classes, bookings, or trainers — only payments against a
`memberId`. `gym-membership-service-python` calls this service when merging duplicate member
accounts.

## Tests

```
pytest
ruff check .
```
