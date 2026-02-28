import sqlite3
import json
from pathlib import Path
from datetime import datetime

from src.logging import logger


class JobRepository:
    def __init__(self, db_path: str = "data_folder/jobs.db"):
        logger.debug(f"Initializing JobRepository with db_path: {db_path}")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._create_table()
        self._migrate_schema()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _create_table(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    linkedin_job_id TEXT,
                    title TEXT,
                    company TEXT,
                    location TEXT,
                    link TEXT UNIQUE,
                    apply_method TEXT,
                    description TEXT,
                    score INTEGER,
                    score_breakdown TEXT,
                    has_connections BOOLEAN DEFAULT 0,
                    connection_count INTEGER DEFAULT 0,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    scored_at TIMESTAMP
                )
            """)
            conn.commit()
        logger.debug("Jobs table created or already exists")

    def _migrate_schema(self):
        """Add new columns if they don't exist (for existing DBs)."""
        new_columns = [
            ("description", "TEXT"),
            ("score", "INTEGER"),
            ("score_breakdown", "TEXT"),
            ("has_connections", "BOOLEAN DEFAULT 0"),
            ("connection_count", "INTEGER DEFAULT 0"),
            ("scored_at", "TIMESTAMP"),
        ]
        with self._get_connection() as conn:
            cursor = conn.execute("PRAGMA table_info(jobs)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            for col_name, col_type in new_columns:
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
                    logger.debug(f"Migrated: added column '{col_name}' to jobs table")
            conn.commit()

    def insert_job(self, job) -> bool:
        """Insert a job into the database. Returns True if inserted, False if already exists."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs (linkedin_job_id, title, company, location, link, apply_method, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (job.id, job.title, job.company, job.location, job.link, job.apply_method, datetime.now())
                )
                conn.commit()
                if conn.total_changes > 0:
                    logger.debug(f"Inserted job: {job.title} at {job.company}")
                    return True
                else:
                    logger.debug(f"Job already exists: {job.title} at {job.company}")
                    return False
        except Exception as e:
            logger.error(f"Failed to insert job: {e}")
            return False

    def update_job_description(self, link: str, description: str):
        """Update the description for a job."""
        with self._get_connection() as conn:
            conn.execute("UPDATE jobs SET description = ? WHERE link = ?", (description, link))
            conn.commit()

    def update_job_score(self, link: str, score: int, score_breakdown: dict,
                         has_connections: bool = False, connection_count: int = 0):
        """Update scoring data for a job."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE jobs SET score = ?, score_breakdown = ?, has_connections = ?,
                    connection_count = ?, scored_at = ?
                WHERE link = ?
                """,
                (score, json.dumps(score_breakdown), has_connections, connection_count, datetime.now(), link)
            )
            conn.commit()

    def get_unscored_jobs(self) -> list:
        """Return all jobs that haven't been scored yet."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM jobs WHERE score IS NULL ORDER BY scraped_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_jobs_sorted_by_score(self, limit: int = 50) -> list:
        """Return jobs sorted by score descending."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE score IS NOT NULL ORDER BY score DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def job_exists(self, link: str) -> bool:
        """Check if a job with the given link already exists."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM jobs WHERE link = ?", (link,))
            return cursor.fetchone() is not None

    def get_all_jobs(self) -> list:
        """Return all stored jobs as a list of dicts."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM jobs ORDER BY scraped_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_job_count(self) -> int:
        """Return the total number of jobs stored."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM jobs")
            return cursor.fetchone()[0]
