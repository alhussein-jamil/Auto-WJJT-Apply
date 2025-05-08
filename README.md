# Auto WTTJ Applicator

Automate job applications on [Welcome to the Jungle](https://www.welcometothejungle.com/) using AI-generated customized CVs and motivation letters.

## Features

- Scrapes job listings that allow direct applications
- Generates tailored CVs and motivation letters using LLM (OpenAI GPT-4, Claude, or local models)
- Automatically submits applications with generated documents
- Logs all actions and application outcomes
- Highly configurable and extensible

## Requirements

- Python 3.10+
- Playwright
- OpenAI API key (or alternative LLM provider)
- WeasyPrint or pdfkit for PDF generation

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/auto-wttj-applicator
cd auto-wttj-applicator

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install

# Set up your environment
cp .env.example .env
# Edit .env with your credentials and preferences
```

## Configuration

Edit the `.env` file with your credentials and preferences:

- `OPENAI_API_KEY`: Your OpenAI API key
- `LLM_PROVIDER`: Choose between "openai", "anthropic", or "local"
- `BASE_CV_PATH`: Path to your base CV content
- `BASE_PROFILE_PATH`: Path to your profile data (JSON)
- `EMAIL` and `NAME`: Your contact information
- `MAX_APPLICATIONS_PER_DAY`: Limit daily applications
- `PLAYWRIGHT_HEADLESS`: Run browser in headless mode (True/False)

## Usage

```bash
# Run the main application
python main.py

# Optional arguments
python main.py --max-jobs 5  # Process only 5 jobs
python main.py --headless False  # Run with visible browser
python main.py --dry-run  # Generate documents without submitting
```

## Project Structure

```
auto-wttj-applicator/
├── main.py                     # Entry point
├── config.py                   # Configuration loader
├── browser/
│   └── wttj_scraper.py         # Job scraping module
├── llm/
│   └── generate_documents.py   # Document generation with LLM
├── submit/
│   └── auto_submit.py          # Application submission
├── templates/
│   ├── cv_template.html        # CV template
│   └── letter_template.html    # Motivation letter template
├── output/                     # Generated documents
├── logs/                       # Application logs
├── utils/
│   └── logger.py               # Logging utility
└── data/                       # Profile data
```

## Extending

- Add support for other job platforms
- Implement alternative LLM providers
- Create custom CV templates
- Add a web dashboard for monitoring

## License

MIT