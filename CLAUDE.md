# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Telegram bot for time tracking using the Pomodoro Technique, integrated with Google Sheets and Jira Cloud. Users can create projects/tasks, run work and break timers, view productivity reports, and export session data.

## Key Commands

### Python Virtual Environment
**IMPORTANT**: This project uses a Python virtual environment. Always activate it before running Python commands:
```bash
source venv/bin/activate
```

All Python commands below assume the virtual environment is activated.

### Running the Bot
```bash
python bot.py
```
The bot automatically initializes/migrates the SQLite database (`focus_pomodoro.db`) on startup.

### Development Setup
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your BOT_TOKEN, DOMAIN_URL, ADMIN_USER_ID, etc.
```

For local development with web timer and OAuth:
```bash
ngrok http 5002  # Run in separate terminal
# Update .env with ngrok HTTPS URL as DOMAIN_URL
```

### Database Management
The database schema is automatically created and migrated on bot startup via `database.create_database()`. Schema changes are handled through the `_check_add_columns()` helper and `_apply_migrations()` function.

## Architecture

### Core Components

**bot.py** - Main entry point. Initializes the Telegram bot application, registers all handlers (commands, callbacks, conversation flows), starts Flask web server in a background thread, and runs the bot polling loop.

**config.py** - Environment configuration loader. Defines `timer_states` dict (in-memory timer state keyed by user_id), loads settings from `.env`, and exports constants like `TOKEN`, `DOMAIN_URL`, `SUPPORTED_LANGUAGES`.

**database.py** - SQLite database interface. Tables: `users`, `projects`, `tasks`, `pomodoro_sessions`, `bot_settings`, `forwarded_messages`. All DB functions handle connections and include error logging. Foreign key constraints are enabled (`PRAGMA foreign_keys = ON`). Includes CRUD operations for projects/tasks (create, read, update/rename, delete, archive).

**web_app.py** - Flask web application. Serves:
- Timer interface at `/timer/<user_id>` (dynamically translated based on user's language preference)
- OAuth callbacks for Google (`/oauth2callback`) and Jira (`/oauth2callback/jira`)
- Timer control APIs (pause/resume/stop) secured with Telegram WebApp initData verification
- Static pages (home, privacy, terms)

The Flask app shares `timer_states` dict and receives the Telegram bot's `JobQueue` via `set_job_queue()` to schedule timer completion callbacks.

### Handlers Module

**handlers/commands.py** - All command handlers (`/start`, `/create_project`, `/start_timer`, etc.). Contains conversation handlers for interactive flows (project/task creation, renaming, forwarded messages). Handles reply keyboard button presses via `handle_text_message()`.

**handlers/callbacks.py** - Inline button callback handlers for interactive UI (project/task selection, renaming, reports, deletion confirmations, Jira issue imports).

**handlers/google_auth.py** - Google OAuth flow and Sheets export. Uses OAuth 2.0 authorization code flow with manual code copy/paste (not automatic redirect). Credentials stored as JSON in `users.google_credentials_json`.

**handlers/jira_auth.py** - Jira Cloud OAuth and issue management. Fetches user's assigned issues, allows import as bot tasks (stores Jira issue key as task name prefix like `[PROJ-123]`), prompts for worklog submission after timer completion.

**handlers/admin.py** - Admin commands (statistics, notification toggle). Admin status stored in `users.is_admin` column.

### Timer State Management

Timer state is stored in-memory in the `timer_states` dict (shared between bot.py and web_app.py):
```python
timer_states[user_id] = {
    'state': 'running'|'paused'|'stopped',
    'start_time': datetime,        # When current run segment started
    'initial_start_time': datetime, # Original timer start (for DB logging)
    'accumulated_time': float,     # Minutes accumulated before current segment
    'duration': float,             # Total timer duration in minutes
    'session_type': 'work'|'break',
    'job': Job                     # PTB JobQueue scheduled job
}
```

**State is not persisted** - timers are lost on bot restart. Timer completion is handled by `timer_finished()` callback scheduled via `JobQueue`.

### Internationalization (i18n)

**i18n_utils.py** - Translation system using `python-i18n` library. Translations stored in `locales/{language_code}.yml`. User language preference stored in `users.language_code` (auto-detected from Telegram client on first `/start`).

The `_(user_id, key, **kwargs)` function retrieves translations. Both bot messages and web timer UI are translated using this system. Flask integration via custom context processor in `web_app.py`.

### Database Schema Notes

- **Status Fields**: `projects.status` and `tasks.status` use constants `STATUS_ACTIVE=0` and `STATUS_DONE=1` for archiving.
- **Foreign Keys**: Cascading deletes configured for projects→tasks and tasks→sessions. User table has `current_project_id` and `current_task_id` with `ON DELETE SET NULL`.
- **Credentials**: OAuth credentials stored as JSON strings in `google_credentials_json` and `jira_credentials_json` columns.
- **Jira Integration**: Tasks created from Jira have names like `[JIRA-KEY] Summary`. Last session ID tracked to prompt for Jira worklog.

### Conversation Handlers

ConversationHandlers in `bot.py` manage multi-step flows:
- Google OAuth code entry (`WAITING_CODE` state)
- Jira OAuth code entry (`WAITING_JIRA_CODE` state)
- Project creation with name prompt (`WAITING_PROJECT_NAME` state)
- Task creation with name prompt (`WAITING_TASK_NAME` state)
- Project renaming with new name prompt (`WAITING_RENAME_PROJECT_NAME` state)
- Task renaming with new name prompt (`WAITING_RENAME_TASK_NAME` state)
- Forwarded message handling (`FORWARDED_MESSAGE_PROJECT_SELECT`, `FORWARDED_MESSAGE_PROJECT_CREATE` states)

All use `/cancel` as fallback command to exit the conversation.

### Web API Authentication

Timer control endpoints (`/api/timer/<user_id>/pause`, `/resume`, `/stop`) require Telegram WebApp `initData` verification. The `_verify_tg_init_data()` function validates HMAC signature and timestamp per Telegram Mini App spec. Public status endpoint (`/api/timer_status/<user_id>`) allows unauthenticated access but validates identity if initData is provided.

**CRITICAL**: The HMAC verification uses a specific parameter order mandated by Telegram:
```python
# Correct: "WebAppData" is the key, bot TOKEN is the message
secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()

