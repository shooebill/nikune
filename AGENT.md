# VS Code Agent Settings for Nikune Project

## Project Commands

### Development
```bash
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# System test (recommended first run)
python main.py --test

# System health check
python main.py --health

# Post tweet immediately
python main.py --post-now

# Post with specific category
python main.py --post-now --category お肉

# Start scheduler (runs continuously)
python main.py --schedule

# Setup database with sample data
python main.py --setup-db

# Import from CSV
python main.py --setup-db --csv data/templates.csv

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

- This project uses Python virtual environment (`.venv/`)
- Twitter API credentials should be stored in `.env` file
- Main dependencies: tweepy, schedule, requests, python-dotenv, redis
- Database: SQLite (persistent) + Redis (caching/session management)
- Development tools: black, isort, flake8, mypy (configure via .flake8 and pyproject.toml)

## Project Structure

- `nikune/` - Main package with core modules
  - `twitter_client.py` - Twitter API integration (完成)
  - `database.py` - SQLite + Redis database management (完成)
  - `content_generator.py` - Tweet content generation (完成)
  - `scheduler.py` - Tweet scheduling system (完成)
  - `health_check.py` - System health monitoring (完成)
- `config/` - Configuration and settings
  - `settings.py` - Environment variable management (完成)
- `main.py` - Application entry point with CLI (完成)
- `data/` - Database and CSV files storage
- `requirements.txt` - Python dependencies
- `.env` - Twitter API credentials (create manually)

## Development Status

✅ **Project Complete & Production Ready**

All core functionalities implemented and tested:
- Twitter API integration with posting, retweeting, liking
- Dual database system (SQLite + Redis) with duplicate prevention
- Dynamic content generation with time-based placeholders
- Flexible scheduling system (default: 9:00, 13:30, 19:00 daily)
- System health monitoring and diagnostics
- Comprehensive CLI interface for all operations
- CSV import/export for template management
- Full error handling and logging

Ready for production deployment! 🐻🍖