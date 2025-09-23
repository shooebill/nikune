# Suggested Commands for Nikune Project

## Environment Setup
```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Deactivate virtual environment
deactivate
```

## Development Commands
```bash
# Run the main application
python main.py

# Install new dependencies
pip install <package_name>
pip freeze > requirements.txt

# Python code execution
python -m nikune.module_name
```

## System Commands (macOS/Darwin)
```bash
# File operations
ls -la                    # List files with details
find . -name "*.py"       # Find Python files
grep -r "pattern" .       # Search for patterns

# Git operations
git status                # Check git status
git add .                 # Stage all changes
git commit -m "message"   # Commit changes
git push                  # Push to remote

# Process management
ps aux | grep python      # Find Python processes
kill -9 <pid>            # Kill process by PID
```

## Environment Variables
Create/edit `.env` file for:
- Twitter API credentials
- Configuration settings
- Secret keys

## Notes
- This is a new project with empty implementation files
- No testing framework is currently configured
- No linting/formatting tools are set up yet
- Most development commands will need to be established as the project grows