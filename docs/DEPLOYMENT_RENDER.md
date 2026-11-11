# Deploying on Render

The dashboard deploys to Render as **one Docker web service**:
- The `Dockerfile` builds the React frontend with Node 22.
- It installs the pinned Python 3.12 inference stack.
- It copies the Colab-trained model artifacts that are committed in `data_warehouse/`.
- FastAPI then serves the API and the built frontend from the same address.

Nothing is trained during the build or at runtime, and the service does not need Google Colab or Google Drive.

## 1. What to choose in Render

| Setting | Value |
|---|---|
| Service type | Web Service |
| Runtime / language | **Docker** |
| Repository / branch | `HRacheal/University-Institutional-Analytics-Dashboard`, `main` |
| Root directory | *(leave empty: the repository root)* |
| Dockerfile path | `./Dockerfile` (docker context `.`) |
| Build command | *(none: the Dockerfile builds everything, including `npm ci && npm run build`)* |
| Start command | *(none: the image's entrypoint runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers`)* |
| Health check path | `/api/health` |
| Instance type | **Standard (2 GB RAM)** or larger. All 20 models loaded use about 0.9 GB, so Starter (512 MB) runs out of memory |
| Instances | **1** (see section 4) |
| Persistent disk | Name `uiad-data`, mount path **`/var/data`**, size 1 GB |

Render sets `PORT` itself (10000 by default), and the image listens on `0.0.0.0:$PORT`. Render also provides HTTPS and the TLS certificate automatically; HTTP requests are redirected to HTTPS.

## 2. Environment variables

| Key | Value | Notes |
|---|---|---|
| `UIAD_ENV` | `production` | This setting does the following: <ul><li>marks the session cookie Secure</li><li>adds HSTS</li><li>hides `/api/docs`</li><li>never creates the demo account or a credentials file</li></ul> |
| `UIAD_VAR_DIR` | `/var/data` | Must equal the disk mount path |
| `UIAD_SEED_DEMO_USERS` | `0` | Production already disables the demo account; this makes it explicit |
| `UIAD_CLIENT_IP_HEADERS` | `True-Client-IP,CF-Connecting-IP` | Render's edge (Cloudflare) sets these to the real visitor address, which the login rate limit uses |
| `UIAD_IMPORT_ACCOUNTS_FILE` | `/etc/secrets/uiad_accounts.json` | Your existing local accounts, uploaded as a Render **Secret File** (section 3a) |
| `UIAD_BOOTSTRAP_ADMIN_PASSWORD` | *(not needed when accounts are imported)* | Fallback only, when no administrator is imported. It is used for the first start, and must have at least 10 characters with upper- and lower-case letters and a digit, and must not contain `admin` |
| `UIAD_DATABASE_URL` | *(optional)* | Only for the PostgreSQL option in section 3 |

Optional variables with sensible defaults are listed in `backend/README.md` (session lifetime, lockout, rate limit, upload limits).

If an administrator exists, either imported or already in the database, startup never asks for a bootstrap password. If none exists, startup stops with a message that names both options.

## 3. Where the data is stored

The image has no state. Everything that changes lives in `UIAD_VAR_DIR` and the database:
- users and sessions;
- the audit log;
- the prediction history and its downloadable result files;
- uploaded CSV imports;
- the log.

**Option A — SQLite on the persistent disk (recommended, simplest).** Attach the disk at `/var/data` and leave `UIAD_DATABASE_URL` unset. The database is `/var/data/uiad.db`. Render snapshots disks daily.

**Option B — Render PostgreSQL.** Steps:
1. Create a Render PostgreSQL instance in the same region.
2. Copy its **Internal Database URL** into `UIAD_DATABASE_URL`. The `postgres://…` form is accepted and converted to the psycopg driver automatically.
3. **Keep the disk anyway:** prediction result files and imports are files in `/var/data`.

Tables are created automatically at first start.

The local database file (`backend/var/uiad.db`) itself is **not** uploaded: it is git-ignored and excluded from the image. Only the **accounts** are migrated (section 3a).

## 3a. Migrating your existing Admin and Management accounts

The hosted dashboard uses your **existing local accounts**, `admin` (ADMIN) and `manager` (MANAGEMENT), with the same usernames, passwords, roles, permissions and status. Nothing is reset, and nobody has to change a password.

**Why only the accounts, not the whole database file?** Copying `uiad.db` would bring:
- local session tokens, which would stay valid online;
- the local audit log;
- prediction runs that point to files that only exist on your PC.

Copying only the accounts avoids all of that, and also works with PostgreSQL.

**How it works:**
1. **Export, locally.** The export opens the database read-only and doesn't change it, whether or not the dashboard is running:
   ```powershell
   cd C:\Users\Admin\Downloads\University-Institutional-Analytics-Dashboard\backend
   ..\.venv\Scripts\python -m app.core.accounts export
   ```
   - It writes `backend\var\render_accounts.json`, which is git-ignored and excluded from the Docker image.
   - It prints only usernames, roles and status.
   - The file holds each account's username, name, email, department, role, role permissions, active and must-change-password flags, and the **password hash**. It never holds the password itself.
   - It refuses to write to any location inside the repository that Git would track.
2. **Upload it to Render.** Go to the service → **Environment** → **Secret Files** → **Add Secret File**.
   - Filename: `uiad_accounts.json`.
   - Contents: paste the file's contents. Open it in Notepad, select all, copy, and paste straight into Render; don't paste it anywhere else.
   - Render stores it encrypted and provides it at `/etc/secrets/uiad_accounts.json`. `UIAD_IMPORT_ACCOUNTS_FILE` already points there, via `render.yaml`.
3. **Deploy.** At startup, *before* the administrator check, each exported account whose username does not exist yet is inserted, all in one transaction.
   - The Render log shows `account import: created=['admin', 'manager'] already_present=[]`.
   - Because `admin` now exists, no bootstrap password is needed and no extra administrator is created.
4. **Sign in** at the Render address with your usual local usernames and passwords.
5. **Clean up.**
   - Delete the Secret File in Render; later starts log `not present, nothing to import`.
   - Delete the local `backend\var\render_accounts.json`.

**Guarantees:**
- **No duplicates.** A username that already exists is never inserted again.
- **Online changes win.** If the existing account has a *different* password (for example, changed online), it is left unchanged and a warning is logged.
- **Fail-safe.** A malformed file or an unknown role stops startup without importing anything.
- **Permissions.** `ADMIN` and `MANAGEMENT` are system roles. Their permissions come from the same code locally and on Render, and the import checks that they match.
- **Status.** Active and must-change-password flags, full name, department, creation time and last sign-in are kept. The lockout counters start at zero.
- **No exposure.** Hashes are never printed or logged. The audit log records `account_import` with usernames only.

**Things to know:**
- **One-time copy.** After migration the two databases are independent: a password changed locally later does not change online, and vice versa. To copy an account again, delete it online first, export, and redeploy with the Secret File.
- **Treat the hashes as secret.** The file contains password hashes. scrypt hashes are slow to attack, but treat the file like a password: never commit, e-mail or chat it.
- **Strong passwords.** The online dashboard is reachable from the internet. If either local password is short or easy to guess, change it locally *before* exporting, or online after migration (**Change password**).

## 4. Why one instance

- SQLite on a disk can only be used by one instance.
- Render disks prevent scaling beyond one instance and zero-downtime deploys, so each deploy has a short restart.
- The login rate limiter is in memory per process.
- The image therefore runs one uvicorn worker.

This is ample for an institutional dashboard. Models load lazily on first use and are then cached; the first prediction for a task takes a moment longer.

## 5. Deploy, step by step

**Option 1: Blueprint (uses `render.yaml`)**
1. Render Dashboard → **New → Blueprint** → connect GitHub → choose `University-Institutional-Analytics-Dashboard`, branch `main`.
2. Render reads `render.yaml`, which defines the Docker service, Standard plan, disk, health check and variables.
3. Click **Apply**. If the service already exists from an earlier attempt, open it instead.
4. Add the Secret File `uiad_accounts.json` (section 3a, step 2), then choose **Manual Deploy → Deploy latest commit**. The first build takes about 5–10 minutes: npm, Python wheels and the image itself.

**Option 2: manual web service**
1. Render Dashboard → **New → Web Service** → connect the repository, branch `main`.
2. Language **Docker**. Leave the root directory, build command and start command empty.
3. Instance type **Standard**. Under **Advanced**:
   - add the disk (`/var/data`, 1 GB);
   - set the health check path `/api/health`;
   - add the variables from section 2;
   - add the Secret File `uiad_accounts.json` (section 3a).
4. Click **Create Web Service**.

`render.yaml` sets `autoDeploy: false`, so pushing to GitHub does not redeploy. Use **Manual Deploy → Deploy latest commit** when you want an update. Change it to `true` if you prefer automatic deploys.

## 6. After the first deploy: check it

1. Open `https://<your-service>.onrender.com/api/health`. Expect `"status": "ok"`, `"models_registered": 20` and `"artifacts_present": 20`.
2. Open `https://<your-service>.onrender.com`. Sign in as `admin` with your **existing local password**, then sign in as `manager` the same way. In the Render log you should see `account import: created=['admin', 'manager']`.
3. Check **Models**: all 20 tasks are listed with their saved metrics.
4. Run one prediction, then download it from **Prediction history**. This confirms that the disk is writable.
5. **Administration → Users** shows exactly the two migrated accounts.
6. Delete the Secret File in Render and the local `backend\var\render_accounts.json`.
7. Optional: add a custom domain under **Settings → Custom Domains**. The certificate is automatic.

**If the deploy fails:**

| Symptom in the Render logs | Cause and fix |
|---|---|
| `BootstrapError: No administrator exists yet` | The Secret File is missing or has the wrong name. Add `uiad_accounts.json` (section 3a) and redeploy |
| `AccountImportError: …` | The Secret File content is incomplete or not the exported file. Paste the whole file again |
| `account import: … already exist here with a different password` | An account with that name was created online before; it was left unchanged |
| `UIAD_BOOTSTRAP_ADMIN_PASSWORD is too weak` | Choose a password that meets the rules in section 2 |
| `Out of memory` / instance restarts | Use Standard (2 GB) or larger |
| Users disappear after a redeploy | No disk is attached, or `UIAD_VAR_DIR` differs from the mount path |

## 7. Security in production

| Control | How it works |
|---|---|
| HTTPS | Render terminates TLS. The session cookie is `Secure; HttpOnly; SameSite=Strict`, and HSTS is sent (1 year) |
| Security headers | <ul><li>`Content-Security-Policy`: only own scripts, styles, fonts and API calls; no framing</li><li>`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Permissions-Policy`</li><li>`Cache-Control: no-store` on the API</li></ul> |
| API docs | `/api/docs` and `/api/openapi.json` return 404. To show them temporarily, set `UIAD_API_DOCS=1` |
| Passwords | <ul><li>scrypt hashes</li><li>forced change at first sign-in</li><li>rule: at least 10 characters with mixed case and a digit</li></ul> |
| Brute force | <ul><li>Account lockout: 5 failures → 15 minutes (HTTP 423)</li><li>Per-address limit: 20 failures in 15 minutes → HTTP 429 with `Retry-After`</li></ul> |
| Sessions | 8 hours absolute and 60 minutes idle; revoked at logout and when the password changes |
| Roles | <ul><li>ADMIN: everything, including user management, audit log, settings and integrations</li><li>MANAGEMENT: analytics, reports and predictions, but every `/api/admin/*` endpoint returns 403</li><li>Enforced by the server on every request</li></ul> |
| First run | Existing accounts are imported from a Secret File. There is no demo account, no `initial_credentials.txt`, and no hard-coded or default passwords |
| Container | Runs as an unprivileged user (uid 10001). Only the disk is writable application data |
| Secrets | Read from environment variables only. The `.dockerignore` excludes `.env`, databases, `backend/var`, `.git` and the virtual environments from the image |

## 8. Run the production image locally (optional)

This needs Docker Desktop. This run imports your exported accounts exactly as Render will:

```powershell
cd C:\Users\Admin\Downloads\University-Institutional-Analytics-Dashboard
docker build -t uiad .
docker run --rm -p 10000:10000 -e PORT=10000 -e UIAD_IMPORT_ACCOUNTS_FILE=/etc/secrets/uiad_accounts.json `
  -v ${PWD}\backend\var\render_accounts.json:/etc/secrets/uiad_accounts.json:ro -v uiad_data:/var/data uiad
```

Open http://127.0.0.1:10000. Chrome accepts Secure cookies on `127.0.0.1`.
