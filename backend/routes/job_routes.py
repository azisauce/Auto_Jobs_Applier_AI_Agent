"""Job routes — list and detail endpoints."""

import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import get_current_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

DB_PATH = str(Path(__file__).resolve().parent.parent.parent / "data_folder" / "jobs.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("")
async def list_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: Optional[str] = Query("scraped_at", pattern="^(scraped_at|score|title|company)$"),
    order: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    _user: str = Depends(get_current_user),
):
    """Return a paginated list of jobs."""
    offset = (page - 1) * limit

    # Safe sort columns (already validated by pattern above)
    sort_column = sort_by if sort_by else "scraped_at"
    sort_order = "DESC" if order == "desc" else "ASC"

    # Handle NULL scores — put them last when sorting by score
    if sort_column == "score":
        order_clause = f"CASE WHEN score IS NULL THEN 1 ELSE 0 END, score {sort_order}"
    else:
        order_clause = f"{sort_column} {sort_order}"

    conn = _get_connection()
    try:
        cursor = conn.execute(
            f"SELECT * FROM jobs ORDER BY {order_clause} LIMIT ? OFFSET ?",
            (limit, offset),
        )
        jobs = [dict(row) for row in cursor.fetchall()]

        total_cursor = conn.execute("SELECT COUNT(*) FROM jobs")
        total = total_cursor.fetchone()[0]
    finally:
        conn.close()

    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/{job_id}")
async def get_job(job_id: int, _user: str = Depends(get_current_user)):
    """Return a single job by its ID."""
    conn = _get_connection()
    try:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return dict(row)
