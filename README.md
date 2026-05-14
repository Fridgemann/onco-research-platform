# Oncology Research Platform

A fullstack web application for oncology researchers to upload datasets, run statistical analyses, and collaborate securely in workspaces. Built as a graduation project with a deliberate emphasis on information security.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.12), async SQLAlchemy + asyncpg |
| Database | PostgreSQL |
| Cache / Rate limiting | Redis + slowapi |
| File storage | MinIO (S3-compatible, encrypted at rest) |
| Task queue | Celery + Redis |
| Migrations | Alembic |
| Frontend | Next.js 15, React, TailwindCSS |

---

## Security Architecture

### Authentication
- **JWT access tokens** (15 min) returned in response body, stored in memory — never in `localStorage`
- **Refresh tokens** (7 days) in `httpOnly`, `SameSite=lax` cookie scoped to `/api/auth/refresh`
- **Absolute session lifetime** enforced via `session_iat` claim — token rotation does not extend the session; expiry is fixed at login time
- Session cookie has no `Max-Age`/`Expires` — dies on browser close

### Authorization
- **RBAC**: Admin / Researcher / Collaborator (platform-level roles)
- Workspace-level roles: Owner / Collaborator
- All protected routes enforce ownership/membership server-side

### Data Protection
- **Field-level Fernet encryption** (AES-128-CBC) for email and full name at rest
- SHA-256 email hash stored separately for indexed lookups without decryption
- Datasets encrypted at rest in MinIO
- No PII in URLs or logs

### Audit Trail
- Append-only `audit_logs` table — PostgreSQL trigger prevents `UPDATE`/`DELETE`
- Every significant action (login, register, invite, dataset upload, analysis, member changes) is logged with IP and user agent
- SIEM-ready structured format

### Hardening
- Account lockout after 5 failed login attempts (15 min)
- Rate limiting: 5/min on login, 10/min on register, 20/min on token refresh
- Generic auth errors (never reveal whether email exists)
- CORS restricted to `FRONTEND_URL` (not wildcard)
- `secure=True` cookies in production

---

## Running Locally

### Prerequisites
- Docker Desktop
- Python 3.12
- Node.js 18+

### 1. Start infrastructure

```bash
docker-compose up postgres redis minio -d
```

### 2. Backend

```bash
cd backend

# Create and activate virtualenv
python -m venv onco-research
source onco-research/bin/activate        # macOS/Linux
.\onco-research\Scripts\activate         # Windows PowerShell

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY, FERNET_KEY, DATABASE_URL at minimum

# Run migrations
alembic upgrade head

# Start API
uvicorn app.main:app --reload
# → http://localhost:8000/docs
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | 32-byte hex string for JWT signing |
| `FERNET_KEY` | Yes | Fernet key for field-level encryption |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | No | Defaults to `redis://localhost:6379/0` |
| `APP_ENV` | No | `development` or `production` |
| `FRONTEND_URL` | No | Production frontend origin for CORS |
| `SMTP_HOST/USER/PASSWORD` | No | Email delivery (dev logs invite links instead) |

Generate keys:
```bash
# SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"

# FERNET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **Note:** Postgres runs on port 5433 locally (5432 may be occupied by a system install).

---

## Running Tests

```bash
cd backend
source onco-research/bin/activate
pytest -v
```

84 tests covering:
- Authentication flows and session security
- Invite system (create, accept, decline, revoke) with OWASP A01 ownership checks
- Dataset access control
- Workspace member management (leave, remove)
- Absolute session lifetime enforcement

---

## API Endpoints

### Auth
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/register` | None | Register new researcher account |
| POST | `/api/auth/login` | None | Returns access token + sets refresh cookie |
| POST | `/api/auth/refresh` | httpOnly cookie | Rotate tokens; enforces absolute session lifetime |
| POST | `/api/auth/logout` | Bearer | Clears refresh cookie |
| GET | `/api/auth/me` | Bearer | Current user profile |

### Workspaces
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/workspaces` | Bearer | Create workspace |
| GET | `/api/workspaces` | Bearer | List own workspaces |
| GET | `/api/workspaces/{id}` | Bearer | Get workspace (members only) |
| PATCH | `/api/workspaces/{id}` | Bearer (owner) | Update workspace |
| DELETE | `/api/workspaces/{id}` | Bearer (owner) | Delete workspace |
| GET | `/api/workspaces/{id}/members` | Bearer (member) | List members with decrypted emails |
| DELETE | `/api/workspaces/{id}/members/me` | Bearer | Leave workspace |
| DELETE | `/api/workspaces/{id}/members/{user_id}` | Bearer (owner) | Remove member |

### Invites
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/workspaces/{id}/invites` | Bearer (owner) | Create invite + send email |
| GET | `/api/workspaces/{id}/invites` | Bearer (owner) | List invites |
| DELETE | `/api/workspaces/{id}/invites/{invite_id}` | Bearer (owner) | Revoke invite |
| POST | `/api/invites/accept` | Bearer | Accept invite (email must match) |
| POST | `/api/invites/decline` | Bearer | Decline invite |

### Datasets
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/workspaces/{id}/datasets` | Bearer (member) | Upload dataset (encrypted) |
| GET | `/api/workspaces/{id}/datasets` | Bearer (member) | List datasets |
| GET | `/api/workspaces/{id}/datasets/{dataset_id}` | Bearer (member) | Download dataset |
| DELETE | `/api/workspaces/{id}/datasets/{dataset_id}` | Bearer (member) | Soft-delete dataset |

### Analysis
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/workspaces/{id}/analysis` | Bearer (member) | Submit analysis job (async via Celery) |

Supported job types: `kaplan_meier`, `descriptive_stats`, `regression`, `logistic_regression`

---

## Features

- Researcher registration and login
- Workspace creation and management
- Collaborator invite system (email-based, token-hashed)
- Encrypted dataset upload and download via MinIO
- Async statistical analysis jobs (Kaplan–Meier, descriptive stats, linear regression, logistic regression)
- Full audit trail on all sensitive actions

---

## Known Limitations

- **No token family / refresh reuse detection** — a stolen refresh cookie could be silently reused until the 7-day absolute expiry. Mitigation: session-only cookie (dies on browser close) + absolute lifetime.
- **Email delivery** — in development, invite links are logged to the console rather than sent. Production requires SMTP configuration.
- **No MFA** — single-factor auth only.
- **Frontend TypeScript** — pre-existing type errors in Recharts analysis components; does not affect runtime.
- **Clinical deployment** — this platform is a portfolio/research prototype. Production clinical use would require additional compliance work (HIPAA/KVKK, audit review processes, pen testing).

---

## Demo Flow

1. Register a researcher account
2. Login → access token stored in memory, refresh cookie set
3. Create a workspace
4. Invite a collaborator by email → copy invite link from Members tab
5. Register collaborator account → accept invite via link
6. Owner views Members tab — both users listed with emails
7. Upload a CSV dataset
8. Run a Kaplan–Meier or descriptive stats analysis
9. View results inline
10. Owner removes collaborator, or collaborator leaves workspace
11. Inspect `/api/auth/me`, Swagger UI at `http://localhost:8000/docs`
