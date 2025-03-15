# Focus To-Do List Pomodoro Telegram Bot

This bot will help users manage tasks and boost productivity using the Pomodoro Technique, with all the features you’ve outlined. Below, I’ll break it down into clear steps and components, explaining how to implement each feature and suggesting tools to make it happen.

## Implementation Requirements and Planning

### Overview of the Bot

The bot will allow users to:

- Create and select projects and tasks.
- Start, pause, and stop a Pomodoro timer, with a countdown displayed in a Telegram mini-app.
- Log timer events (start, pause, stop) as messages in the chat.
- Store time entries in a database for generating reports (by project, task, day, or month).
- Offer pro features: exporting data to Google Spreadsheets and playing background music during Pomodoro sessions.

Here’s how we can build it:

---

### Core Features and Implementation

#### 1. Project and Task Management

**What it does:**

- Users can create projects and tasks within those projects.
- They can select a project and task to work on before starting a timer.

**How to implement:**

- **Commands:**
  - `/create_project "Project Name"`: Creates a new project.
  - `/create_task "Task Name" "Project Name"`: Adds a task to a specified project.
  - `/select_project "Project Name"`: Sets the current project.
  - `/select_task "Task Name"`: Sets the current task within the selected project.
- **User Interface:** Use Telegram’s inline keyboards or reply keyboards to display a list of projects or tasks for selection, making it user-friendly.
- **Storage:** Store this data in a database (more on this later).

**Example flow:**

- User sends `/create_project "Website Design"`.
- Bot replies: “Project ‘Website Design’ created!”
- User sends `/create_task "Design Homepage" "Website Design"`.
- Bot replies: “Task ‘Design Homepage’ added to ‘Website Design’!”

---

#### 2. Pomodoro Timer with Countdown

**What it does:**

- Users can start a timer (default 25 minutes) for a selected task, pause it, resume it, or stop it.
- A countdown timer is shown in a Telegram mini-app.

**How to implement:**

- **Commands:**
  - `/start_timer`: Starts a 25-minute Pomodoro timer for the selected task.
  - `/pause_timer`: Pauses the running timer.
  - `/resume_timer`: Resumes the paused timer.
  - `/stop_timer`: Stops the timer early.
- **Timer Logic:**
  - When `/start_timer` is called, record the start time and set the timer state to “running.”
  - Track accumulated work time (e.g., if paused after 10 minutes, store 10 minutes worked).
  - On pause, calculate time worked so far and pause the countdown.
  - On resume, continue from the remaining time (e.g., 15 minutes left).
  - When 25 minutes of work time is reached or the timer is stopped, end the session.
- **Mini-App Countdown:**
  - A Telegram mini-app is a web-based interface embedded in Telegram (built with HTML, CSS, JavaScript).
  - Create a simple web page showing the countdown (e.g., “15:32 remaining”).
  - When the user opens the mini-app (via a button like “View Timer”), the bot sends the current state: start time, accumulated work time, and timer status (running/paused).
  - JavaScript calculates remaining time (25 minutes - accumulated work time) and updates the countdown every second if running.
  - If paused, it shows the remaining time statically.

**Example flow:**

- User sends `/start_timer`.
- Bot replies: “Timer started for ‘Design Homepage’ in ‘Website Design’.”
- User opens the mini-app, sees “24:59” counting down.
- User sends `/pause_timer` after 10 minutes.
- Mini-app updates to “15:00” (paused).
- User sends `/resume_timer`, and the countdown continues.

---

#### 3. Chat Messages for Timer Events

**What it does:**

- The bot sends a message to the chat for each timer event (start, pause, stop, completion).

**How to implement:**

- Use the Telegram Bot API to send messages.
- Examples:
  - `/start_timer`: “Timer started for ‘Design Homepage’ in ‘Website Design’.”
  - `/pause_timer`: “Timer paused. 15 minutes remaining.”
  - `/resume_timer`: “Timer resumed for ‘Design Homepage’.”
  - `/stop_timer`: “Timer stopped. 20 minutes worked.”
  - Timer expires: “Time’s up! 25-minute Pomodoro completed. Take a break!”

**Timer expiration:**

- Use a scheduler (e.g., Python’s APScheduler) to send the “Time’s up!” message when the timer finishes.
- Schedule a task when the timer starts or resumes, calculating the expiration time based on remaining work time (e.g., 15 minutes left = schedule message in 15 minutes).
- Cancel the task if paused or stopped.

---

#### 4. Database for Time Entries and Reports

**What it does:**

