# Technical documentation: University Institutional Analytics Dashboard

Audience: developers and administrators who run, extend or audit the system.
Model results are described separately in [`MODEL_EVALUATION_REFERENCE.md`](MODEL_EVALUATION_REFERENCE.md).

## 1. Architecture

```
 Departmental sources            Data warehouse (Python)                 Backend (FastAPI)                Frontend (Refine/React)
 ─────────────────────           ───────────────────────                 ─────────────────                ───────────────────────
 Admissions ┐                    pipelines/uci_processing                app/integrations  ── active      13 pages (overview,
 Registrar  ├─ sample data  ───► pipelines/synthetic (generator)         source per department ──►        enrolment, performance,
 Finance    │  CSV import        pipelines/feature_engineering ──►       app/analytics (metrics)          retention, graduation,
 IT         ┘  REST connector    data/processed/modeling/*.csv           app/ml (inference only) ◄──      admissions, finance & IT,
                                 pipelines/model_training (COLAB ONLY)   pipelines/model_registry         forecasting, predictions,
                                 models/ reports/ artifacts/manifest     app/api (+ RBAC, audit)    ───►  segmentation, models,
                                                                         serves frontend/dist             history, reports, admin)
```

- **Model training runs only in Google Colab.** It runs in the project's single Colab notebook and writes its outputs to `MyDrive/analytics_project_outputs/<task>/`, with a SHA-256 `backup_manifest.json` per task.
- The local machine is used for dashboard development, tests and inference only.
- The saved artifacts are registered in `data_warehouse/artifacts/artifact_manifest.json`.
- `pipelines.model_registry` loads each artifact lazily, verifies its SHA-256 and caches it. `pipelines.model_registry.audit` re-runs every model on its held-out test rows and checks that the saved metrics reproduce.

## 2. Data

| Zone | Source | Use |
|---|---|---|
| `UCI` | `data/raw/data.csv` (4,424 students; CC BY 4.0), never edited | 4 benchmark models only. Never mixed with institutional data |
| `SYNTHETIC` | `data/synthetic/` (5,000 generated students, 2016FA–2026FA; as-of date 2026-11-10) | All dashboards and the 16 institutional models |

- **Labelling:** every API response carries a `data` label, every prediction carries the synthetic or UCI label, and every downloaded file starts with a `#` label header.
- **Sources:** an administrator can switch any department from the sample data to imported CSV data. The banner on each page shows the active source per department.

## 3. Backend

See [`backend/README.md`](../backend/README.md) for running instructions, configuration, the code map and RBAC.

### API overview (all JSON unless stated; all require a session)

**Authentication and analytics**

