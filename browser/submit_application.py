"""
Submit application module for Welcome to the Jungle.

This module automates the application submission process.
"""

import os
import time
import multiprocessing
from typing import Dict, Any, Optional
from pathlib import Path

from loguru import logger
from playwright.sync_api import sync_playwright, Page, Browser

# Get settings
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import Settings
from browser.wttj_scraper import WTTJScraper


def _handle_job_search_404(page: Page, job_url: str) -> bool:
    """
    Handle 404 errors when searching for jobs.
    Returns True if able to recover from the error.
    """
    try:
        # Check if we're on a 404 page
        if "404" in page.title() or "not found" in page.title().lower():
            logger.warning(f"Encountered 404 page when navigating to: {job_url}")

            # Try to screenshot the 404 page
            try:
                page.screenshot(path="logs/404_error.png")
            except:
                pass

            # If on French version of the site, try switching to English
            if "/fr/" in page.url:
                english_url = job_url.replace("/fr/", "/en/")
                logger.info(f"Trying English version of URL: {english_url}")
                page.goto(english_url, timeout=60000)
                return True

            # If on English version, try French version
            elif "/en/" in page.url:
                french_url = job_url.replace("/en/", "/fr/")
                logger.info(f"Trying French version of URL: {french_url}")
                page.goto(french_url, timeout=60000)
                return True

            # Try to go to the homepage and search again
            try:
                logger.info("Navigating to homepage to restart search")
                page.goto("https://www.welcometothejungle.com/en", timeout=30000)
                return True
            except:
                return False

    except Exception as e:
        logger.error(f"Error handling 404: {str(e)}")

    return False