- Store time entries to track work sessions.
- Generate reports grouped by project, task, day, or month.

**How to implement:**

- **Database Schema:**
  - **Users**: `user_id` (Telegram ID), other details if needed.
  - **Projects**: `project_id`, `user_id`, `project_name`.
  - **Tasks**: `task_id`, `project_id`, `task_name`.
  - **PomodoroSessions**: `session_id`, `user_id`, `project_id`, `task_id`, `start_time`, `end_time`, `work_duration`, `completed` (true if 25 minutes worked).
- **Storing Time Entries:**
  - When a session ends (timer expires or is stopped), save the session with start time, end time, work duration, and completion status.
  - Example: Start at 10:00, pause at 10:10, resume at 10:15, end at 10:30 → `work_duration = 25 minutes`, `completed = true`.
- **Reports:**
  - Command: `/report [type]` (e.g., `/report daily`, `/report monthly`).
  - Query the database to sum `work_duration` grouped by:
    - Project: Total time per project.
    - Task: Total time per task.
    - Day: Total time for today.
    - Month: Total time this month.
  - Reply with a summary, e.g., “Today: 50 minutes (Website Design: 25 min, Task X: 25 min).”

**Tools:**

- Use SQLite (simple) or PostgreSQL (scalable) with an ORM like SQLAlchemy in Python.

---

#### 5. Pro Feature: Google Spreadsheet Integration

**What it does:**

- Export time entries to a Google Spreadsheet for manual reporting.

**How to implement:**

- **Authentication:**
  - Command: `/connect_google`.
  - Use OAuth2 via Google Sheets API. Send the user a link to authenticate and grant access.
  - Store the access token securely for the user.
- **Exporting Data:**
  - Command: `/export_to_sheets "Spreadsheet ID"`.
  - Use the Google Sheets API to append rows to a sheet with columns like: `Date`, `Project`, `Task`, `Duration`, `Completed`.
  - Example row: `2023-10-15, Website Design, Design Homepage, 25 min, Yes`.
- **Setup:**
  - Users provide a Spreadsheet ID (or create one via the bot).
  - Bot writes time entries periodically or on demand.

**Tools:**

- Google’s `google-api-python-client` library.

---

#### 6. Pro Feature: Background Music

**What it does:**

- Play focus-enhancing music during Pomodoro sessions.

**How to implement:**

- **Simple Approach:**
  - Command: `/set_music [option]` (e.g., `/set_music calm`).
  - Store a few audio files (e.g., instrumental tracks, white noise) on your server.
  - When `/start_timer` is called, send the chosen audio file to the chat.
  - Telegram allows users to play audio in the background while using the app.
- **Limitations:**
  - Telegram has file size limits (e.g., 50 MB for bots), so keep files small.
- **Alternative:**
  - Send a link to a streaming service (e.g., YouTube or Spotify), but playback would depend on the user’s apps.

**Example:**

- User sends `/set_music calm`.
- Bot replies: “Music set to ‘Calm Focus’.”
- On `/start_timer`, bot sends the audio file with the timer start message.

---

### Technical Stack

Here’s a suggested setup:

- **Bot Framework:** Python with `python-telegram-bot` (easy to use, supports commands and conversations).
- **Database:** SQLite (for simplicity).
- **Mini-App:** Flask or Django to serve a web page with HTML/CSS/JavaScript for the countdown.
- **Scheduler:** APScheduler for timer expiration messages.
- **APIs:** Google Sheets API for the pro feature.
- **Deployment:** Heroku, AWS, or a VPS for hosting the bot and mini-app.

---

### Development Steps

1. **Setup the Bot:**
   - Register a bot with Telegram’s BotFather to get an API token.
   - Use `python-telegram-bot` to handle commands.
2. **Database:**
   - Create tables for users, projects, tasks, and sessions.
3. **Core Features:**
   - Implement project/task commands and timer logic.
   - Use a `ConversationHandler` to manage user states.
4. **Mini-App:**
   - Build a simple web page with JavaScript for the countdown.
   - Host it and link it via a Telegram button.
5. **Scheduler:**
   - Use APScheduler to send expiration messages.
6. **Reports:**
   - Write database queries for report generation.
7. **Pro Features:**
   - Add Google Sheets integration and music playback.

---

### User Flow Example

