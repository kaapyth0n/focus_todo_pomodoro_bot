from telegram import Update, ReplyKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
import database
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import JobQueue
import threading
import os
from config import TOKEN, DOMAIN_URL
import logging
import sqlite3 # Needed for DB check exception handling

# Import handlers
from handlers import commands as cmd_handlers
from handlers import callbacks as cb_handlers
from handlers import google_auth as google_auth_handlers # Import google auth handlers
from handlers import admin as admin_handlers # Import admin handlers
from handlers import jira_auth as jira_auth_handlers
# Import Flask runner
from web_app import run_flask, set_job_queue
from handlers.commands import (
    FORWARDED_MESSAGE_PROJECT_SELECT, FORWARDED_MESSAGE_PROJECT_CREATE,
    handle_forwarded_message, handle_forwarded_project_name
)

# Shared state (consider moving to a better place later, e.g., context.bot_data or a dedicated module)
# These need to be accessible by handlers and potentially the web_app (via import)
user_data = {}  # {user_id: {'current_project': project_id, 'current_task': task_id}}
timer_states = {}  # {user_id: {'start_time': datetime, 'accumulated_time': int, 'state': 'running'/'paused'/'stopped', 'job': Job}}

# Get a logger instance
log = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    
    # Get user's language from Telegram client if available
    user_language = user.language_code
    if user_language and user_language in SUPPORTED_LANGUAGES:
        # Set the user's language in the database
        from i18n_utils import set_user_lang
        set_user_lang(user.id, user_language)
        log.info(f"User {user.id} language automatically set to {user_language} from Telegram client")
    
    # Add or update user in database
    database.add_user(user.id, user.first_name, user.last_name)
    
    # Use the user's language for the welcome message
    from i18n_utils import _
    welcome_message = _(user.id, 'welcome')
    await update.message.reply_text(welcome_message)

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

async def setup_bot_commands(application: Application):
    """Sets the bot commands menu."""
    commands = [
        BotCommand("start", "Start the bot & show keyboard"),
        BotCommand("language", "Set preferred language"),
        BotCommand("help", "Show help message"),
        BotCommand("list_projects", "List/select projects"),
        BotCommand("create_project", "Create a new project"),
        BotCommand("list_tasks", "List/select tasks in current project"),
        BotCommand("create_task", "Create a new task in current project"),
        BotCommand("start_timer", "Start work timer (default 25min)"),
        BotCommand("pause_timer", "Pause current timer"),
        BotCommand("resume_timer", "Resume paused timer"),
        BotCommand("stop_timer", "Stop current timer & log"),
        BotCommand("report", "Show report options"),
        BotCommand("connect_google", "Connect Google Sheets account"),
        BotCommand("export_to_sheets", "Export data to Google Sheets"),
        BotCommand("connect_jira", "Connect Jira Cloud account"),
        BotCommand("disconnect_jira", "Disconnect Jira Cloud account"),
        BotCommand("fetch_jira_projects", "List Jira projects with your open issues"),
    ]
    await application.bot.set_my_commands(commands)
    log.info("Bot commands menu set.")

async def post_init(application: Application):
    """Runs after the application is initialized."""
    await setup_bot_commands(application)

