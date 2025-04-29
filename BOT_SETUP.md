# Bot Setup Guide

## Job Queue Setup

The Focus Pomodoro Bot requires the job queue functionality from the python-telegram-bot library to manage timers.

### Installation Instructions

To properly install the required dependencies:

```bash
# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies with the job-queue extra
pip install -r requirements.txt
```

### Troubleshooting Job Queue Errors

If you encounter an error like:
```
TypeError: ApplicationBuilder.job_queue() missing 1 required positional argument: 'job_queue'
```

This typically means the job queue extension isn't installed properly. Fix it by running:

```bash
pip install "python-telegram-bot[job-queue]"
```

### Library Version Information

This bot has been tested with python-telegram-bot version 21.x. The job queue functionality requires the `[job-queue]` extra to be installed. 

The production server setup installs this correctly as specified in DEPLOY.md:
```bash
pip install "python-telegram-bot[job-queue]" flask
```

## Database Setup

The database will be automatically created when the bot is first run. No additional setup is required.

## Running the Bot

To run the bot:

```bash
# Activate the virtual environment if not already activated
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Run the bot
python bot.py
```

The bot will start and display "Bot is running..." when successful. 