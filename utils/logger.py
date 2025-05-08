"""
Logging utility for tracking job applications.
Uses SQLite to persist application logs and outcomes.
"""

import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, List

from loguru import logger
from pydantic import BaseModel

# Get settings
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings

settings = get_settings()

# Configure loguru logger
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("logs/app.log", rotation="10 MB", level="DEBUG", retention="1 week")


class JobApplication(BaseModel):
    """Model representing a job application record."""
    job_id: str
    company: str
    job_title: str
    job_url: str
    applied_at: datetime = datetime.now()
    status: str = "pending"  # pending, success, failed
    cv_path: Optional[str] = None
    letter_path: Optional[str] = None
    prompt: Optional[str] = None
    response: Optional[str] = None
    error_message: Optional[str] = None


def init_db():
    """Initialize the SQLite database with required tables."""
    conn = sqlite3.connect(settings.log_db_path)
    cursor = conn.cursor()

    # Create applications table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        company TEXT NOT NULL,
        job_title TEXT NOT NULL,
        job_url TEXT NOT NULL,
        applied_at TEXT NOT NULL,
        status TEXT NOT NULL,
        cv_path TEXT,
        letter_path TEXT,
        prompt TEXT,
        response TEXT,
        error_message TEXT
    )
    ''')

    conn.commit()
    conn.close()

    logger.info(f"Database initialized at {settings.log_db_path}")


def log_application(application: JobApplication):
    """Log a job application to the database."""
    conn = sqlite3.connect(settings.log_db_path)
    cursor = conn.cursor()

    cursor.execute('''
    INSERT INTO applications (
        job_id, company, job_title, job_url, applied_at,
        status, cv_path, letter_path, prompt, response, error_message
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        application.job_id,
        application.company,
        application.job_title,
        application.job_url,
        application.applied_at.isoformat(),
        application.status,
        application.cv_path,
        application.letter_path,
        application.prompt,
        application.response,
        application.error_message
    ))

    conn.commit()
    conn.close()

    logger.info(f"Logged application to {application.company} for {application.job_title} - Status: {application.status}")


def update_application_status(job_id: str, status: str, error_message: Optional[str] = None):
    """Update the status of an existing application."""
    conn = sqlite3.connect(settings.log_db_path)
    cursor = conn.cursor()

    if error_message:
        cursor.execute('''
        UPDATE applications SET status = ?, error_message = ? WHERE job_id = ?
        ''', (status, error_message, job_id))
    else:
        cursor.execute('''
        UPDATE applications SET status = ? WHERE job_id = ?
        ''', (status, job_id))

    conn.commit()
    conn.close()

    logger.info(f"Updated application status for job {job_id} to {status}")


def get_application_history(limit: int = 100) -> List[Dict[str, Any]]:
    """Get history of applications."""
    conn = sqlite3.connect(settings.log_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
    SELECT * FROM applications ORDER BY applied_at DESC LIMIT ?
    ''', (limit,))

    rows = cursor.fetchall()
    applications = [dict(row) for row in rows]

    conn.close()

    return applications


def has_applied_to_job(job_id: str) -> bool:
    """Check if already applied to a specific job."""
    conn = sqlite3.connect(settings.log_db_path)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT COUNT(*) FROM applications WHERE job_id = ?
    ''', (job_id,))

    count = cursor.fetchone()[0]
    conn.close()

    return count > 0


def get_application_stats() -> Dict[str, int]:
    """Get application statistics."""
    conn = sqlite3.connect(settings.log_db_path)
    cursor = conn.cursor()

    # Get total counts by status
    cursor.execute('''
    SELECT status, COUNT(*) FROM applications GROUP BY status
    ''')
    status_counts = dict(cursor.fetchall())

    # Get count for today
    today = datetime.now().date().isoformat()
    cursor.execute('''
    SELECT COUNT(*) FROM applications
    WHERE applied_at LIKE ?
    ''', (f"{today}%",))
    today_count = cursor.fetchone()[0]

    conn.close()

    return {
        "total": sum(status_counts.values()),
        "success": status_counts.get("success", 0),
        "failed": status_counts.get("failed", 0),
        "pending": status_counts.get("pending", 0),
        "today": today_count
    }


# Initialize the database when the module is imported
# init_db()