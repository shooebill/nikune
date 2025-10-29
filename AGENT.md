# VS Code Agent Settings for Nikune Project

## Project Commands

### Development
```bash
# All commands use uv for automatic dependency management
# No manual virtual environment activation needed!

# System test (recommended first run)
uv run python main.py --test

# System health check
uv run python main.py --health

# Post tweet immediately
uv run python main.py --post-now

# Post with specific category
uv run python main.py --post-now --category お肉

# Quote retweet check
uv run python main.py --quote-check

# Quote retweet check (dry run - no API calls)
uv run python main.py --quote-check --dry-run

# Start scheduler (runs continuously)
uv run python main.py --schedule

# Setup database with sample data
uv run python main.py --setup-db

# Import from CSV
uv run python main.py --setup-db --csv data/templates.csv

# Manual dependency management (if needed)
uv add <package>        # Add package
uv remove <package>     # Remove package  
uv sync                 # Sync dependencies
```

### Code Quality
```bash
# Format code (uv automatically manages dependencies)
uv run black .

# Sort imports
uv run isort .

# Run both formatting commands
uv run isort . && uv run black .

# Lint code
uv run flake8 .

# Type check
uv run mypy nikune/
```

### Testing
```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=nikune

# Run specific test
uv run pytest tests/test_specific.py
```

## Environment Setup Notes

- **Package Management**: Uses `uv` for ultra-fast dependency management (replaces pip/venv)
- **Python Version**: Requires Python 3.14+ (automatically managed by uv)
- **Virtual Environment**: Automatically created/managed by uv (no manual activation needed)
- **Twitter API credentials**: Store in `.env` file in project root
- **Main dependencies**: tweepy, schedule, requests, python-dotenv, redis
- **Database**: SQLite (persistent) + Redis (caching/session management)
- **Development tools**: black, isort, flake8, mypy (all managed via pyproject.toml)

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
- **🆕 Auto Quote Retweet**: Automatically quote tweets meat-related content from followed users
- Dual database system (SQLite + Redis) with duplicate prevention
- Dynamic content generation with time-based placeholders
- Flexible scheduling system (default: 9:00, 13:30, 19:00 daily)
- **🆕 Rate Limiting**: Smart rate limiting (2 quotes/hour, 30min intervals)
- **🆕 Dry Run Mode**: Test functionality without API calls using mock data
- System health monitoring and diagnostics
- Comprehensive CLI interface for all operations
- CSV import/export for template management
- Full error handling and logging
- **🆕 UV Package Management**: Ultra-fast dependency management with Python 3.14

Ready for production deployment! 🐻🍖

### Recent Updates
- **Auto Quote Retweet System**: Detects meat-related tweets and adds thoughtful comments
- **Mock Timeline for Testing**: API-free testing with realistic mock data
- **Enhanced Rate Limiting**: Prevents Twitter API violations with smart throttling
- **UV Integration**: Modern Python tooling for faster development workflow