# WRONG: Do not swap the parameters (common mistake)
# secret_key = hmac.new(TOKEN.encode(), b"WebAppData", hashlib.sha256).digest()
```

The web timer page (`templates/timer.html`) must include the Telegram WebApp SDK script in the `<head>` section:
```html
<script src="https://telegram.org/js/telegram-web-app.js"></script>
```

And must call `Telegram.WebApp.ready()` after initialization to signal readiness to Telegram. The `initData` property provides authentication credentials that must be passed in the `X-Telegram-Init-Data` header for all authenticated API requests.

## Important Patterns

### Error Handling
- All database operations use try/except blocks with rollback on error
- Logging via Python's `logging` module (configured in `bot.py` main block)
- Web endpoints return JSON error responses with appropriate HTTP status codes

### State Synchronization
- User's current project/task stored in DB (`users.current_project_id`, `users.current_task_id`)
- DB access via `database.get_current_project(user_id)` and `database.set_current_project(user_id, project_id)`
- Timer state is in-memory only; session data persisted to `pomodoro_sessions` table only on timer completion/stop

### Admin Notifications
Admin receives notifications on:
- New user registration (first `/start`)
- Project creation
- Task creation

Controlled by `bot_settings.admin_notifications` setting (toggle via `/admin_notify_toggle`).

### Report Generation
Reports aggregate from `pomodoro_sessions` table filtered by `session_type = 'work'`. Three report types:
- Daily: `get_daily_report(user_id, offset=0)` - offset in days
- Weekly: `get_weekly_report(user_id, offset=0)` - offset in weeks, Monday-based
- Monthly: `get_monthly_report(user_id, offset=0)` - offset in months

All return structured data with project/task breakdown.

## Testing Notes

No automated test suite is present. Manual testing workflow:
1. Start bot locally with ngrok
2. Test Telegram commands via bot chat
3. Test web timer at `https://<ngrok-url>/timer/<your-user-id>`
4. Verify OAuth flows by checking callback pages and credential storage
5. Check SQLite DB directly for data verification

## Configuration Requirements

