"""
Document generation module using LLMs to create tailored CVs and motivation letters.
Supports OpenAI, Anthropic, and local models for document generation.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import jinja2
import openai
from anthropic import Anthropic
from loguru import logger
from weasyprint import HTML
import httpx

# Get settings
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings

settings = get_settings()


class LLMProvider:
    """Base class for LLM providers."""

    def generate_content(self, prompt: str) -> str:
        """Generate content from the LLM."""
        raise NotImplementedError("Subclasses must implement this method")


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        self.api_key = api_key or settings.openai_api_key
        self.model = model
        openai.api_key = self.api_key

    def generate_content(self, prompt: str) -> str:
        """Generate content using OpenAI models."""
        try:
            # Check if we're using openai v1.0+
            if hasattr(openai, 'OpenAI'):  # v1.0+
                client = openai.OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are an expert at creating customized CVs and motivation letters for job applications."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2000
                )
                return response.choices[0].message.content.strip()
            else:  # Legacy v0.x
                response = openai.ChatCompletion.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are an expert at creating customized CVs and motivation letters for job applications."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2000
                )
                return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error using OpenAI API: {str(e)}")
            # In case of error, return a default response for dev mode
            if settings.development_mode:
                logger.warning("Using mock content due to OpenAI API error in development mode")
                return "<h1>Mock CV/Letter Content (Development Mode)</h1><p>This is placeholder content generated because the OpenAI API request failed.</p>"
            return ""


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-2"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        try:
            self.client = Anthropic(api_key=self.api_key)
        except Exception as e:
            logger.error(f"Error initializing Anthropic client: {str(e)}")
            self.client = None

    def generate_content(self, prompt: str) -> str:
        """Generate content using Anthropic Claude models."""
        try:
            if settings.development_mode:
                logger.info("[DEV MODE] Using mock content for Anthropic API")
                return "<h1>Mock Claude Content (Development Mode)</h1><p>This is placeholder content for development mode since no actual API call is being made.</p>"

            if not self.client:
                raise ValueError("Anthropic client not initialized")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system="You are an expert at creating customized CVs and motivation letters for job applications.",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error using Anthropic API: {str(e)}")
            if settings.development_mode:
                logger.warning("Using mock content due to Anthropic API error in development mode")
                return "<h1>Mock Claude Content (Development Mode)</h1><p>This is placeholder content generated because the Anthropic API request failed.</p>"
            return ""


class GoogleProvider(LLMProvider):
    """Google Gemini API provider using the official Google GenAI SDK."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        self.api_key = api_key or settings.gemini_api_key
        self.model = model
        self.client = None

        # Initialize client if API key is available
        if self.api_key:
            try:
                from google.genai import Client
                self.client = Client(api_key=self.api_key)
                logger.info(f"Initialized Google GenAI client with model: {self.model}")
            except ImportError:
                logger.error("Failed to import google-genai package. Please install with: pip install -q -U google-genai")
            except Exception as e:
                logger.error(f"Error initializing Google GenAI client: {str(e)}")

    def generate_content(self, prompt: str) -> str:
        """Generate content using Google Gemini models with the official SDK."""
        if settings.development_mode:
            logger.info("[DEV MODE] Using mock content for Google Gemini API")
            return "<h1>Mock Gemini Content (Development Mode)</h1><p>This is placeholder content for development mode since no actual API call is being made.</p>"

        if not self.api_key:
            logger.error("Google Gemini API key not provided.")
            if settings.development_mode:
                return "<h1>Mock Gemini Content (Development Mode)</h1><p>This is placeholder content generated because no API key was provided.</p>"
            return ""

        if not self.client:
            logger.error("Google GenAI client not initialized.")
            if settings.development_mode:
                return "<h1>Mock Gemini Content (Development Mode)</h1><p>This is placeholder content generated because the client was not initialized.</p>"
            return ""

        try:
            # Use the new API format
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )

            # Extract text from the response
            if hasattr(response, 'text'):
                return response.text
            elif hasattr(response, 'parts') and len(response.parts) > 0:
                return response.parts[0].text
            elif isinstance(response, dict) and 'text' in response:
                return response['text']

            logger.error(f"Unexpected response structure from Gemini API: {response}")
            if settings.development_mode:
                return "<h1>Mock Gemini Content (Development Mode)</h1><p>This is placeholder content generated because of an unexpected response structure.</p>"
            return ""

        except Exception as e:
            logger.error(f"Error using Google Gemini API: {str(e)}")
            if settings.development_mode:
                return "<h1>Mock Gemini Content (Development Mode)</h1><p>This is placeholder content generated because of a general error.</p>"
            return ""


