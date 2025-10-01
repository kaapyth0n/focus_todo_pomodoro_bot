#!/bin/bash
# Focus Pomodoro Bot Production Deployment Script
# Usage: bash ~/deploy_to_prod.sh

set -e

APP_DIR="/opt/focus_pomodoro"
SERVICE="focus_pomodoro"
VENV="$APP_DIR/venv"
LOG_FILE="/var/log/focus_deploy.log"

# Log to file
exec > >(tee -a "$LOG_FILE") 2>&1

# Stop the bot service
echo "Stopping $SERVICE..."
systemctl stop $SERVICE || true

# Update codebase
echo "Pulling latest code from main branch..."
cd $APP_DIR
git pull origin main
if [ $? -ne 0 ]; then
    echo "Git pull failed! Aborting."
    exit 1
fi

# Create/activate virtualenv and update dependencies
echo "Updating Python dependencies..."
if [ ! -d "$VENV" ]; then
    python3 -m venv $VENV
fi
source $VENV/bin/activate
pip install -r requirements.txt --upgrade
pip check  # Validate no conflicts
deactivate

# Restart the bot service
echo "Starting $SERVICE..."
systemctl start $SERVICE
systemctl enable $SERVICE  # Ensure it starts on boot

# Show service status
echo "Service status:"
systemctl status $SERVICE --no-pager

echo "Deployment complete. Check $LOG_FILE for details."