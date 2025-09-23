# Code Style and Conventions

## Current Status
This is a new project with minimal code implemented. Most files are empty, so conventions need to be established.

## Python Style Recommendations

### General Guidelines
- Follow PEP 8 Python style guide
- Use descriptive variable and function names
- Add docstrings to classes and functions
- Use type hints where appropriate

### File Structure
```python
# Standard import order:
# 1. Standard library imports
# 2. Third-party imports  
# 3. Local application imports

import os
import sys

import tweepy
import schedule

from nikune.config import settings
```

### Naming Conventions
- **Files**: snake_case (twitter_client.py, content_generator.py)
- **Classes**: PascalCase (TwitterClient, ContentGenerator)
- **Functions/Variables**: snake_case (get_tweets, user_id)
- **Constants**: UPPER_SNAKE_CASE (API_KEY, MAX_RETRIES)

### Code Organization
Based on the module structure:
- `twitter_client.py`: Twitter API interaction classes and functions
- `scheduler.py`: Task scheduling and timing logic
- `content_generator.py`: Content creation and generation logic
- `config/settings.py`: Configuration management

### Documentation
- Use docstrings for all public functions and classes
- Include type hints for function parameters and returns
- Add inline comments for complex logic

### Error Handling
- Use specific exception types
- Log errors appropriately
- Handle API rate limits and network issues

## Future Recommendations
1. Set up Black for code formatting
2. Configure flake8 for linting
3. Use isort for import sorting
4. Add mypy for type checking
5. Establish testing conventions with pytest

## Environment Variables
- Store sensitive data (API keys, tokens) in .env file
- Use python-dotenv for loading environment variables
- Never commit secrets to version control