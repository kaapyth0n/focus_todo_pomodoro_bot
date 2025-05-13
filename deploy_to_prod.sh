#!/bin/bash
# Focus Pomodoro Bot Production Deployment Script
# Usage: bash ~/deploy_to_prod.sh

set -e

APP_DIR="/opt/focus_pomodoro"
SERVICE="focus_pomodoro"
VENV="$APP_DIR/venv"

# Stop the bot service
echo "Stopping $SERVICE..."
systemctl stop $SERVICE || true

# Update codebase
echo "Pulling latest code from main branch..."
cd $APP_DIR
git pull origin main

# Activate virtualenv and update dependencies
echo "Updating Python dependencies..."
source $VENV/bin/activate
pip install -r requirements.txt
pip install "python-telegram-bot[job-queue]" flask

deactivate

# Restart the bot service
echo "Starting $SERVICE..."
systemctl start $SERVICE

# Show service status
echo "Service status:"
systemctl status $SERVICE --no-pager 