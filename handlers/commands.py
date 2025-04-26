from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown # Import escape_markdown
from telegram import constants # For ParseMode
import database
from datetime import datetime, timedelta
from config import timer_states, DOMAIN_URL
import logging
import sqlite3
from . import google_auth as google_auth_handlers # Import the module itself
from . import admin as admin_handlers # Import admin handlers
from database import STATUS_ACTIVE, STATUS_DONE # Import status constants
import math # For formatting time

log = logging.getLogger(__name__)

# --- Reply Keyboard Definition ---

BTN_START_WORK = "🚀 Start Work"
BTN_PAUSE = "⏸️ Pause"
BTN_RESUME = "▶️ Resume"
BTN_STOP = "⏹️ Stop"
BTN_REPORT = "📊 Report"
BTN_BREAK_5 = "☕️ Break (5m)"

MAIN_KEYBOARD = [
    [BTN_START_WORK],               # Row 1
    [BTN_PAUSE, BTN_RESUME, BTN_STOP], # Row 2
    [BTN_REPORT, BTN_BREAK_5],      # Row 3
]
REPLY_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message, adds user to database, and shows keyboard, notifies admin if new."""
    user = update.message.from_user
    is_new_user = False # Flag to track if user was added
    log.info(f"Received /start command from user {user.id} ('{user.username or user.first_name}')")
    try:
        existing_user = database.get_google_credentials(user.id) # Re-using this check temporarily
        if not existing_user: 
            is_new_user = True # Assume new if no google creds, needs better check
            
        database.add_user(user.id, user.first_name, user.last_name)
        
        # Notify admin if it seems like a new user
        if is_new_user:
            await admin_handlers.send_admin_notification(
                context, 
                f"New user started: {user.first_name} (ID: {user.id}, Username: @{user.username or 'N/A'})"
            )

        # Reset current project/task if not found (good practice on start)
        current_proj = database.get_current_project(user.id)
        current_task = database.get_current_task(user.id)
        if current_proj:
             proj_name = database.get_project_name(current_proj)
             if not proj_name:
                 log.warning(f"User {user.id}'s current project {current_proj} not found. Clearing.")
                 database.clear_current_project(user.id)
             elif current_task:
                 task_name = database.get_task_name(current_task)
                 if not task_name:
                     log.warning(f"User {user.id}'s current task {current_task} not found. Clearing.")
                     database.clear_current_task(user.id)
        else:
            database.clear_current_project(user.id) # Clears task too

        # Send welcome message with the reply keyboard
        await update.message.reply_text(
            'Welcome to your Focus To-Do List Bot! Use the menu or keyboard below.', 
            reply_markup=REPLY_MARKUP
        )
    except sqlite3.Error as e:
        log.error(f"DB Error in start for user {user.id}: {e}")
        await update.message.reply_text("An error occurred connecting to the database. Please try again later.")
    except Exception as e:
        log.error(f"Error in start command for user {user.id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred. Please try again later.")

# --- Project Management Commands ---
async def create_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a new project and notifies admin."""
    user = update.message.from_user # Get user object
    user_id = user.id
    project_name = ' '.join(context.args)
    log.debug(f"User {user_id} attempting to create project '{project_name}'")
    if not project_name:
        await update.message.reply_text('Please provide a project name. Usage: /create_project "Project Name"')
        return
        
    try:
        existing_projects = database.get_projects(user_id)
        for _, existing_name in existing_projects:
            if existing_name.lower() == project_name.lower():
                await update.message.reply_text(f'Project "{existing_name}" already exists.')
                return
                
        added_id = database.add_project(user_id, project_name)
        if added_id:
            log.info(f"User {user_id} created project '{project_name}' (ID: {added_id})")
            await update.message.reply_text(f'Project "{project_name}" created! Select it with /select_project or /list_projects.')
            # Notify admin
            await admin_handlers.send_admin_notification(
                context, 
                f"Project created by {user.first_name} ({user_id}): '{project_name}' (ID: {added_id})"
            )
        else:
            log.warning(f"Failed DB call to create project '{project_name}' for user {user_id}")
            await update.message.reply_text("Failed to create project due to a database error.")
            
    except sqlite3.Error as e:
        log.error(f"DB Error in create_project for user {user_id}: {e}")
        await update.message.reply_text("An error occurred accessing project data. Please try again later.")
    except Exception as e:
        log.error(f"Error in create_project command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred.")

