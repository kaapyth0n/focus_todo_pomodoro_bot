# Focus Pomodoro Bot

A Telegram bot that helps you manage projects and tasks, track your work sessions using the Pomodoro Technique, and export your data.

## Features

- **Project & Task Management:**
    - Create projects and tasks.
    - Rename projects and tasks with duplicate name checking.
    - Interactive prompts if names are omitted from creation commands.
    - Select active projects and tasks for tracking.
    - Mark projects and tasks as "done" (archive) to hide them from main lists.
    - View active or archived projects/tasks.
    - Delete projects or tasks (with confirmation).
    - Forward messages to create tasks in existing or new projects.
- **Pomodoro Timer:**
    - Start customizable work timers (default 25 mins) for selected tasks.
    - Start short (5 min), medium (10 min), or long (15 min) break timers (prompted after work, or via button).
    - Pause and resume timers.
    - Stop timers early, logging the time worked.
    - View the current timer countdown in a web interface that matches your language preference.
    - Interactive web timer with control buttons (pause/resume/stop) and sound muting option.
- **Reporting & Data:**
    - View daily, weekly, and monthly productivity reports with project/task breakdown.
    - Connect to Google Sheets account via OAuth.
    - Export all logged Pomodoro sessions to a specified Google Sheet.
- **User Experience:**
    - Reply Keyboard with common actions (Start, Stop, Pause, Resume, Report, Break).
    - Inline buttons for list selection, navigation, and actions.
    - Persistent selection of the current project and task.
    - Multi-language support (English, German, Russian) for both bot and web interface.
    - Directly create tasks from forwarded messages.
- **Admin Features:**
    - Notifications for new user registrations and project/task creations.
    - Toggle admin notifications on/off.
    - View basic bot usage statistics.
- **Jira Cloud Integration:**
    - Connect your Jira Cloud account via OAuth.
    - Import open Jira issues assigned to you as bot tasks (with project auto-creation).
    - When you stop a timer for a Jira-linked task, the bot will prompt you to log the session as work in Jira.
    - Worklog is added to the corresponding Jira issue with the time spent.

## Setup Instructions

### Prerequisites

