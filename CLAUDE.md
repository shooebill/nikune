# Claude Code Settings for Nikune Project

## Project Commands

### Development
```bash
# Activate virtual environment and run
source venv/bin/activate && python main.py

# Install dependencies
pip install -r requirements.txt

# Update requirements after adding new packages
pip freeze > requirements.txt
```

### Code Quality (Future Setup)
```bash
# Format code (when black is installed)
black .

# Lint code (when flake8 is installed)
flake8 .

# Sort imports (when isort is installed)
isort .

# Type check (when mypy is installed)
mypy nikune/
```

### Testing (Future Setup)
```bash
# Run tests (when pytest is installed)
pytest

# Run tests with coverage (when pytest-cov is installed)
pytest --cov=nikune
```

## Environment Setup Notes

- This project uses Python virtual environment (`venv/`)
- Twitter API credentials should be stored in `.env` file
- Main dependencies: tweepy, schedule, requests, python-dotenv

## Project Structure

- `nikune/` - Main package with core modules
- `config/` - Configuration and settings
- `main.py` - Application entry point
- `requirements.txt` - Python dependencies

## Development Status

This is a new project with basic structure in place but minimal implementation. Core modules (twitter_client, scheduler, content_generator) are ready for development.