from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database
from datetime import datetime, timedelta
from config import timer_states, DOMAIN_URL
import logging
import sqlite3

log = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and adds user to database."""
    user = update.message.from_user
    log.info(f"Received /start command from user {user.id} ('{user.username or user.first_name}')")
    try:
        database.add_user(user.id, user.first_name, user.last_name)
        if database.get_current_project(user.id) is None:
            database.clear_current_project(user.id)
        await update.message.reply_text('Welcome to your Focus To-Do List Bot! Use /create_project or /help to get started.')
    except sqlite3.Error as e:
        log.error(f"DB Error in start for user {user.id}: {e}")
        await update.message.reply_text("An error occurred connecting to the database. Please try again later.")
    except Exception as e:
        log.error(f"Error in start command for user {user.id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred. Please try again later.")

# --- Project Management Commands ---
async def create_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a new project."""
    user_id = update.message.from_user.id
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
    """Lists user's projects with inline buttons for selection."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} requested project list.")
    try:
        projects = database.get_projects(user_id)
        if not projects:
            await update.message.reply_text("You don't have any projects yet. /create_project")
            return
            
        current_project_id = database.get_current_project(user_id)
        keyboard = []
        for project_id, project_name in projects:
            button_text = project_name
            if project_id == current_project_id:
                button_text = f"➡️ {project_name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"select_project:{project_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select a project (➡️ = current):", reply_markup=reply_markup)
        
        log.debug(f"Displayed project list for user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB Error in list_projects for user {user_id}: {e}")
        await update.message.reply_text("An error occurred listing projects.")
    except Exception as e:
        log.error(f"Error in list_projects command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred.")

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
    """Adds a task to the currently selected project."""
    user_id = update.message.from_user.id
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
    """Lists tasks in the current project with inline buttons for selection."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} requested task list.")
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            await update.message.reply_text('Please select a project first using /list_projects.')
            return
            
        tasks = database.get_tasks(current_project_id)
        project_name = database.get_project_name(current_project_id) or "Current Project"
        
        if not tasks:
            await update.message.reply_text(f"No tasks found for project '{project_name}'. /create_task")
            return
            
        current_task_id = database.get_current_task(user_id)
        keyboard = []
        for task_id, task_name in tasks:
            button_text = task_name
            if task_id == current_task_id:
                 button_text = f"➡️ {task_name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"select_task:{task_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Select a task in '{project_name}' (➡️ = current):", reply_markup=reply_markup)
        
        log.debug(f"Displayed task list for user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB Error in list_tasks for user {user_id}: {e}")
        await update.message.reply_text("An error occurred listing tasks.")
    except Exception as e:
        log.error(f"Error in list_tasks command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred.")

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
    keyboard = [[InlineKeyboardButton("View Timer", url=timer_url)]]
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
            await update.message.reply_text('Please select a project and task first.')
            return
            
        project_name = database.get_project_name(project_id)
        task_name = database.get_task_name(task_id)
        
        if not project_name or not task_name:
            await update.message.reply_text(f'Error: The selected project/task no longer exists.')
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
        if user_id in timer_states and timer_states[user_id].get('job') == job:
            log.debug(f"Timer state found for user {user_id}, processing completion.")
            project_id, task_id, project_name, task_name = None, None, None, None
            
            if session_type == 'work':
                project_id = database.get_current_project(user_id)
                task_id = database.get_current_task(user_id)
                if project_id and task_id:
                     project_name = database.get_project_name(project_id)
                     task_name = database.get_task_name(task_id)
                     if not project_name or not task_name:
                          log.warning(f"Work timer finished for {user_id}, but project/task name missing (deleted?).")
                          project_id, task_id = None, None
                else:
                    log.warning(f"Work timer finished for {user_id}, but project/task not selected in DB.")
                    await context.bot.send_message(chat_id=user_id, text=f"⏱️ Work timer finished ({duration_minutes} min), but project/task was unselected. Time not logged.")
                    if user_id in timer_states: del timer_states[user_id]
                    return 
            
            timer_state_data = timer_states[user_id]
            timer_state_data['accumulated_time'] = duration_minutes
            timer_state_data['state'] = 'stopped' 
            initial_start_time = timer_state_data['initial_start_time']

            database.add_pomodoro_session(
                user_id=user_id, project_id=project_id, task_id=task_id,
                start_time=initial_start_time, duration_minutes=duration_minutes, 
                session_type=session_type, completed=1       
            )
            
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
            elif session_type == 'break': 
                 success_message = f"🧘 Break finished ({duration_minutes} minutes). Time for work!" 
                 await context.bot.send_message(chat_id=user_id, text=success_message)

            log.info(f"Session type '{session_type}' completed and logged for user {user_id}.")
            del timer_states[user_id]
                
        else:
            log.warning(f"Timer finished job executed for user {user_id}, but state was missing or job outdated.")

    except sqlite3.Error as e:
        log.error(f"DB Error in timer_finished for user {user_id}: {e}")
        try: await context.bot.send_message(chat_id=user_id, text="An error occurred saving session data.")
        except: pass
        if user_id in timer_states: del timer_states[user_id]
    except Exception as e:
        log.error(f"Unexpected error in timer_finished for user {user_id}: {e}", exc_info=True)
        try: await context.bot.send_message(chat_id=user_id, text="An unexpected error occurred when finishing the timer.")
        except: pass
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
        duration_minutes = state_data['duration'] 
        session_type = state_data['session_type'] 
        job = state_data.get('job')

        if job:
            job.schedule_removal()
            log.debug(f"Removed job for stopped timer (user {user_id}).")
            
        if current_state == 'running':
            current_time = datetime.now()
            time_worked_current_interval = (current_time - start_time_current_interval).total_seconds() / 60
            accumulated_time += time_worked_current_interval
        
        is_completed = 1 if accumulated_time >= (duration_minutes - 0.01) else 0 
        
        project_id, task_id, project_name, task_name = None, None, None, None
        log_message_details = f"Duration: {accumulated_time:.2f} / {duration_minutes} minutes"

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
        else: 
            timer_type_display = "Break timer"

        database.add_pomodoro_session(
            user_id=user_id, project_id=project_id, task_id=task_id,
            start_time=initial_start_time, duration_minutes=accumulated_time,
            session_type=session_type, completed=is_completed
        )
            
        message = f'⏹️ {timer_type_display} stopped.\n\n{log_message_details}'
        await update.message.reply_text(message)
        log.info(f"Stopped and logged {session_type} timer for user {user_id}.")
           
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
    user_id = update.effective_user.id
    log.info(f"Generating daily report for user {user_id}")
    try:
        total_minutes, project_breakdown = database.get_daily_report(user_id)
        
        if total_minutes == 0:
            await update.message.reply_text("No work sessions recorded today.")
            return
            
        report = f"📊 *Daily Report*\n\nTotal work time today: *{total_minutes:.1f} minutes*\n\n"
        if project_breakdown:
            report += "*Project Breakdown:*\n"
            for project_name, minutes in project_breakdown:
                percentage = (minutes / total_minutes) * 100 if total_minutes > 0 else 0
                report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
        
        await update.message.reply_text(report, parse_mode='Markdown')
        log.debug(f"Sent daily report to user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB error generating daily report for user {user_id}: {e}")
        await update.message.reply_text("Failed to generate daily report due to a database error.")
    except Exception as e:
        log.error(f"Error in report_daily for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred generating the report.")

async def report_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log.info(f"Generating weekly report for user {user_id}")
    try:
        total_minutes, daily_breakdown, project_breakdown = database.get_weekly_report(user_id)
        
        if total_minutes == 0:
            await update.message.reply_text("No work sessions recorded this week.")
            return
        
        report = f"📈 *Weekly Report*\n\nTotal work time this week: *{total_minutes:.1f} minutes*\n\n"
        if daily_breakdown:
            report += "*Daily Breakdown:*\n"
            for date, minutes in daily_breakdown:
                try: date_obj = datetime.fromisoformat(date).strftime("%a, %b %d")
                except: date_obj = date
                report += f"• {date_obj}: {minutes:.1f} min\n"
        
        if project_breakdown:
            report += "\n*Project Breakdown:*\n"
            for project_name, minutes in project_breakdown:
                percentage = (minutes / total_minutes) * 100 if total_minutes > 0 else 0
                report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
        
        await update.message.reply_text(report, parse_mode='Markdown')
        log.debug(f"Sent weekly report to user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB error generating weekly report for user {user_id}: {e}")
        await update.message.reply_text("Failed to generate weekly report due to a database error.")
    except Exception as e:
        log.error(f"Error in report_weekly for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred generating the report.")

async def report_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log.info(f"Generating monthly report for user {user_id}")
    try:
        total_minutes, project_breakdown = database.get_monthly_report(user_id)
        
        if total_minutes == 0:
            await update.message.reply_text("No work sessions recorded this month.")
            return
        
        current_month = datetime.now().strftime("%B %Y")
        report = f"📅 *Monthly Report: {current_month}*\n\nTotal work time this month: *{total_minutes:.1f} minutes* ({total_minutes/60:.1f} hours)\n\n"
        if project_breakdown:
            report += "*Project Breakdown:*\n"
            for project_name, minutes in project_breakdown:
                percentage = (minutes / total_minutes) * 100 if total_minutes > 0 else 0
                report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
        
        await update.message.reply_text(report, parse_mode='Markdown')
        log.debug(f"Sent monthly report to user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB error generating monthly report for user {user_id}: {e}")
        await update.message.reply_text("Failed to generate monthly report due to a database error.")
    except Exception as e:
        log.error(f"Error in report_monthly for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred generating the report.")

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
        "Project Management:\n"
        "  /create_project \"Project Name\" - Create a new project.\n"
        "  /list_projects - List and select projects (➡️ indicates current).\n"
        "  /select_project \"Project Name\" - Select a project by name.\n"
        "  /delete_project - Delete a project and its data.\n\n"
        "Task Management:\n"
        "  /create_task \"Task Name\" - Add task to the current project.\n"
        "  /list_tasks - List and select tasks in the current project (➡️ indicates current).\n"
        "  /select_task \"Task Name\" - Select a task by name.\n"
        "  /delete_task - Delete a task and its data.\n\n"
        "Timer Control:\n"
        "  /start_timer [minutes] - Start Pomodoro (default 25 min). E.g., /start_timer 45\n"
        "  /pause_timer - Pause the current timer.\n"
        "  /resume_timer - Resume the paused timer.\n"
        "  /stop_timer - Stop the timer early and log time.\n"
        "  (Breaks are offered after work sessions)\n\n"
        "Reporting:\n"
        "  /report - Get daily, weekly, or monthly work time reports.\n\n"
        "Other:\n"
        "  /help - Show this help message.\n"
        "  /start - Initialize or welcome message."
    )
    try:
        await update.message.reply_text(help_text)
    except Exception as e:
         log.error(f"Failed to send help message: {e}") 