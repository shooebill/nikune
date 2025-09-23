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

### Code Quality
```bash
# Format code
black .

# Sort imports
isort .

# Run both formatting commands
isort . && black .

# Lint code (when flake8 is installed)
flake8 .

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
- Development tools: black, isort (for code formatting)

## Project Structure

- `nikune/` - Main package with core modules
- `config/` - Configuration and settings
- `main.py` - Application entry point
- `requirements.txt` - Python dependencies

## Development Status

This is a new project with basic structure in place but minimal implementation. Core modules (twitter_client, scheduler, content_generator) are ready for development.