"""
Configuration management for the auto-wttj-applicator.
Loads environment variables and provides application settings.
"""

from pathlib import Path
from typing import Optional, Literal
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    gemini_api_key: str = Field(default="", env="GEMINI_API_KEY")
    anthropic_api_key: str = Field(default="", env="ANTHROPIC_API_KEY")
    google_api_key: str = Field(default="", env="GOOGLE_API_KEY")

    # Profile paths
    base_cv_path: Path = Field(default=Path("./data/base_cv.txt"), env="BASE_CV_PATH")
    base_profile_path: Path = Field(default=Path("./data/profile.json"), env="BASE_PROFILE_PATH")

    # User info
    email: str = Field(default="", env="EMAIL")
    name: str = Field(default="", env="NAME")
    user_email: Optional[str] = Field(default=None, env="USER_EMAIL")
    user_password: Optional[str] = Field(default=None, env="USER_PASSWORD")

    # WTTJ credentials
    wttj_username: Optional[str] = Field(default=None, env="WTTJ_USERNAME")
    wttj_password: Optional[str] = Field(default=None, env="WTTJ_PASSWORD")

    # LLM settings
    llm_provider: Literal["openai", "anthropic", "google", "local"] = Field(default="google", env="LLM_PROVIDER")
    completion_model: str = Field(default="claude-3-opus-20240229", env="COMPLETION_MODEL")
    gpt_model: str = Field(default="gpt-4o", env="GPT_MODEL")
    gemini_model: str = Field(default="gemini-1.0-pro", env="GEMINI_MODEL")

    # Application settings
    max_jobs_per_run: int = Field(default=5, env="MAX_JOBS_PER_RUN")
    max_applications_per_day: int = Field(default=10, env="MAX_APPLICATIONS_PER_DAY")
    playwright_headless: bool = Field(default=True, env="PLAYWRIGHT_HEADLESS")

    # Paths
    output_dir: Path = Field(default=Path("./output"), env="OUTPUT_DIR")
    log_db_path: Path = Field(default=Path("./logs/job_log.db"), env="LOG_DB_PATH")

    # HTML templates
    cv_template_path: Path = Field(default=Path("./templates/cv_template.html"))
    letter_template_path: Path = Field(default=Path("./templates/letter_template.html"))

    # WTTJ URLs
    wttj_base_url: str = "https://www.welcometothejungle.com"
    wttj_jobs_url: str = "https://www.welcometothejungle.com/en/jobs"

    # Development settings
    development_mode: bool = Field(default=False, env="DEVELOPMENT_MODE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def ensure_paths_exist(self) -> None:
        """Ensure all necessary directories exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_db_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure base profile and CV files exist (create empty if not)
        if not self.base_profile_path.exists():
            self.base_profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.base_profile_path, "w") as f:
                f.write("{}")

        if not self.base_cv_path.exists():
            self.base_cv_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.base_cv_path, "w") as f:
                f.write("")

# Create a singleton settings instance
settings = Settings()
settings.ensure_paths_exist()

# Function to access settings
def get_settings() -> Settings:
    """Get the application settings."""
    return settings
