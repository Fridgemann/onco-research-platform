# Oncology Research Platform

## Project Overview
A fullstack oncology research platform built as a graduation project with a security (infosec) emphasis.
Researchers can upload datasets, run statistical analyses, and invite collaborators to workspaces.

## Stack
- **Frontend:** React + Vite + TailwindCSS (not started yet)
- **Backend:** FastAPI (Python 3.12)
- **Database:** PostgreSQL (async via SQLAlchemy + asyncpg)
- **Cache / Rate limiting:** Redis + slowapi
- **File storage:** MinIO (S3-compatible, encrypted)
- **Task queue:** Celery + Redis (for async statistical jobs)
- **Migrations:** Alembic

## Running the Project (Windows PowerShell)
```powershell
# Start infrastructure (from project root)
docker-compose up postgres redis minio -d

# Activate venv and start API (from backend/)
.\onco-research\Scripts\activate
uvicorn app.main:app --reload
# → http://localhost:8000/docs
```

## Key Conventions
- Always use `async def` for route handlers
- Every significant action must call `write_audit_log()` from `app/services/audit.py`
- Use `Depends(get_current_user)` or the shorthand `CurrentUser` for protected routes
- Use `require_role(UserRole.X)` for role-restricted routes
- All new models must be registered in `alembic/env.py`
- All new routers must be mounted in `app/main.py`
- Enum columns must use `values_callable=lambda x: [e.value for e in x]` to avoid uppercase mismatch with Postgres
- Field-level encryption via `encrypt_field()` / `decrypt_field()` for any PII
- Never expose `hashed_password`, `email_encrypted`, or `full_name_encrypted` in responses

## Security Architecture
- JWT access tokens (15min) returned in response body
- Refresh tokens (7 days) in httpOnly cookie scoped to `/api/auth/refresh`
- RBAC: Admin / Researcher / Collaborator (platform-level roles in `UserRole`)
- Field-level Fernet encryption for email and full name
- SHA-256 email hash stored separately for indexed lookups
- Account lockout after 5 failed logins (15min)
- Append-only audit log (PostgreSQL trigger prevents UPDATE/DELETE)
- Rate limiting via slowapi + Redis
- Generic auth errors (never reveal if email exists)

## Project Structure
```
onco-research-platform/
├── docker-compose.yml
└── backend/
    ├── alembic.ini
    ├── .env                         # never commit this
    ├── requirements.txt
    ├── alembic/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/
    │       └── 0001_initial_schema.py
    └── app/
        ├── main.py
        ├── api/
        │   ├── dependencies.py      # get_current_user, require_role, CurrentUser, AdminUser, ResearcherUser
        │   └── routes/
        │       └── auth.py          # /register /login /refresh /logout /me
        ├── core/
        │   ├── config.py            # pydantic-settings, reads .env
        │   ├── database.py          # async SQLAlchemy engine, get_db()
        │   ├── security.py          # JWT, bcrypt, Fernet encrypt/decrypt
        │   └── rate_limit.py        # slowapi limiter
        ├── models/
        │   ├── user.py              # User, UserRole
        │   ├── audit_log.py         # AuditLog, AuditAction
        │   └── workspace.py         # Workspace, WorkspaceMember, MemberRole (IN PROGRESS)
        ├── schemas/
        │   └── auth.py              # RegisterRequest, LoginRequest, TokenResponse, UserResponse
        ├── services/
        │   └── audit.py             # write_audit_log()
        └── tasks/                   # Celery tasks (not started)
```

## What's Built
- Auth system: register, login, refresh, logout, me
- RBAC dependency system
- Audit logging (append-only, SIEM-ready)
- Rate limiting (5/min on login, 100/min general)
- Field-level encryption for PII
- Account lockout after failed logins
- DB models: User, AuditLog

## What's In Progress
- `app/models/workspace.py` — Workspace and WorkspaceMember models being written by the developer

## What's Next (in order)
1. Finish workspace model → migration → schemas → routes
2. Collaborator invite system (email-based)
3. Dataset upload to MinIO (encrypted)
4. Statistical analysis jobs via Celery (Kaplan-Meier, regression, descriptive stats)
5. React + Vite frontend

## API Endpoints (implemented)
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/auth/register | None | Register (role=researcher by default) |
| POST | /api/auth/login | None | Returns access token + sets refresh cookie |
| POST | /api/auth/refresh | httpOnly cookie | Returns new access token |
| POST | /api/auth/logout | Bearer | Clears refresh cookie |
| GET | /api/auth/me | Bearer | Returns current user profile |

## Environment Variables (.env)
```
APP_ENV=development
SECRET_KEY=<32 byte hex>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/oncology_db
REDIS_URL=redis://localhost:6379/0
FERNET_KEY=<Fernet key>
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=oncology-datasets
MINIO_SECURE=false
```

## Notes
- Postgres runs on port 5433 (not 5432) because a local PostgreSQL installation occupies 5432
- venv is named `onco-research` and lives in `backend/onco-research/`
- bcrypt is pinned to 4.0.1 due to passlib incompatibility with newer versions
- The developer is learning FastAPI, SQLAlchemy, Pydantic and Alembic through this project
