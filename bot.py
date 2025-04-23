from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import database
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import JobQueue
import threading
from flask import Flask, render_template_string
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get bot token and domain from environment variables
TOKEN = os.getenv('BOT_TOKEN')
DOMAIN_URL = os.getenv('DOMAIN_URL')

# Validate required environment variables
if not TOKEN:
    raise ValueError("Missing BOT_TOKEN in environment variables. Please check your .env file.")
if not DOMAIN_URL:
    print("Warning: DOMAIN_URL not found in environment variables. Using localhost as fallback.")
    DOMAIN_URL = "http://localhost:5002"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    database.add_user(user.id, user.first_name, user.last_name)
    await update.message.reply_text('Welcome to your Focus To-Do List Bot! Use /create_project to get started.')

# Dictionary to store user state (e.g., selected project)
user_data = {}  # {user_id: {'current_project': project_id}}
timer_states = {}  # {user_id: {'start_time': datetime, 'accumulated_time': int, 'state': 'running'/'paused', 'job': APScheduler job}}

async def create_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    project_name = ' '.join(context.args)
    if not project_name:
        await update.message.reply_text('Please provide a project name. Usage: /create_project "Project Name"')
        return
    database.add_project(user_id, project_name)
    await update.message.reply_text(f'Project "{project_name}" created! Select it with /select_project.')

async def select_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    project_name = ' '.join(context.args)
    if not project_name:
        # If no project name is given, list projects instead
        await list_projects(update, context)
        return
    projects = database.get_projects(user_id)
    for proj_id, proj_name in projects:
        if proj_name == project_name:
            user_data[user_id] = {'current_project': proj_id}
            await update.message.reply_text(f'Project "{project_name}" selected.')
            return
    await update.message.reply_text('Project not found. Create it with /create_project.')

