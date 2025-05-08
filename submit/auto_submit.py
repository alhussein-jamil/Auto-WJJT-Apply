"""
Auto-submission module for job applications on Welcome to the Jungle.
Handles logging in, navigating to job pages, and submitting applications with generated documents.
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

from loguru import logger
from playwright.sync_api import sync_playwright

# Get settings
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings
from utils.logger import update_application_status

settings = get_settings()


class ApplicationSubmitter:
    """Submits job applications on Welcome to the Jungle."""

    def __init__(self, headless: Optional[bool] = None):
        """Initialize the application submitter."""
        self.headless = settings.playwright_headless if headless is None else headless
        self.base_url = settings.wttj_base_url
        self.browser = None
        self.page = None

    def __enter__(self):
        """Context manager entry - starts the browser."""
        self._start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - closes the browser."""
        self._close_browser()

    def _start_browser(self):
        """Start the Playwright browser."""
        playwright = sync_playwright().start()
        self.browser = playwright.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page()
        self.page.set_viewport_size({"width": 1920, "height": 1080})
        logger.info("Browser started for application submission")

    def _close_browser(self):
        """Close the Playwright browser."""
        if self.browser:
            self.browser.close()
            self.browser = None
            self.page = None
            logger.info("Browser closed")

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Login to Welcome to the Jungle. Returns True if successful."""
        if not username:
            username = settings.wttj_username
        if not password:
            password = settings.wttj_password

        if not username or not password:
            logger.warning("No credentials provided, continuing anonymously")
            return False

        try:
            self.page.goto(f"{self.base_url}/en/signin")
            self.page.fill('input[name="email"]', username)
            self.page.fill('input[name="password"]', password)
            self.page.click('button[type="submit"]')

            # Wait for navigation after login
            self.page.wait_for_url(f"{self.base_url}/en**", timeout=10000)

            # Check if login was successful
            if "signin" not in self.page.url:
                logger.info("Successfully logged in")
                return True
            else:
                logger.error("Login failed")
                return False

        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            return False

    def navigate_to_job(self, job_url: str) -> bool:
        """Navigate to the job page."""
        try:
            self.page.goto(job_url)
            self.page.wait_for_load_state("networkidle")

            # Verify we're on the job page
            title_element = self.page.query_selector("h1")
            if not title_element:
                logger.error(f"Could not find job title on page {job_url}")
                return False

            logger.info(f"Successfully navigated to job page: {title_element.inner_text().strip()}")
            return True

        except Exception as e:
            logger.error(f"Error navigating to job page {job_url}: {str(e)}")
            return False

    def click_apply_button(self) -> bool:
        """Find and click the apply button."""
        try:
            # Look for the apply button with different selectors
            apply_selectors = [
                "button[data-testid='apply-button']",
                "a[data-testid='apply-button']",
                "button:has-text('Apply')",
                "button:has-text('Apply for this job')"
            ]

            apply_button = None
            for selector in apply_selectors:
                apply_button = self.page.query_selector(selector)
                if apply_button:
                    break

            if not apply_button:
                logger.error("Could not find apply button")
                return False

            # Click the button and wait for the application form
            apply_button.click()
            time.sleep(2)  # Allow time for any animations or redirects

            # Check if we have a form
            form = self.page.query_selector("form")
            if not form:
                logger.error("No application form found after clicking apply")
                return False

            logger.info("Successfully clicked apply button and found application form")
            return True

        except Exception as e:
            logger.error(f"Error clicking apply button: {str(e)}")
            return False

    def fill_application_form(self, cv_path: Path, letter_path: Path) -> bool:
        """Fill out the application form with the generated documents."""
        try:
            # Wait for form to be fully loaded
            self.page.wait_for_selector("form", state="visible", timeout=10000)

            # Find and fill personal information fields
            self._fill_personal_info()

            # Upload CV and motivation letter
            if not self._upload_documents(cv_path, letter_path):
                return False

            # Check for additional fields and fill them if needed
            self._fill_additional_fields()

            logger.info("Successfully filled application form")
            return True

        except Exception as e:
            logger.error(f"Error filling application form: {str(e)}")
            return False

    def _fill_personal_info(self):
        """Fill personal information fields in the form."""
        # Common field patterns
        field_mappings = {
            "name": ["input[name*='name']", "input[placeholder*='name' i]", "input[aria-label*='name' i]"],
            "first_name": ["input[name*='first_name' i]", "input[placeholder*='first name' i]"],
            "last_name": ["input[name*='last_name' i]", "input[placeholder*='last name' i]"],
            "email": ["input[type='email']", "input[name*='email']", "input[placeholder*='email' i]"],
            "phone": ["input[type='tel']", "input[name*='phone']", "input[placeholder*='phone' i]"]
        }

        # Fill each field type if found
        for field_type, selectors in field_mappings.items():
            for selector in selectors:
                field = self.page.query_selector(selector)
                if field:
                    # Determine value based on field type
                    if field_type == "name":
                        field.fill(settings.name)
                    elif field_type == "first_name":
                        first_name = settings.name.split()[0] if " " in settings.name else settings.name
                        field.fill(first_name)
                    elif field_type == "last_name":
                        last_name = settings.name.split()[-1] if " " in settings.name else ""
                        field.fill(last_name)
                    elif field_type == "email":
                        field.fill(settings.email)
                    elif field_type == "phone":
                        # Leave phone empty or get from config in the future
                        pass

                    logger.debug(f"Filled {field_type} field")
                    break

    def _upload_documents(self, cv_path: Path, letter_path: Path) -> bool:
        """Upload CV and motivation letter to the application form."""
        try:
            # Find file upload fields
            file_inputs = self.page.query_selector_all("input[type='file']")

            if not file_inputs or len(file_inputs) == 0:
                logger.error("No file upload fields found in the form")
                return False

            # Typically the first file input is for CV
            cv_uploaded = False
            letter_uploaded = False

            # Look for labeled inputs first
            for input_field in file_inputs:
                # Try to find a label or aria-label
                label = None
                parent_label = self.page.evaluate("(element) => { const closest = element.closest('label'); return closest ? closest.textContent : null; }", input_field)

                if parent_label:
                    label = parent_label.lower()
                elif input_field.get_attribute("aria-label"):
                    label = input_field.get_attribute("aria-label").lower()

                # Upload based on label
                if label:
                    if "cv" in label or "resume" in label:
                        input_field.set_input_files(str(cv_path))
                        cv_uploaded = True
                        logger.info(f"Uploaded CV to labeled field: {label}")
                    elif "letter" in label or "motivation" in label or "cover" in label:
                        input_field.set_input_files(str(letter_path))
                        letter_uploaded = True
                        logger.info(f"Uploaded motivation letter to labeled field: {label}")

            # If we couldn't identify by labels, use position-based logic
            if not cv_uploaded and len(file_inputs) >= 1:
                file_inputs[0].set_input_files(str(cv_path))
                cv_uploaded = True
                logger.info("Uploaded CV to first file input")

            if not letter_uploaded and len(file_inputs) >= 2:
                file_inputs[1].set_input_files(str(letter_path))
                letter_uploaded = True
                logger.info("Uploaded motivation letter to second file input")

            # Check if uploads were successful
            if not cv_uploaded:
                logger.error("Failed to upload CV")
                return False

            # Some forms might only ask for CV
            if len(file_inputs) >= 2 and not letter_uploaded:
                logger.warning("Failed to upload motivation letter - might not be required")

            # Wait a moment for uploads to complete
            time.sleep(2)

            return True

        except Exception as e:
            logger.error(f"Error uploading documents: {str(e)}")
            return False

    def _fill_additional_fields(self):
        """Fill any additional required fields in the application form."""
        # Check for required fields that are empty
        required_fields = self.page.query_selector_all("input[required]:not([type='file']), textarea[required]")

        for field in required_fields:
            # Skip fields that are already filled
            if field.evaluate("(el) => el.value.length > 0"):
                continue

            field_type = field.get_attribute("type") or ""

            # Fill based on field type
            if field_type == "checkbox":
                field.check()
            elif field_type == "text" or field_type == "":
                # Try to determine what the field is for
                placeholder = field.get_attribute("placeholder") or ""
                name = field.get_attribute("name") or ""
                label_text = ""

                # Try to find associated label
                id_attr = field.get_attribute("id")
                if id_attr:
                    label = self.page.query_selector(f"label[for='{id_attr}']")
                    if label:
                        label_text = label.inner_text().lower()

                # Fill with appropriate value
                if any(term in (placeholder + name + label_text).lower() for term in ["linkedin", "github", "website"]):
                    field.fill("https://linkedin.com/in/username")  # Replace with actual profile URL
                else:
                    # Generic text for other fields
                    field.fill("Please see my attached CV and cover letter.")

    def submit_application(self) -> bool:
        """Submit the application form."""
        try:
            # Find the submit button
            submit_selectors = [
                "button[type='submit']",
                "button:has-text('Submit')",
                "button:has-text('Send')",
                "button:has-text('Apply')",
                "input[type='submit']"
            ]

            submit_button = None
            for selector in submit_selectors:
                submit_button = self.page.query_selector(selector)
                if submit_button:
                    break

            if not submit_button:
                logger.error("Could not find submit button")
                return False

            # Check if button is disabled
            is_disabled = submit_button.get_attribute("disabled") is not None
            if is_disabled:
                logger.error("Submit button is disabled - form may have missing required fields")
                return False

            # Click submit button
            logger.info("Submitting application...")
            submit_button.click()

            # Wait for submission to complete
            self.page.wait_for_load_state("networkidle", timeout=20000)

            # Check for success indicators
            success_indicators = [
                "//h1[contains(text(), 'Thank you')]",
                "//p[contains(text(), 'application has been submitted')]",
                "//div[contains(text(), 'successfully')]",
                "//div[contains(@class, 'success')]"
            ]

            for xpath in success_indicators:
                if self.page.query_selector(f"xpath={xpath}"):
                    logger.info("Application successfully submitted!")
                    return True

            # If we didn't find success indicators but also didn't get errors,
            # consider it a tentative success
            logger.info("Application submitted, but success couldn't be confirmed")
            return True

        except Exception as e:
            logger.error(f"Error submitting application: {str(e)}")
            return False


def submit_application(job: Dict[str, Any], documents: Dict[str, Path], headless: Optional[bool] = None) -> bool:
    """
    Submit an application for a job using generated documents.

    Args:
        job: Job details including URL
        documents: Dictionary with paths to CV and motivation letter
        headless: Whether to run browser in headless mode

    Returns:
        True if application was successfully submitted
    """
    job_id = job.get("job_id", "")
    job_url = job.get("url", "")

    if not job_url:
        logger.error("No job URL provided")
        update_application_status(job_id, "failed", "No job URL provided")
        return False

    cv_path = documents.get("cv")
    letter_path = documents.get("letter")

    if not cv_path or not letter_path:
        logger.error("Missing required documents")
        update_application_status(job_id, "failed", "Missing required documents")
        return False

    with ApplicationSubmitter(headless=headless) as submitter:
        # Try to login if credentials are available
        if settings.wttj_username and settings.wttj_password:
            submitter.login()

        # Navigate to job page
        if not submitter.navigate_to_job(job_url):
            update_application_status(job_id, "failed", "Failed to navigate to job page")
            return False

        # Click apply button and wait for form
        if not submitter.click_apply_button():
            update_application_status(job_id, "failed", "Failed to access application form")
            return False

        # Fill application form
        if not submitter.fill_application_form(cv_path, letter_path):
            update_application_status(job_id, "failed", "Failed to fill application form")
            return False

        # Submit application
        success = submitter.submit_application()
        if success:
            update_application_status(job_id, "success")
            logger.info(f"Successfully applied to job: {job.get('title')} at {job.get('company')}")
        else:
            update_application_status(job_id, "failed", "Failed to submit application")

        return success


if __name__ == "__main__":
    # Example usage
    from pathlib import Path

    example_job = {
        "job_id": "example-123",
        "title": "Python Developer",
        "company": "Example Corp",
        "url": "https://www.welcometothejungle.com/en/companies/example-corp/jobs/python-developer_paris"
    }

    example_docs = {
        "cv": Path("output/example_cv.pdf"),
        "letter": Path("output/example_letter.pdf")
    }

    success = submit_application(example_job, example_docs, headless=False)
    print(f"Application submission {'successful' if success else 'failed'}")