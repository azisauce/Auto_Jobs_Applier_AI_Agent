"""FastAPI application entry point."""

import sys
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.auth import get_current_user
from backend.routes.auth_routes import router as auth_router
from backend.routes.job_routes import router as job_router
from backend.routes.script_routes import router as script_router

app = FastAPI(title="AIHawk Job Dashboard", version="1.0.0")

# CORS — allow Angular dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public routes (no auth)
app.include_router(auth_router)

# Protected routes (auth required)
app.include_router(job_router)
app.include_router(script_router)


# Auth check endpoint (used by Angular auth guard)
@app.get("/api/auth/me")
async def auth_me(user: str = Depends(get_current_user)):
    return {"authenticated": True, "username": user}


# Serve Angular static files in production
ANGULAR_DIST = PROJECT_ROOT / "frontend" / "dist" / "frontend" / "browser"
if ANGULAR_DIST.exists():
    app.mount("/", StaticFiles(directory=str(ANGULAR_DIST), html=True), name="angular")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
