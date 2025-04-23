# Focus Pomodoro Bot

A Telegram bot that helps you manage tasks and boost productivity using the Pomodoro Technique.

## Features

- Create and manage projects and tasks
- Start, pause, and stop Pomodoro timers (25-minute work sessions)
- View timer countdown in a beautiful web interface
- Track your productivity with detailed session logs

## Setup Instructions

### Prerequisites

- Python 3.7+
- A Telegram bot token (obtained from [BotFather](https://t.me/botfather))
- [ngrok](https://ngrok.com/) or similar tool for exposing local server (optional, for development)

### Installation

1. Clone this repository:

   ```bash
   git clone https://github.com/yourusername/focus-pomodoro-bot
   cd focus-pomodoro-bot
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file with your configuration:

   ```bash
   cp .env.example .env
   ```

4. Edit the `.env` file and fill in your bot token and domain URL:

   ```plaintext
   BOT_TOKEN=your_telegram_bot_token_here
   DOMAIN_URL=https://your-domain.com
   FLASK_PORT=5002
   ```

   For local development, you can use ngrok:

   ```bash
   ngrok http 5002
   ```

   Then use the ngrok URL in your `.env` file.

### Running the Bot

1. Initialize the database:

   ```bash
   python database.py
   ```

2. Start the bot:

   ```bash
   python bot.py
   ```

## Usage

Once the bot is running, you can interact with it in Telegram using these commands:

- `/start` - Initialize the bot
- `/create_project "Project Name"` - Create a new project
- `/select_project "Project Name"` - Select an existing project (or use `/list_projects`)
- `/list_projects` - List your projects and select one via buttons
- `/create_task "Task Name"` - Create a new task in the current project
- `/select_task "Task Name"` - Select a task from the current project (or use `/list_tasks`)
- `/list_tasks` - List tasks in the current project and select one via buttons
- `/start_timer` - Start a 25-minute Pomodoro timer for the selected task
- `/pause_timer` - Pause the current timer
- `/resume_timer` - Resume a paused timer
- `/stop_timer` - Stop the current timer
- `/report` - View productivity reports (daily, weekly, monthly)
- `/delete_project` - Select a project to delete (asks for confirmation)
- `/delete_task` - Select a task in the current project to delete (asks for confirmation)

## Development

The project structure:

```plaintext
focus_pomodoro_bot/
├── bot.py          # Main bot script
├── database.py     # Database helper functions
├── .env            # Environment configuration
└── requirements.txt
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.