def main():
    log.info("Initializing Pomodoro Bot...")
    
    # According to DEPLOY.md, in production the correct installation is:
    # pip install "python-telegram-bot[job-queue]"
    # For PTB 21.x, we don't need to explicitly create a job queue
    
    try:
        # Standard initialization for python-telegram-bot 21.x with job-queue extra
        application = Application.builder().token(TOKEN).post_init(post_init).build()
        
        # Check if job queue is available
        if not hasattr(application, 'job_queue') or application.job_queue is None:
            log.warning("Job queue not available. Make sure python-telegram-bot is installed with [job-queue] extra.")
            log.warning("Run: pip install 'python-telegram-bot[job-queue]'")
    except Exception as e:
        log.error(f"Error initializing application: {e}")
        # Fallback to simpler initialization if anything fails
        application = Application.builder().token(TOKEN).build()
        log.warning("Using basic initialization without post_init.")

    # Define reply keyboard button texts (ensure these match the ones in handlers/commands.py)
    BTN_START_WORK = "🚀 Start Work"
    BTN_PAUSE = "⏸️ Pause"
    BTN_RESUME = "▶️ Resume"
    BTN_STOP = "⏹️ Stop"
    BTN_REPORT = "📊 Report"
    BTN_BREAK_5 = "☕️ Break (5m)"
    BTN_LIST_PROJECTS = "📂 Projects"
    BTN_LIST_TASKS = "📝 Tasks"

    # --- Google Auth Conversation Handler ---
    google_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('connect_google', google_auth_handlers.connect_google)],
        states={
            google_auth_handlers.WAITING_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, google_auth_handlers.receive_oauth_code)
            ],
        },
        fallbacks=[CommandHandler('cancel', google_auth_handlers.cancel_oauth)],
    )
    application.add_handler(google_conv_handler)

    # --- Create Project Conversation Handler ---
    create_project_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('create_project', cmd_handlers.create_project)],
        states={
            cmd_handlers.WAITING_PROJECT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_handlers.receive_project_name)
            ],
        },
        fallbacks=[CommandHandler('cancel', cmd_handlers.cancel_creation)],
    )
    application.add_handler(create_project_conv_handler)

    # --- Create Task Conversation Handler ---
    create_task_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('create_task', cmd_handlers.create_task)],
        states={
            cmd_handlers.WAITING_TASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_handlers.receive_task_name)
            ],
        },
        fallbacks=[CommandHandler('cancel', cmd_handlers.cancel_creation)],
    )
    application.add_handler(create_task_conv_handler)

    # --- Rename Project Conversation Handler ---
    rename_project_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_handlers.button_callback, pattern="^rename_project:")],
        states={
            cmd_handlers.WAITING_RENAME_PROJECT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_handlers.handle_rename_project_name)
            ],
        },
        fallbacks=[CommandHandler('cancel', cmd_handlers.cancel_rename)],
    )
    application.add_handler(rename_project_conv_handler)

    # --- Rename Task Conversation Handler ---
    rename_task_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_handlers.button_callback, pattern="^rename_task:")],
        states={
            cmd_handlers.WAITING_RENAME_TASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_handlers.handle_rename_task_name)
            ],
        },
        fallbacks=[CommandHandler('cancel', cmd_handlers.cancel_rename)],
    )
    application.add_handler(rename_task_conv_handler)

    # --- Forwarded Message Conversation Handler ---
    forwarded_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.FORWARDED, cmd_handlers.handle_forwarded_message)],
        states={
            cmd_handlers.FORWARDED_MESSAGE_PROJECT_SELECT: [
                CallbackQueryHandler(cb_handlers.button_callback, pattern="^forwarded_select_project:"),
                CallbackQueryHandler(cb_handlers.button_callback, pattern="^forwarded_create_new_project$")
            ],
            cmd_handlers.FORWARDED_MESSAGE_PROJECT_CREATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_handlers.handle_forwarded_project_name)
            ],
        },
        fallbacks=[CommandHandler('cancel', cmd_handlers.cancel_creation)],
        name="forwarded_message_conversation",
        persistent=False,
        allow_reentry=True
    )
    application.add_handler(forwarded_conv_handler)

    # --- Jira Auth Conversation Handler ---
    jira_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('connect_jira', jira_auth_handlers.connect_jira)],
        states={
            jira_auth_handlers.WAITING_JIRA_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, jira_auth_handlers.receive_jira_oauth_code)
            ],
        },
        fallbacks=[CommandHandler('cancel', jira_auth_handlers.cancel_jira_oauth)],
    )
    application.add_handler(jira_conv_handler)

    # Register command handlers from handlers.commands
    application.add_handler(CommandHandler('start', cmd_handlers.start))
    application.add_handler(CommandHandler('select_project', cmd_handlers.select_project))
    application.add_handler(CommandHandler('list_projects', cmd_handlers.list_projects))
    application.add_handler(CommandHandler('select_task', cmd_handlers.select_task))
    application.add_handler(CommandHandler('list_tasks', cmd_handlers.list_tasks))
    application.add_handler(CommandHandler('start_timer', cmd_handlers.start_timer))
    application.add_handler(CommandHandler('pause_timer', cmd_handlers.pause_timer))
    application.add_handler(CommandHandler('resume_timer', cmd_handlers.resume_timer))
    application.add_handler(CommandHandler('stop_timer', cmd_handlers.stop_timer))
    application.add_handler(CommandHandler('report', cmd_handlers.report_command))
    application.add_handler(CommandHandler('delete_project', cmd_handlers.delete_project_command))
    application.add_handler(CommandHandler('delete_task', cmd_handlers.delete_task_command))
    application.add_handler(CommandHandler('help', cmd_handlers.help_command))
    application.add_handler(CommandHandler('export_to_sheets', google_auth_handlers.export_to_sheets))
    application.add_handler(CommandHandler('language', cmd_handlers.set_language_command))
    # Register Admin Handlers
    application.add_handler(CommandHandler(admin_handlers.INITIAL_ADMIN_COMMAND.lstrip('/'), admin_handlers.set_initial_admin))
    application.add_handler(CommandHandler('admin_notify_toggle', admin_handlers.admin_notify_toggle))
    application.add_handler(CommandHandler('admin_stats', admin_handlers.admin_stats))
    application.add_handler(CommandHandler('disconnect_jira', jira_auth_handlers.disconnect_jira))
    application.add_handler(CommandHandler('fetch_jira_projects', jira_auth_handlers.fetch_jira_projects))
    application.add_handler(CallbackQueryHandler(jira_auth_handlers.jira_project_callback, pattern="^jira_project:"))
    application.add_handler(CallbackQueryHandler(jira_auth_handlers.jira_issue_callback, pattern="^jira_issue:"))
    application.add_handler(CallbackQueryHandler(jira_auth_handlers.log_jira_callback, pattern="^log_jira:"))
    application.add_handler(CallbackQueryHandler(jira_auth_handlers.jira_add_all_callback, pattern="^jira_add_all:"))
    application.add_handler(CallbackQueryHandler(cb_handlers.button_callback))

    # Register the general text handler LAST
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        cmd_handlers.handle_text_message
    ))

    # Inject JobQueue into Flask so web endpoints can schedule/resume timers
    try:
        if hasattr(application, 'job_queue') and application.job_queue is not None:
            set_job_queue(application.job_queue)
        else:
            log.warning("Application has no job_queue; web controls may not function.")
    except Exception as inj_err:
        log.error(f"Failed to inject JobQueue into Flask: {inj_err}")

    # Start Flask in a separate thread (imported from web_app.py)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True  # Make thread exit when main program exits
    flask_thread.start()

    # Start the bot
    print("Bot is running...")
    log.info("Telegram bot polling started.")
    application.run_polling()

# --- Database Check/Initialization Helper ---
def check_and_update_db_schema():
    """Ensures DB schema exists and is up-to-date."""
    try:
        # Call create_database on every startup.
        # It handles both initial creation and checking/adding missing columns/tables.
        log.info("Checking/Updating database schema...")
        database.create_database()
        log.info("Database schema check/update complete.")
        
    except sqlite3.Error as e:
        log.critical(f"CRITICAL: Error checking/updating database schema: {e}", exc_info=True)
        exit(1)
    except Exception as e:
        log.critical(f"CRITICAL: Unexpected error during DB schema check: {e}", exc_info=True)
        exit(1)

if __name__ == '__main__':
    # Configure logging early
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.vendor.ptb_urllib3.urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR) # Quiet Google discovery cache

    # Check/Initialize/Update database schema before starting bot
    check_and_update_db_schema()

    main()