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

**database.py** - SQLite database interface. Tables: `users`, `projects`, `tasks`, `pomodoro_sessions`, `bot_settings`, `forwarded_messages`. All DB functions handle connections and include error logging. Foreign key constraints are enabled (`PRAGMA foreign_keys = ON`).

**web_app.py** - Flask web application. Serves:
- Timer interface at `/timer/<user_id>` (dynamically translated based on user's language preference)
- OAuth callbacks for Google (`/oauth2callback`) and Jira (`/oauth2callback/jira`)
- Timer control APIs (pause/resume/stop) secured with Telegram WebApp initData verification
- Static pages (home, privacy, terms)

The Flask app shares `timer_states` dict and receives the Telegram bot's `JobQueue` via `set_job_queue()` to schedule timer completion callbacks.

### Handlers Module

**handlers/commands.py** - All command handlers (`/start`, `/create_project`, `/start_timer`, etc.). Contains conversation handlers for interactive flows (project/task creation, forwarded messages). Handles reply keyboard button presses via `handle_text_message()`.

**handlers/callbacks.py** - Inline button callback handlers for interactive UI (project/task selection, reports, deletion confirmations, Jira issue imports).

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
- Forwarded message handling (`FORWARDED_MESSAGE_PROJECT_SELECT`, `FORWARDED_MESSAGE_PROJECT_CREATE` states)

All use `/cancel` as fallback command to exit the conversation.

### Web API Authentication

Timer control endpoints (`/api/timer/<user_id>/pause`, `/resume`, `/stop`) require Telegram WebApp `initData` verification. The `_verify_tg_init_data()` function validates HMAC signature and timestamp per Telegram Mini App spec. Public status endpoint (`/api/timer_status/<user_id>`) allows unauthenticated access but validates identity if initData is provided.

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