1. User starts with `/start`: “Welcome to Focus To-Do List Bot!”
2. `/create_project "App Development"`.
3. `/create_task "Code Login" "App Development"`.
4. `/select_project "App Development"`, `/select_task "Code Login"`.
5. `/start_timer`: “Timer started for ‘Code Login’.” (Mini-app shows 25:00 countdown.)
6. After 10 minutes, `/pause_timer`: “Timer paused. 15 min left.”
7. `/resume_timer`: Countdown resumes.
8. Timer ends: “Time’s up! 25-minute Pomodoro completed.”
9. `/report daily`: “Today: 25 min on App Development.”

---

### Tips

- **Start Small:** Focus on core features (tasks, timer, reports) first, then add pro features.
- **Test Locally:** Run the bot on your machine before deploying.
- **Documentation:** Check Telegram’s Bot API and Mini-App docs for details.

This plan should get you started on building your bot. Let me know if you need help with specific code examples or setup!

## Implementation Steps

## Step 1: Set Up the Project

### 1.1 Create the Project Directory

First, let’s set up a directory for your bot:

```bash
mkdir focus_pomodoro_bot
cd focus_pomodoro_bot
```

### 1.2 Install Dependencies

You’ll need a few Python libraries:

- `python-telegram-bot`: To interact with Telegram’s Bot API.
- `sqlite3`: For database management (included with Python by default).

Install the Telegram library using pip:

```bash
pip install python-telegram-bot
```

### 1.3 Project Structure

Here’s a simple structure to keep things organized:

```plaintext
focus_pomodoro_bot/
├── bot.py          # Main bot script
├── database.py     # Database functions
└── requirements.txt
```

In future, could be like:

```plaintext
focus_pomodoro_bot/
├── bot.py          # Main bot script
├── database.py     # Database helper functions
├── handlers.py     # Command handlers
├── mini_app.py     # Mini-app web server (using Flask)
├── templates/      # HTML templates for mini-app
│   └── timer.html
└── requirements.txt
```

For now, create empty files for `bot.py` and `database.py`. Add the dependency to `requirements.txt`:

```plaintext
python-telegram-bot
```

---

## Step 2: Set Up SQLite Database

Since you’ve chosen SQLite, let’s create a database to store users, projects, tasks, and Pomodoro sessions.

### 2.1 Create `database.py`

See the file "database.py"

Run this file to create the database:

```bash
python database.py
```

This sets up tables for:

- **Users**: Stores user info (Telegram ID, first name, last name).
- **Projects**: Links projects to users.
- **Tasks**: Links tasks to projects.
- **Pomodoro Sessions**: Tracks Pomodoro sessions with start/end times and completion status.

---

## Step 3: Build the Telegram Bot

Now, let’s create the bot in `bot.py`. Replace `'YOUR_BOT_TOKEN_HERE'` with the API key you got from BotFather.

### 3.1 Create `bot.py`

See the file "bot.py"

Run the bot:

```bash
python bot.py
```

Test it by sending `/start` in Telegram. It should welcome you and add your info to the database.

---

## Step 4: Add Project and Task Commands

Let’s add commands to manage projects and tasks.

### 4.1 Add to `bot.py`