| Area | Endpoints | Permission |
|---|---|---|
| Auth | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password` | none (login), or session |
| Analytics | `GET /api/analytics/options`, `/overview`, `/enrollment`, `/enrollment/compare`, `/performance`, `/performance/attention`, `/retention?comparison=FALL_TO_FALL\|SPRING_TO_SPRING\|SUMMER_TO_SUMMER`, `/graduation`, `/admissions`, `/finance`, `/it` | `analytics:read` |
| Exports | `GET /api/analytics/export/{enrollment\|performance\|retention\|graduation}.csv` | `analytics:read` + `reports:export` |

Filters (query parameters): `academic_year`, `season`, `school_id`, `programme_id`, `level`, `nationality_iso3`, `gender`, `delivery_mode`, `study_load`.

**Models and predictions**

| Area | Endpoints | Permission |
|---|---|---|
| Models | `GET /api/models`, `/models/status`, `/models/{task}`, `/models/{task}/schema`, `/models/{task}/template.csv`, `/figures/{path}` (PNG files under `reports/` only) | `models:read` |
| Predict | `POST /api/predict/{task}` `{rows:[…≤200], explain}` · `POST /api/predict/{task}/batch` (multipart CSV) | `predictions:run` |
| Cohort | `POST /api/predict/{task}/cohort` | `predictions:run` + `student_level:read` |
| History | `GET /api/predictions`, `GET /api/predictions/{id}/download` | `predictions:history` (+ `reports:export` to download) |
| Forecasts and segments | `GET /api/forecasts`, `/forecasts/history?series=`, `/segmentation`, `/segmentation/assignments.csv` | `analytics:read` (the anomaly list and assignments also need `student_level:read`) |

**Administration**

| Endpoints | Permission |
|---|---|
| `/api/admin/users`, `/users/{id}`, `/users/{id}/reset-password` | `admin:users` |
| `/api/admin/roles`, `/roles/{role}` | `admin:roles` |
| `/api/admin/integrations…` | `admin:integrations` |
| `/api/admin/sync-runs`, `/integrations/{id}/sync` | `admin:sync` |
| `/api/admin/settings…` | `admin:settings` |
| `/api/admin/audit` | `admin:audit` |

**Error responses**

| Status | Meaning |
|---|---|
| 401 | Not signed in |
| 403 | Missing permission, or the password must be changed first |
| 413 | Upload too large |
| 422 | Invalid input. The `details` field lists missing columns, unknown categories and non-numeric values |
| 423 | Account locked |
| 503 | A model artifact is not restored or failed its SHA-256 check |

Unexpected errors return a generic 500 response with an `X-Request-ID` that matches the entry in `backend/var/uiad.log`.

### Prediction semantics
- **Thresholds:**
  - Binary classifiers use the **original threshold**: the one that maximised class-1 F1 on the cross-validation out-of-fold predictions.
  - A **supplementary class-0 threshold** is shown where it exists (Batch 2–5 methodology). It never replaces the original.
- **Risk bands** (for tasks whose adverse outcome is known):
  - `HIGH` = adverse outcome predicted at the original threshold.
  - `ELEVATED` = not predicted adverse, but the adverse probability is at or above the training base rate.
  - `LOW` = otherwise.
  - Offer and acceptance models use `LIKELY` / `UNLIKELY` instead.
- **Explanations** (single requests of 20 rows or fewer):
  - Tree models use per-record TreeSHAP contributions towards class 1, or towards the predicted class for multiclass models. Linear models use coefficient × scaled value.
  - Contributions are summed back to the original feature.
  - Units are probability for random forests and log-odds for boosted and linear models.
  - These are associations, not causes.
- **Survival models:** they return a relative hazard compared with a student at the training mean, within the same level. They do not give an absolute probability.
- **Cohort scoring:** uses the registrar feature panel at the documented prediction point, and only for students whose outcome was not yet recorded at that point.
  - It refuses to run when the registrar source is not the synthetic sample.
  - It is not offered for the Fall→Fall retention models, because no complete future base term exists.

## 4. Frontend

- **Stack:** Refine 5 with `@refinedev/antd` 6, Ant Design 5, React 19, React Router 7, Recharts 3, TanStack Query, Vite 8 and TypeScript 5.9 (strict).
- **Shell (`frontend/src`):**
  - `App.tsx` contains the routes and the access-control guard.
  - `auth.ts` holds the auth and access-control providers, which map each page to a permission from `/api/auth/me`.
  - `api.ts` is the fetch client. It uses the same-origin cookie, so no token is ever kept in JavaScript-readable storage.
- **Pages (`pages/*.tsx`):**
  - Overview; Enrolment (all 9 filters, term comparison); Performance; Retention (Fall, Spring and Summer comparisons); Graduation; Admissions; Finance & IT.
  - AI & forecasting: Forecasting, Predictions (single / CSV / cohort), Segmentation, Model evaluation, Prediction history.
  - Reports; Administration (users, roles, integrations, sync runs, audit, settings).
  - Login and Change password.
- **Charts (`viz/`):**
  - The reference palette has been validated for colour-vision deficiency (CVD) in light and dark mode.
  - Charts use one y-axis, 2px lines and rounded bars, with tooltips on every chart and a legend whenever there are two or more series.
  - Every chart has a **Table** view and a **CSV** download of exactly the plotted rows.
  - Status colours always appear with an icon and a text label.
- **Model output** is shown in dashed "model output" panels that are visually separated from the recorded figures. Each one carries the model's warnings and limitations.
- **States:** pages show a skeleton while loading. Errors show the server message with a retry button; 403 and 503 responses have their own explanations.
- **Layout:** responsive down to 390px wide, with a light/dark toggle.

```powershell
cd frontend
npm install
npm run dev         # http://localhost:5173 (needs the backend on :8000)
npm run typecheck; npm test; npm run build
```

## 5. Departmental integrations

- **Connectors:** each department (Admissions, Registrar, Finance, IT) has a `sample` connector, a `csv_import` connector and a `rest_api` connector. Exactly one per department is the **active source**.
- **CSV import:**
  - Data contracts come from `data/synthetic/schema/data_dictionary.csv`: columns, types, required fields, allowed values and primary keys.
  - An upload is validated in full before anything is stored. A rejected file stores nothing.
  - Every import is logged in `sync_runs`.
- **REST connector:**
  - Status stays `AWAITING_INTEGRATION` until an administrator sets a `base_url` and the **name** of the environment variable that holds the token.
  - **No live departmental API is connected in this delivery.** No connection has been invented.

## 6. Security notes
- **Passwords:**
  - Hashed with scrypt (N=2^14, r=8, p=1, 16-byte salt).
  - Must be at least 10 characters, with upper- and lower-case letters and a digit, and must not contain the username.
  - A change is forced at first sign-in.
- **Sessions:**
  - Server-side, with absolute and idle expiry; only the SHA-256 of the token is stored.
  - The cookie is httpOnly with SameSite=Strict, and Secure in production.
- **Lockout:** 5 failed sign-ins lock the account for 15 minutes.
- **Audit log:** covers authentication, exports, predictions, downloads and every administrative change.
- **Upload limits:** size and row-count limits apply; CSV files are read as text and validated before use.
- **Figures endpoint:** restricted to PNG files under `data_warehouse/reports` (path-traversal tested).
- **Repository hygiene:**
  - No secrets are in the repository.
  - `backend/var/` (database, log, initial credentials) and `.env*` are git-ignored.

## 7. Operations
- **Backups:** the database and prediction files are in `backend/var/`; copy that folder.
- **Model artifacts:** use `python -m pipelines.model_registry.restore --source <Drive outputs>` to restore from Drive with SHA-256 verification. Mismatching local files are archived to `_superseded_local/`, never overwritten silently.
- **Restoration audit:** `python -m pipelines.model_registry.audit` (inference only).
- **Production:** deploy the Docker image (`Dockerfile`, `render.yaml`) behind HTTPS with `UIAD_ENV=production` and persistent storage for `UIAD_VAR_DIR` (SQLite) or PostgreSQL via `UIAD_DATABASE_URL`. Step-by-step: [`DEPLOYMENT_RENDER.md`](DEPLOYMENT_RENDER.md).

## 8. Installation and environment setup
```powershell
# prerequisites: Python 3.12, Node.js (LTS recommended), Git
git clone <repository> ; cd University-Institutional-Analytics-Dashboard
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt     # pandas, numpy, scikit-learn 1.6.1, xgboost 3.4.1, lightgbm, catboost,
                                                            # statsmodels, shap, fastapi, uvicorn, sqlalchemy, pytest ...
cd frontend; npm install; npm run build; cd ..
```
The data (`data/`) and the model artifacts (`data_warehouse/models`, `reports`) are part of the project folder.
If they are missing, restore them as described in §10.

## 9. Project structure
```
backend/          FastAPI app (app/core, auth, analytics, integrations, ml, api) + tests/
frontend/         Refine/React app (src/pages, components, viz) + tests (vitest)
data/             raw UCI file (read-only), processed UCI, synthetic institutional data, modelling datasets
data_warehouse/   pipelines (uci_processing, synthetic, feature_engineering, model_training, model_registry),
                  models/, reports/, artifacts/ (artifact_manifest.json, training_provenance.json, audits),
                  _superseded_local/ (archived earlier artifacts; never deleted)
docs/             FINAL_TECHNICAL_REPORT, MODEL_EVALUATION_REFERENCE (+ generator), TECHNICAL_DOCUMENTATION,
                  PRESENTATION, COMPLETION_REPORT
```

## 10. Using the dashboard
1. **Start and sign in.** Start the backend (see `backend/README.md`) and open <http://127.0.0.1:8000>. Sign in with the initial credentials from `backend/var/initial_credentials.txt`, then set a new password.
2. **Explore the institutional pages.** Use the filter bar at the top of a page. Every chart has a **Table** toggle and a **CSV** button. The banner shows the data source and labels.
3. **Make predictions.** Open **AI & forecasting → Predictions**, then pick a model. There are three ways to score:
   - **Single:** fill in the form, which is pre-filled with a valid example, and tick *Explain*.
   - **Batch:** download the CSV template, fill it in and upload it.
   - **Cohort:** score current students at the documented prediction point.

   Results show the probability, a risk band and the thresholds. Every run appears in **Prediction history**.
4. **Review model evaluation.** **Model evaluation** shows every task's metrics, thresholds, figures, warnings and the restoration status.
5. **Administer (ADMIN only).**
   - Users: create users, reset passwords, deactivate accounts.
   - Roles: build custom roles from permissions.
   - Integrations: upload validated CSVs or configure a REST connector.
   - Also: sync runs, audit log and settings.

## 11. Restoring models, reproducing the evaluation, backup
**Where training happens.** Model training happens only in the project's Google Colab notebook, never on the local machine.

**Restoring models locally.** Either path verifies SHA-256 and archives conflicting local files.
- **From Drive** (for example a downloaded copy of `MyDrive/analytics_project_outputs`):
  ```
  python -m pipelines.model_registry.restore --source <outputs> --archive-conflicts
  ```
- **From one or more task sets:**
  ```
  python -m pipelines.model_registry.import_colab_sets --source <folder> --task <task> ...
  ```
- **Portable XGBoost exports:**
  ```
  python -m pipelines.model_registry.import_colab_sets --portable --source <export set>
  ```

**Reproducing the evaluation** (no training):
- `python -m pipelines.model_registry.audit` reloads every artifact, predicts its held-out test rows and compares the result with the saved metrics. Tolerance is 1e-6.
- The audit writes `artifacts/restoration_audit.{md,json}`.
- `python docs/build_model_reference.py` regenerates `MODEL_EVALUATION_REFERENCE.md` from the saved results.

**Re-training (Colab only).**
1. In the existing notebook, mount Drive and extract the project ZIP to `/content`. The ZIP is only read.
2. Apply the recorded patches from `_batch5_and_final_tooling`.
3. Run `python -m pipelines.model_training.run_all --only <task> --skip-forecasting`.
4. Copy the outputs to a **new** Drive set with a `backup_manifest.json`.

The 2026-11-11 Batch 1 retrain driver, logs and notes are in `MyDrive/analytics_project_outputs/_batch1_colab_retrain_tooling/`.

**Backup.**

| What | Where |
|---|---|
| Project | The ZIPs `MyDrive/University-Institutional-Analytics-Dashboard*.zip`. Never overwrite them; upload a new, differently named ZIP |
| Models | One set per task in `MyDrive/analytics_project_outputs/`, each with a SHA-256 `backup_manifest.json` |
| Dashboard state | Copy `backend/var/` (database, prediction files) |