class DocumentGenerator:
    """Generates tailored CV and motivation letter documents."""

    def __init__(self, llm_provider: Optional[str] = None):
        """Initialize the document generator with specified LLM provider."""
        self.llm_provider_name = llm_provider or settings.llm_provider
        self.llm = self._init_llm_provider()

        # Initialize Jinja2 environment
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("templates"),
            autoescape=jinja2.select_autoescape(['html', 'xml'])
        )

    def _init_llm_provider(self) -> LLMProvider:
        """Initialize the appropriate LLM provider."""
        if self.llm_provider_name == "openai":
            return OpenAIProvider()
        elif self.llm_provider_name == "anthropic":
            return AnthropicProvider()
        elif self.llm_provider_name == "google":
            return GoogleProvider()
        else:
            logger.warning(f"Unsupported LLM provider: {self.llm_provider_name}, falling back to OpenAI")
            return OpenAIProvider()

    def load_profile(self, profile_path: Optional[Path] = None) -> Dict[str, Any]:
        """Load the user's profile from the specified path."""
        path = profile_path or settings.base_profile_path
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading profile from {path}: {str(e)}")
            return {}

    def load_base_cv(self, cv_path: Optional[Path] = None) -> str:
        """Load the base CV content from the specified path."""
        path = cv_path or settings.base_cv_path
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error loading base CV from {path}: {str(e)}")
            return ""

    def generate_cv_content(self, job: Dict[str, Any], profile: Dict[str, Any]) -> str:
        """Generate tailored CV content for the specific job."""
        # Create prompt for the LLM
        prompt = f"""
        Create a tailored CV for a job application.

        JOB DETAILS:
        Title: {job['title']}
        Company: {job['company']}
        Description: {job['description']}

        CANDIDATE PROFILE:
        {json.dumps(profile, indent=2)}

        BASE CV:
        {self.load_base_cv()}

        FORMAT INSTRUCTIONS:
        1. Return HTML format suitable for rendering in a web page
        2. Focus on skills and experiences most relevant to the job
        3. Ensure the CV highlights qualifications that match the job requirements
        4. Keep tone professional and achievements quantified where possible
        5. Organize in standard CV sections: Profile, Experience, Education, Skills
        6. ONLY return the HTML content without any explanations or markdown

        HTML:
        """

        # Generate the content using the LLM
        content = self.llm.generate_content(prompt)

        # Clean the output if needed
        if "```html" in content:
            content = content.split("```html")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        return content

    def generate_letter_content(self, job: Dict[str, Any], profile: Dict[str, Any]) -> str:
        """Generate tailored motivation letter content for the specific job."""
        # Create prompt for the LLM
        prompt = f"""
        Create a personalized motivation letter for a job application.

        JOB DETAILS:
        Title: {job['title']}
        Company: {job['company']}
        Description: {job['description']}

        CANDIDATE PROFILE:
        {json.dumps(profile, indent=2)}

        FORMAT INSTRUCTIONS:
        1. Return HTML format suitable for rendering in a web page
        2. Address specific points from the job description
        3. Explain why the candidate is a good fit based on their experience
        4. Highlight enthusiasm for the role and company specifically
        5. Keep length to 1 page maximum (3-4 paragraphs)
        6. Use formal business letter format with appropriate greeting and closing
        7. ONLY return the HTML content without any explanations or markdown

        HTML:
        """

        # Generate the content using the LLM
        content = self.llm.generate_content(prompt)

        # Clean the output if needed
        if "```html" in content:
            content = content.split("```html")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        return content

    def render_to_html(self, template_name: str, content: str, context: Dict[str, Any]) -> str:
        """Render content with the specified template to HTML."""
        template = self.jinja_env.get_template(f"{template_name}.html")

        # Combine content with any additional context
        full_context = {
            **context,
            "content": content,
            "generated_date": datetime.now().strftime("%Y-%m-%d")
        }

        return template.render(**full_context)

    def render_to_pdf(self, html_content: str, output_path: Path) -> Path:
        """Render HTML content to PDF file."""
        try:
            # In development mode, just create a mock PDF (or skip PDF generation)
            if settings.development_mode:
                logger.info(f"[DEV MODE] Skipping PDF generation, would save to: {output_path}")
                # Still create the directory and write the HTML to disk
                output_path.parent.mkdir(parents=True, exist_ok=True)
                html_path = output_path.with_suffix('.html')
                with open(html_path, 'w') as f:
                    f.write(html_content)
                logger.info(f"[DEV MODE] Saved HTML version to: {html_path}")
                return output_path

            # Create parent directories if they don't exist
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save the HTML file for reference
            html_path = output_path.with_suffix('.html')
            with open(html_path, 'w') as f:
                f.write(html_content)
            logger.info(f"Saved HTML version to: {html_path}")

            # Try multiple methods to handle different weasyprint versions
            pdf_generated = False

            # Method 1: Use subprocess to call weasyprint CLI
            try:
                import subprocess
                logger.info("Attempting to generate PDF using weasyprint CLI...")
                cmd = ["weasyprint", str(html_path), str(output_path)]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    logger.info(f"PDF successfully generated using weasyprint CLI at {output_path}")
                    pdf_generated = True
                else:
                    logger.warning(f"CLI method failed: {result.stderr}")
            except Exception as e:
                logger.warning(f"Error using weasyprint CLI: {str(e)}")

            # Method 2: Latest weasyprint API
            if not pdf_generated:
                try:
                    logger.info("Attempting to generate PDF using latest weasyprint API...")
                    try:
                        from weasyprint import HTML
                        HTML(string=html_content).write_pdf(str(output_path))
                        logger.info(f"PDF generated using latest API at {output_path}")
                        pdf_generated = True
                    except TypeError as e:
                        logger.warning(f"Latest API failed with TypeError: {str(e)}")
                except Exception as e:
                    logger.warning(f"Error with latest weasyprint API: {str(e)}")

            # Method 3: Legacy weasyprint API
            if not pdf_generated:
                try:
                    logger.info("Attempting to generate PDF using legacy weasyprint API...")
                    import weasyprint
                    from weasyprint import HTML as WeasyHTML
                    # For older versions of weasyprint
                    WeasyHTML(string=html_content).write_pdf(str(output_path))
                    logger.info(f"PDF generated using legacy API at {output_path}")
                    pdf_generated = True
                except Exception as e:
                    logger.warning(f"Legacy API failed: {str(e)}")

            # Method 4: Install compatible versions if available and user permitted
            if not pdf_generated and not settings.development_mode:
                logger.warning("All PDF generation methods failed.")
                logger.info("Consider running: pip install weasyprint==52.5 pydyf==0.5.0")

                # If in development mode, we can still proceed
                if settings.development_mode:
                    logger.info("[DEV MODE] Continuing despite PDF generation failure")
                    return output_path

                # For production, we should report the error
                logger.error("PDF generation failed. Check weasyprint and pydyf compatibility.")
                return None

            return output_path
        except Exception as e:
            logger.error(f"Error generating PDF: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

            # In development mode, still return the path even if generation failed
            if settings.development_mode:
                return output_path
            return None

    def generate_documents(self, job: Dict[str, Any]) -> Dict[str, Path]:
        """
        Generate both CV and motivation letter for a job application.

        Args:
            job: Job details dictionary

        Returns:
            Dictionary with paths to generated documents
        """
        # Load user profile
        profile = self.load_profile()

        # Prepare output paths
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        company_slug = job['company'].lower().replace(" ", "_")
        job_slug = job['title'].lower().replace(" ", "_")
        file_prefix = f"{timestamp}_{company_slug}_{job_slug}"

        cv_path = settings.output_dir / f"{file_prefix}_cv.pdf"
        letter_path = settings.output_dir / f"{file_prefix}_letter.pdf"

        # Generate CV
        cv_content = self.generate_cv_content(job, profile)
        cv_html = self.render_to_html("cv_template", cv_content, {
            "job": job,
            "name": settings.name,
            "email": settings.email,
        })
        cv_file = self.render_to_pdf(cv_html, cv_path)

        # Generate motivation letter
        letter_content = self.generate_letter_content(job, profile)
        letter_html = self.render_to_html("letter_template", letter_content, {
            "job": job,
            "name": settings.name,
            "email": settings.email,
        })
        letter_file = self.render_to_pdf(letter_html, letter_path)

        return {
            "cv": cv_file,
            "letter": letter_file,
            "cv_html": cv_html,
            "letter_html": letter_html
        }


def generate_documents_for_job(job: Dict[str, Any], llm_provider: Optional[str] = None) -> Dict[str, Path]:
    """
    Convenience function to generate documents for a job.

    Args:
        job: Job details dictionary
        llm_provider: Which LLM provider to use

    Returns:
        Dictionary with paths to generated documents
    """
    # Ensure output directory exists
    if settings.development_mode:
        os.makedirs(settings.output_dir, exist_ok=True)
        logger.info(f"[DEV MODE] Ensuring output directory exists: {settings.output_dir}")

    generator = DocumentGenerator(llm_provider=llm_provider)
    try:
        return generator.generate_documents(job)
    except Exception as e:
        logger.error(f"Error generating documents: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

        if settings.development_mode:
            # In development mode, return mock document paths
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            company_slug = job.get('company', 'unknown').lower().replace(" ", "_")
            job_slug = job.get('title', 'unknown').lower().replace(" ", "_")
            file_prefix = f"{timestamp}_{company_slug}_{job_slug}"

            cv_path = settings.output_dir / f"{file_prefix}_cv.pdf"
            letter_path = settings.output_dir / f"{file_prefix}_letter.pdf"

            logger.info(f"[DEV MODE] Returning mock document paths due to error")
            return {
                "cv": cv_path,
                "letter": letter_path,
                "cv_html": "<h1>Mock CV (Development Mode - Error Recovery)</h1>",
                "letter_html": "<h1>Mock Letter (Development Mode - Error Recovery)</h1>"
            }
        return {}


if __name__ == "__main__":
    # Example usage
    example_job = {
        "title": "Python Developer",
        "company": "Example Corp",
        "description": "We are looking for a Python developer with experience in web scraping and automation.",
        "url": "https://example.com/jobs/123",
        "job_id": "example-123"
    }

    docs = generate_documents_for_job(example_job)
    print(f"CV generated at: {docs['cv']}")
    print(f"Letter generated at: {docs['letter']}")