Similarly to select_project, implement select_task (you'll need to add get_tasks function).

### 4.2 Update `database.py`

Add more functions as needed (e.g., get_tasks, etc.)

### 4.3 Register Commands

Test these commands:

- `/create_project "My Work"`
- `/select_project "My Work"`
- `/create_task "Write Report"`

---

## What’s Next?

We’ve set up the bot with SQLite and basic project/task management. Here’s what you might want to add next:

1. **Pomodoro Timer**: Use `apscheduler` to manage 25-minute timers and notify users when they’re done.
2. **Mini-App**: Create a web-based countdown timer using Flask.
3. **Reports**: Generate daily work summaries from the database.

Let me know which feature you’d like to tackle next or if you need help refining what we’ve built so far!

## Step 5: Implement Pomodoro Timer

This is more complex. We'll need to track timer states for each user.

### 5.1 Timer States

Add to user_data:

- timer_running: bool
- start_time: datetime
- accumulated_time: int (seconds worked)
- pause_time: datetime (when paused)
- scheduler_job: job for expiration

I should also think about how to notify the user when the timer finishes. I can use APScheduler to schedule a task that sends a message to the user when the 25 minutes are up. I'll need to install APScheduler and integrate it into the bot.

Since we're using python-telegram-bot v20, which is async, I need to use asyncio to send the message. This might be tricky with APScheduler, as it runs in a separate thread.

Another approach is to use the bot's job queue, which is built into python-telegram-bot.

python-telegram-bot has a JobQueue that can be used to schedule tasks.

That might be a better option, as it integrates well with the bot's event loop.

```python
def main():
    application = Application.builder().token(TOKEN).build()
    job_queue = application.job_queue
    # ... rest of the code
```

### 5.2 Start Timer, Pause Timer, Resume Timer, Stop Timer

I can calculate the exact time worked when pausing or stopping.

- When starting or resuming, calculate the remaining_time = 25 - accumulated_time, and schedule the job to run after remaining_time minutes.
- When pausing, or if stopped or completed, remove the job.
- When the job runs, it means the total work time has reached 25 minutes.

To simplify, I can allow only one timer per user at a time.

Now, I need to integrate this with the database to save the sessions when the timer is stopped or completed.

Don't forget to add the add_pomodoro_session function to database.py.

## Step 6: Implement Mini-App for Countdown

For the mini-app, we'll use Flask to serve a simple web page.

### 6.1 Set Up Flask

Install Flask:

```bash
pip install flask
```

Since the bot is running with application.run_polling(), which blocks, I need to run Flask in a separate thread.

Note: For production, deploy Flask properly (e.g., with Gunicorn) and update the URL in the inline button.

In mini_app.py:

```python
from flask import Flask, render_template, request
import json

app = Flask(__name__)

@app.route('/timer')
def timer():
    user_id = request.args.get('user_id')
    # Get timer state from bot (you'll need to implement this)
    timer_state = get_timer_state(user_id)
    return render_template('timer.html', timer_state=json.dumps(timer_state))

if __name__ == '__main__':
    app.run(port=5000)
```

### 6.2 Timer State

You'll need a way to share the timer state between the bot and the mini-app. For simplicity, you can use a shared dictionary or a database query. Here's a basic example:

In bot.py, add:

```python
def get_timer_state(user_id):
    if user_id in user_data and 'timer_running' in user_data[user_id]:
        if user_data[user_id]['timer_running']:
            elapsed = (datetime.now() - user_data[user_id]['start_time']).total_seconds()
            total_worked = user_data[user_id]['accumulated_time'] + elapsed
        else:
            total_worked = user_data[user_id]['accumulated_time']
        remaining = max(25 * 60 - total_worked, 0)
        return {
            'running': user_data[user_id]['timer_running'],
            'remaining': remaining
        }
    return {'running': False, 'remaining': 0}
```

### 6.3 HTML Template

Create templates/timer.html:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Pomodoro Timer</title>
    <script>
      let timerState = {{ timer_state|safe }};
      let remaining = timerState.remaining;
      let running = timerState.running;

      function updateTimer() {
          if (running && remaining > 0) {
              remaining -= 1;
              document.getElementById('timer').innerText = Math.floor(remaining / 60) + ':' + ('0' + Math.floor(remaining % 60)).slice(-2);
          } else if (remaining <= 0) {
              document.getElementById('timer').innerText = 'Time’s up!';
          }
      }

      setInterval(updateTimer, 1000);
    </script>
  </head>
  <body>
    <h1>Pomodoro Timer</h1>
    <div id="timer">Loading...</div>
  </body>
</html>
```

### 6.4 Link Mini-App in Bot

To open the mini-app, send a message with a button:

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def show_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    url = f'http://yourdomain.com:5000/timer?user_id={user_id}'  # Replace with your domain
    keyboard = [[InlineKeyboardButton("View Timer", url=url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Click to view the timer:', reply_markup=reply_markup)
```

Add this command to the bot.

## Step 7: Implement Reports

For reports, let's add a simple daily report.

First, add a function to database.py:

```python
def get_daily_report(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = datetime.now().date().isoformat()
    cursor.execute('''
        SELECT SUM(work_duration) FROM pomodoro_sessions
        WHERE user_id = ? AND DATE(start_time) = ?
    ''', (user_id, today))
    total_minutes = cursor.fetchone()[0] or 0
    conn.close()
    return total_minutes
```

Then, the report command:

```python
async def report_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    total_minutes = database.get_daily_report(user_id)
    await update.message.reply_text(f'Today: {total_minutes} minutes worked.')
```

## Step 8: Pro Features (Optional)

For pro features like Google Sheets integration and background music, you can extend the bot later.

- Google Sheets: Use google-api-python-client to append rows to a spreadsheet.
- Background Music: Upload audio files and send them with /start_timer.

## Final Steps

1. Run the Bot: Start bot.py and mini_app.py (use waitress or gunicorn for production).
2. Test: Use Telegram to test commands and timer functionality.
3. Deploy: Host on Heroku, AWS, or a VPS.
