"""
Welcome to the Jungle (WTTJ) scraper module.

This module provides functionality to scrape job listings from Welcome to the Jungle.
"""
import os
import time
import sys
import math
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, quote

from loguru import logger
from playwright.sync_api import sync_playwright

# Add parent directory to path to allow absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import Settings


class WTTJScraper:
    """Scrapes jobs from Welcome to the Jungle."""

    def __init__(self, settings: Optional[Settings] = None):
        """
        Initialize WTTJ scraper.

        Args:
            settings: Settings object
        """
        self.settings = settings or Settings()
        self.base_url = "https://www.welcometothejungle.com"
        self.jobs_url = f"{self.base_url}/en/jobs"
        self.page = None
        self.browser = None
        self.context = None
        self.logged_in = False
        self.logger = logger  # Use the imported logger

        # Create logs directory if it doesn't exist
        os.makedirs("logs", exist_ok=True)

    def __enter__(self):
        """Start the browser when entering the context."""
        self.start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the browser when exiting the context."""
        self.close_browser()

    def start_browser(self, headless: bool = True):
        """Start the browser session."""
        try:
            playwright = sync_playwright().start()
            browser_type = playwright.chromium
            self.browser = browser_type.launch(headless=headless)
            self.page = self.browser.new_page()
            self.page.set_viewport_size({"width": 1280, "height": 800})
            self.page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            self.logger.info("Browser started successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start browser: {str(e)}")
            return False

    def close_browser(self):
        """Close the browser session."""
        if self.browser:
            try:
                self.browser.close()
                self.logger.info("Browser closed successfully")
            except Exception as e:
                self.logger.error(f"Error closing browser: {str(e)}")
            finally:
                self.browser = None
                self.page = None

    def save_page_source(self, filepath="logs/page_source.html"):
        """Save the current page source to a file for debugging."""
        try:
            content = self.page.content()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self.logger.info(f"Page source saved to {filepath}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save page source: {str(e)}")
            return False

    def login(self, username: str, password: str) -> bool:
        """
        Log in to Welcome to the Jungle with improved reliability.

        Args:
            username: WTTJ username (email)
            password: WTTJ password

        Returns:
            True if login was successful, False otherwise
        """
        if not username or not password:
            self.logger.warning("No login credentials provided")
            return False

        # Number of retry attempts
        max_retries = 2
        retry_count = 0

        while retry_count <= max_retries:
            try:
                if retry_count > 0:
                    self.logger.info(f"Retry attempt {retry_count} of {max_retries}")

                self.logger.info(f"Attempting to log in as {username}")

                # Use a longer timeout for the initial page load
                login_url = f"{self.base_url}/en/login"

                # Clear cookies and cache before attempting login
                if retry_count > 0:
                    self.logger.info("Clearing cookies and cache before retry")
                    self.page.context.clear_cookies()

                # Navigate to login page with increased timeout
                try:
                    self.logger.info(f"Navigating to {login_url}")
                    self.page.goto(login_url, timeout=60000)
                except Exception as e:
                    self.logger.warning(f"Navigation timeout, but continuing: {str(e)}")
                    # Even if timeout occurs, page might have loaded enough to continue

                # Check if the page is actually loaded
                if not self.page.url:
                    self.logger.error("Page failed to load at all")
                    retry_count += 1
                    continue

                # Wait for page to stabilize
                try:
                    self.page.wait_for_load_state("networkidle", timeout=15000)
                except Exception as e:
                    self.logger.warning(f"Wait for load state timed out, but continuing: {str(e)}")

                # Take a screenshot before login
                self.page.screenshot(path=f"logs/login_page_before_{retry_count}.png")
                self.save_page_source(f"logs/login_page_before_{retry_count}.html")

                # Check for WTTJ maintenance page
                if "maintenance" in self.page.content().lower():
                    self.logger.error("WTTJ site is in maintenance mode")
                    return False

                # Check if we're already logged in
                sign_in_button = self.page.query_selector("text=Sign in")

                if not sign_in_button:
                    self.logger.info("Already logged in or login page has different structure")

                    # Check for user avatar which indicates logged-in state
                    user_avatar = self.page.query_selector("a[href='/en/profile']") or self.page.query_selector("img[alt='User avatar']")
                    if user_avatar:
                        self.logger.info("Already logged in (detected user avatar)")
                        return True

                # Handle cookie banner if present (with shorter timeout)
                cookie_selectors = [
                    "button:has-text('Accept all cookies')",
                    "button:has-text('OK for me')",
                    "button:has-text('Got it!')"
                ]

                for selector in cookie_selectors:
                    try:
                        if self.page.is_visible(selector, timeout=5000):
                            self.page.click(selector)
                            self.logger.info(f"Clicked cookie consent: {selector}")
                            self.page.wait_for_timeout(1000)  # Wait a moment after clicking
                            break
                    except Exception as e:
                        self.logger.warning(f"Error clicking cookie consent: {str(e)}")

                # Handle location popup if present
                location_popup_handled = self._handle_location_popup_during_login()
                if location_popup_handled:
                    self.logger.info("Location popup handled during login")

                # Wait briefly after handling popups
                self.page.wait_for_timeout(1000)

                # Take another screenshot after popups
                self.page.screenshot(path=f"logs/login_after_popups_{retry_count}.png")

                # Try LinkedIn login first if available
                linkedin_login = self._try_linkedin_login(username, password)
                if linkedin_login:
                    self.logger.info("LinkedIn login successful")
                    return True

                # Find and fill email field - try multiple selectors for robustness
                email_selectors = [
                    'input[type="email"]',
                    'input[name="email"]',
                    'input[placeholder*="email" i]',
                    'input[placeholder*="Email" i]'
                ]

                email_filled = False
                for selector in email_selectors:
                    try:
                        if self.page.is_visible(selector, timeout=5000):
                            self.page.fill(selector, username)
                            self.logger.info(f"Filled email using selector: {selector}")
                            email_filled = True
                            break
                    except Exception as e:
                        self.logger.warning(f"Error filling email with selector {selector}: {str(e)}")

                if not email_filled:
                    self.logger.error("Could not find email field")
                    self.page.screenshot(path=f"logs/login_email_not_found_{retry_count}.png")
                    retry_count += 1
                    continue

                # Find and fill password field
                password_selectors = [
                    'input[type="password"]',
                    'input[name="password"]',
                    'input[placeholder*="password" i]',
                    'input[placeholder*="Password" i]'
                ]

                password_filled = False
                for selector in password_selectors:
                    try:
                        if self.page.is_visible(selector, timeout=5000):
                            self.page.fill(selector, password)
                            self.logger.info(f"Filled password using selector: {selector}")
                            password_filled = True
                            break
                    except Exception as e:
                        self.logger.warning(f"Error filling password with selector {selector}: {str(e)}")

                if not password_filled:
                    self.logger.error("Could not find password field")
                    self.page.screenshot(path=f"logs/login_password_not_found_{retry_count}.png")
                    retry_count += 1
                    continue

                # Find and click submit button
                submit_selectors = [
                    'button[type="submit"]',
                    'button:has-text("Log in")',
                    'button:has-text("Sign in")',
                    'input[type="submit"]'
                ]

                submit_clicked = False
                for selector in submit_selectors:
                    try:
                        if self.page.is_visible(selector, timeout=5000):
                            # Take a screenshot before clicking
                            self.page.screenshot(path=f"logs/login_before_submit_{retry_count}.png")

                            # Click the button
                            self.page.click(selector)
                            self.logger.info(f"Clicked submit button: {selector}")
                            submit_clicked = True
                            break
                    except Exception as e:
                        self.logger.warning(f"Error clicking submit with selector {selector}: {str(e)}")

                if not submit_clicked:
                    self.logger.error("Could not find login submit button")
                    self.page.screenshot(path=f"logs/login_submit_not_found_{retry_count}.png")
                    retry_count += 1
                    continue

                # Wait for navigation after login with more generous timeout
                try:
                    self.page.wait_for_load_state("networkidle", timeout=30000)
                except Exception as e:
                    self.logger.warning(f"Timeout waiting after login submit, but continuing: {str(e)}")

                # Take a screenshot after login attempt
                self.page.screenshot(path=f"logs/login_after_submit_{retry_count}.png")
                self.save_page_source(f"logs/login_after_submit_{retry_count}.html")

                # Multiple checks to verify login success
                login_success = self._verify_login_success()
                if login_success:
                    self.logger.info("Login successful! Verification completed.")
                    return True

                # If we get here, login failed - try again
                self.logger.warning(f"Login attempt {retry_count + 1} failed")
                retry_count += 1

                # Wait before next retry
                self.page.wait_for_timeout(5000)

            except Exception as e:
                self.logger.error(f"Error during login attempt {retry_count + 1}: {str(e)}")
                import traceback
                self.logger.error(traceback.format_exc())
                self.page.screenshot(path=f"logs/login_error_{retry_count}.png")
                retry_count += 1

                # Wait before next retry
                self.page.wait_for_timeout(5000)

        # If we get here, all retries failed
        self.logger.error(f"Login failed after {max_retries + 1} attempts")
        return False


    def _handle_location_popup_during_login(self) -> bool:
        """Handle location popups specifically during login process."""
        try:
            # Check for the "Looks like you're in France?" popup
            france_popup_texts = [
                "Looks like you're in France",
                "It looks like you're in France",
                "Stay on the current website"
            ]

            # Look for any text containing these phrases
            for text in france_popup_texts:
                try:
                    text_element = self.page.query_selector(f"text={text}")
                    if text_element:
                        self.logger.info(f"Found location popup with text: {text}")

                        # Look for "Stay" buttons
                        stay_buttons = [
                            "button:has-text('Stay on the current website')",
                            "button:has-text('Stay on this website')",
                            "button:has-text('Stay')",
                            ".modal-footer button:nth-child(2)",  # Usually the second button is "Stay"
                        ]

                        for button in stay_buttons:
                            try:
                                if self.page.is_visible(button, timeout=3000):
                                    self.page.click(button)
                                    self.logger.info(f"Clicked 'Stay' button: {button} during login")
                                    self.page.wait_for_timeout(1000)
                                    return True
                            except Exception as e:
                                self.logger.warning(f"Error clicking stay button {button}: {str(e)}")

                        # If we couldn't find a specific button, try clicking close button
                        close_buttons = [
                            "button[aria-label='Close']",
                            "button.close",
                            "[data-testid='modal-close']"
                        ]

                        for button in close_buttons:
                            try:
                                if self.page.is_visible(button, timeout=2000):
                                    self.page.click(button)
                                    self.logger.info(f"Clicked close button: {button} during login")
                                    self.page.wait_for_timeout(1000)
                                    return True
                            except Exception as e:
                                self.logger.warning(f"Error clicking close button {button}: {str(e)}")
                except Exception as e:
                    self.logger.warning(f"Error checking for text '{text}': {str(e)}")

            return False
        except Exception as e:
            self.logger.warning(f"Error in _handle_location_popup_during_login: {str(e)}")
            return False


    def _try_linkedin_login(self, username: str, password: str) -> bool:
        """Try to login via LinkedIn if the option is available."""
        try:
            linkedin_selectors = [
                "a[href*='linkedin']",
                "a:has-text('Continue with LinkedIn')",
                "button:has-text('Continue with LinkedIn')",
                "button:has-text('Sign in with LinkedIn')",
                "a:has-text('Sign in with LinkedIn')"
            ]

            for selector in linkedin_selectors:
                try:
                    if self.page.is_visible(selector, timeout=3000):
                        self.page.screenshot(path="logs/before_linkedin_click.png")
                        self.logger.info(f"Found LinkedIn login option: {selector}")

                        # Click the LinkedIn button
                        self.page.click(selector)
                        self.logger.info("Clicked LinkedIn login button")

                        # Wait for LinkedIn page to load
                        try:
                            self.page.wait_for_load_state("networkidle", timeout=20000)
                        except Exception as e:
                            self.logger.warning(f"Timeout waiting for LinkedIn page to load: {str(e)}")

                        self.page.screenshot(path="logs/linkedin_login_page.png")

                        # Check if we're on LinkedIn domain
                        if "linkedin.com" in self.page.url:
                            self.logger.info("Successfully navigated to LinkedIn login")

                            # Fill LinkedIn email field
                            email_filled = False
                            for email_selector in ["input#username", "input[name='session_key']", "input[type='email']"]:
                                try:
                                    if self.page.is_visible(email_selector, timeout=5000):
                                        self.page.fill(email_selector, username)
                                        self.logger.info(f"Filled LinkedIn email using selector: {email_selector}")
                                        email_filled = True
                                        break
                                except Exception as e:
                                    self.logger.warning(f"Error filling LinkedIn email: {str(e)}")

                            if not email_filled:
                                self.logger.error("Could not find LinkedIn email field")
                                self.page.screenshot(path="logs/linkedin_email_not_found.png")
                                return False

                            # Fill LinkedIn password field
                            password_filled = False
                            for password_selector in ["input#password", "input[name='session_password']", "input[type='password']"]:
                                try:
                                    if self.page.is_visible(password_selector, timeout=5000):
                                        self.page.fill(password_selector, password)
                                        self.logger.info(f"Filled LinkedIn password using selector: {password_selector}")
                                        password_filled = True
                                        break
                                except Exception as e:
                                    self.logger.warning(f"Error filling LinkedIn password: {str(e)}")

                            if not password_filled:
                                self.logger.error("Could not find LinkedIn password field")
                                self.page.screenshot(path="logs/linkedin_password_not_found.png")
                                return False

                            # Click LinkedIn sign in button
                            sign_in_clicked = False
                            for sign_in_selector in ["button[type='submit']", "button:has-text('Sign in')"]:
                                try:
                                    if self.page.is_visible(sign_in_selector, timeout=5000):
                                        self.page.click(sign_in_selector)
                                        self.logger.info(f"Clicked LinkedIn sign in button: {sign_in_selector}")
                                        sign_in_clicked = True
                                        break
                                except Exception as e:
                                    self.logger.warning(f"Error clicking LinkedIn sign in: {str(e)}")

                            if not sign_in_clicked:
                                self.logger.error("Could not find LinkedIn sign in button")
                                self.page.screenshot(path="logs/linkedin_sign_in_not_found.png")
                                return False

                            # Wait for redirect back to WTTJ
                            try:
                                self.page.wait_for_load_state("networkidle", timeout=30000)
                            except Exception as e:
                                self.logger.warning(f"Timeout waiting for redirect after LinkedIn login: {str(e)}")

                            self.page.screenshot(path="logs/after_linkedin_login.png")

                            # Check for LinkedIn authorization screen
                            authorize_clicked = False
                            for authorize_selector in ["button:has-text('Allow')", "button:has-text('Authorize')", "button:has-text('Continue')"]:
                                try:
                                    if self.page.is_visible(authorize_selector, timeout=5000):
                                        self.page.click(authorize_selector)
                                        self.logger.info(f"Clicked LinkedIn authorization button: {authorize_selector}")
                                        authorize_clicked = True
                                        break
                                except Exception as e:
                                    self.logger.warning(f"Error with LinkedIn authorization: {str(e)}")

                            if authorize_clicked:
                                # Wait again for final redirect
                                try:
                                    self.page.wait_for_load_state("networkidle", timeout=30000)
                                except Exception as e:
                                    self.logger.warning(f"Timeout waiting after LinkedIn authorization: {str(e)}")

                                self.page.screenshot(path="logs/after_linkedin_authorization.png")

                                # Check if we're back on WTTJ and logged in
                                if "welcometothejungle.com" in self.page.url:
                                    login_success = self._verify_login_success()
                                    if login_success:
                                        self.logger.info("LinkedIn login successful!")
                                        return True

                                self.logger.warning("LinkedIn login process completed but login verification failed")
                                return False
                            else:
                                self.logger.warning("Clicked LinkedIn login but didn't navigate to LinkedIn domain")
                                return False
                except Exception as e:
                    self.logger.warning(f"Error with LinkedIn selector {selector}: {str(e)}")

            self.logger.info("No LinkedIn login option found")
            return False

        except Exception as e:
            self.logger.error(f"Error in LinkedIn login attempt: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False


    def _verify_login_success(self) -> bool:
        """Verify if login was successful using multiple checks."""

        # Check 1: URL check - we should no longer be on the login page
        current_url = self.page.url
        if "/login" in current_url or "/sign-in" in current_url:
            self.logger.warning("Still on login page after submission - login likely failed")

            # Check for error messages
            try:
                error_elements = self.page.query_selector_all("div.error-message, p.error, .error-text")
                if error_elements:
                    for error in error_elements:
                        error_text = error.inner_text()
                        if error_text:
                            self.logger.error(f"Login error message: {error_text}")
            except Exception as e:
                self.logger.warning(f"Error checking for error messages: {str(e)}")

            return False

        # Check 2: Look for user avatar or profile elements
        avatar_selectors = [
            "a[href='/en/profile']",
            "img[alt='User avatar']",
            "a[href*='account']",
            ".user-profile-icon"
        ]

        for selector in avatar_selectors:
            try:
                if self.page.is_visible(selector, timeout=3000):
                    self.logger.info(f"Found profile element after login: {selector}")
                    return True
            except Exception as e:
                continue

        # Check 3: Look for elements that indicate we're logged in
        logged_in_indicators = [
            "a:has-text('Profile')",
            "a:has-text('My Account')",
            "a:has-text('Sign out')",
            "a:has-text('Log out')"
        ]

        for selector in logged_in_indicators:
            try:
                if self.page.is_visible(selector, timeout=3000):
                    self.logger.info(f"Found logged-in indicator: {selector}")
                    return True
            except Exception as e:
                continue

        # Check 4: Look for elements that indicate we're still in the login process
        login_elements = [
            "input[type='password']",
            "button:has-text('Log in')",
            "button:has-text('Sign in')"
        ]

        for selector in login_elements:
            try:
                if self.page.is_visible(selector, timeout=3000):
                    self.logger.warning(f"Still seeing login element: {selector} - login failed")
                    return False
            except Exception as e:
                continue

        # If we've reached here without a clear indicator, check if we're still on the login page
        if "/login" not in current_url and "/sign-in" not in current_url:
            self.logger.info("Login appears to be successful based on URL change")
            return True

        # If we reach here, login status is inconclusive
        self.logger.warning("Login status inconclusive - will proceed with caution")
        return False

    def get_job_listings(self, query: str, location: str = None, radius: int = 20, page_num: int = 1) -> list:
        """
        Get job listings from Welcome to the Jungle based on search filters.

        Args:
            query: Job search query (e.g., "Python Developer")
            location: Location (e.g., "Paris")
            radius: Search radius in km (default: 20)
            page_num: Page number to fetch (default: 1)

        Returns:
            List of job dictionaries from the search results
        """
        jobs = []
        try:
            # Handle language/region settings
            self._accept_cookies()
            self._check_and_handle_region_popup()

            # Determine if we should use English or French version
            current_url = self.page.url
            locale = "en"
            if "/fr/" in current_url:
                locale = "fr"
                self.logger.info("Using French locale for search")

            # Default Paris coordinates if no location specified
            paris_coordinates = "48.856614,2.3522219"

            # Build search URL with parameters
            params = {
                "query": query,
                "page": page_num,
                "aroundRadius": radius * 1000  # Convert to meters
            }

            # Add location parameters if specified
            if location:
                # Try to get coordinates for the location
                coordinates = self._get_coordinates_for_location(location) or paris_coordinates
                params["aroundLatLng"] = coordinates

                # Add country filter (default to France if not specified)
                params["refinementList[offices.country_code][]"] = "FR"

            # Construct final search URL
            search_params = "&".join([f"{k}={v}" for k, v in params.items()])
            search_url = f"https://www.welcometothejungle.com/{locale}/jobs?{search_params}"

            self.logger.info(f"Searching jobs with URL: {search_url}")
            self.page.goto(search_url, timeout=60000)
            self.page.wait_for_load_state("networkidle", timeout=30000)

            # Save page source for debugging
            self.save_page_source(f"search_page_{page_num}.html")
            self.page.screenshot(path=f"logs/search_page_{page_num}.png")

            # Wait for the jobs container to load
            job_container_selector = "[data-testid='job-list']"
            try:
                self.page.wait_for_selector(job_container_selector, timeout=10000)
            except Exception as e:
                self.logger.warning(f"Could not find job container: {str(e)}")
                # Check for alternative job containers
                alt_job_containers = [
                    "section.sc-bXCLTC",  # Common WTTJ class for job results
                    "div.ais-Hits",
                    "div[data-testid='search-results']"
                ]
                for container in alt_job_containers:
                    try:
                        if self.page.is_visible(container):
                            job_container_selector = container
                            self.logger.info(f"Found alternative job container: {container}")
                            break
                    except:
                        continue

            # Parse job listings from the page
            job_link_selector = f"{job_container_selector} a[href*='/jobs/']:not([href*='@'])"
            job_elements = self.page.query_selector_all(job_link_selector)

            self.logger.info(f"Found {len(job_elements)} job elements on page {page_num}")

            for element in job_elements:
                try:
                    # Get job details
                    href = element.get_attribute("href")

                    # Extract job ID and slugs from URL
                    job_parts = href.split("/jobs/")[1].split("-at-")
                    if len(job_parts) >= 2:
                        job_slug = job_parts[0].strip()
                        company_slug = job_parts[1].split("/")[0].strip()

                        # Get job title
                        title_element = element.query_selector("h3, h4, .job-title")
                        title = title_element.inner_text() if title_element else "Unknown Title"

                        # Get company name
                        company_element = element.query_selector(".company-name, [data-testid='job-card-company']")
                        company = company_element.inner_text() if company_element else "Unknown Company"

                        # Build full URL if it's a relative URL
                        if href.startswith("/"):
                            base_url = "https://www.welcometothejungle.com"
                            href = f"{base_url}{href}"

                        job = {
                            "id": f"{company_slug}_{job_slug}",
                            "title": title,
                            "company": company,
                            "url": href,
                            "job_slug": job_slug,
                            "company_slug": company_slug
                        }
                        jobs.append(job)
                except Exception as e:
                    self.logger.warning(f"Error parsing job element: {str(e)}")
                    continue

            # Check if there are more pages
            next_page_selector = "a[aria-label='Next']"
            has_next_page = self.page.is_visible(next_page_selector)

            self.logger.info(f"Found {len(jobs)} jobs on page {page_num}, has_next_page: {has_next_page}")

        except Exception as e:
            self.logger.error(f"Error getting job listings: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())

        return jobs

    def _check_and_handle_region_popup(self) -> None:
        """Handle region popups that appear on WTTJ site"""
        try:
            # Look for "Looks like you're in France?" popup
            selectors = [
                "[role='dialog']",
                ".modal-content",
                "div:has-text('Looks like you')"
            ]

            for selector in selectors:
                if self.page.is_visible(selector, timeout=3000):
                    self.logger.info(f"Found region popup: {selector}")
                    self.page.screenshot(path=f"logs/region_popup.png")

                    # Look for the stay button
                    stay_buttons = [
                        "button:has-text('Stay on the current website')",
                        "button:has-text('Stay')",
                        ".modal-footer button:nth-child(2)",  # Usually the second button is "Stay"
                        "[role='dialog'] button:nth-child(2)"
                    ]

                    for button in stay_buttons:
                        try:
                            if self.page.is_visible(button):
                                self.page.click(button)
                                self.logger.info(f"Clicked 'Stay' button: {button}")
                                self.page.wait_for_timeout(2000)
                                return
                        except Exception as e:
                            self.logger.warning(f"Error clicking stay button {button}: {str(e)}")

                    # If we couldn't find a specific button, try clicking close button
                    close_buttons = [
                        "button[aria-label='Close']",
                        "button.close",
                        "[data-testid='modal-close']",
                        ".modal-header button"
                    ]

                    for button in close_buttons:
                        try:
                            if self.page.is_visible(button):
                                self.page.click(button)
                                self.logger.info(f"Clicked close button: {button}")
                                self.page.wait_for_timeout(2000)
                                return
                        except Exception as e:
                            self.logger.warning(f"Error clicking close button {button}: {str(e)}")

        except Exception as e:
            self.logger.warning(f"Error handling region popup: {str(e)}")

    def _get_coordinates_for_location(self, location: str) -> str:
        """
        Get coordinates for a location.
        This is a simple implementation that returns hardcoded coordinates for common locations.

        Args:
            location: Location name

        Returns:
            String with latitude,longitude or None if not found
        """
        location_map = {
            "paris": "48.856614,2.3522219",
            "lyon": "45.764043,4.835659",
            "marseille": "43.296482,5.36978",
            "lille": "50.62925,3.057256",
            "bordeaux": "44.837789,-0.57918",
            "toulouse": "43.604652,1.444209",
            "nice": "43.7101728,7.2619532",
            "nantes": "47.218371,-1.553621"
        }

        # Normalize location name
        normalized_location = location.lower().strip()

        # Check if we have coordinates for this location
        if normalized_location in location_map:
            return location_map[normalized_location]

        # Return None if not found - we'll use default coordinates
        return None

    def get_job_details(self, job_url: str) -> Dict[str, Any]:
        """
        Extract job details from a job page.

        Args:
            job_url: URL of the job posting

        Returns:
            Dictionary with job details
        """
        # Check if this is a fake URL from development mode
        if self.settings.development_mode and "company-example" in job_url:
            return self._get_mock_job_details(job_url)

        details = {
            "title": "",
            "company": "",
            "description": "",
            "url": job_url,
            "id": job_url.split("/")[-1],
            "allow_internal_apply": False
        }

        try:
            # Navigate to the job page
            self.page.goto(job_url, timeout=15000)
            self.page.wait_for_load_state("networkidle", timeout=10000)

            # Save page for debugging
            job_id_safe = details['id'].split('?')[0]  # Remove query params for filename
            self.save_page_source(f"logs/job_page_{job_id_safe}.html")
            self.page.screenshot(path=f"logs/job_page_{job_id_safe}.png")

            # Extract job title
            title_selectors = [
                "h1",
                "h1.ais-Highlight",
                "h2.ais-Highlight",
                "h1[data-testid='job-title']"
            ]
            for selector in title_selectors:
                title_element = self.page.query_selector(selector)
                if title_element:
                    details["title"] = title_element.inner_text().strip()
                    break

            # Extract company name
            company_selectors = [
                "a[data-testid='company-name']",
                ".sc-bXCLTC",
                "div[data-testid='company-name']"
            ]
            for selector in company_selectors:
                company_element = self.page.query_selector(selector)
                if company_element:
                    details["company"] = company_element.inner_text().strip()
                    break

            # Extract job description
            description_selectors = [
                "div[data-testid='job-description']",
                ".sc-bXCLTC",
                "section[data-testid='job-section-description']"
            ]
            for selector in description_selectors:
                description_element = self.page.query_selector(selector)
                if description_element:
                    details["description"] = description_element.inner_text().strip()
                    break

            # More robust way to check if this allows internal application - no clicking needed

            # 1. Check if the apply button exists and what kind it is
            apply_button_selectors = [
                "a[data-testid='job-apply-button']",
                "button[data-testid='job-apply-button']",
                "a.ais-Highlight",
                "a[href*='apply']",
                "button:has-text('Apply')"
            ]

            # First, try to determine if we have an external link
            for selector in apply_button_selectors:
                apply_button = self.page.query_selector(selector)
                if apply_button and apply_button.is_visible():
                    # Check if it's an external link
                    href = apply_button.get_attribute("href")
                    if href:
                        # If link goes to external site, it's not an internal application
                        if (href.startswith("http://") or href.startswith("https://")) and self.base_url not in href:
                            self.logger.info(f"Apply button leads to external URL: {href}")
                            details["allow_internal_apply"] = False
                            break

                    # Check button text for clues
                    button_text = apply_button.inner_text().lower()
                    if "apply on company website" in button_text or "external" in button_text:
                        details["allow_internal_apply"] = False
                        break

                    # If we made it here, it's likely an internal button
                    # But let's do more checks to be sure

            # 2. Check for direct evidence of internal application capability
            internal_indicators = [
                # Form elements or upload indicators
                "input[type='file']",
                "textarea[name*='cover']",
                "textarea[name*='motivation']",
                "form[action*='apply']",
                "button[type='submit']",

                # WTTJ-specific patterns
                "div[role='dialog']",
                "h2:has-text('My information')",
                "h2:has-text('Apply')",
                "[data-testid='application-form']",

                # Elements visible before clicking that indicate internal application
                "[data-testid='job-apply-container']",
                "div.job-application-container",
                "button[data-testid='form-submit-button']",

                # Text indicators
                "div:has-text('Upload your resume')",
                "div:has-text('Upload your CV')",
                "div:has-text('Already have an account')"
            ]

            for indicator in internal_indicators:
                if self.page.query_selector(indicator):
                    self.logger.info(f"Found internal application indicator: {indicator}")
                    details["allow_internal_apply"] = True
                    break

            # 3. Check page source for key patterns if we still don't know
            if not details["allow_internal_apply"]:
                page_content = self.page.content().lower()
                internal_keywords = [
                    "upload your cv",
                    "upload your resume",
                    "fill in the form",
                    "cover letter",
                    "motivation letter",
                    "application form",
                    "sign in to apply",
                    "login to apply"
                ]

                for keyword in internal_keywords:
                    if keyword in page_content:
                        self.logger.info(f"Found internal application keyword in page content: {keyword}")
                        details["allow_internal_apply"] = True
                        break

            # 4. Final check - if there's an apply button, but we haven't determined it's external,
            # and we don't have clear signs of an internal application, we'll try a simulated click
            # just to see if a dialog or form appears without actually processing it
            if not details["allow_internal_apply"]:
                for selector in apply_button_selectors:
                    apply_button = self.page.query_selector(selector)
                    if apply_button and apply_button.is_visible():
                        try:
                            self.logger.info("Performing safe click check on apply button")

                            # Create a MutationObserver to detect if a dialog or form appears
                            dialog_check_script = """
                            () => {
                                return new Promise((resolve) => {
                                    // Flag to track if we found anything
                                    let foundDialog = false;

                                    // Set up mutation observer
                                    const observer = new MutationObserver((mutations) => {
                                        for (const mutation of mutations) {
                                            if (mutation.addedNodes.length) {
                                                // Check if any added nodes look like dialogs or forms
                                                for (const node of mutation.addedNodes) {
                                                    if (node.nodeType === 1) { // Element node
                                                        const element = node;
                                                        if (
                                                            element.tagName === 'FORM' ||
                                                            element.tagName === 'DIALOG' ||
                                                            element.getAttribute('role') === 'dialog' ||
                                                            element.classList.contains('modal') ||
                                                            element.querySelector('form') ||
                                                            element.querySelector('input[type="file"]') ||
                                                            element.querySelector('textarea')
                                                        ) {
                                                            foundDialog = true;
                                                            observer.disconnect();
                                                            resolve(true);
                                                            return;
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    });

                                    // Start observing
                                    observer.observe(document.body, {
                                        childList: true,
                                        subtree: true
                                    });

                                    // Click the button
                                    const button = document.querySelector('""" + selector + """');
                                    if (button) {
                                        button.click();
                                    }

                                    // Set timeout to resolve if nothing happens
                                    setTimeout(() => {
                                        observer.disconnect();
                                        resolve(foundDialog);
                                    }, 5000);
                                });
                            }
                            """

                            # Run the dialog check script
                            found_dialog = self.page.evaluate(dialog_check_script)

                            if found_dialog:
                                self.logger.info("Dialog or form detected after click - this is likely an internal application")
                                details["allow_internal_apply"] = True
                                break

                        except Exception as e:
                            self.logger.error(f"Error during safe click check: {str(e)}")
                            # Error doesn't change our result, just continue with what we know

            # Report the determination
            if details["allow_internal_apply"]:
                self.logger.info(f"Job allows internal application: {details['title']} at {details['company']}")
            else:
                self.logger.info(f"Job does NOT allow internal application: {details['title']} at {details['company']}")

        except Exception as e:
            self.logger.error(f"Error extracting job details: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())

        return details

    def _get_mock_job_details(self, job_url: str) -> Dict[str, Any]:
        """
        Create mock job details for development mode.

        Args:
            job_url: The example URL

        Returns:
            Dictionary with mock job details
        """
        job_id = job_url.split("/")[-1]
        job_type = "data scientist" if "data-scientist" in job_id else "python developer"

        return {
            "title": f"Senior {job_type.title()}",
            "company": "Example Company",
            "description": f"""
            We are looking for an experienced {job_type} to join our team.

            Requirements:
            - 3+ years of experience in {job_type} role
            - Strong problem-solving skills
            - Team player with excellent communication

            What we offer:
            - Competitive salary
            - Remote work options
            - Professional development opportunities
            """,
            "url": job_url,
            "id": job_id,
            "allow_internal_apply": True  # Always allow internal apply for mock jobs
        }

    def get_internal_jobs(self, max_jobs: int = 20, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get jobs that allow internal applications and are not premium-only.

        Args:
            max_jobs: Maximum number of jobs to collect (default: 20)
            filters: Dictionary with search filters, e.g.,
                    {"query": "python", "location": "Paris", "radius": 20}

        Returns:
            List of job dictionaries that allow internal applications
        """
        try:
            internal_jobs = []
            filters = filters or {}
            query = filters.get("query", "")
            location = filters.get("location", None)
            radius = int(filters.get("radius", 20))

            # Estimate number of pages to check (assuming ~15 jobs per page)
            est_pages = max(1, math.ceil(max_jobs / 15))
            self.logger.info(f"Collecting up to {max_jobs} internal jobs, checking ~{est_pages} pages")

            # Iterate through pages
            page_num = 1
            total_found = 0

            while page_num <= est_pages and total_found < max_jobs:
                self.logger.info(f"Fetching jobs from page {page_num}")

                # Get job listings for this page
                page_jobs = self.get_job_listings(query=query, location=location, radius=radius, page_num=page_num)

                if not page_jobs:
                    self.logger.info(f"No jobs found on page {page_num}, stopping search")
                    break

                # Check each job URL for internal application option
                for job in page_jobs:
                    if total_found >= max_jobs:
                        break

                    job_url = job.get("url")
                    if not job_url:
                        continue

                    # Get detailed job info
                    try:
                        detailed_job = self.get_job_details(job_url)

                        # Check multiple possible field names for internal application permission
                        allows_internal = (
                            detailed_job.get("allows_internal_application", False) or
                            detailed_job.get("allow_internal_apply", False) or
                            detailed_job.get("internal_application", False)
                        )

                        if allows_internal:
                            self.logger.info(f"Found job that allows internal application: {detailed_job.get('title')} at {detailed_job.get('company')}")
                            internal_jobs.append(detailed_job)
                            total_found += 1

                            # Add short delay to avoid rate limiting
                            time.sleep(1)
                    except Exception as e:
                        self.logger.warning(f"Error checking job {job_url}: {str(e)}")

                # Move to next page
                page_num += 1
                time.sleep(2)  # Small delay between pages

            self.logger.info(f"Found {len(internal_jobs)} jobs that allow internal applications")

            # If in development mode and no jobs found, return test job data
            if not internal_jobs and self.settings.development_mode:
                self.logger.warning("No internal jobs found, generating test jobs for development")
                internal_jobs = self._generate_test_jobs(max_jobs=max_jobs)

            return internal_jobs

        except Exception as e:
            self.logger.error(f"Error getting internal jobs: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())

            # If in development mode, return test job data
            if self.settings.development_mode:
                self.logger.warning("Generating test jobs for development due to error")
                return self._generate_test_jobs(max_jobs=max_jobs)

            return []

    def _generate_test_jobs(self, max_jobs: int = 5) -> List[Dict[str, Any]]:
        """Generate test job data for development mode"""
        test_jobs = []
        companies = ["TechCorp", "DataSystems", "AILabs", "CloudServices", "DevOps Solutions"]
        job_titles = ["Python Developer", "Backend Engineer", "Data Scientist", "ML Engineer", "DevOps Engineer"]

        for i in range(min(max_jobs, 5)):
            company = companies[i]
            title = job_titles[i]
            company_slug = company.lower().replace(" ", "-")
            job_slug = title.lower().replace(" ", "-")

            job = {
                "id": f"{company_slug}_{job_slug}",
                "title": title,
                "company": company,
                "url": f"https://www.welcometothejungle.com/en/companies/{company_slug}/jobs/{job_slug}",
                "company_slug": company_slug,
                "job_slug": job_slug,
                "description": f"This is a test job for {title} at {company}. We're looking for someone with Python, SQL, and cloud experience.",
                "requirements": "- 3+ years Python experience\n- SQL knowledge\n- Experience with cloud services\n- Good communication skills",
                "allows_internal_application": True,
                "is_premium": False,
                "location": "Paris, France",
                "skills": ["Python", "SQL", "AWS", "Git"]
            }
            test_jobs.append(job)

        self.logger.info(f"Generated {len(test_jobs)} test jobs for development mode")
        return test_jobs

    def _accept_cookies(self) -> None:
        """Handle cookie consent banners"""
        try:
            cookie_accept_selectors = [
                "button:has-text('OK for me')",
                "button:has-text('Accept all cookies')",
                "button:has-text('I choose')",
                "button:has-text('Got it!')",
                "button[data-testid='cookie-consent-button-accept']"
            ]

            for selector in cookie_accept_selectors:
                try:
                    if self.page.is_visible(selector, timeout=3000):
                        self.page.click(selector)
                        self.logger.info(f"Clicked cookie consent button: {selector}")
                        self.page.wait_for_timeout(1000)
                        return
                except Exception as e:
                    self.logger.warning(f"Error clicking cookie consent button {selector}: {str(e)}")

        except Exception as e:
            self.logger.warning(f"Error handling cookie consent: {str(e)}")

        # If we failed to find specific buttons, try a more generic approach
        try:
            # Look for elements that look like cookie banners
            banner_selectors = [
                "#cookie-banner",
                ".cookie-banner",
                ".cookie-consent",
                ".cookie-notice",
                "[data-testid*='cookie']",
                ".wttj-sc-1c2f42q"  # Common WTTJ class for banners
            ]

            for selector in banner_selectors:
                if self.page.is_visible(selector):
                    # Try to find any button in the banner
                    buttons = self.page.query_selector_all(f"{selector} button")
                    if buttons:
                        # Usually the accept button is the last one
                        buttons[-1].click()
                        self.logger.info(f"Clicked button in cookie banner: {selector}")
                        self.page.wait_for_timeout(1000)
                        return
        except Exception as e:
            self.logger.warning(f"Error with generic cookie banner approach: {str(e)}")

        self.logger.info("No cookie consent banner found or couldn't interact with it")


def get_internal_jobs_standalone(query: str = "", location: str = None, radius: int = 20,
                               max_jobs: int = 5, username: str = None, password: str = None,
                               settings: Optional[Settings] = None) -> List[Dict[str, Any]]:
    """
    Convenience function to get internal jobs without manual browser handling.

    Args:
        query: Job search query
        location: Location filter
        radius: Search radius in km
        max_jobs: Maximum number of jobs to return
        username: WTTJ username/email (optional)
        password: WTTJ password (optional)
        settings: Application settings

    Returns:
        List of job dictionaries
    """
    settings = settings or Settings()

    filters = {}
    if query:
        filters["query"] = query
    if location:
        filters["location"] = location
        filters["radius"] = radius

    try:
        scraper = WTTJScraper(settings)

        # Log in if credentials provided
        if username and password:
            login_success = scraper.login(username, password)
            if login_success:
                scraper.logger.info("Successfully logged in to WTTJ")
            else:
                scraper.logger.warning("Failed to log in to WTTJ, will scrape without authentication")

        # Get internal jobs
        jobs = scraper.get_internal_jobs(max_jobs=max_jobs, filters=filters)

        # Close browser when done
        scraper.close_browser()

        return jobs

    except Exception as e:
        scraper.logger.error(f"Error in get_internal_jobs_standalone: {str(e)}")
        import traceback
        scraper.logger.error(traceback.format_exc())
        return []