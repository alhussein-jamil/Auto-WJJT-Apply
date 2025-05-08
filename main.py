#!/usr/bin/env python3
"""
Auto WTTJ Applicator - Main Entry Point

Automates job applications on Welcome to the Jungle using AI-generated customized CVs and motivation letters.
"""

import os
import sys
import json
import uuid
from datetime import datetime, date
import sqlite3
from typing import Dict, Any
import time

import typer
from loguru import logger

from config import get_settings, Settings
from utils.logger import get_application_stats
from browser.wttj_scraper import WTTJScraper

# Import settings
settings = get_settings()

# Initialize typer app
app = typer.Typer(help="Auto WTTJ Applicator - Automate job applications on Welcome to the Jungle")

# Configure logger
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("logs/auto_wttj.log", rotation="10 MB", retention="1 week", level="DEBUG")

def init_db(db_path: str):
    """Initialize the SQLite database with necessary tables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create applications table if it doesn't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS applications (
        job_id TEXT PRIMARY KEY,
        company TEXT,
        title TEXT,
        url TEXT,
        status TEXT,
        applied_at TEXT,
        cv_path TEXT,
        letter_path TEXT,
        notes TEXT
    )
    ''')

    conn.commit()
    conn.close()

def add_application(db_path: str, **kwargs):
    """Add a new application record to the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get column names from the applications table
    cursor.execute("PRAGMA table_info(applications)")
    columns = [row[1] for row in cursor.fetchall()]

    # Filter the kwargs to include only existing columns
    filtered_kwargs = {k: v for k, v in kwargs.items() if k in columns}

    # Convert datetime objects to ISO format strings
    for key, value in filtered_kwargs.items():
        if isinstance(value, datetime):
            filtered_kwargs[key] = value.isoformat()

    # Prepare the SQL query
    columns_str = ", ".join(filtered_kwargs.keys())
    placeholders = ", ".join(["?"] * len(filtered_kwargs))
    values = tuple(filtered_kwargs.values())

    query = f"INSERT OR REPLACE INTO applications ({columns_str}) VALUES ({placeholders})"

    cursor.execute(query, values)
    conn.commit()
    conn.close()

def update_application(db_path: str, job_id: str, data: Dict[str, Any]):
    """Update an existing application record."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get column names from the applications table
    cursor.execute("PRAGMA table_info(applications)")
    columns = [row[1] for row in cursor.fetchall()]

    # Filter the data to include only existing columns
    filtered_data = {k: v for k, v in data.items() if k in columns and k != 'job_id'}

    if not filtered_data:
        conn.close()
        return

    # Convert datetime objects to ISO format strings
    for key, value in filtered_data.items():
        if isinstance(value, datetime):
            filtered_data[key] = value.isoformat()

    # Prepare the SET clause
    set_clause = ", ".join([f"{k} = ?" for k in filtered_data.keys()])
    values = list(filtered_data.values())
    values.append(job_id)  # Add job_id for the WHERE clause

    query = f"UPDATE applications SET {set_clause} WHERE job_id = ?"

    cursor.execute(query, values)
    conn.commit()
    conn.close()

def has_applied_to_job(db_path: str, job_id: str) -> bool:
    """Check if an application has already been submitted for a job."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM applications WHERE job_id = ?", (job_id,))
    count = cursor.fetchone()[0]

    conn.close()
    return count > 0

