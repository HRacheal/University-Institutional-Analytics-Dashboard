# Backend (FastAPI)

The API behind the dashboard. It serves institutional analytics, predictions from saved models, administration and
departmental integrations, and in production it also serves the built frontend (`frontend/dist`).

**The backend never trains models.** It only loads the saved artifacts listed in
`data_warehouse/artifacts/artifact_manifest.json`, through `pipelines.model_registry`, which checks each file's SHA-256 on load.

## Run

```powershell
# from the project root, once
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..        # optional: lets the API serve the UI at http://127.0.0.1:8000

# start
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- **First start:** the database is created at `backend/var/uiad.db` (SQLite).
  - An `admin` account is created; a `manager` demo account is also created unless `UIAD_SEED_DEMO_USERS=0`.
  - Their random initial passwords are written **once** to `backend/var/initial_credentials.txt`. This file is git-ignored. Read it, sign in, then delete it.
  - Every account must change its password at first sign-in.
- **Addresses:**
  - UI: <http://127.0.0.1:8000>
  - Interactive API docs: <http://127.0.0.1:8000/api/docs>
  - Health check: `/api/health`
- **Development with hot reload:** run `npm run dev` in `frontend/`, which serves on port 5173 and proxies `/api` to port 8000.

## Configuration (environment variables, prefix `UIAD_`)

| Variable | Default | Purpose |
|---|---|---|
| `UIAD_ENV` | `development` | `production` makes the session cookie Secure (requires HTTPS) |
| `UIAD_DATABASE_URL` | SQLite in `var/` | e.g. `postgresql+psycopg://user@host/db`; the password comes from the environment, never from files |
| `UIAD_VAR_DIR` | `backend/var` | Database, log (`uiad.log`), prediction result files, initial credentials |
| `UIAD_DW_ROOT` / `UIAD_DATA_ROOT` | project folders | Location of the data warehouse (models, reports) and the data |
| `UIAD_SESSION_HOURS` / `UIAD_SESSION_IDLE_MINUTES` | 8 / 60 | Absolute and idle session lifetime |
| `UIAD_MAX_FAILED_LOGINS` / `UIAD_LOCKOUT_MINUTES` | 5 / 15 | Account lockout (HTTP 423) |
| `UIAD_BOOTSTRAP_ADMIN_USER` / `UIAD_BOOTSTRAP_ADMIN_PASSWORD` | `admin` / random | Initial administrator. The password, if given, must still be changed at first sign-in |
| `UIAD_SEED_DEMO_USERS` | `1` | Create the `manager` demo account |
| `UIAD_MAX_UPLOAD_MB` / `UIAD_MAX_BATCH_ROWS` | 20 / 20000 | CSV upload limits |
| `UIAD_CORS_ORIGINS` | `http://localhost:5173,…` | Allowed origins for the development frontend |

Departmental REST connectors read their API token from the environment variable **named** in the integration's
configuration (for example `UIAD_ADMISSIONS_API_TOKEN`). Tokens are never stored in the database or shown in the UI.

## Code map

| Package | Responsibility |
|---|---|
| `app/core` | Settings, database tables (SQLAlchemy Core), password hashing (scrypt), sessions, the RBAC dependency `require(...)`, and first-start bootstrap |
| `app/auth` | `/api/auth/login`, `logout`, `me` and `change-password`. Sessions use an httpOnly SameSite=Strict cookie (a Bearer header is also accepted); only the SHA-256 of each token is stored. Includes lockout and auditing |
| `app/analytics` | Metric calculations for enrolment, performance, retention, graduation, admissions, finance and IT, with filters, definitions, limitations and data-source labels |
| `app/integrations` | Departmental connectors (`sample`, `csv_import`, `rest_api`), data contracts from the data dictionary, validation, active-source switching and the sync history |
| `app/ml` | Model catalogue, input schemas, single / CSV / cohort prediction, risk bands, explanations, prediction history, forecasts and segmentation. Inference only |
| `app/api` | HTTP routers: `analytics.py`, `ml.py` and `admin.py` |
| `app/main.py` | App factory, logging (with an X-Request-ID on every request), error mapping (422 invalid input, 503 artifact unavailable) and serving of the SPA |
| `app/admissions`, `registrar`, `finance`, `it`, `admin`, `management` | Empty package placeholders from the original scaffold. The live code is in `analytics/`, `integrations/` and `api/` |

## Roles and permissions

| Permission | ADMIN | MANAGEMENT |
|---|---|---|
| `analytics:read`, `student_level:read`, `predictions:run`, `predictions:history`, `models:read`, `reports:export` | ✓ | ✓ |
| `admin:users`, `admin:roles`, `admin:integrations`, `admin:sync`, `admin:settings`, `admin:audit` | ✓ | — |

- **Role rules:**
  - Administrators can create custom roles from these permissions.
  - The two system roles cannot be changed.
  - The last active administrator cannot be removed or demoted.
- **Data visibility:**
  - Prediction history is per-user (administrators see all runs).
  - Pseudonymous student IDs are returned only with `student_level:read`.
- **Audit:** sign-ins, exports, predictions, downloads and administrative changes are written to the audit log.

## Tests

```powershell
cd backend
..\.venv\Scripts\python -m pytest tests -q -p no:cacheprovider -W ignore
```

`tests/test_api.py` covers:
- **Access:** authentication, lockout, the forced password change, RBAC and the audit log.
- **Data:** every analytics endpoint and the exports.
- **Models:** the model catalogue and warnings, predictions from every model family (binary, multiclass, regression, survival), validation errors, CSV batch, cohort scoring and history ownership.
- **Other features:** explanations, forecasts, segmentation, admin roles and integrations.
- **Security:** path-traversal protection.

The tests use a temporary database and never touch `backend/var`.
