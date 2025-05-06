# Focus Pomodoro Bot Deployment Guide

This document provides detailed instructions for deploying, configuring, and maintaining the Focus Pomodoro Bot on a production server.

## Server Information

- **Current Production Server**: 217.154.83.34
- **Domain**: pomodoro.kapitonov.su
- **User**: root (SSH key authentication)
- **Application Directory**: /opt/focus_pomodoro

## Architecture Overview

The Focus Pomodoro Bot consists of:

1. **Telegram Bot**: Python application using python-telegram-bot library
2. **Web Application**: Flask app for timer display
3. **Database**: SQLite for data storage
4. **Nginx**: Web server with SSL/TLS support

## Deployment Process

### 1. Server Setup

```bash
# Update system packages
apt update && apt upgrade -y

# Install required dependencies
apt install -y python3.12 python3.12-venv python3-pip sqlite3 nginx ufw certbot python3-certbot-nginx

# Create service user
adduser --system --group pomodoro

# Create application directory
mkdir -p /opt/focus_pomodoro
chown pomodoro:pomodoro /opt/focus_pomodoro
```

### 2. Application Deployment

```bash
# Clone the application repository to the server (first-time setup)
git clone https://github.com/kaapyth0n/focus_todo_pomodoro_bot /opt/focus_pomodoro
chown -R pomodoro:pomodoro /opt/focus_pomodoro
```

# If updating an existing deployment, see the 'Code Updates' section below for the recommended workflow.

# Copy database and sound files if needed (first-time setup only)
scp focus_pomodoro.db clock-ticking-sound-effect-240503.mp3 root@217.154.83.34:/opt/focus_pomodoro/
chown pomodoro:pomodoro /opt/focus_pomodoro/focus_pomodoro.db /opt/focus_pomodoro/clock-ticking-sound-effect-240503.mp3
```

### 3. Python Environment Setup

```bash
# Create and activate virtual environment
cd /opt/focus_pomodoro
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install --upgrade pip
pip install -r requirements.txt
pip install "python-telegram-bot[job-queue]" flask

# Deactivate virtual environment
deactivate

# Ensure proper permissions
chown -R pomodoro:pomodoro venv
```

### 4. Configuration

Create or update the `.env` file:

```bash
cat > /opt/focus_pomodoro/.env << EOL
BOT_TOKEN=your_telegram_bot_token
DOMAIN_URL=https://pomodoro.kapitonov.su
FLASK_PORT=5002
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=urn:ietf:wg:oauth:2.0:oob
EOL

# Set proper permissions
chown pomodoro:pomodoro .env
chmod 600 .env
```

### 5. Systemd Service Setup

```bash
cat > /etc/systemd/system/focus_pomodoro.service << EOL
[Unit]
Description=Focus Pomodoro Bot & API
After=network.target

[Service]
User=pomodoro
WorkingDirectory=/opt/focus_pomodoro
Environment=PATH=/opt/focus_pomodoro/venv/bin:$PATH
ExecStart=/opt/focus_pomodoro/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

