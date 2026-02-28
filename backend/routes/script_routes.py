"""Script execution routes — trigger and monitor the CLI scripts."""

import subprocess
import sys
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user

router = APIRouter(prefix="/api/script", tags=["script"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ScriptType(str, Enum):
    COLLECT = "collect"
    SCORE = "score"


class RunScriptRequest(BaseModel):
    script_type: ScriptType = ScriptType.COLLECT


class ScriptStatus:
    """Singleton to track script execution state."""

    def __init__(self):
        self.running: bool = False
        self.script_type: Optional[str] = None
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.exit_code: Optional[int] = None
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def start(self, script_type: str):
        with self._lock:
            self.running = True
            self.script_type = script_type
            self.started_at = datetime.now().isoformat()
            self.finished_at = None
            self.exit_code = None
            self.error = None

    def finish(self, exit_code: int, error: Optional[str] = None):
        with self._lock:
            self.running = False
            self.finished_at = datetime.now().isoformat()
            self.exit_code = exit_code
            self.error = error

    def to_dict(self):
        with self._lock:
            return {
                "running": self.running,
                "script_type": self.script_type,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "exit_code": self.exit_code,
                "error": self.error,
            }


_status = ScriptStatus()


def _run_script_in_background(script_type: str):
    """Run the main.py script in a background thread."""
    try:
        flag = "--collect" if script_type == "collect" else "--score"
        result = subprocess.run(
            [sys.executable, "main.py", flag],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max
        )
        _status.finish(
            exit_code=result.returncode,
            error=result.stderr[-2000:] if result.returncode != 0 and result.stderr else None,
        )
    except subprocess.TimeoutExpired:
        _status.finish(exit_code=-1, error="Script timed out after 1 hour")
    except Exception as e:
        _status.finish(exit_code=-1, error=str(e))


@router.post("/run")
async def run_script(body: RunScriptRequest, _user: str = Depends(get_current_user)):
    """Start the collection or scoring script in the background."""
    if _status.running:
        raise HTTPException(status_code=409, detail="A script is already running")

    _status.start(body.script_type.value)

    thread = threading.Thread(target=_run_script_in_background, args=(body.script_type.value,), daemon=True)
    thread.start()

    return {"message": f"Script '{body.script_type.value}' started", "status": _status.to_dict()}


@router.get("/status")
async def get_script_status(_user: str = Depends(get_current_user)):
    """Get the current script execution status."""
    return _status.to_dict()