- Python 3.10+ (due to dependencies like `google-auth`)
- A Telegram bot token (obtained from [BotFather](https://t.me/botfather))
- Google Cloud Project credentials (`credentials.json`) for Google Sheets integration (see [Google Cloud Setup](#google-cloud-setup))
- `ngrok` (optional, for local development web timer access): [ngrok.com](https://ngrok.com/)

### Installation

1.  Clone this repository:
    ```bash
    git clone https://github.com/yourusername/focus-pomodoro-bot
    cd focus-pomodoro-bot
    ```
2.  Create and activate a virtual environment (recommended):
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    This installs all required packages including `python-telegram-bot`, `Flask`, `Flask-Babel`, and `python-i18n` for localization.
3.  **Google Cloud Setup (for Sheets Export):**
    - Go to the [Google Cloud Console](https://console.cloud.google.com/).
    - Create a new project (or use an existing one).
    - Enable the "Google Sheets API".
    - Create OAuth 2.0 Client ID credentials. When asked for "Application type", select "Web application".
    - Download the credentials JSON file.
        - **Important:** The file downloaded from Google is often named `client_secret_XXXX.json`. You **must** rename this file to exactly `credentials.json` and place it in the root directory of this project.
    - **Configure OAuth Consent Screen:**
        - In the Google Cloud Console, navigate to "APIs & Services" -> "OAuth consent screen".
        - If you haven't configured it before, you'll need to choose a User Type (e.g., "External").
        - Fill in the required app information:
            - App name (e.g., "Focus Pomodoro Bot")
            - User support email
            - Developer contact information
        - **Authorized domains:** Add the domain part of your `DOMAIN_URL` (e.g., if `DOMAIN_URL` is `https://sub.example.com`, add `example.com` or `sub.example.com`). If using `ngrok`, add your `ngrok.io` domain (e.g. `your-hash.ngrok-free.app`).
        - **Application Home Page link:** Set this to your `DOMAIN_URL` (e.g., `https://your-domain-or-ngrok-url.com/`). The bot serves a basic home page here.
        - **Application Privacy Policy link:** Set this to `YOUR_DOMAIN_URL/privacy` (e.g., `https://your-domain-or-ngrok-url.com/privacy`). The bot serves a template privacy policy here. Review and update `templates/privacy_policy.html` to match your specifics.
        - **Application Terms of Service link:** Set this to `YOUR_DOMAIN_URL/terms` (e.g., `https://your-domain-or-ngrok-url.com/terms`). The bot serves template terms of service here. Review and update `templates/terms_of_service.html` to match your specifics.
        - Save the consent screen settings.
    - **Configure Redirect URIs for your OAuth Client ID:**
        - Go back to "APIs & Services" -> "Credentials".
        - Click on the name of your OAuth 2.0 Client ID.
        - Under "Authorized redirect URIs", click "ADD URI".
        - Add `YOUR_DOMAIN_URL/oauth2callback` (e.g., `https://your-domain-or-ngrok-url.com/oauth2callback`). This is the URL that Google will redirect to after user authorization.
        - Save the changes.
    - **Note about the OAuth flow:**
        - When a user runs the `/connect_google` command, they'll be directed to a Google authorization page
        - After authorizing the app, Google will redirect them to your server's `/oauth2callback` endpoint
        - The page will display the authorization code for the user to copy
        - The user must paste this code back into the Telegram chat to complete the connection

4.  Create a `.env` file from the example:
    ```bash
    cp .env.example .env
    ```
5.  Edit the `.env` file and fill in your details:
    ```plaintext
    # Mandatory
    BOT_TOKEN=your_telegram_bot_token_here
    DOMAIN_URL=https://your-domain-or-ngrok-url.com # For web timer link and OAuth redirects
    ADMIN_USER_ID=your_telegram_user_id # Your numeric Telegram ID for admin features
    GOOGLE_CLIENT_ID=your_google_client_id_here
    GOOGLE_CLIENT_SECRET=your_google_client_secret_here

    # Optional (defaults are usually fine)
    FLASK_PORT=5002
    ```
    - **`BOT_TOKEN`**: Your Telegram bot token from BotFather.
    - **`DOMAIN_URL`**: The publicly accessible URL where the Flask web app will run. For local development, use your `ngrok` HTTPS URL (e.g., `https://xxxx-xxxx-xxxx.ngrok-free.app`).
    - **`ADMIN_USER_ID`**: Your *numeric* Telegram User ID. You can get this from bots like `@userinfobot`. This user will receive notifications.
    - **`GOOGLE_CLIENT_ID`** and **`GOOGLE_CLIENT_SECRET`**: From your downloaded credentials file.
    - **`FLASK_PORT`**: The local port the Flask app will listen on (must match ngrok if used).

### Running the Bot

1.  (If using ngrok for local development) Start ngrok:
    ```bash
    ngrok http 5002
    ```
    Make sure the HTTPS URL from ngrok is set as `DOMAIN_URL` in your `.env` file.

2.  Start the bot:
    ```bash
    python bot.py
    ```
    The bot will automatically check and create/update the `focus_pomodoro.db` SQLite database file on startup.

### Jira Cloud Integration (Optional)

To enable Jira integration, you need to create an OAuth 2.0 (3LO) app in your Atlassian (Jira Cloud) account:

1. Go to [Atlassian Developer Console](https://developer.atlassian.com/console/myapps/create-3lo-app/).
2. Click **Create app** > **OAuth 2.0 (3LO)**.
3. Enter an app name (e.g., "Focus Pomodoro Bot Integration").
4. Set the **Redirect URL** to:
   - `https://your-domain-or-ngrok-url.com/oauth2callback/jira`
   - (Replace with your actual DOMAIN_URL)
5. Add the following **OAuth scopes**:
   - `read:jira-work`
   - `write:jira-work`
   - `read:jira-user`
   - `offline_access`
6. Save the app and copy the **Client ID** and **Client Secret**.
7. Add these to your `.env` file:
   ```
   JIRA_CLIENT_ID=your_jira_client_id_here
   JIRA_CLIENT_SECRET=your_jira_client_secret_here
   ```
8. Restart the bot after updating your environment variables.

**Note:**
- Each user will authorize the bot to access their Jira account via the `/connect_jira` command (to be implemented).
- The bot will use these credentials to fetch your open Jira tasks and log work sessions.

## Usage

Interact with the bot in Telegram using commands or the reply keyboard.

### Main Commands

-   `/start`: Initialize the bot, show the keyboard, and register the user.
-   `/help`: Show a detailed help message with all commands.

**Project Management:**
-   `/create_project [\"Project Name\"]`: Create a new project. If name is omitted, the bot will ask for it.
-   `/list_projects`: Show active projects with buttons to select, mark done, rename, or view archived projects.
-   `/select_project \"Project Name\"`: Select an active project by name.
-   `/delete_project`: Show a list of projects to delete (asks for confirmation).
-   **Rename**: Click the ✏️ Rename button next to any project in the project list to rename it.

**Task Management:**
-   `/create_task [\"Task Name\"]`: Add a task to the *currently selected project*. If name is omitted, the bot will ask.
-   `/list_tasks`: Show active tasks in the current project with buttons to select, mark done, rename, or view archived tasks.
-   `/select_task \"Task Name\"`: Select an active task by name within the current project.
-   `/delete_task`: Show a list of tasks in the current project to delete (asks for confirmation).
-   **Rename**: Click the ✏️ Rename button next to any task in the task list to rename it.
-   **Forward a message** to the bot to create a task from that message in an existing or new project.

**Timer Control:**
-   `/start_timer [minutes]`: Start a work timer for the selected task (default 25 min, e.g., `/start_timer 45`).
-   `/pause_timer`: Pause the current work or break timer.
-   `/resume_timer`: Resume the paused timer.
-   `/stop_timer`: Stop the current timer early and log the time worked.
-   *(Break timers are offered via buttons after a work session or using the ☕️ Break (5m) reply keyboard button)*

**Reporting:**
-   `/report`: Show buttons to generate daily, weekly, or monthly work time reports.

**Google Sheets Integration:**
-   `/connect_google`: Start the process to authorize the bot to access your Google Sheets.
-   `/export_to_sheets <SPREADSHEET_ID> [SheetName]`: Export all logged session data to the specified Google Sheet ID and optional sheet name (defaults to "Pomodoro Log").

**Jira Integration:**
-   `/connect_jira`: Start the process to authorize the bot to access your Jira Cloud account.
-   `/disconnect_jira`: Remove your Jira credentials from the bot.
-   `/fetch_jira_projects`: List Jira projects with open issues assigned to you. Select a project to see your issues, and import them as bot tasks.
    - Imported Jira issues are shown as tasks with names like `[JIRA-KEY] Issue Summary`.
    - When you stop a timer for a Jira-linked task, you will be prompted to log the session to Jira.

**Admin Commands (Only for ADMIN_USER_ID):**
-   `/admin_notify_toggle`: Turn admin notifications on/off.
-   `/admin_stats`: Show basic bot usage statistics.
-   *(Initial admin setup command is hidden)*

**Language Settings:**
-   `/language`: Set your preferred language (currently supports English, German, and Russian).
    - The chosen language applies to both bot messages and the web timer interface.
    - Your language preference is remembered between sessions.
    - When you first start the bot, it will automatically detect your language from your Telegram client settings (if available and supported).

### Reply Keyboard

-   **🚀 Start Work**: Equivalent to `/start_timer`.
-   **⏸️ Pause**: Equivalent to `/pause_timer`.
-   **▶️ Resume**: Equivalent to `/resume_timer`.
-   **⏹️ Stop**: Equivalent to `/stop_timer`.
-   **📊 Report**: Equivalent to `/report`.
-   **☕️ Break (5m)**: Starts a 5-minute break timer (if no other timer is active).

## Development

### Project Structure

```plaintext
focus_pomodoro_bot/
├── handlers/           # Request handlers (commands, callbacks)
│   ├── __init__.py
│   ├── admin.py
│   ├── callbacks.py
│   ├── commands.py
│   └── google_auth.py
├── locales/            # Localization files (translations)
│   ├── en.yml          # English translations
│   ├── de.yml          # German translations  
│   └── ru.yml          # Russian translations
├── templates/          # Web app templates
│   └── timer.html      # Timer page template
├── venv/               # Virtual environment (if used)
├── bot.py              # Main application entry point, sets up handlers
├── config.py           # Configuration loading and timer state management
├── database.py         # Database schema setup and query functions
├── web_app.py          # Flask web application for timer view
├── i18n_utils.py       # Internationalization utilities
├── babel_extract.py    # Helper script for translation extraction
├── requirements.txt    # Python dependencies
├── focus_pomodoro.db   # SQLite database file (created automatically)
├── credentials.json    # Google Cloud credentials (!!! ADD TO .gitignore !!!)
├── .env                # Environment variables (token, domain, etc.)
├── .env.example        # Example environment file
├── .gitignore          # Git ignore file
├── README.md           # This file
└── ... (other potential files like sounds, logs)
```

### Internationalization (i18n)

The bot supports multiple languages (currently English, German, and Russian) through a YAML-based translation system:

1. **Bot Interface**: Uses the python-i18n library with translations stored in `locales/*.yml` files.
2. **Web Interface**: The timer web app uses the same translations, integrated with Flask via a custom context processor.
3. **User Preferences**: Users can change their language with the `/language` command, which is remembered and used for all interactions, including the web timer.
4. **Adding Languages**: To add a new language:
   - Create a new `locales/[language_code].yml` file based on the existing ones
   - Add the language code to `SUPPORTED_LANGUAGES` in `config.py`

**Important:** Ensure `credentials.json` and `.env` are added to your `.gitignore` file to avoid committing sensitive information.

## License

This project is licensed under the MIT License.