async def list_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    projects = database.get_projects(user_id)
    if not projects:
        await update.message.reply_text("You don't have any projects yet. Create one with /create_project.")
        return
        
    keyboard = []
    for project_id, project_name in projects:
        keyboard.append([InlineKeyboardButton(project_name, callback_data=f"select_project:{project_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a project:", reply_markup=reply_markup)

async def create_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data or 'current_project' not in user_data[user_id]:
        await update.message.reply_text('Please select a project first with /select_project.')
        return
    task_name = ' '.join(context.args)
    if not task_name:
        await update.message.reply_text('Please provide a task name. Usage: /create_task "Task Name"')
        return
    project_id = user_data[user_id]['current_project']
    database.add_task(project_id, task_name)
    await update.message.reply_text(f'Task "{task_name}" added to project!')

async def select_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data or 'current_project' not in user_data[user_id]:
        await update.message.reply_text('Please select a project first with /select_project or /list_projects.')
        return
    task_name = ' '.join(context.args)
    if not task_name:
        # If no task name is given, list tasks for the current project
        await list_tasks(update, context)
        return
    project_id = user_data[user_id]['current_project']
    tasks = database.get_tasks(project_id)
    for task_id, t_name in tasks:
        if t_name == task_name:
            user_data[user_id]['current_task'] = task_id
            await update.message.reply_text(f'Task "{task_name}" selected.')
            return
    await update.message.reply_text('Task not found. Create it with /create_task.')

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data or 'current_project' not in user_data[user_id]:
        await update.message.reply_text('Please select a project first using /select_project or /list_projects.')
        return
        
    project_id = user_data[user_id]['current_project']
    tasks = database.get_tasks(project_id)
    
    if not tasks:
        project_name = database.get_project_name(project_id)
        await update.message.reply_text(f"No tasks found for project '{project_name}'. Create one with /create_task.")
        return
        
    keyboard = []
    for task_id, task_name in tasks:
        keyboard.append([InlineKeyboardButton(task_name, callback_data=f"select_task:{task_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a task:", reply_markup=reply_markup)

from datetime import datetime, timedelta

async def start_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in timer_states:
        await update.message.reply_text('A timer is already running or paused. Please stop it first.')
        return
    if user_id not in user_data or 'current_project' not in user_data[user_id] or 'current_task' not in user_data[user_id]:
        await update.message.reply_text('Please select a project and task first.')
        return
    timer_states[user_id] = {
        'state': 'running',
        'accumulated_time': 0,
        'start_time': datetime.now(),
        'job': context.job_queue.run_once(timer_finished, 25 * 60, data={'user_id': user_id})
    }
    # Send message with a button to view the timer
    timer_url = f'{DOMAIN_URL}/timer/{user_id}'
    keyboard = [[InlineKeyboardButton("View Timer", url=timer_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Timer started for 25 minutes.', reply_markup=reply_markup)

async def timer_finished(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data['user_id']
    if user_id in timer_states:
        timer_states[user_id]['accumulated_time'] = 25
        timer_states[user_id]['state'] = 'stopped'
        
        # Get project and task IDs from user_data
        if user_id in user_data and 'current_project' in user_data[user_id] and 'current_task' in user_data[user_id]:
            project_id = user_data[user_id]['current_project']
            task_id = user_data[user_id]['current_task']
            
            # Save completed session to database
            start_time = timer_states[user_id]['start_time']
            database.add_pomodoro_session(
                user_id=user_id,
                project_id=project_id,
                task_id=task_id,
                start_time=start_time,
                work_duration=25,  # Full Pomodoro session
                completed=1        # Completed successfully
            )
            
            # Get project and task names for the message
            project_name = database.get_project_name(project_id)
            task_name = database.get_task_name(task_id)
            
            success_message = (
                f"✅ Time's up! Pomodoro session completed.\n\n"
                f'Project: {project_name}\n'
                f'Task: {task_name}\n'
                f'Duration: 25 minutes'
            )
            await context.bot.send_message(chat_id=user_id, text=success_message)
        else:
            # Generic message if project/task data is missing
            await context.bot.send_message(chat_id=user_id, text="✅ Time's up! Pomodoro session completed.")
        
        # Clean up timer state
        del timer_states[user_id]

async def pause_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in timer_states or timer_states[user_id]['state'] != 'running':
        await update.message.reply_text('No timer is running.')
        return
    current_time = datetime.now()
    time_worked = (current_time - timer_states[user_id]['start_time']).total_seconds() / 60
    timer_states[user_id]['accumulated_time'] += time_worked
    timer_states[user_id]['state'] = 'paused'
    timer_states[user_id]['job'].schedule_removal()
    del timer_states[user_id]['job']
    await update.message.reply_text(f'Timer paused. Accumulated time: {timer_states[user_id]["accumulated_time"]:.2f} minutes.')

async def resume_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in timer_states or timer_states[user_id]['state'] != 'paused':
        await update.message.reply_text('No timer is paused.')
        return
    accumulated_time = timer_states[user_id]['accumulated_time']
    remaining_time = 25 - accumulated_time
    if remaining_time <= 0:
        await update.message.reply_text('Timer already completed.')
        del timer_states[user_id]
        return
    timer_states[user_id]['state'] = 'running'
    timer_states[user_id]['start_time'] = datetime.now()
    timer_states[user_id]['job'] = context.job_queue.run_once(timer_finished, remaining_time * 60, data={'user_id': user_id})
    await update.message.reply_text('Timer resumed.')

async def stop_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in timer_states:
        await update.message.reply_text('No timer is running or paused.')
        return
    
    # Calculate the final accumulated time
    if timer_states[user_id]['state'] == 'running':
        current_time = datetime.now()
        time_worked = (current_time - timer_states[user_id]['start_time']).total_seconds() / 60
        timer_states[user_id]['accumulated_time'] += time_worked
    
    accumulated_time = timer_states[user_id]['accumulated_time']
    is_completed = 1 if accumulated_time >= 25 else 0
    
    # Get project and task IDs from user_data
    if user_id in user_data and 'current_project' in user_data[user_id] and 'current_task' in user_data[user_id]:
        project_id = user_data[user_id]['current_project']
        task_id = user_data[user_id]['current_task']
        
        # Save session to database
        start_time = timer_states[user_id]['start_time']
        database.add_pomodoro_session(
            user_id=user_id,
            project_id=project_id,
            task_id=task_id,
            start_time=start_time,
            work_duration=accumulated_time,
            completed=is_completed
        )
        
        # Get project and task names for the message
        project_name = database.get_project_name(project_id)
        task_name = database.get_task_name(task_id)
        
        message = (
            f'⏹ Timer stopped.\n\n'
            f'Project: {project_name}\n'
            f'Task: {task_name}\n'
            f'Duration: {accumulated_time:.2f} minutes'
        )
        await update.message.reply_text(message)
    else:
        # Generic message if project/task data is missing
        await update.message.reply_text(f'⏹ Timer stopped. Total time worked: {accumulated_time:.2f} minutes.')
    
    # Cancel the scheduled job if it exists
    if 'job' in timer_states[user_id]:
        timer_states[user_id]['job'].schedule_removal()
    
    # Clean up timer state
    del timer_states[user_id]

app = Flask(__name__)

@app.route('/timer/<int:user_id>')
def timer_page(user_id):
    if user_id not in timer_states:
        return render_template_string("""
            <html>
                <head>
                    <title>Focus Pomodoro Timer</title>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            text-align: center;
                            margin-top: 50px;
                        }
                        .message {
                            color: #666;
                            font-size: 18px;
                        }
                    </style>
                </head>
                <body>
                    <h1>No Active Timer</h1>
                    <p class="message">There is no active timer for this user.</p>
                </body>
            </html>
        """)
    
    state = timer_states[user_id]
    if state['state'] == 'running':
        start_time = state['start_time'].isoformat()
        accumulated_time = state['accumulated_time']
        return render_template_string("""
            <html>
                <head>
                    <title>Focus Pomodoro Timer</title>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            text-align: center;
                            margin-top: 50px;
                            background-color: #f7f9fc;
                        }
                        .timer-container {
                            max-width: 500px;
                            margin: 0 auto;
                            padding: 20px;
                            border-radius: 10px;
                            background-color: white;
                            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                        }
                        .timer {
                            font-size: 60px;
                            font-weight: bold;
                            color: #333;
                            margin: 30px 0;
                        }
                        .status {
                            color: #4CAF50;
                            font-size: 18px;
                            margin-bottom: 20px;
                        }
                    </style>
                </head>
                <body>
                    <div class="timer-container">
                        <h1>Focus Timer</h1>
                        <div class="status">Timer Running</div>
                        <div id="countdown" class="timer">25:00</div>
                    </div>
                    <script>
                        var startTime = new Date('{{ start_time }}').getTime();
                        var accumulatedTime = {{ accumulated_time }};
                        
                        function updateCountdown() {
                            var now = new Date().getTime();
                            var timeWorked = (now - startTime) / 60000;  // in minutes
                            var totalTime = accumulatedTime + timeWorked;
                            var remaining = 25 - totalTime;
                            
                            if (remaining <= 0) {
                                document.getElementById('countdown').innerText = "00:00";
                                document.querySelector('.status').innerText = "Time's up!";
                                document.querySelector('.status').style.color = "#F44336";
                            } else {
                                var minutes = Math.floor(remaining);
                                var seconds = Math.floor((remaining - minutes) * 60);
                                document.getElementById('countdown').innerText = 
                                    String(minutes).padStart(2, '0') + ":" + 
                                    String(seconds).padStart(2, '0');
                            }
                        }
                        
                        // Update immediately and then every second
                        updateCountdown();
                        setInterval(updateCountdown, 1000);
                    </script>
                </body>
            </html>
        """, start_time=start_time, accumulated_time=accumulated_time)
    elif state['state'] == 'paused':
        accumulated_time = state['accumulated_time']
        remaining = 25 - accumulated_time
        minutes = int(remaining)
        seconds = int((remaining - minutes) * 60)
        return render_template_string("""
            <html>
                <head>
                    <title>Focus Pomodoro Timer</title>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            text-align: center;
                            margin-top: 50px;
                            background-color: #f7f9fc;
                        }
                        .timer-container {
                            max-width: 500px;
                            margin: 0 auto;
                            padding: 20px;
                            border-radius: 10px;
                            background-color: white;
                            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                        }
                        .timer {
                            font-size: 60px;
                            font-weight: bold;
                            color: #333;
                            margin: 30px 0;
                        }
                        .status {
                            color: #FFC107;
                            font-size: 18px;
                            margin-bottom: 20px;
                        }
                    </style>
                </head>
                <body>
                    <div class="timer-container">
                        <h1>Focus Timer</h1>
                        <div class="status">Timer Paused</div>
                        <div class="timer">{{ minutes }}:{{ seconds }}</div>
                    </div>
                </body>
            </html>
        """, minutes=f"{minutes:02d}", seconds=f"{seconds:02d}")
    else:
        return render_template_string("""
            <html>
                <head>
                    <title>Focus Pomodoro Timer</title>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            text-align: center;
                            margin-top: 50px;
                        }
                        .message {
                            color: #666;
                            font-size: 18px;
                        }
                    </style>
                </head>
                <body>
                    <h1>Invalid Timer State</h1>
                    <p class="message">The timer is in an invalid state.</p>
                </body>
            </html>
        """)
    
def run_flask():
    # Use the port from environment variable if available, otherwise default to 5002
    port = int(os.getenv('FLASK_PORT', 5002))
    app.run(host='0.0.0.0', port=port)

# Report commands
async def report_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    total_minutes, project_breakdown = database.get_daily_report(user_id)
    
    if total_minutes == 0:
        await update.message.reply_text("You haven't completed any Pomodoro sessions today.")
        return
        
    # Format the report message
    report = f"📊 *Daily Report*\n\n"
    report += f"Total time today: *{total_minutes:.1f} minutes*\n\n"
    
    if project_breakdown:
        report += "*Project Breakdown:*\n"
        for project_name, minutes in project_breakdown:
            percentage = (minutes / total_minutes) * 100
            report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
    
    await update.message.reply_text(report, parse_mode='Markdown')

async def report_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    total_minutes, daily_breakdown, project_breakdown = database.get_weekly_report(user_id)
    
    if total_minutes == 0:
        await update.message.reply_text("You haven't completed any Pomodoro sessions this week.")
        return
    
    # Format the report message
    report = f"📈 *Weekly Report*\n\n"
    report += f"Total time this week: *{total_minutes:.1f} minutes*\n\n"
    
    if daily_breakdown:
        report += "*Daily Breakdown:*\n"
        for date, minutes in daily_breakdown:
            try:
                # Format date as "Mon, Jan 15"
                date_obj = datetime.fromisoformat(date).strftime("%a, %b %d")
                report += f"• {date_obj}: {minutes:.1f} min\n"
            except (ValueError, TypeError):
                # Fallback if date parsing fails
                report += f"• {date}: {minutes:.1f} min\n"
    
    report += "\n*Project Breakdown:*\n"
    for project_name, minutes in project_breakdown:
        percentage = (minutes / total_minutes) * 100
        report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
    
    await update.message.reply_text(report, parse_mode='Markdown')

async def report_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    total_minutes, project_breakdown = database.get_monthly_report(user_id)
    
    if total_minutes == 0:
        await update.message.reply_text("You haven't completed any Pomodoro sessions this month.")
        return
    
    # Format the report message
    current_month = datetime.now().strftime("%B %Y")
    report = f"📅 *Monthly Report: {current_month}*\n\n"
    report += f"Total time this month: *{total_minutes:.1f} minutes* ({total_minutes/60:.1f} hours)\n\n"
    
    if project_breakdown:
        report += "*Project Breakdown:*\n"
        for project_name, minutes in project_breakdown:
            percentage = (minutes / total_minutes) * 100
            report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
    
    await update.message.reply_text(report, parse_mode='Markdown')

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) == 0:
        keyboard = [
            [InlineKeyboardButton("📊 Daily", callback_data="report_daily")],
            [InlineKeyboardButton("📈 Weekly", callback_data="report_weekly")],
            [InlineKeyboardButton("📅 Monthly", callback_data="report_monthly")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Which report would you like to see?", reply_markup=reply_markup)
        return
    
    report_type = context.args[0].lower()
    if report_type == "daily":
        await report_daily(update, context)
    elif report_type == "weekly":
        await report_weekly(update, context)
    elif report_type == "monthly":
        await report_monthly(update, context)
    else:
        await update.message.reply_text("Unknown report type. Available options: daily, weekly, monthly")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id # Use query.from_user.id for callback queries

    if data == "report_daily":
        # Create a fake update with the original message
        fake_update = Update(0, query.message)
        fake_update.message.from_user = query.from_user
        await report_daily(fake_update, context)
    elif data == "report_weekly":
        fake_update = Update(0, query.message)
        fake_update.message.from_user = query.from_user
        await report_weekly(fake_update, context)
    elif data == "report_monthly":
        fake_update = Update(0, query.message)
        fake_update.message.from_user = query.from_user
        await report_monthly(fake_update, context)
    elif data.startswith("select_project:"):
        project_id = int(data.split(":")[1])
        project_name = database.get_project_name(project_id)
        if project_name:
            # Ensure user_data dictionary exists for the user
            if user_id not in user_data:
                user_data[user_id] = {}
            user_data[user_id]['current_project'] = project_id
            # Edit the original message to show selection
            await query.edit_message_text(f'Project "{project_name}" selected.')
            # Optionally, clear the current task selection
            if 'current_task' in user_data[user_id]:
                del user_data[user_id]['current_task']
        else:
            await query.edit_message_text('Error: Project not found.')
    elif data.startswith("select_task:"):
        task_id = int(data.split(":")[1])
        task_name = database.get_task_name(task_id)
        if task_name:
            # Ensure user_data dictionary exists for the user (should already exist if project is selected)
            if user_id not in user_data:
                user_data[user_id] = {} # Should ideally not happen if project is selected
            user_data[user_id]['current_task'] = task_id
            await query.edit_message_text(f'Task "{task_name}" selected.')
        else:
            await query.edit_message_text('Error: Task not found.')

    # --- Deletion Callbacks ---
    elif data == "cancel_delete":
        await query.edit_message_text("Deletion cancelled.")
        
    elif data.startswith("confirm_delete_project:"):
        project_id = int(data.split(":")[1])
        project_name = database.get_project_name(project_id) or "Unknown Project"
        keyboard = [
            [InlineKeyboardButton("🔴 Yes, DELETE it!", callback_data=f"delete_project:{project_id}")],
            [InlineKeyboardButton("🟢 No, cancel", callback_data="cancel_delete")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"❗️ Are you ABSOLUTELY SURE you want to delete project '{project_name}'?\nThis will delete all its tasks and recorded time entries.", reply_markup=reply_markup)
        
    elif data.startswith("delete_project:"):
        project_id = int(data.split(":")[1])
        project_name = database.get_project_name(project_id) or "Unknown Project"
        deleted = database.delete_project(project_id)
        if deleted:
             # Clear selected project if it was the one deleted
            if user_id in user_data and user_data[user_id].get('current_project') == project_id:
                del user_data[user_id]['current_project']
                if 'current_task' in user_data[user_id]: # Also clear task
                    del user_data[user_id]['current_task']
            await query.edit_message_text(f"✅ Project '{project_name}' and all associated data have been deleted.")
        else:
            await query.edit_message_text(f"❌ Failed to delete project '{project_name}'. Check logs.")
            
    elif data.startswith("confirm_delete_task:"):
        task_id = int(data.split(":")[1])
        task_name = database.get_task_name(task_id) or "Unknown Task"
        keyboard = [
            [InlineKeyboardButton("🔴 Yes, DELETE it!", callback_data=f"delete_task:{task_id}")],
            [InlineKeyboardButton("🟢 No, cancel", callback_data="cancel_delete")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"❗️ Are you ABSOLUTELY SURE you want to delete task '{task_name}'?\nThis will delete all its recorded time entries.", reply_markup=reply_markup)
        
    elif data.startswith("delete_task:"):
        task_id = int(data.split(":")[1])
        task_name = database.get_task_name(task_id) or "Unknown Task"
        deleted = database.delete_task(task_id)
        if deleted:
            # Clear selected task if it was the one deleted
            if user_id in user_data and user_data[user_id].get('current_task') == task_id:
                del user_data[user_id]['current_task']
            await query.edit_message_text(f"✅ Task '{task_name}' and its time entries have been deleted.")
        else:
            await query.edit_message_text(f"❌ Failed to delete task '{task_name}'. Check logs.")

# --- Deletion Commands ---

async def delete_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    projects = database.get_projects(user_id)
    if not projects:
        await update.message.reply_text("You don't have any projects to delete.")
        return
        
    keyboard = []
    for project_id, project_name in projects:
        # Use a different callback prefix to trigger confirmation
        keyboard.append([InlineKeyboardButton(f"🗑️ {project_name}", callback_data=f"confirm_delete_project:{project_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Which project do you want to delete? (This action is irreversible!)", reply_markup=reply_markup)

async def delete_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data or 'current_project' not in user_data[user_id]:
        await update.message.reply_text('Please select a project first using /list_projects before deleting tasks.')
        return
        
    project_id = user_data[user_id]['current_project']
    tasks = database.get_tasks(project_id)
    project_name = database.get_project_name(project_id)
    
    if not tasks:
        await update.message.reply_text(f"No tasks found in project '{project_name}' to delete.")
        return
        
    keyboard = []
    for task_id, task_name in tasks:
        # Use a different callback prefix to trigger confirmation
        keyboard.append([InlineKeyboardButton(f"🗑️ {task_name}", callback_data=f"confirm_delete_task:{task_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Which task in '{project_name}' do you want to delete? (This action is irreversible!)", reply_markup=reply_markup)

def main():
    print(f"Starting Pomodoro Bot with domain: {DOMAIN_URL}")
    application = Application.builder().token(TOKEN).build()
    job_queue = application.job_queue
    
    # Register the commands
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('create_project', create_project))
    application.add_handler(CommandHandler('select_project', select_project))
    application.add_handler(CommandHandler('create_task', create_task))
    application.add_handler(CommandHandler('select_task', select_task))
    application.add_handler(CommandHandler('start_timer', start_timer))
    application.add_handler(CommandHandler('pause_timer', pause_timer))
    application.add_handler(CommandHandler('resume_timer', resume_timer))
    application.add_handler(CommandHandler('stop_timer', stop_timer))
    application.add_handler(CommandHandler('report', report_command))
    application.add_handler(CommandHandler('list_projects', list_projects))
    application.add_handler(CommandHandler('list_tasks', list_tasks))
    application.add_handler(CommandHandler('delete_project', delete_project_command))
    application.add_handler(CommandHandler('delete_task', delete_task_command))
    
    # Add handler for the inline buttons in reports
    from telegram.ext import CallbackQueryHandler
    application.add_handler(CallbackQueryHandler(button_callback))

    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True  # Make thread exit when main program exits
    flask_thread.start()

    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()