# Enable and start service
systemctl daemon-reload
systemctl enable focus_pomodoro
systemctl start focus_pomodoro
```

### 6. Nginx Configuration

```bash
cat > /etc/nginx/sites-available/pomodoro << EOL
server {
    listen 80;
    server_name pomodoro.kapitonov.su;

    location / {
        proxy_pass http://127.0.0.1:5002;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOL

# Enable site configuration
ln -sf /etc/nginx/sites-available/pomodoro /etc/nginx/sites-enabled/

# Test and reload Nginx
nginx -t
systemctl reload nginx
```

### 7. SSL/TLS Certificate

```bash
# Request certificate from Let's Encrypt
certbot --nginx -d pomodoro.kapitonov.su --non-interactive --agree-tos -m admin@kapitonov.su --redirect
```

### 8. Firewall Configuration

```bash
# Configure firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

## Maintenance Operations

### Service Management

```bash
# Check service status
systemctl status focus_pomodoro

# Start service
systemctl start focus_pomodoro

# Stop service
systemctl stop focus_pomodoro

# Restart service
systemctl restart focus_pomodoro

# View real-time logs
journalctl -fu focus_pomodoro
```

### Database Backup

The database is stored as `focus_pomodoro.db` in the application directory. Back it up regularly:

```bash
# Backup database
cp /opt/focus_pomodoro/focus_pomodoro.db /opt/backups/focus_pomodoro_$(date +%Y%m%d).db

# Or transfer to another server
scp /opt/focus_pomodoro/focus_pomodoro.db backup_server:/path/to/backup/
```

### Code Updates

To update the application code (recommended workflow):

```bash
# Stop the service
systemctl stop focus_pomodoro

# Backup the current application and database
cp -r /opt/focus_pomodoro /opt/focus_pomodoro_backup_$(date +%Y%m%d_%H%M%S)

# Update code using git
cd /opt/focus_pomodoro
git pull origin main

# Ensure correct permissions (if needed)
chown -R pomodoro:pomodoro /opt/focus_pomodoro

# Update dependencies if needed
source venv/bin/activate
pip install -r requirements.txt
pip install "python-telegram-bot[job-queue]" flask
deactivate

# Restart the service
systemctl start focus_pomodoro
```

> **Note:**
> - The `.env` file and `focus_pomodoro.db` are preserved during git-based updates.
> - Only use the tar/scp method if you need to deploy from a machine that cannot push to the repository, or for initial setup.

### Log Management

The application logs are stored in the systemd journal. Access them with:

```bash
# View recent logs
journalctl -u focus_pomodoro -n 100

# Follow logs in real-time
journalctl -fu focus_pomodoro

# View logs since a specific time
journalctl -u focus_pomodoro --since "2025-04-28 10:00:00"

# View logs between specific times
journalctl -u focus_pomodoro --since "2025-04-28 10:00:00" --until "2025-04-28 11:00:00"

# Export logs to a file
journalctl -u focus_pomodoro -n 1000 > /tmp/focus_pomodoro_logs.txt
```

Nginx web server logs are available at:
- Access logs: `/var/log/nginx/access.log`
- Error logs: `/var/log/nginx/error.log`

## SSL Certificate Renewal

Let's Encrypt certificates are valid for 90 days and automatically renewed by the certbot systemd timer:

```bash
# Check certificate status
certbot certificates

# Manual renewal (if needed)
certbot renew

# Check automatic renewal timer
systemctl list-timers | grep certbot
```

## Troubleshooting

### Common Issues

1. **Bot not responding:**
   ```bash
   # Check service status
   systemctl status focus_pomodoro
   
   # Check logs for errors
   journalctl -u focus_pomodoro -n 100
   ```

2. **Timer functionality not working:**
   ```bash
   # Ensure job queue is properly configured
   grep -A 5 "def main" /opt/focus_pomodoro/bot.py
   
   # Line should include 'job_queue()' in the Application builder:
   # application = Application.builder().token(TOKEN).post_init(post_init).job_queue().build()
   ```

3. **Web interface not accessible:**
   ```bash
   # Check Nginx status
   systemctl status nginx
   
   # Check Nginx configuration
   nginx -t
   
   # Check SSL certificate
   certbot certificates
   
   # Test Flask app locally
   curl -s http://localhost:5002/
   ```

4. **Database issues:**
   ```bash
   # Check database file existence and permissions
   ls -la /opt/focus_pomodoro/focus_pomodoro.db
   
   # Use sqlite3 to check database
   sqlite3 /opt/focus_pomodoro/focus_pomodoro.db .tables
   ```

### Recovery Procedures

1. **Roll back to previous version:**
   ```bash
   systemctl stop focus_pomodoro
   rm -rf /opt/focus_pomodoro
   cp -r /opt/focus_pomodoro_backup_YYYYMMDD /opt/focus_pomodoro
   chown -R pomodoro:pomodoro /opt/focus_pomodoro
   systemctl start focus_pomodoro
   ```

2. **Restore database backup:**
   ```bash
   systemctl stop focus_pomodoro
   cp /opt/backups/focus_pomodoro_YYYYMMDD.db /opt/focus_pomodoro/focus_pomodoro.db
   chown pomodoro:pomodoro /opt/focus_pomodoro/focus_pomodoro.db
   systemctl start focus_pomodoro
   ```

## Monitoring

To implement basic monitoring for the service, you can:

1. Set up a cron job to check the service status:
   ```bash
   # Add to root's crontab
   */5 * * * * systemctl is-active --quiet focus_pomodoro || echo "Focus Pomodoro service down" | mail -s "Alert: Service Down" admin@example.com
   ```

2. Monitor disk space usage:
   ```bash
   # Check disk space
   df -h /opt
   
   # Monitor database size
   du -h /opt/focus_pomodoro/focus_pomodoro.db
   ```

## Security Considerations

1. **File Permissions:**
   - Ensure `.env` file permissions are restricted to 600
   - Application files should be owned by pomodoro user

2. **Regular Updates:**
   - Keep the system updated with security patches
   - Update Python dependencies regularly for security fixes

3. **Backups:**
   - Implement regular database backups
   - Consider off-site backups for disaster recovery

## Contacts and Support

For questions or assistance with this deployment, contact:
- Email: admin@kapitonov.su
- GitHub repository: https://github.com/kaapyth0n/focus_todo_pomodoro_bot

