from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
import logging
import sys

from app.core.config import settings
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.api.routes import auth, workspace, invite, dataset
from app.api.routes.analysis import router as analysis_router, jobs_router

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
)

app = FastAPI(
    title="Oncology Research Platform API",
    version="0.1.0",
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url="/redoc" if settings.APP_ENV == "development" else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"] if settings.APP_ENV == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(workspace.router, prefix="/api")
app.include_router(invite.workspace_invite_router, prefix="/api")
app.include_router(invite.invite_router, prefix="/api")
app.include_router(dataset.router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok", "env": settings.APP_ENV}