def _submit_application_worker(job, documents, config_dict, result_queue):
    """
    Worker function to submit application in a separate process.
    This avoids the "Playwright Sync API inside asyncio loop" error.
    """
    try:
        # Convert config_dict back to Settings object
        config = Settings(**config_dict)

        # Create a unique identifier for this application attempt
        job_id = job.get('id', 'unknown-job')
        timestamp = int(time.time())
        attempt_id = f"{timestamp}_{job_id}"

        # Create screenshots directory for this attempt
        screenshot_dir = f"logs/screenshots/{attempt_id}"
        os.makedirs(screenshot_dir, exist_ok=True)

        logger.info(f"Worker process: Starting application submission for {job.get('title', '')} at {job.get('company', '')}")
        logger.info(f"Logging screenshots to {screenshot_dir}")

        with sync_playwright() as playwright:
            browser_type = playwright.chromium

            # Launch browser
            browser = browser_type.launch(headless=not config.development_mode)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            # Enable file uploads
            page = context.new_page()

            logger.info("Browser started successfully for application submission")

            # Handle login
            login_success = _handle_login(page, config, screenshot_dir)
            if not login_success and not config.development_mode:
                logger.error("Login failed, cannot proceed with application")
                browser.close()
                result_queue.put({"success": False, "proof": []})
                return

            # Navigate to the job page
            job_url = job.get("url", "")
            if not job_url:
                logger.error("No job URL provided")
                browser.close()
                result_queue.put({"success": False, "proof": []})
                return

            logger.info(f"Navigating to job page: {job_url}")
            try:
                page.goto(job_url, timeout=60000)

                # Check for 404 error
                if "404" in page.title() or "not found" in page.title().lower():
                    logger.warning("Detected 404 page, attempting recovery")
                    recovery_successful = _handle_job_search_404(page, job_url)
                    if not recovery_successful and not config.development_mode:
                        logger.error("Could not recover from 404 error")
                        browser.close()
                        result_queue.put({"success": False, "proof": []})
                        return
            except Exception as e:
                logger.error(f"Error navigating to job page: {str(e)}")
                if not config.development_mode:
                    browser.close()
                    result_queue.put({"success": False, "proof": []})
                    return

            # Take screenshot after page load
            page.wait_for_load_state("networkidle", timeout=30000)
            job_page_path = f"{screenshot_dir}/job_page.png"
            page.screenshot(path=job_page_path)
            logger.info(f"Job page screenshot saved: {job_page_path}")

            # Find and click the apply button
            apply_clicked = _click_apply_button(page, screenshot_dir)
            if not apply_clicked and not config.development_mode:
                logger.error("Could not find apply button")
                browser.close()
                result_queue.put({"success": False, "proof": []})
                return

            # Wait for application form to load
            page.wait_for_load_state("networkidle", timeout=30000)

            # Take screenshot of application form
            application_form_path = f"{screenshot_dir}/application_form.png"
            page.screenshot(path=application_form_path)
            logger.info(f"Application form screenshot saved: {application_form_path}")

            # Start the actual form filling
            proof_images = [job_page_path, application_form_path]

            # In development mode, simulate successful submission
            if config.development_mode:
                logger.info(f"[DEV MODE] Simulating successful application to {job.get('title', '')} at {job.get('company', '')}")
                result_queue.put({"success": True, "proof": proof_images})
                browser.close()
                return

            # Handle the actual application submission
            submission_success, more_proof = _fill_and_submit_application_form(page, job, documents, config, screenshot_dir)
            proof_images.extend(more_proof)

            # Close the browser when done
            browser.close()
            logger.info("Browser closed after application attempt")

            # Return the result with proof
            result_queue.put({"success": submission_success, "proof": proof_images})

    except Exception as e:
        logger.error(f"Worker process error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        result_queue.put({"success": False, "proof": []})


def _handle_login(page: Page, config: Settings, screenshot_dir: str) -> bool:
    """Handle the login process with detailed error handling and visual proof."""
    try:
        if not config.user_email or not config.user_password:
            logger.warning("No login credentials provided, skipping login")
            return False

        logger.info(f"Logging in as {config.user_email}")

        # Navigate to login page with extended timeout
        login_url = "https://www.welcometothejungle.com/en/login"
        try:
            page.goto(login_url, timeout=60000)
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            logger.warning(f"Timeout during login page navigation, but continuing: {str(e)}")
            # Even if timeout occurs, page might have loaded enough to continue

        # Take screenshot of login page
        login_page_path = f"{screenshot_dir}/login_page.png"
        page.screenshot(path=login_page_path)
        logger.info(f"Login page screenshot saved: {login_page_path}")

        # Handle cookie consent if present - with shorter timeout
        try:
            _handle_cookie_consent(page)
        except Exception as e:
            logger.warning(f"Error handling cookie consent: {str(e)}")

        # Check for "Stay on current website" popup related to location
        try:
            _handle_location_popup(page)
        except Exception as e:
            logger.warning(f"Error handling location popup: {str(e)}")

        # Wait briefly after handling popups
        page.wait_for_timeout(1000)

        # First, try to look for LinkedIn login option
        try:
            linkedin_login_attempted = _attempt_linkedin_login(page, config, screenshot_dir)
            if linkedin_login_attempted:
                # Wait for navigation after LinkedIn login with increased timeout
                try:
                    page.wait_for_load_state("networkidle", timeout=45000)
                except Exception as e:
                    logger.warning(f"Timeout waiting for page load after LinkedIn login: {str(e)}")

                # Take screenshot after login attempt
                after_linkedin_login_path = f"{screenshot_dir}/after_linkedin_login.png"
                page.screenshot(path=after_linkedin_login_path)
                logger.info(f"Post-LinkedIn-login screenshot saved: {after_linkedin_login_path}")

                # Check for successful login
                login_success = _verify_login_success(page)
                if login_success:
                    logger.info("LinkedIn login successful")
                    return True
                else:
                    logger.warning("LinkedIn login failed - could not verify successful login")
                    # Fall back to regular login if LinkedIn failed
        except Exception as e:
            logger.warning(f"Error during LinkedIn login attempt: {str(e)}")

        # If LinkedIn login wasn't available or failed, proceed with regular login

        # Fill login form with multiple selector attempts and shorter timeouts
        login_form_elements = {
            'email': {
                'selectors': [
                    'input[type="email"]',
                    'input[name="email"]',
                    'input[placeholder*="email" i]'
                ],
                'value': config.user_email
            },
            'password': {
                'selectors': [
                    'input[type="password"]',
                    'input[name="password"]',
                    'input[placeholder*="password" i]'
                ],
                'value': config.user_password
            }
        }

        # Fill each form element
        for field_name, field_data in login_form_elements.items():
            field_filled = False
            for selector in field_data['selectors']:
                try:
                    if page.is_visible(selector, timeout=5000):
                        page.fill(selector, field_data['value'])
                        logger.info(f"Filled {field_name} using selector: {selector}")
                        field_filled = True
                        break
                except Exception as e:
                    logger.warning(f"Error filling {field_name} with selector {selector}: {str(e)}")

            if not field_filled:
                logger.error(f"Could not find {field_name} field")
                page.screenshot(path=f"{screenshot_dir}/{field_name}_field_not_found.png")
                return False

        # Take a screenshot after filling the form
        page.screenshot(path=f"{screenshot_dir}/form_filled.png")

        # Click login button
        submit_clicked = False
        submit_selectors = [
            'button[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Sign in")',
            'input[type="submit"]'
        ]

        for selector in submit_selectors:
            try:
                if page.is_visible(selector, timeout=5000):
                    page.click(selector)
                    logger.info(f"Clicked submit button: {selector}")
                    submit_clicked = True
                    break
            except Exception as e:
                logger.warning(f"Error clicking submit button {selector}: {str(e)}")

        if not submit_clicked:
            logger.error("Could not find login submit button")
            page.screenshot(path=f"{screenshot_dir}/submit_not_found.png")
            return False

        # Wait for navigation after login with increased timeout
        try:
            page.wait_for_load_state("networkidle", timeout=45000)
        except Exception as e:
            logger.warning(f"Timeout waiting for page load after login: {str(e)}")
            # Continue anyway, we'll check for login success

        # Take screenshot after login attempt
        after_login_path = f"{screenshot_dir}/after_login.png"
        page.screenshot(path=after_login_path)
        logger.info(f"Post-login screenshot saved: {after_login_path}")

        # Check for successful login multiple ways
        login_success = _verify_login_success(page)

        if login_success:
            logger.info("Login successful")
            return True
        else:
            logger.warning("Login failed - could not verify successful login")
            return False

    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        page.screenshot(path=f"{screenshot_dir}/login_error.png")
        return False


def _attempt_linkedin_login(page: Page, config: Settings, screenshot_dir: str) -> bool:
    """Attempt to login using LinkedIn option if available."""
    try:
        # Common selectors for LinkedIn login buttons
        linkedin_selectors = [
            "button:has-text('Continue with LinkedIn')",
            "button:has-text('Sign in with LinkedIn')",
            "button:has-text('Login with LinkedIn')",
            "a:has-text('Continue with LinkedIn')",
            "a:has-text('Sign in with LinkedIn')",
            "a:has-text('Login with LinkedIn')",
            "a[href*='linkedin']",
            "button[data-testid='linkedin-button']",
            "div.linkedin-login-button"
        ]

        # Check for LinkedIn login option
        linkedin_button_found = False
        for selector in linkedin_selectors:
            try:
                if page.is_visible(selector):
                    # Take screenshot before clicking LinkedIn button
                    before_linkedin_path = f"{screenshot_dir}/before_linkedin_click.png"
                    page.screenshot(path=before_linkedin_path)

                    # Highlight the LinkedIn button
                    page.evaluate(f"""(selector) => {{
                        const el = document.querySelector(selector);
                        if (el) {{
                            el.style.border = '3px solid blue';
                            el.style.backgroundColor = 'rgba(0, 0, 255, 0.1)';
                        }}
                    }}""", selector)

                    # Take screenshot with highlighted LinkedIn button
                    highlighted_linkedin_path = f"{screenshot_dir}/linkedin_button_highlighted.png"
                    page.screenshot(path=highlighted_linkedin_path)

                    # Click the LinkedIn button
                    page.click(selector)
                    logger.info(f"Clicked LinkedIn login button with selector: {selector}")
                    linkedin_button_found = True

                    # Wait for LinkedIn login page to load
                    page.wait_for_load_state("networkidle", timeout=20000)

                    # Take screenshot of LinkedIn login page
                    linkedin_login_page_path = f"{screenshot_dir}/linkedin_login_page.png"
                    page.screenshot(path=linkedin_login_page_path)

                    # Handle LinkedIn authentication
                    linkedin_auth_success = _handle_linkedin_auth(page, config, screenshot_dir)
                    return linkedin_auth_success
            except Exception as e:
                logger.warning(f"Error with LinkedIn selector {selector}: {str(e)}")
                continue

        if not linkedin_button_found:
            logger.info("LinkedIn login option not found, will use regular login")
            return False

    except Exception as e:
        logger.error(f"LinkedIn login attempt error: {str(e)}")
        page.screenshot(path=f"{screenshot_dir}/linkedin_login_error.png")
        return False

    return False


def _handle_linkedin_auth(page: Page, config: Settings, screenshot_dir: str) -> bool:
    """Handle the LinkedIn authentication flow."""
    try:
        # Check if we're on a LinkedIn domain
        current_url = page.url
        if "linkedin.com" not in current_url:
            logger.warning("Not on LinkedIn login page after clicking LinkedIn button")
            return False

        logger.info("On LinkedIn login page, proceeding with authentication")

        # Common LinkedIn login form field selectors
        linkedin_email_selectors = [
            "input[id='username']",
            "input[name='session_key']",
            "input[type='email']"
        ]

        linkedin_password_selectors = [
            "input[id='password']",
            "input[name='session_password']",
            "input[type='password']"
        ]

        # Try to fill email field
        email_filled = False
        for selector in linkedin_email_selectors:
            try:
                if page.is_visible(selector):
                    page.fill(selector, config.user_email)
                    logger.info(f"Filled LinkedIn email field using selector: {selector}")
                    email_filled = True
                    break
            except Exception as e:
                logger.warning(f"Error filling LinkedIn email field with selector {selector}: {str(e)}")

        if not email_filled:
            logger.error("Could not find LinkedIn email field")
            page.screenshot(path=f"{screenshot_dir}/linkedin_email_not_found.png")
            return False

        # Try to fill password field
        password_filled = False
        for selector in linkedin_password_selectors:
            try:
                if page.is_visible(selector):
                    page.fill(selector, config.user_password)
                    logger.info(f"Filled LinkedIn password field using selector: {selector}")
                    password_filled = True
                    break
            except Exception as e:
                logger.warning(f"Error filling LinkedIn password field with selector {selector}: {str(e)}")

        if not password_filled:
            logger.error("Could not find LinkedIn password field")
            page.screenshot(path=f"{screenshot_dir}/linkedin_password_not_found.png")
            return False

        # Take screenshot after filling LinkedIn form
        page.screenshot(path=f"{screenshot_dir}/linkedin_form_filled.png")

        # Click LinkedIn login button
        linkedin_submit_clicked = False
        linkedin_submit_selectors = [
            "button[type='submit']",
            "button:has-text('Sign in')",
            "input[type='submit']"
        ]

        for selector in linkedin_submit_selectors:
            try:
                if page.is_visible(selector):
                    page.click(selector)
                    logger.info(f"Clicked LinkedIn submit button with selector: {selector}")
                    linkedin_submit_clicked = True
                    break
            except Exception as e:
                logger.warning(f"Error clicking LinkedIn submit button with selector {selector}: {str(e)}")

        if not linkedin_submit_clicked:
            logger.error("Could not find LinkedIn submit button")
            page.screenshot(path=f"{screenshot_dir}/linkedin_submit_not_found.png")
            return False

        # Wait for authorization to complete and redirect back to WTTJ
        page.wait_for_load_state("networkidle", timeout=30000)

        # Take screenshot after LinkedIn authorization
        page.screenshot(path=f"{screenshot_dir}/after_linkedin_auth.png")

        # Check if we're back on WTTJ
        current_url = page.url
        if "welcometothejungle.com" in current_url:
            logger.info("Successfully returned to WTTJ after LinkedIn login")
            return True
        else:
            # We might need to handle "Allow" screens or other LinkedIn prompts
            allow_button_selectors = [
                "button:has-text('Allow')",
                "button:has-text('Authorize')",
                "button:has-text('Accept')",
                "button[type='submit']"
            ]

            for selector in allow_button_selectors:
                try:
                    if page.is_visible(selector):
                        page.click(selector)
                        logger.info(f"Clicked LinkedIn authorization button with selector: {selector}")
                        page.wait_for_load_state("networkidle", timeout=20000)

                        # Take screenshot after clicking allow
                        page.screenshot(path=f"{screenshot_dir}/after_linkedin_allow.png")

                        # Check URL again
                        if "welcometothejungle.com" in page.url:
                            logger.info("Successfully returned to WTTJ after LinkedIn authorization")
                            return True
                        break
                except Exception as e:
                    logger.warning(f"Error with LinkedIn allow button {selector}: {str(e)}")

            logger.warning(f"LinkedIn login process incomplete - current URL: {current_url}")
            return False

    except Exception as e:
        logger.error(f"LinkedIn authentication error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        page.screenshot(path=f"{screenshot_dir}/linkedin_auth_error.png")
        return False


def _handle_cookie_consent(page: Page) -> None:
    """Handle cookie consent banners."""
    cookie_buttons = [
        "button:has-text('Accept all cookies')",
        "button:has-text('OK for me')",
        "button:has-text('Got it!')",
        "button[data-testid='cookie-consent-button-accept']"
    ]

    for button in cookie_buttons:
        try:
            if page.is_visible(button):
                page.click(button)
                logger.info(f"Clicked cookie consent button: {button}")
                page.wait_for_timeout(1000)
                break
        except Exception as e:
            logger.warning(f"Error clicking cookie consent: {str(e)}")


def _handle_location_popup(page: Page) -> None:
    """Handle location popups that might appear."""
    # Check for the "Looks like you're in France?" popup first
    try:
        france_popup_selectors = [
            "button:has-text('Stay on the current website')",
            "button:has-text('Stay on this website')",
            ".modal button:has-text('Stay')",
            "[role='dialog'] button:has-text('Stay')"
        ]

        # Take screenshot before handling popup
        try:
            page.screenshot(path="logs/popup_before.png")
        except:
            pass

        for selector in france_popup_selectors:
            if page.is_visible(selector, timeout=5000):
                # Highlight the button for screenshot
                page.evaluate(f"""(selector) => {{
                    const el = document.querySelector(selector);
                    if (el) {{
                        el.style.border = '3px solid red';
                        el.style.backgroundColor = 'rgba(255, 0, 0, 0.2)';
                    }}
                }}""", selector)

                try:
                    page.screenshot(path="logs/popup_highlighted.png")
                except:
                    pass

                # Click the button
                page.click(selector)
                logger.info(f"Clicked France location popup button: {selector}")
                page.wait_for_timeout(2000)
                return
    except Exception as e:
        logger.warning(f"Error handling France popup: {str(e)}")

    # Try clicking on the modal close button if visible
    try:
        close_button_selectors = [
            "button[data-testid='modal-close']",
            "button.modal-close",
            "button.close",
            "button[aria-label='Close']",
            "svg[data-testid='icon-times']"
        ]

        for selector in close_button_selectors:
            if page.is_visible(selector, timeout=2000):
                page.click(selector)
                logger.info(f"Clicked popup close button: {selector}")
                page.wait_for_timeout(1000)
                return
    except Exception as e:
        logger.warning(f"Error clicking close button: {str(e)}")

    # Generic approach for other popups
    location_buttons = [
        "button:has-text('Stay on the current website')",
        "button:has-text('Stay on this website')",
        "button:has-text('Continue')",
        "button:has-text('Accept')",
        "button:has-text('OK')",
        "button:has-text('Got it')"
    ]

    for button in location_buttons:
        try:
            if page.is_visible(button):
                page.click(button)
                logger.info(f"Clicked location popup button: {button}")
                page.wait_for_timeout(1000)
                break
        except Exception as e:
            logger.warning(f"Error clicking location popup: {str(e)}")

    # As a last resort, try clicking on the overlay/backdrop to dismiss modal
    try:
        backdrop_selectors = [
            ".modal-backdrop",
            ".overlay",
            "[data-testid='modal-backdrop']"
        ]

        for selector in backdrop_selectors:
            if page.is_visible(selector):
                # Click in the top-left corner of the backdrop to avoid clicking on the modal itself
                box = page.query_selector(selector).bounding_box()
                if box:
                    page.click(selector, position={"x": 10, "y": 10})
                    logger.info(f"Clicked backdrop to dismiss popup: {selector}")
                    page.wait_for_timeout(1000)
                    break
    except Exception as e:
        logger.warning(f"Error clicking backdrop: {str(e)}")


def _verify_login_success(page: Page) -> bool:
    """Verify if login was successful using multiple checks."""

    # Check 1: URL check - we should no longer be on the login page
    current_url = page.url
    if "/login" in current_url or "/sign-in" in current_url:
        logger.warning("Still on login page after submission - login likely failed")
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
            if page.is_visible(selector):
                logger.info(f"Found profile element after login: {selector}")
                return True
        except:
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
            if page.is_visible(selector):
                logger.info(f"Found logged-in indicator: {selector}")
                return True
        except:
            continue

    # Check 4: Look for elements that indicate we're still in the login process
    login_failure_indicators = [
        "div.error-message",
        "p.error",
        "input[type='password']"  # If we still see password field, login failed
    ]

    for selector in login_failure_indicators:
        try:
            if page.is_visible(selector):
                logger.warning(f"Found login failure indicator: {selector}")
                return False
        except:
            continue

    # If we reach here without a clear indicator, assume success if we're not on login page
    if "/login" not in current_url and "/sign-in" not in current_url:
        logger.info("Login appears to be successful based on URL change")
        return True

    return False


def _click_apply_button(page: Page, screenshot_dir: str) -> bool:
    """Find and click the apply button with proof screenshots."""
    apply_button_selectors = [
        "a[data-testid='job-apply-button']",
        "button[data-testid='job-apply-button']",
        "a.ais-Highlight",
        "a[href*='apply']",
        "button:has-text('Apply')",
        "div.wttj-sc-1c2f42q a",  # Common WTTJ button class
        "[role='button']:has-text('Apply')"
    ]

    # First, take a screenshot to show the page with the apply button
    before_click_path = f"{screenshot_dir}/before_apply_click.png"
    page.screenshot(path=before_click_path)
    logger.info(f"Pre-apply button screenshot saved: {before_click_path}")

    # Try each selector
    for selector in apply_button_selectors:
        try:
            if page.is_visible(selector):
                # Highlight the button before clicking (for screenshot proof)
                page.evaluate(f"""(selector) => {{
                    const el = document.querySelector(selector);
                    if (el) {{
                        el.style.border = '3px solid red';
                    }}
                }}""", selector)

                # Take screenshot with highlighted button
                highlighted_button_path = f"{screenshot_dir}/apply_button_highlighted.png"
                page.screenshot(path=highlighted_button_path)
                logger.info(f"Apply button highlighted screenshot saved: {highlighted_button_path}")

                # Click the button
                page.click(selector)
                logger.info(f"Clicked apply button with selector: {selector}")
                return True
        except Exception as e:
            logger.warning(f"Error with apply button selector {selector}: {str(e)}")

    # If we get here, we couldn't find any apply button
    no_button_path = f"{screenshot_dir}/apply_button_not_found.png"
    page.screenshot(path=no_button_path)
    logger.error(f"Could not find apply button, screenshot saved: {no_button_path}")

    # Check for alternative paths - sometimes the job details page IS the application form
    if _is_already_on_application_form(page):
        logger.info("Already on application form - no need to click apply button")
        return True

    return False


def _is_already_on_application_form(page: Page) -> bool:
    """Check if we're already on an application form without needing to click apply."""
    form_indicators = [
        "input[type='file']",
        "textarea[name*='cover']",
        "textarea[name*='motivation']",
        "form[action*='apply']",
        "input[name='resume']",
        "[data-testid='application-form']",
        "div:has-text('Upload your resume')",
        "div:has-text('Upload your CV')"
    ]

    for indicator in form_indicators:
        try:
            if page.is_visible(indicator):
                logger.info(f"Already on application form - found indicator: {indicator}")
                return True
        except:
            continue

    return False


def _fill_and_submit_application_form(page: Page, job: Dict[str, Any],
                                     documents: Dict[str, Any], config: Settings,
                                     screenshot_dir: str) -> tuple:
    """
    Fill out and submit the application form with CV and motivation letter.
    Returns tuple of (success, list_of_proof_image_paths)
    """
    proof_images = []
    try:
        # Get document paths - ensure they exist
        cv_path = documents.get("cv")
        letter_path = documents.get("letter")

        if not cv_path or not os.path.exists(cv_path):
            logger.error(f"CV file not found: {cv_path}")
            error_path = f"{screenshot_dir}/cv_missing.png"
            page.screenshot(path=error_path)
            proof_images.append(error_path)
            return False, proof_images

        if not letter_path or not os.path.exists(letter_path):
            logger.warning(f"Motivation letter file not found: {letter_path}")
            # We'll continue without the letter as some forms don't require it

        # Wait for the form to be ready
        page.wait_for_timeout(2000)

        # Look for all possible file upload fields
        upload_filled = False

        # Common CV/resume upload field selectors
        cv_upload_selectors = [
            "input[type='file'][name*='resume']",
            "input[type='file'][name*='cv']",
            "input[type='file'][accept*='pdf']",
            "input[type='file']"  # Fallback to any file input
        ]

        # Try to upload CV
        for selector in cv_upload_selectors:
            try:
                if page.is_visible(selector) or page.query_selector(selector):
                    # Some file inputs may be hidden, so we need to handle them specially
                    upload_element = page.query_selector(selector)
                    if upload_element:
                        page.set_input_files(selector, cv_path)
                        logger.info(f"Uploaded CV using selector: {selector}")
                        upload_filled = True

                        # Take screenshot after CV upload
                        cv_uploaded_path = f"{screenshot_dir}/cv_uploaded.png"
                        page.screenshot(path=cv_uploaded_path)
                        proof_images.append(cv_uploaded_path)
                        break
            except Exception as e:
                logger.warning(f"Error uploading CV with selector {selector}: {str(e)}")

        if not upload_filled:
            logger.warning("Could not find CV upload field - form might have different structure")
            form_structure_path = f"{screenshot_dir}/form_structure.png"
            page.screenshot(path=form_structure_path)
            proof_images.append(form_structure_path)

        # Try to upload motivation letter if we have it
        if letter_path and os.path.exists(letter_path):
            letter_upload_selectors = [
                "input[type='file'][name*='letter']",
                "input[type='file'][name*='motivation']",
                "input[type='file'][name*='cover']",
                "input[type='file']:nth-of-type(2)"  # Try second file input if there are multiple
            ]

            for selector in letter_upload_selectors:
                try:
                    if page.is_visible(selector) or page.query_selector(selector):
                        page.set_input_files(selector, letter_path)
                        logger.info(f"Uploaded motivation letter using selector: {selector}")

                        # Take screenshot after letter upload
                        letter_uploaded_path = f"{screenshot_dir}/letter_uploaded.png"
                        page.screenshot(path=letter_uploaded_path)
                        proof_images.append(letter_uploaded_path)
                        break
                except Exception as e:
                    logger.warning(f"Error uploading letter with selector {selector}: {str(e)}")

        # Fill in any required text fields
        _fill_common_text_fields(page, config)

        # Take screenshot of completed form
        completed_form_path = f"{screenshot_dir}/completed_form.png"
        page.screenshot(path=completed_form_path)
        proof_images.append(completed_form_path)

        # Look for and click the submit button
        submit_clicked = False
        submit_selectors = [
            "button[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Send')",
            "button:has-text('Send application')",
            "button:has-text('Submit application')",
            "input[type='submit']"
        ]

        for selector in submit_selectors:
            try:
                if page.is_visible(selector):
                    # Highlight the button before clicking (for screenshot proof)
                    page.evaluate(f"""(selector) => {{
                        const el = document.querySelector(selector);
                        if (el) {{
                            el.style.border = '3px solid green';
                        }}
                    }}""", selector)

                    # Take screenshot with highlighted submit button
                    submit_highlighted_path = f"{screenshot_dir}/submit_button_highlighted.png"
                    page.screenshot(path=submit_highlighted_path)
                    proof_images.append(submit_highlighted_path)

                    # Click the submit button
                    page.click(selector)
                    logger.info(f"Clicked submit button with selector: {selector}")
                    submit_clicked = True

                    # Wait for submission processing
                    page.wait_for_timeout(5000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    break
            except Exception as e:
                logger.warning(f"Error with submit button selector {selector}: {str(e)}")

        if not submit_clicked:
            logger.error("Could not find submit button")
            no_submit_path = f"{screenshot_dir}/submit_button_not_found.png"
            page.screenshot(path=no_submit_path)
            proof_images.append(no_submit_path)
            return False, proof_images

        # Take screenshot after submission
        after_submit_path = f"{screenshot_dir}/after_submit.png"
        page.screenshot(path=after_submit_path)
        proof_images.append(after_submit_path)

        # Check for success indicators
        submission_successful = _verify_submission_success(page)

        if submission_successful:
            logger.info(f"Application successfully submitted for {job.get('title', '')} at {job.get('company', '')}")
            success_path = f"{screenshot_dir}/submission_success.png"
            page.screenshot(path=success_path)
            proof_images.append(success_path)
            return True, proof_images
        else:
            logger.warning(f"Submission verification failed for {job.get('title', '')}")
            failure_path = f"{screenshot_dir}/submission_verification_failed.png"
            page.screenshot(path=failure_path)
            proof_images.append(failure_path)
            return False, proof_images

    except Exception as e:
        logger.error(f"Error filling application form: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        error_path = f"{screenshot_dir}/form_fill_error.png"
        try:
            page.screenshot(path=error_path)
            proof_images.append(error_path)
        except:
            pass
        return False, proof_images


def _fill_common_text_fields(page: Page, config: Settings) -> None:
    """Fill in common text fields found in application forms."""
    # Common field mapping
    field_mapping = {
        # Name fields
        "input[name*='name' i]": config.user_name,
        "input[name*='full' i][name*='name' i]": config.user_name,
        "input[placeholder*='name' i]": config.user_name,

        # Email fields
        "input[type='email']": config.user_email,
        "input[name*='email' i]": config.user_email,
        "input[placeholder*='email' i]": config.user_email,

        # Phone fields
        "input[type='tel']": config.user_phone or "+33600000000",
        "input[name*='phone' i]": config.user_phone or "+33600000000",
        "input[placeholder*='phone' i]": config.user_phone or "+33600000000",

        # LinkedIn fields
        "input[name*='linkedin' i]": config.user_linkedin or "https://linkedin.com/in/user",
        "input[placeholder*='linkedin' i]": config.user_linkedin or "https://linkedin.com/in/user",

        # Cover letter or message fields (if text input rather than file)
        "textarea[name*='cover' i]": "Please refer to the attached motivation letter.",
        "textarea[name*='motivation' i]": "Please refer to the attached motivation letter.",
        "textarea[name*='message' i]": "Please refer to the attached motivation letter.",
        "textarea[placeholder*='cover' i]": "Please refer to the attached motivation letter.",
        "textarea[placeholder*='motivation' i]": "Please refer to the attached motivation letter."
    }

    # Try to fill each field
    for selector, value in field_mapping.items():
        try:
            if value and (page.is_visible(selector) or page.query_selector(selector)):
                page.fill(selector, value)
                logger.info(f"Filled field using selector: {selector}")
        except Exception as e:
            logger.debug(f"Could not fill field with selector {selector}: {str(e)}")
            # Continue with other fields


def _verify_submission_success(page: Page) -> bool:
    """Verify if the application was successfully submitted."""
    # Success indicators
    success_indicators = [
        "div:has-text('Application submitted')",
        "div:has-text('Thank you for your application')",
        "div:has-text('Application received')",
        "div:has-text('Application sent')",
        "div:has-text('Success')",
        "h1:has-text('Thank you')",
        "h2:has-text('Thank you')"
    ]

    for indicator in success_indicators:
        try:
            if page.is_visible(indicator):
                logger.info(f"Found submission success indicator: {indicator}")
                return True
        except:
            continue

    # URL-based success check: sometimes redirects to a confirmation page
    current_url = page.url
    if "confirm" in current_url or "success" in current_url or "thank" in current_url:
        logger.info(f"URL suggests successful submission: {current_url}")
        return True

    # Check for absence of form elements as success indicator
    # If the form disappeared, it might have been submitted successfully
    form_gone = True
    form_elements = [
        "input[type='file']",
        "button[type='submit']",
        "textarea[name*='cover']"
    ]

    for element in form_elements:
        if page.is_visible(element):
            form_gone = False
            break

    if form_gone:
        logger.info("Form elements no longer visible - likely successful submission")
        return True

    # Look for failure indicators
    failure_indicators = [
        "div.error",
        "p.error",
        "div:has-text('Error')",
        "div:has-text('Failed')"
    ]

    for indicator in failure_indicators:
        try:
            if page.is_visible(indicator):
                error_text = page.inner_text(indicator)
                logger.warning(f"Found submission failure indicator: {indicator} with text: {error_text}")
                return False
        except:
            continue

    # If we can't clearly determine success or failure, assume it worked
    # Unless we're still on the same page with the form
    if "apply" in current_url:
        logger.warning("Still on application page - submission might have failed")
        return False

    logger.info("Couldn't find clear success/failure indicators, assuming success")
    return True


def submit_application(job: Dict[str, Any], documents: Dict[str, Any], config: Optional[Settings] = None) -> bool:
    """
    Submit an application through Welcome to the Jungle.

    Args:
        job: Job details dictionary
        documents: Dictionary with paths to documents (CV and motivation letter)
        config: Application settings

    Returns:
        True if application was submitted successfully, False otherwise
    """
    config = config or Settings()

    # For development mode, just simulate a successful submission
    if config.development_mode:
        logger.info(f"[DEV MODE] Simulating successful application to {job.get('title', '')} at {job.get('company', '')}")
        return True

    logger.info(f"Starting application submission for {job.get('title', '')} at {job.get('company', '')}")

    try:
        # Create a multiprocessing queue to get the result from the worker process
        result_queue = multiprocessing.Queue()

        # Convert config to dict for serialization
        config_dict = config.dict()

        # Create a new process to run the submission
        process = multiprocessing.Process(
            target=_submit_application_worker,
            args=(job, documents, config_dict, result_queue)
        )

        # Start the process
        process.start()

        # Wait for the process to complete or timeout
        process.join(timeout=300)  # 5 minute timeout

        # Check if process timed out
        if process.is_alive():
            logger.error("Application submission timed out")
            process.terminate()
            process.join()
            return False

        # Get the result from the worker
        result = {"success": False, "proof": []}
        if not result_queue.empty():
            result = result_queue.get()

        if result["proof"]:
            logger.info(f"Captured {len(result['proof'])} proof screenshots during submission")

        return result["success"]

    except Exception as e:
        logger.error(f"Error submitting application: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False