def count_applications_for_date(db_path: str, target_date: date) -> int:
    """Count applications submitted on a specific date."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Convert date to string format used in database
    date_str = target_date.isoformat()
    date_pattern = f"{date_str}%"  # Match the beginning of the ISO date string

    cursor.execute(
        "SELECT COUNT(*) FROM applications WHERE applied_at LIKE ? AND status != 'failed'",
        (date_pattern,)
    )
    count = cursor.fetchone()[0]

    conn.close()
    return count

@app.command()
def run(
    query: str = typer.Option(None, "--query", "-q", help="Job search query (e.g., 'python developer')"),
    location: str = typer.Option(None, "--location", "-l", help="Job location (e.g., 'Paris')"),
    max_jobs: int = typer.Option(5, "--max", "-m", help="Maximum number of jobs to process"),
    radius: int = typer.Option(20, "--radius", "-r", help="Search radius in km (when location is specified)"),
    dev_mode: bool = typer.Option(False, "--dev", "-d", help="Enable development mode with test data"),
):
    """Run the auto applicator with the specified parameters."""
    try:
        # Initialize config and database
        config = Settings()

        # Override config with command line options if provided
        config.max_jobs_per_run = max_jobs
        config.development_mode = dev_mode

        db_path = config.log_db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        init_db(db_path)

        # Log configuration
        logger.info(f"Database initialized at {db_path}")
        logger.info(f"Configuration: max jobs = {config.max_jobs_per_run}, daily limit = {config.max_applications_per_day}")

        # Check remaining applications for today
        today = datetime.now().date()
        applied_today = count_applications_for_date(db_path, today)
        remaining = config.max_applications_per_day - applied_today

        if remaining <= 0:
            logger.warning(f"Daily application limit reached ({config.max_applications_per_day}). Try again tomorrow.")
            return

        logger.info(f"Applications today: {applied_today}/{config.max_applications_per_day}, remaining: {remaining}")

        # Prepare filters
        filters = {}
        if query:
            filters["query"] = query
        if location:
            filters["location"] = location
            filters["radius"] = str(radius)

        if filters:
            filter_str = ", ".join(f"{k}: {v}" for k, v in filters.items())
            logger.info(f"Job filters: {filter_str}")
        else:
            logger.info("No job filters specified")

        # Get job listings
        with WTTJScraper(settings=config) as scraper:
            # Ensure we're logged in before getting job listings
            if config.user_email and config.user_password:
                logged_in = scraper.login(config.user_email, config.user_password)
                if logged_in:
                    logger.info(f"Successfully logged in as {config.user_email}")
                else:
                    logger.warning("Failed to log in with provided credentials. Continuing without login.")
            else:
                logger.warning("No WTTJ credentials provided in config. Will scrape without logging in.")

            jobs = scraper.get_internal_jobs(max_jobs=max_jobs, filters=filters)

        if not jobs:
            logger.error("No suitable jobs found. Try adjusting your search filters.")
            return

        logger.info(f"Found {len(jobs)} suitable jobs for application")

        # Process each job (limited by remaining applications)
        jobs_to_process = min(len(jobs), remaining)
        logger.info(f"Processing {jobs_to_process} jobs")

        for job in jobs[:jobs_to_process]:
            process_job(job, config)

    except Exception as e:
        logger.error(f"Error in run command: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


@app.command()
def show_stats():
    """Display application statistics."""
    stats = get_application_stats()

    typer.echo("Application Statistics:")
    typer.echo(f"  Total applications: {stats['total']}")
    typer.echo(f"  Successful: {stats['success']}")
    typer.echo(f"  Failed: {stats['failed']}")
    typer.echo(f"  Pending: {stats['pending']}")
    typer.echo(f"  Today: {stats['today']}")
    typer.echo(f"  Daily limit: {settings.max_applications_per_day}")
    typer.echo(f"  Remaining today: {max(0, settings.max_applications_per_day - stats['today'])}")


@app.command()
def setup():
    """
    Set up the environment for the application.
    Creates necessary directories and initializes the configuration.
    """
    # Ensure settings are loaded and paths exist
    settings.ensure_paths_exist()

    # Check if profile file exists and has content
    if not settings.base_profile_path.exists() or os.path.getsize(settings.base_profile_path) == 0:
        typer.echo("No profile data found. Let's create a basic profile.")
        create_profile()

    # Check if base CV file exists and has content
    if not settings.base_cv_path.exists() or os.path.getsize(settings.base_cv_path) == 0:
        typer.echo("No base CV found. Please create one at: " + str(settings.base_cv_path))
        typer.echo("You can use any text editor to create your CV in plain text format.")

    # Verify API keys
    if not settings.openai_api_key and settings.llm_provider == "openai":
        typer.echo("Warning: No OpenAI API key set. Please add it to your .env file.")
    if not settings.gemini_api_key and settings.llm_provider == "google":
        typer.echo("Warning: No Gemini API key set. Please add it to your .env file.")

    # Verify WTTJ credentials
    if not settings.wttj_username or not settings.wttj_password:
        typer.echo("Warning: No WTTJ credentials set. You can still use the tool but won't be able to apply to jobs that require login.")

    typer.echo("Setup complete! You can now run the application with: python main.py")


def create_profile():
    """Interactive profile creation helper."""
    profile = {
        "full_name": typer.prompt("Your full name"),
        "title": typer.prompt("Your professional title"),
        "summary": typer.prompt("A brief professional summary (2-3 sentences)"),
        "skills": {
            "programming_languages": typer.prompt("Programming languages (comma-separated)").split(","),
            "frameworks": typer.prompt("Frameworks (comma-separated)").split(","),
            "tools": typer.prompt("Tools (comma-separated)").split(","),
            "soft_skills": typer.prompt("Soft skills (comma-separated)").split(",")
        },
        "experience": []
    }

    # Add experience
    adding_experience = typer.confirm("Would you like to add work experience?", default=True)
    while adding_experience:
        experience = {
            "title": typer.prompt("Job title"),
            "company": typer.prompt("Company name"),
            "location": typer.prompt("Location"),
            "start_date": typer.prompt("Start date (YYYY-MM)"),
            "end_date": typer.prompt("End date (YYYY-MM or 'Present')"),
            "description": typer.prompt("Job description"),
            "technologies": typer.prompt("Technologies used (comma-separated)").split(",")
        }
        profile["experience"].append(experience)
        adding_experience = typer.confirm("Add another experience?", default=False)

    # Add education
    profile["education"] = []
    adding_education = typer.confirm("Would you like to add education?", default=True)
    while adding_education:
        education = {
            "degree": typer.prompt("Degree"),
            "institution": typer.prompt("Institution"),
            "location": typer.prompt("Location"),
            "graduation_date": typer.prompt("Graduation date (YYYY)"),
            "highlights": typer.prompt("Highlights (comma-separated)").split(",")
        }
        profile["education"].append(education)
        adding_education = typer.confirm("Add another education entry?", default=False)

    # Save to file
    with open(settings.base_profile_path, "w") as f:
        json.dump(profile, f, indent=4)

    typer.echo(f"Profile saved to {settings.base_profile_path}")


def process_job(job: Dict[str, Any], config: Settings):
    """Process a job listing and submit an application if applicable."""
    try:
        # Extract job details
        job_id = job.get("job_id", f"job_{int(time.time())}")
        job_title = job.get("title", "Unknown position")
        company = job.get("company", "Unknown company")
        job_url = job.get("url", "")

        logger.info(f"Processing job: {job_title} at {company}")

        # Check if we've already applied
        if has_applied_to_job(config.log_db_path, job_id):
            logger.info(f"Already applied to {job_title} at {company}, skipping")
            return False

        # Create application record with safely stringified values
        application = {
            "job_id": job_id,
            "company": str(company),
            "job_title": str(job_title),
            "job_url": str(job_url),
            "status": "pending",
            "applied_at": datetime.now().isoformat()  # Convert datetime to string immediately
        }

        try:
            # Log the pending application
            add_application(config.log_db_path, **application)
            logger.info(f"Added application record for {job_title}")
        except Exception as e:
            logger.error(f"Error adding application to database: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False

        # Generate tailored documents
        from llm.generate_documents import generate_documents_for_job
        documents = generate_documents_for_job(job, config.llm_provider)

        try:
            # Update application with document paths
            # Convert all paths to strings to avoid potential serialization issues
            application_update = {
                "cv_path": str(documents.get("cv", "")) if documents.get("cv") else "",
                "letter_path": str(documents.get("letter", "")) if documents.get("letter") else "",
                "status": "document_generated"
            }
            update_application(config.log_db_path, job_id, application_update)
            logger.info(f"Updated application with document paths")
        except Exception as e:
            logger.error(f"Error updating application with document paths: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # Continue anyway

        # Submit the application
        from browser.submit_application import submit_application
        success = submit_application(job, documents, config)

        try:
            # Final status update
            if success:
                logger.info(f"Successfully applied to {job_title} at {company}")
                status_update = {"status": "applied"}
            else:
                logger.warning(f"Failed to submit application to {job_title} at {company}")
                status_update = {"status": "failed"}

            update_application(config.log_db_path, job_id, status_update)
        except Exception as e:
            logger.error(f"Error updating final application status: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # Continue anyway

        return success

    except Exception as e:
        logger.error(f"Error processing job: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    # Run the CLI app
    app()