async def select_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Selects a project by name or lists projects if no name is given."""
    user_id = update.message.from_user.id
    project_name = ' '.join(context.args)
    log.debug(f"User {user_id} attempting to select project '{project_name}' (or list)")
    if not project_name:
        await list_projects(update, context)
        return
        
    try:
        projects = database.get_projects(user_id)
        project_found = False
        for proj_id, proj_name_db in projects:
            if proj_name_db.lower() == project_name.lower(): 
                database.set_current_project(user_id, proj_id)
                log.info(f"User {user_id} selected project {proj_id} ('{proj_name_db}') via command.")
                await update.message.reply_text(f'Project "{proj_name_db}" selected.')
                project_found = True
                break
                
        if not project_found:
            await update.message.reply_text('Project not found. Use /list_projects or /create_project.')
            
    except sqlite3.Error as e:
        log.error(f"DB Error in select_project for user {user_id}: {e}")
        await update.message.reply_text("An error occurred accessing project data.")
    except Exception as e:
        log.error(f"Error in select_project command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred.")

async def list_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists user's active projects with buttons for selection and marking done."""
    user_id = update.effective_user.id
    log.debug(f"User {user_id} requested active project list.")
    try:
        # Fetch only active projects
        projects = database.get_projects(user_id, status=STATUS_ACTIVE)
        
        keyboard = []
        if not projects:
            keyboard.append([InlineKeyboardButton("No active projects found. Create one?", callback_data="noop_create_project")]) # Placeholder
        else:
            current_project_id = database.get_current_project(user_id)
            for project_id, project_name in projects:
                button_text = project_name
                if project_id == current_project_id:
                    button_text = f"➡️ {project_name}" # Indicate current project
                # Row: [Select Button, Mark Done Button]
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data=f"select_project:{project_id}"),
                    InlineKeyboardButton("✅ Mark Done", callback_data=f"mark_project_done:{project_id}")
                ])
                
        # Add button to view archived projects
        keyboard.append([InlineKeyboardButton("🗄️ View Archived Projects", callback_data="list_projects_done")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Use edit_message_text if called from a callback, otherwise reply_text
        if update.callback_query:
            await update.callback_query.edit_message_text("Select an active project (➡️ = current) or mark as done:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("Select an active project (➡️ = current) or mark as done:", reply_markup=reply_markup)
        
        log.debug(f"Displayed active project list for user {user_id}")
    except Exception as e:
        log.error(f"Error listing/editing projects for user {user_id}: {e}", exc_info=True)
        if update.callback_query:
             try: await update.callback_query.message.reply_text("An error occurred listing projects.") # Send new message on callback error
             except: pass
        else: 
             await update.message.reply_text("An error occurred listing projects.")

async def delete_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates the project deletion process."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} initiated project deletion process.")
    try:
        projects = database.get_projects(user_id)
        if not projects:
            await update.message.reply_text("You don't have any projects to delete.")
            return
            
        keyboard = []
        for project_id, project_name in projects:
            keyboard.append([InlineKeyboardButton(f"🗑️ {project_name}", callback_data=f"confirm_delete_project:{project_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Which project to delete? (Irreversible!) Cick to confirm:", reply_markup=reply_markup)
        
        log.debug(f"Displayed project deletion confirmation list for user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB Error in delete_project_command for user {user_id}: {e}")
        await update.message.reply_text("An error occurred accessing projects for deletion.")
    except Exception as e:
        log.error(f"Error in delete_project_command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred.")

# --- Task Management Commands ---
async def create_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a task to the currently selected project and notifies admin."""
    user = update.message.from_user # Get user object
    user_id = user.id
    task_name = ' '.join(context.args)
    log.debug(f"User {user_id} attempting to create task '{task_name}'")
    if not task_name:
        await update.message.reply_text('Usage: /create_task "Task Name"')
        return
        
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            await update.message.reply_text('Please select a project first with /list_projects.')
            return
            
        existing_tasks = database.get_tasks(current_project_id)
        for _, existing_name in existing_tasks:
            if existing_name.lower() == task_name.lower():
                await update.message.reply_text(f'Task "{existing_name}" already exists in this project.')
                return
                
        project_name = database.get_project_name(current_project_id)
        added_id = database.add_task(current_project_id, task_name)
        if added_id and project_name:
            log.info(f"User {user_id} created task '{task_name}' (ID: {added_id}) in project {current_project_id}")
            await update.message.reply_text(f'Task "{task_name}" added to project "{project_name}"!')
            # Notify admin
            await admin_handlers.send_admin_notification(
                context, 
                f"Task created by {user.first_name} ({user_id}) in project '{project_name}': '{task_name}' (ID: {added_id})"
            )
        elif added_id:
             log.warning(f"Failed DB call to create task '{task_name}' for user {user_id}")
             await update.message.reply_text(f'Task "{task_name}" added!')
        else:
            await update.message.reply_text("Failed to add task due to a database error.")
            
    except sqlite3.Error as e:
        log.error(f"DB Error in create_task for user {user_id}: {e}")
        await update.message.reply_text("An error occurred accessing task data.")
    except Exception as e:
        log.error(f"Error in create_task command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred.")

async def select_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Selects a task by name or lists tasks if no name is given."""
    user_id = update.message.from_user.id
    task_name = ' '.join(context.args)
    log.debug(f"User {user_id} attempting to select task '{task_name}' (or list)")
    
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            await update.message.reply_text('Please select a project first with /list_projects.')
            return
            
        project_name = database.get_project_name(current_project_id) or "Selected Project"

        if not task_name:
            await list_tasks(update, context)
            return
            
        tasks = database.get_tasks(current_project_id)
        task_found = False
        for task_id, t_name_db in tasks:
            if t_name_db.lower() == task_name.lower(): 
                database.set_current_task(user_id, task_id)
                log.info(f"User {user_id} selected task {task_id} ('{t_name_db}') via command.")
                await update.message.reply_text(f'Task "{t_name_db}" selected in project "{project_name}".')
                task_found = True
                break
                
        if not task_found:
            await update.message.reply_text(f'Task not found in project "{project_name}". Use /list_tasks or /create_task.')
            
    except sqlite3.Error as e:
        log.error(f"DB Error in select_task for user {user_id}: {e}")
        await update.message.reply_text("An error occurred accessing task data.")
    except Exception as e:
        log.error(f"Error in select_task command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred.")

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists active tasks in the current project with selection/done buttons."""
    user_id = update.effective_user.id
    log.debug(f"User {user_id} requested active task list.")
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
             message_text = 'Please select an active project first using /list_projects.'
             if update.callback_query: await update.callback_query.edit_message_text(text=message_text) 
             else: await update.message.reply_text(text=message_text)
             return
            
        project_name = database.get_project_name(current_project_id) or "Current Project"
        # Fetch only active tasks for the current project
        tasks = database.get_tasks(current_project_id, status=STATUS_ACTIVE)
        
        keyboard = []
        list_title = f"Active tasks in '{project_name}' (➡️ = current):"
        
        if not tasks:
            keyboard.append([InlineKeyboardButton(f"No active tasks found. Create one?", callback_data="noop_create_task")]) # Placeholder
        else:
            current_task_id = database.get_current_task(user_id)
            for task_id, task_name in tasks:
                button_text = task_name
                if task_id == current_task_id:
                     button_text = f"➡️ {task_name}"
                # Row: [Select Button, Mark Done Button]
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data=f"select_task:{task_id}"),
                    InlineKeyboardButton("✅ Mark Done", callback_data=f"mark_task_done:{task_id}")
                ])
                
        # Add button to view archived tasks for this project
        keyboard.append([InlineKeyboardButton("🗄️ View Archived Tasks", callback_data="list_tasks_done")])
        # Add button to go back to project list
        keyboard.append([InlineKeyboardButton("« Back to Projects", callback_data="list_projects_active")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.edit_message_text(text=list_title, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text=list_title, reply_markup=reply_markup)
        
        log.debug(f"Displayed active task list for user {user_id}")
    except Exception as e:
        log.error(f"Error listing/editing tasks for user {user_id}: {e}", exc_info=True)
        if update.callback_query:
             try: await update.callback_query.message.reply_text("An error occurred listing tasks.") 
             except: pass
        else: 
             await update.message.reply_text("An error occurred listing tasks.")

async def delete_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates the task deletion process."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} initiated task deletion process.")
    try:
        current_project_id = database.get_current_project(user_id) 
        if not current_project_id:
            await update.message.reply_text('Please select a project first before deleting tasks.')
            return
            
        tasks = database.get_tasks(current_project_id)
        project_name = database.get_project_name(current_project_id) or "Current Project"
        
        if not tasks:
            await update.message.reply_text(f"No tasks found in project '{project_name}' to delete.")
            return
            
        keyboard = []
        for task_id, task_name in tasks:
            keyboard.append([InlineKeyboardButton(f"🗑️ {task_name}", callback_data=f"confirm_delete_task:{task_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Which task in '{project_name}' to delete? Click to confirm:", reply_markup=reply_markup)
        
        log.debug(f"Displayed task deletion confirmation list for user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB Error in delete_task_command for user {user_id}: {e}")
        await update.message.reply_text("An error occurred accessing tasks for deletion.")
    except Exception as e:
        log.error(f"Error in delete_task_command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred.")

# --- Helper Function for Starting Timers ---
async def _start_timer_internal(context: ContextTypes.DEFAULT_TYPE, user_id: int, duration_minutes: int, session_type: str, project_name: str = None, task_name: str = None):
    """Internal helper to start a timer job (work or break)."""
    if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
        log.warning(f"Attempted to start timer for user {user_id} but another timer is active.")
        try:
             await context.bot.send_message(chat_id=user_id, text='Another timer is already active. Please /stop_timer first.')
        except Exception as bot_error:
             log.error(f"Failed to send message to user {user_id}: {bot_error}")
        return False

    log.info(f"Starting {session_type} timer ({duration_minutes} min) for user {user_id}")
    job_data = {'user_id': user_id, 'duration': duration_minutes, 'session_type': session_type}
    
    try:
        job = context.job_queue.run_once(timer_finished, duration_minutes * 60, data=job_data, name=f"timer_{user_id}")
    except Exception as job_error:
        log.error(f"Failed to schedule timer job for user {user_id}: {job_error}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=user_id, text="Sorry, failed to schedule the timer. Please try again.")
        except Exception as bot_error:
             log.error(f"Failed to send error message to user {user_id}: {bot_error}")
        return False
        
    now = datetime.now()
    timer_states[user_id] = {
        'state': 'running',
        'accumulated_time': 0,
        'start_time': now,
        'initial_start_time': now,
        'duration': duration_minutes,
        'session_type': session_type, 
        'job': job
    }

    timer_url = f'{DOMAIN_URL}/timer/{user_id}'
    keyboard = [[InlineKeyboardButton("View Timer", web_app=WebAppInfo(url=timer_url))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f'Break timer started ({duration_minutes} minutes).'
    if session_type == 'work' and project_name and task_name:
        message = f'Work timer started for task "{task_name}" in project "{project_name}" ({duration_minutes} minutes).'
    elif session_type == 'work':
         message = f'Work timer started ({duration_minutes} minutes).'

    try:
        await context.bot.send_message(chat_id=user_id, text=message, reply_markup=reply_markup)
    except Exception as bot_error:
        log.error(f"Failed to send timer start confirmation to user {user_id}: {bot_error}")
        return False
        
    return True

# --- Timer Commands ---
async def start_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log.debug(f"/start_timer command received from user {user_id}")
    try:
        if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
            await update.message.reply_text('A timer is already active. Please /stop_timer first.')
            return
            
        project_id = database.get_current_project(user_id)
        task_id = database.get_current_task(user_id)
        if not project_id or not task_id:
            await update.message.reply_text('Please select an active project and task first.')
            return
            
        # --- Check Project and Task Status --- 
        project_status = database.get_project_status(project_id)
        task_status = database.get_task_status(task_id)
        
        if project_status != database.STATUS_ACTIVE:
            log.warning(f"User {user_id} tried to start timer on inactive/done project {project_id}.")
            await update.message.reply_text("The selected project is marked as done/archived. Please select an active project.")
            database.clear_current_project(user_id) # Clear selection if inactive
            return
            
        if task_status != database.STATUS_ACTIVE:
            log.warning(f"User {user_id} tried to start timer on inactive/done task {task_id}.")
            await update.message.reply_text("The selected task is marked as done/archived. Please select an active task.")
            database.clear_current_task(user_id) # Clear selection if inactive
            return
        # --- End Status Check --- 
            
        project_name = database.get_project_name(project_id)
        task_name = database.get_task_name(task_id)
        
        if not project_name or not task_name:
            # This check might be redundant now with status check, but keep as fallback
            await update.message.reply_text(f'Error: The selected project/task info could not be retrieved.')
            database.clear_current_task(user_id)
            database.clear_current_project(user_id)
            return

        duration_minutes = 25 
        if context.args:
            try:
                requested_duration = int(context.args[0])
                if 1 <= requested_duration <= 120: 
                    duration_minutes = requested_duration
                else:
                    await update.message.reply_text("Duration must be between 1 and 120 minutes.")
                    return
            except (ValueError, IndexError):
                await update.message.reply_text("Invalid duration. Using default 25 minutes.")
        
        await _start_timer_internal(context, user_id, duration_minutes, 'work', project_name, task_name)

    except sqlite3.Error as e:
        log.error(f"DB Error in start_timer for user {user_id}: {e}")
        await update.message.reply_text("An error occurred accessing project/task data.")
    except Exception as e:
        log.error(f"Error in start_timer command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred starting the timer.")

async def start_break_timer(context: ContextTypes.DEFAULT_TYPE, user_id: int, duration_minutes: int):
    log.debug(f"Starting break timer ({duration_minutes} min) for user {user_id}")
    try:
        await _start_timer_internal(context, user_id, duration_minutes, 'break')
    except Exception as e:
        log.error(f"Error in start_break_timer for user {user_id}: {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=user_id, text="An unexpected error occurred starting the break timer.")
        except Exception as bot_error:
             log.error(f"Failed to send error message to user {user_id}: {bot_error}")

# --- Timer Finish Callback ---
async def timer_finished(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data['user_id']
    duration_minutes = job.data['duration'] 
    session_type = job.data['session_type']
    log.info(f"Timer finished job running for user {user_id}, type: {session_type}, duration: {duration_minutes}")
    
    try:
        timer_state_entry = timer_states.get(user_id)
        if timer_state_entry and timer_state_entry.get('job') == job:
            log.debug(f"Timer state found for user {user_id}, processing completion.")
            project_id, task_id, project_name, task_name = None, None, None, None
            initial_start_time = timer_state_entry['initial_start_time']
            is_completed = 1 # Timer finished naturally
            
            if session_type == 'work':
                project_id = database.get_current_project(user_id)
                task_id = database.get_current_task(user_id)
                if project_id and task_id:
                     project_name = database.get_project_name(project_id)
                     task_name = database.get_task_name(task_id)
                     if not project_name or not task_name:
                          log.warning(f"Work timer finished for {user_id}, but project/task name missing (deleted?).")
                          project_id, task_id = None, None # Ensure they are None if names missing
                else:
                    log.warning(f"Work timer finished for {user_id}, but project/task not selected in DB.")
                    await context.bot.send_message(chat_id=user_id, text=f"⏱️ Work timer finished ({duration_minutes} min), but project/task was unselected. Time not logged.")
                    del timer_states[user_id] # Cleanup state
                    return 
            
            # Add session to DB
            session_added_id = database.add_pomodoro_session(
                user_id=user_id, project_id=project_id, task_id=task_id,
                start_time=initial_start_time, duration_minutes=duration_minutes, 
                session_type=session_type, completed=is_completed       
            )
            
            # Prepare message and attempt auto-append *if* it was a work session
            if session_type == 'work' and project_id and task_id:
                success_message = (
                    f"✅ Time's up! Work session completed.\n\n"
                    f'Project: {project_name}\n'
                    f'Task: {task_name}\n'
                    f'Duration: {duration_minutes} minutes'
                )
                keyboard = [
                    [InlineKeyboardButton("☕️ 5-min Break", callback_data="start_break:5")],
                    [InlineKeyboardButton("☕️☕️ 15-min Break", callback_data="start_break:15")] 
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(chat_id=user_id, text=success_message, reply_markup=reply_markup)
                
                # Attempt automatic append to Google Sheet
                if session_added_id: # Check if DB save was likely successful
                    session_data_for_append = {
                        'start_time': initial_start_time,
                        'duration_minutes': duration_minutes,
                        'completed': is_completed,
                        'session_type': session_type,
                        'project_id': project_id,
                        'task_id': task_id
                    }
                    await google_auth_handlers._append_single_session_to_sheet(user_id, session_data_for_append)
                
            elif session_type == 'break': 
                 success_message = f"🧘 Break finished ({duration_minutes} minutes). Time for work!" 
                 await context.bot.send_message(chat_id=user_id, text=success_message)

            log.info(f"Session type '{session_type}' completed and logged for user {user_id}.")
            del timer_states[user_id] # Cleanup state after processing
                
        else:
            log.warning(f"Timer finished job executed for user {user_id}, but state was missing or job outdated.")

    except Exception as e: # Broader catch for unexpected errors during processing
        log.error(f"Unexpected error processing finished timer job for user {user_id}: {e}", exc_info=True)
        try: await context.bot.send_message(chat_id=user_id, text="An unexpected error occurred when finishing the timer.")
        except: pass
        # Ensure state cleanup even on error
        if user_id in timer_states: del timer_states[user_id]

async def pause_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log.debug(f"/pause_timer received from user {user_id}")
    try:
        state_data = timer_states.get(user_id)
        if not state_data or state_data['state'] != 'running':
            timer_type = state_data.get('session_type', 'timer') if state_data else 'timer'
            await update.message.reply_text(f'No {timer_type} is running.')
            return
            
        current_time = datetime.now()
        start_time = state_data.get('start_time')
        if not start_time:
             log.error(f"Missing start_time in timer state for user {user_id} during pause.")
             await update.message.reply_text("Internal error: Timer state inconsistent.")
             return

        time_worked = (current_time - start_time).total_seconds() / 60
        state_data['accumulated_time'] += time_worked
        state_data['state'] = 'paused'
        
        job = state_data.get('job')
        if job:
            job.schedule_removal()
            state_data['job'] = None 
            log.debug(f"Removed scheduled job for paused timer (user {user_id}).")
            
        timer_type = state_data.get('session_type', 'timer').capitalize()
        await update.message.reply_text(f'{timer_type} paused. Accumulated: {state_data.get("accumulated_time", 0):.2f} min.')
        log.info(f"Paused {timer_type} for user {user_id}.")

    except KeyError as e:
        log.error(f"KeyError accessing timer_states for user {user_id} in pause_timer: {e}")
        await update.message.reply_text("Internal error handling timer state.")
    except Exception as e:
        log.error(f"Error in pause_timer command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred pausing the timer.")

async def resume_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log.debug(f"/resume_timer received from user {user_id}")
    try:
        state_data = timer_states.get(user_id)
        if not state_data or state_data['state'] != 'paused':
            await update.message.reply_text('No timer is paused.')
            return
            
        duration_minutes = state_data['duration']
        accumulated_time = state_data['accumulated_time']
        session_type = state_data['session_type']
        initial_start_time = state_data['initial_start_time']
        remaining_time_minutes = duration_minutes - accumulated_time
        
        if remaining_time_minutes <= 0:
            log.info(f"Attempted to resume completed timer for user {user_id}. Cleaning up.")
            await update.message.reply_text('Timer already completed.')
            try:
                project_id = database.get_current_project(user_id) if session_type == 'work' else None
                task_id = database.get_current_task(user_id) if session_type == 'work' else None
                database.add_pomodoro_session(
                    user_id=user_id, project_id=project_id, task_id=task_id,
                    start_time=initial_start_time, duration_minutes=accumulated_time,
                    session_type=session_type, completed=1 
                )
            except sqlite3.Error as db_err:
                 log.error(f"DB error logging completed session on resume for user {user_id}: {db_err}")
            except Exception as log_err:
                 log.error(f"Unexpected error logging completed session on resume for user {user_id}: {log_err}")
            finally:
                 if user_id in timer_states: del timer_states[user_id] 
            return
            
        job_data = {'user_id': user_id, 'duration': duration_minutes, 'session_type': session_type}
        job = context.job_queue.run_once(timer_finished, remaining_time_minutes * 60, data=job_data, name=f"timer_{user_id}")
        
        state_data['state'] = 'running'
        state_data['start_time'] = datetime.now() 
        state_data['job'] = job
        
        timer_type = session_type.capitalize()
        await update.message.reply_text(f'{timer_type} resumed. {remaining_time_minutes:.2f} minutes remaining.')
        log.info(f"Resumed {timer_type} timer for user {user_id}.")

    except KeyError as e:
        log.error(f"KeyError accessing timer_states for user {user_id} in resume_timer: {e}")
        await update.message.reply_text("Internal error handling timer state.")
    except Exception as e:
        log.error(f"Error in resume_timer command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred resuming the timer.")

async def stop_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log.debug(f"/stop_timer received from user {user_id}")
    state_data = timer_states.get(user_id)
    
    if not state_data or state_data['state'] == 'stopped':
        await update.message.reply_text('No timer is running or paused.')
        return
        
    try:
        current_state = state_data['state']
        accumulated_time = state_data['accumulated_time']
        start_time_current_interval = state_data['start_time'] 
        initial_start_time = state_data['initial_start_time']
        duration_minutes_target = state_data['duration'] # Renamed for clarity
        session_type = state_data['session_type'] 
        job = state_data.get('job')

        if job:
            job.schedule_removal()
            log.debug(f"Removed job for stopped timer (user {user_id}).")
            
        final_accumulated_minutes = accumulated_time # Start with previously accumulated
        if current_state == 'running':
            current_time = datetime.now()
            time_worked_current_interval = (current_time - start_time_current_interval).total_seconds() / 60
            final_accumulated_minutes += time_worked_current_interval
        
        # Use target duration for completion check
        is_completed = 1 if final_accumulated_minutes >= (duration_minutes_target - 0.01) else 0 
        
        project_id, task_id, project_name, task_name = None, None, None, None
        log_message_details = f"Duration: {final_accumulated_minutes:.2f} / {duration_minutes_target} minutes"

        if session_type == 'work':
            timer_type_display = "Work timer"
            project_id = database.get_current_project(user_id)
            task_id = database.get_current_task(user_id)
            if project_id and task_id:
                project_name = database.get_project_name(project_id)
                task_name = database.get_task_name(task_id)
                if project_name and task_name:
                     log_message_details = f'Project: {project_name}\nTask: {task_name}\n{log_message_details}'
                else: 
                    log_message_details += " (Project/Task info missing)"        
            else:
                log_message_details += " (No project/task selected)"
                project_id, task_id = None, None # Ensure null if not properly selected
        else: 
            timer_type_display = "Break timer"

        # Add session to DB
        session_added_id = database.add_pomodoro_session(
            user_id=user_id, project_id=project_id, task_id=task_id,
            start_time=initial_start_time, duration_minutes=final_accumulated_minutes,
            session_type=session_type, completed=is_completed
        )
            
        message = f'⏹️ {timer_type_display} stopped.\n\n{log_message_details}'
        await update.message.reply_text(message)
        log.info(f"Stopped and logged {session_type} timer for user {user_id}.")
        
        # Attempt automatic append to Google Sheet *if* it was a work session and DB save likely worked
        if session_type == 'work' and session_added_id:
            session_data_for_append = {
                'start_time': initial_start_time,
                'duration_minutes': final_accumulated_minutes,
                'completed': is_completed,
                'session_type': session_type,
                'project_id': project_id,
                'task_id': task_id
            }
            await google_auth_handlers._append_single_session_to_sheet(user_id, session_data_for_append)
           
    except sqlite3.Error as e:
         log.error(f"DB Error logging session on stop for user {user_id}: {e}")
         await update.message.reply_text("An error occurred saving the session data.")
    except KeyError as e:
        log.error(f"KeyError accessing timer_states for user {user_id} in stop_timer: {e}")
        await update.message.reply_text("Internal error handling timer state.")
    except Exception as e:
        log.error(f"Error in stop_timer command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred stopping the timer.")
    finally:
        if user_id in timer_states:
            del timer_states[user_id]
            log.debug(f"Cleaned timer state for user {user_id}.")

# --- Report Commands ---
async def report_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the daily report with project and task breakdown."""
    user_id = update.effective_user.id
    log.info(f"Generating daily report for user {user_id}")
    total_minutes, detailed_breakdown = database.get_daily_report(user_id)
    
    if total_minutes == 0:
        await update.effective_message.reply_text("You haven't recorded any work sessions today.")
        return
        
    report = f"📊 *Daily Report*\n\n"
    report += f"Total time today: *{total_minutes:.1f} minutes*\n\n"
    
    if detailed_breakdown:
        report += "*Project & Task Breakdown:*\n"
        for project_data in detailed_breakdown:
            proj_name = escape_markdown(project_data['project_name'], version=2)
            proj_mins = project_data['project_minutes']
            try:
                percentage = (proj_mins / total_minutes) * 100 if total_minutes > 0 else 0
                report += f"• *{proj_name}:* {proj_mins:.1f} min ({percentage:.1f}%)\n"
            except ZeroDivisionError:
                report += f"• *{proj_name}:* {proj_mins:.1f} min\n"
                
            for task_data in project_data['tasks']:
                task_name = escape_markdown(task_data['task_name'], version=2)
                task_mins = task_data['task_minutes']
                report += f"    \- {task_name}: {task_mins:.1f} min\n"
    else:
        report += "No specific project/task time recorded today\."

    try:
        await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
    except Exception as e:
        log.error(f"Failed to send daily report for user {user_id} with MarkdownV2: {e}")
        # Fallback to plain text if Markdown fails
        await update.effective_message.reply_text(report) # Send plain text

async def report_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the weekly report with daily, project, and task breakdown."""
    user_id = update.effective_user.id
    log.info(f"Generating weekly report for user {user_id}")
    total_minutes, daily_breakdown, detailed_project_task_breakdown = database.get_weekly_report(user_id)
    
    if total_minutes == 0:
        await update.effective_message.reply_text("You haven't recorded any work sessions this week.")
        return
    
    report = f"📈 *Weekly Report*\n\n"
    report += f"Total time this week: *{total_minutes:.1f} minutes*\n\n"
    
    if daily_breakdown:
        report += "*Daily Breakdown:*\n"
        for date_str, minutes in daily_breakdown:
            try:
                date_obj = datetime.fromisoformat(date_str).strftime("%a, %b %d")
                report += f"• {escape_markdown(date_obj, version=2)}: {minutes:.1f} min\n"
            except (ValueError, TypeError):
                report += f"• {escape_markdown(date_str, version=2)}: {minutes:.1f} min\n"
        report += "\n"

    if detailed_project_task_breakdown:
        report += "*Project & Task Breakdown:*\n"
        for project_data in detailed_project_task_breakdown:
            proj_name = escape_markdown(project_data['project_name'], version=2)
            proj_mins = project_data['project_minutes']
            try:
                percentage = (proj_mins / total_minutes) * 100 if total_minutes > 0 else 0
                report += f"• *{proj_name}:* {proj_mins:.1f} min ({percentage:.1f}%)\n"
            except ZeroDivisionError:
                 report += f"• *{proj_name}:* {proj_mins:.1f} min\n"

            for task_data in project_data['tasks']:
                task_name = escape_markdown(task_data['task_name'], version=2)
                task_mins = task_data['task_minutes']
                report += f"    \- {task_name}: {task_mins:.1f} min\n"
    else:
        report += "No specific project/task time recorded this week\."
    
    try:
        await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
    except Exception as e:
        log.error(f"Failed to send weekly report for user {user_id} with MarkdownV2: {e}")
        await update.effective_message.reply_text(report)

async def report_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the monthly report with project and task breakdown."""
    user_id = update.effective_user.id
    log.info(f"Generating monthly report for user {user_id}")
    total_minutes, detailed_breakdown = database.get_monthly_report(user_id)
    
    if total_minutes == 0:
        await update.effective_message.reply_text("You haven't recorded any work sessions this month.")
        return
    
    current_month = datetime.now().strftime("%B %Y")
    report = f"📅 *Monthly Report: {escape_markdown(current_month, version=2)}*\n\n"
    report += f"Total time this month: *{total_minutes:.1f} minutes* ({total_minutes/60:.1f} hours)\n\n"
    
    if detailed_breakdown:
        report += "*Project & Task Breakdown:*\n"
        for project_data in detailed_breakdown:
            proj_name = escape_markdown(project_data['project_name'], version=2)
            proj_mins = project_data['project_minutes']
            try:
                percentage = (proj_mins / total_minutes) * 100 if total_minutes > 0 else 0
                report += f"• *{proj_name}:* {proj_mins:.1f} min ({percentage:.1f}%)\n"
            except ZeroDivisionError:
                report += f"• *{proj_name}:* {proj_mins:.1f} min\n"
                
            for task_data in project_data['tasks']:
                task_name = escape_markdown(task_data['task_name'], version=2)
                task_mins = task_data['task_minutes']
                report += f"    \- {task_name}: {task_mins:.1f} min\n"
    else:
        report += "No specific project/task time recorded this month\."

    try:
        await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
    except Exception as e:
        log.error(f"Failed to send monthly report for user {user_id} with MarkdownV2: {e}")
        await update.effective_message.reply_text(report)

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log.info(f"/report command received from user {user_id} with args: {context.args}")
    try:
        if not context.args or len(context.args) == 0:
            keyboard = [ [InlineKeyboardButton("📊 Daily", callback_data="report_daily")],
                         [InlineKeyboardButton("📈 Weekly", callback_data="report_weekly")],
                         [InlineKeyboardButton("📅 Monthly", callback_data="report_monthly")] ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Which work report would you like?", reply_markup=reply_markup)
            return
        
        report_type = context.args[0].lower()
        if report_type == "daily": await report_daily(update, context)
        elif report_type == "weekly": await report_weekly(update, context)
        elif report_type == "monthly": await report_monthly(update, context)
        else: await update.message.reply_text("Unknown report type. Options: daily, weekly, monthly.")
    except Exception as e:
        log.error(f"Error in report_command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred processing the report command.")

# --- Help Command ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log.info(f"User {user_id} requested /help")
    help_text = (
        "Here are the available commands:\n\n"
        "*Project Management:*\n"
        "  `/create_project \"Project Name\"` - Create a new project.\n"
        "  `/list_projects` - List and select projects (➡️ indicates current).\n"
        "  `/select_project \"Project Name\"` - Select a project by name.\n"
        "  `/delete_project` - Delete a project and its data.\n\n"
        "*Task Management:*\n"
        "  `/create_task \"Task Name\"` - Add task to the current project.\n"
        "  `/list_tasks` - List and select tasks in the current project (➡️ indicates current).\n"
        "  `/select_task \"Task Name\"` - Select a task by name.\n"
        "  `/delete_task` - Delete a task and its data.\n\n"
        "*Timer Control:*\n"
        "  `/start_timer [minutes]` - Start Pomodoro (default 25 min). E.g., `/start_timer 45`\n"
        "  `/pause_timer` - Pause the current timer.\n"
        "  `/resume_timer` - Resume the paused timer.\n"
        "  `/stop_timer` - Stop the timer early and log time.\n"
        "  (Breaks are offered after work sessions or via button)\n\n"
        "*Reporting:*\n"
        "  `/report` - Get daily, weekly, or monthly work time reports.\n\n"
        "*Google Sheets:*\n"
        "  `/connect_google` - Authorize access to Google Sheets.\n"
        "  `/export_to_sheets <SPREADSHEET_ID> [SheetName]` - Export all session data.\n\n"
        "*Other:*\n"
        "  `/help` - Show this help message.\n"
        "  `/start` - Initialize or welcome message."
    )
    try:
        # Use MarkdownV2 for better formatting if desired, but requires escaping special chars
        await update.message.reply_text(help_text, parse_mode='Markdown') 
    except Exception as e:
         log.error(f"Failed to send help message: {e}") 

# --- Reply Keyboard Button Handlers ---

async def handle_start_work_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Start Work' button press by calling start_timer."""
    log.debug(f"User {update.message.from_user.id} pressed {BTN_START_WORK}")
    await start_timer(update, context)

async def handle_pause_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Pause' button press by calling pause_timer."""
    log.debug(f"User {update.message.from_user.id} pressed {BTN_PAUSE}")
    await pause_timer(update, context)

async def handle_resume_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Resume' button press by calling resume_timer."""
    log.debug(f"User {update.message.from_user.id} pressed {BTN_RESUME}")
    await resume_timer(update, context)

async def handle_stop_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Stop' button press by calling stop_timer."""
    log.debug(f"User {update.message.from_user.id} pressed {BTN_STOP}")
    await stop_timer(update, context)

async def handle_report_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Report' button press by calling report_command."""
    log.debug(f"User {update.message.from_user.id} pressed {BTN_REPORT}")
    # Clear args for report_command when triggered by button
    context.args = []
    await report_command(update, context)

async def handle_break_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Break (5m)' button press by calling start_break_timer."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} pressed {BTN_BREAK_5}")
    
    # Check if another timer is active before starting break
    if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
        log.warning(f"User {user_id} pressed break button while timer active.")
        await update.message.reply_text('Another timer is already active. Please /stop_timer first.')
        return

    # Start the break timer (using the internal function directly)
    await start_break_timer(context, user_id, 5) # 5 minute break

# --- Help Command --- (ensure it's the last command)
# ... existing help_command ... 