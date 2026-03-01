"""Job routes — list and detail endpoints with filtering support."""

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
    # Filters
    status: Optional[str] = Query(None, pattern="^(viewed|not_viewed|all)?$"),
    location: Optional[str] = Query(None, max_length=200),
    title: Optional[str] = Query(None, max_length=200),
    company: Optional[str] = Query(None, max_length=200),
    _user: str = Depends(get_current_user),
):
    """Return a paginated, filtered list of jobs."""
    offset = (page - 1) * limit

    # Build WHERE clauses dynamically
    conditions = []
    params: list = []

    # Status filter — based on apply_method column
    if status == "viewed":
        conditions.append("apply_method IS NOT NULL AND apply_method != 'Not viewed' AND apply_method != ''")
    elif status == "not_viewed":
        conditions.append("(apply_method IS NULL OR apply_method = 'Not viewed' OR apply_method = '')")

    # Text search filters (case-insensitive LIKE)
    if location:
        conditions.append("LOWER(location) LIKE LOWER(?)")
        params.append(f"%{location}%")

    if title:
        conditions.append("LOWER(title) LIKE LOWER(?)")
        params.append(f"%{title}%")

    if company:
        conditions.append("LOWER(company) LIKE LOWER(?)")
        params.append(f"%{company}%")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Safe sort columns (already validated by pattern above)
    sort_column = sort_by if sort_by else "scraped_at"
    sort_order = "DESC" if order == "desc" else "ASC"

    if sort_column == "score":
        order_clause = f"CASE WHEN score IS NULL THEN 1 ELSE 0 END, score {sort_order}"
    else:
        order_clause = f"{sort_column} {sort_order}"

    conn = _get_connection()
    try:
        cursor = conn.execute(
            f"SELECT * FROM jobs {where_clause} ORDER BY {order_clause} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        jobs = [dict(row) for row in cursor.fetchall()]

        count_cursor = conn.execute(f"SELECT COUNT(*) FROM jobs {where_clause}", params)
        total = count_cursor.fetchone()[0]
    finally:
        conn.close()

    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, (total + limit - 1) // limit),
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