Required environment variables (see `.env.example`):
- `BOT_TOKEN` - From BotFather
- `DOMAIN_URL` - Public HTTPS URL (for OAuth callbacks and web timer)
- `ADMIN_USER_ID` - Numeric Telegram user ID
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` - For Sheets integration
- `JIRA_CLIENT_ID` / `JIRA_CLIENT_SECRET` - For Jira Cloud integration
- `FLASK_PORT` - Default 5002

OAuth redirect URIs must be configured in Google Cloud Console and Atlassian Developer Console to match `DOMAIN_URL/oauth2callback` and `DOMAIN_URL/oauth2callback/jira`.

## Dependency Management

### Updating Pinned Packages in `requirements.txt`

This project uses pinned versions for stability. Updates should be performed intentionally and tested thoroughly. **Recommended frequency: every 1-3 months**, or when changelogs flag important changes (especially for `python-telegram-bot` as Telegram APIs evolve).

#### Safe Update Workflow

1. **Prepare Test Environment**
   ```bash
   git checkout -b update-deps
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Check for Updates**
   ```bash
   pip list --outdated  # Shows available updates
   ```

3. **Update Packages**

   **Targeted approach (recommended):**
   ```bash
   pip install --upgrade python-telegram-bot APScheduler Flask
   ```

   **Update all packages:**
   ```bash
   pip install --upgrade -r requirements.txt --upgrade-strategy eager
   ```

   **Interactive approach:**
   ```bash
   pip install pip-review
   pip-review --local --interactive
   ```

4. **Freeze New Versions**
   ```bash
   pip freeze > requirements.txt
   git diff requirements.txt  # Review changes, watch for major version jumps
   ```

5. **Test Thoroughly**
   ```bash
   python bot.py  # Run bot locally
   # Test job_queue:
   python -c "from telegram.ext import Application; app = Application.builder().token('dummy').build(); print(app.job_queue is not None)"
   # Run deploy_to_prod.sh in staging if available
   ```

6. **Security Check (Optional but Recommended)**
   ```bash
   pip install pip-audit safety
   pip-audit  # Check for known vulnerabilities
   safety check  # Alternative security scanner
   ```

7. **Commit and Deploy**
   ```bash
   git add requirements.txt
   git commit -m "Update dependencies to latest stable versions"
   git checkout main
   git merge update-deps
   bash deploy_to_prod.sh  # Script's --upgrade will install new pins
   ```

#### Tips
- **Watch for breaking changes**: Review changelogs on PyPI before major version bumps
- **Looser pins**: For minor updates only, use `~=3.1.0` syntax instead of exact pins (but exact pins keep deploys reproducible)
- **Priority packages**: Monitor `python-telegram-bot`, `Flask`, `APScheduler` closely
- **CI/CD**: Consider GitHub Actions + Dependabot for automated updates at scale

## Troubleshooting

### Telegram WebApp Authentication Issues

If timer control buttons return 401 Unauthorized:

1. **Verify SDK is loaded**: Check that `templates/timer.html` includes:
   ```html
   <script src="https://telegram.org/js/telegram-web-app.js"></script>
   ```
   This must be in the `<head>` section before any JavaScript that uses `window.Telegram.WebApp`.

2. **Check HMAC parameter order**: In `web_app.py`, the `_verify_tg_init_data()` function must use the correct parameter order:
   ```python
   secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
   ```
   The first parameter is always `"WebAppData"`, the second is the bot token. Swapping these is a common mistake that causes hash mismatch.

3. **Debug verification failures**: Temporarily change logging level from `debug` to `warning` in `_verify_tg_init_data()` to see which verification step fails:
   - "initData is empty" - SDK not loaded or Mini App not properly launched
   - "hash mismatch" - Wrong HMAC parameter order or incorrect bot token
   - "timestamp too old" - `auth_date` exceeds `max_age_sec` (default 3600s/1 hour)

4. **Verify Mini App launch method**: `initData` is only populated when launched from inline keyboard buttons with `WebAppInfo`, not from custom keyboards or direct URL access.

5. **Test with browser console**: Check `window.Telegram.WebApp.initData` in the browser console. It should be a non-empty query string. If empty, the issue is with SDK loading or launch method.