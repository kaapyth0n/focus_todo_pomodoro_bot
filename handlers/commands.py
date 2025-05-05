from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, WebAppInfo, User
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters
from telegram.helpers import escape_markdown # Import escape_markdown
from telegram import constants # For ParseMode
import database
from datetime import datetime, timedelta
from config import timer_states, DOMAIN_URL, SUPPORTED_LANGUAGES
import logging
import sqlite3
from . import google_auth as google_auth_handlers # Import the module itself
from . import admin as admin_handlers # Import admin handlers
from database import STATUS_ACTIVE, STATUS_DONE # Import status constants
import math # For formatting time
from i18n_utils import _, get_language_name # Import the translation helper and name getter

log = logging.getLogger(__name__)

# --- Conversation Handler States ---
WAITING_PROJECT_NAME, WAITING_TASK_NAME = range(2)

# --- Dynamic Reply Keyboard Generation ---
def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Generates the main ReplyKeyboardMarkup with translated button labels."""
    keyboard = [
        [_ (user_id, 'button_start_work')],                     # Row 1
        [
            _(user_id, 'button_pause'), 
            _(user_id, 'button_resume'), 
            _(user_id, 'button_stop')
        ],                                                    # Row 2
        [_ (user_id, 'button_report'), _(user_id, 'button_break_5')],   # Row 3
        [
            _(user_id, 'button_list_projects'), 
            _(user_id, 'button_list_tasks')
        ]                                                     # Row 4
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message, adds user to database, and shows keyboard, notifies admin if new."""
    user = update.message.from_user
    user_id = user.id # Define user_id upfront for logging in exceptions
    is_new_user = False # Flag to track if user was added
    log.info(f"Received /start command from user {user_id} ('{user.username or user.first_name}')")
    try:
        existing_user = database.get_google_credentials(user_id) # Re-using this check temporarily
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
        current_proj = database.get_current_project(user_id)
        current_task = database.get_current_task(user_id)
        if current_proj:
             proj_name = database.get_project_name(current_proj)
             if not proj_name:
                 log.warning(f"User {user_id}'s current project {current_proj} not found. Clearing.")
                 database.clear_current_project(user_id)
             elif current_task:
                 task_name = database.get_task_name(current_task)
                 if not task_name:
                     log.warning(f"User {user_id}'s current task {current_task} not found. Clearing.")
                     database.clear_current_task(user_id)
        else:
            database.clear_current_project(user_id) # Clears task too

        # Send welcome message with the dynamically generated, translated keyboard
        welcome_message = _(user_id, 'welcome')
        reply_markup = get_main_keyboard(user_id) # Generate translated keyboard
        await update.message.reply_text(
            welcome_message, 
            reply_markup=reply_markup
        )
    except sqlite3.Error as e:
        log.error(f"DB Error in start for user {user_id}: {e}")
        await update.message.reply_text(_(user_id, 'error_db')) # Example: Use a generic DB error key
    except Exception as e:
        log.error(f"Error in start command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'error_unexpected')) # Example: Use a generic unexpected error key

# --- Refactored Project Creation Logic ---
async def _create_project_logic(user: User, context: ContextTypes.DEFAULT_TYPE, project_name: str) -> int | None:
    """Handles the actual creation of a project, including checks and notifications."""
    user_id = user.id
    try:
        existing_projects = database.get_projects(user_id)
        for _, existing_name in existing_projects:
            if existing_name.lower() == project_name.lower():
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=_(user_id, 'project_already_exists', existing_name=existing_name)
                )
                return None # Indicate failure (duplicate)
                
        added_id = database.add_project(user_id, project_name)
        if added_id:
            # Set the newly created project as the current/active project
            database.set_current_project(user_id, added_id)
            log.info(f"User {user_id} created project '{project_name}' (ID: {added_id}) and set as current")
            # Notify admin
            await admin_handlers.send_admin_notification(
                context, 
                f"Project created by {user.first_name} ({user_id}): '{project_name}' (ID: {added_id})"
            )
            return added_id # Indicate success
        else:
            log.warning(f"Failed DB call to create project '{project_name}' for user {user_id}")
            await context.bot.send_message(chat_id=user_id, text=_(user_id, 'error_db'))
            return None # Indicate failure (DB error)
            
    except sqlite3.Error as e:
        log.error(f"DB Error in _create_project_logic for user {user_id}: {e}")
        await context.bot.send_message(chat_id=user_id, text=_(user_id, 'error_accessing_data'))
        return None # Indicate failure (exception)
    except Exception as e:
        log.error(f"Error in _create_project_logic for user {user_id}: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=_(user_id, 'error_unexpected'))
        return None # Indicate failure (exception)

# --- Project Management Commands ---
async def create_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | str:
    """Starts the project creation conversation or creates directly if name provided."""
    user = update.message.from_user
    user_id = user.id
    project_name = ' '.join(context.args).strip()
    log.debug(f"User {user_id} using /create_project. Args: {context.args}")

    if project_name:
        added_id = await _create_project_logic(user, context, project_name)
        if added_id:
            await update.message.reply_text(
                _(user_id, 'project_created_selected', project_name=project_name)
            )
        # If added_id is None, _create_project_logic already sent an error message.
        return ConversationHandler.END
    else:
        await update.message.reply_text(_(user_id, 'project_create_prompt'))
        return WAITING_PROJECT_NAME

async def receive_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the project name from the user during the conversation."""
    user = update.message.from_user
    user_id = user.id
    project_name = update.message.text.strip()
    log.debug(f"Received potential project name '{project_name}' from user {user_id} in conversation.")

    if not project_name or len(project_name) > 100: # Basic validation
        await update.message.reply_text(_(user_id, 'project_create_invalid_name'))
        return WAITING_PROJECT_NAME # Stay in the same state

    added_id = await _create_project_logic(user, context, project_name)
    if added_id:
        await update.message.reply_text(
             _(user_id, 'project_created_selected', project_name=project_name)
        )
    # If added_id is None, _create_project_logic already sent an error message.
    return ConversationHandler.END

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
                await update.message.reply_text(_(user_id, 'project_selected', project_name=proj_name_db))
                project_found = True
                break
                
        if not project_found:
            await update.message.reply_text(_(user_id, 'project_not_found'))
            
    except sqlite3.Error as e:
        log.error(f"DB Error in select_project for user {user_id}: {e}")
        await update.message.reply_text(_(user_id, 'error_accessing_data'))
    except Exception as e:
        log.error(f"Error in select_project command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'error_unexpected'))

async def list_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists user's active projects with buttons for selection and marking done."""
    user_id = update.effective_user.id
    log.debug(f"User {user_id} requested active project list.")
    try:
        # Fetch only active projects
        projects = database.get_projects(user_id, status=STATUS_ACTIVE)
        
        keyboard = []
        list_title = _(user_id, 'project_list_title') # Translate title

        if not projects:
            keyboard.append([InlineKeyboardButton(_(user_id, 'project_none_found'), callback_data="noop_create_project")]) 
        else:
            current_project_id = database.get_current_project(user_id)
            for project_id, project_name in projects:
                button_text = project_name
                if project_id == current_project_id:
                    button_text = f"➡️ {project_name}" # Indicate current project
                # Row: [Select Button, Mark Done Button]
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data=f"select_project:{project_id}"),
                    InlineKeyboardButton(_(user_id, 'button_mark_project_done'), callback_data=f"mark_project_done:{project_id}")
                ])
                
        # Add button to view archived projects
        keyboard.append([InlineKeyboardButton(_(user_id, 'button_view_archived_projects'), callback_data="list_projects_done")])
        # Add button to create a new project
        keyboard.append([InlineKeyboardButton(_(user_id, 'button_create_new_project'), callback_data="create_new_project")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Use edit_message_text if called from a callback, otherwise reply_text
        if update.callback_query:
            await update.callback_query.edit_message_text(list_title, reply_markup=reply_markup)
        else:
            await update.message.reply_text(list_title, reply_markup=reply_markup)
        
        log.debug(f"Displayed active project list for user {user_id}")
    except Exception as e:
        log.error(f"Error listing/editing projects for user {user_id}: {e}", exc_info=True)
        error_msg = _(user_id, 'error_unexpected') # Generic error
        if update.callback_query:
             try: await update.callback_query.message.reply_text(error_msg)
             except: pass
        else: 
             await update.message.reply_text(error_msg)

async def delete_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates the project deletion process."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} initiated project deletion process.")
    try:
        projects = database.get_projects(user_id)
        if not projects:
            await update.message.reply_text(_(user_id, 'delete_project_none'))
            return
            
        keyboard = []
        for project_id, project_name in projects:
            keyboard.append([InlineKeyboardButton(f"🗑️ {project_name}", callback_data=f"confirm_delete_project:{project_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(_(user_id, 'delete_project_prompt'), reply_markup=reply_markup)
        
        log.debug(f"Displayed project deletion confirmation list for user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB Error in delete_project_command for user {user_id}: {e}")
        await update.message.reply_text(_(user_id, 'error_accessing_data'))
    except Exception as e:
        log.error(f"Error in delete_project_command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'error_unexpected'))

# --- Refactored Task Creation Logic ---
async def _create_task_logic(user: User, context: ContextTypes.DEFAULT_TYPE, task_name: str) -> int | None:
    """Handles the actual creation of a task, including checks and notifications."""
    user_id = user.id
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            # This check might be redundant if create_task handles it, but good failsafe
            await context.bot.send_message(chat_id=user_id, text=_(user_id, 'task_create_no_project'))
            return None 
            
        existing_tasks = database.get_tasks(current_project_id)
        for _, existing_name in existing_tasks:
            if existing_name.lower() == task_name.lower():
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=_(user_id, 'task_already_exists', existing_name=existing_name)
                )
                return None # Indicate failure (duplicate)
                
        project_name = database.get_project_name(current_project_id) # Get project name for logging/notification
        added_id = database.add_task(current_project_id, task_name)
        if added_id and project_name:
            # Set the newly created task as the current/active task
            database.set_current_task(user_id, added_id)
            log.info(f"User {user_id} created task '{task_name}' (ID: {added_id}) in project {current_project_id} ('{project_name}') and set as current")
            # Notify admin
            await admin_handlers.send_admin_notification(
                context, 
                f"Task created by {user.first_name} ({user_id}) in project '{project_name}': '{task_name}' (ID: {added_id})"
            )
            return added_id # Indicate success
        elif added_id: # Project name might be missing, but task added
            # Set task as current even if project name is missing
            database.set_current_task(user_id, added_id)
            log.warning(f"Task '{task_name}' created for user {user_id} in project {current_project_id}, but project name missing. Set as current task.")
            return added_id
        else:
            log.warning(f"Failed DB call to create task '{task_name}' for user {user_id} in project {current_project_id}")
            await context.bot.send_message(chat_id=user_id, text=_(user_id, 'error_db'))
            return None # Indicate failure (DB error)
            
    except sqlite3.Error as e:
        log.error(f"DB Error in _create_task_logic for user {user_id}: {e}")
        await context.bot.send_message(chat_id=user_id, text=_(user_id, 'error_accessing_data'))
        return None # Indicate failure (exception)
    except Exception as e:
        log.error(f"Error in _create_task_logic for user {user_id}: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=_(user_id, 'error_unexpected'))
        return None # Indicate failure (exception)

# --- Task Management Commands ---
async def create_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | str:
    """Starts the task creation conversation or creates directly if name provided."""
    user = update.message.from_user
    user_id = user.id
    task_name = ' '.join(context.args).strip()
    log.debug(f"User {user_id} using /create_task. Args: {context.args}")

    # Check if project is selected BEFORE starting conversation or direct creation
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            await update.message.reply_text(_(user_id, 'task_create_no_project'))
            return ConversationHandler.END # End immediately if no project selected
    except Exception as e:
        log.error(f"Error checking current project for user {user_id} in create_task: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'error_unexpected'))
        return ConversationHandler.END

    project_name = database.get_project_name(current_project_id) or "Current Project" # Fallback for prompt

    if task_name:
        added_id = await _create_task_logic(user, context, task_name)
        if added_id:
            await update.message.reply_text(
                _(user_id, 'task_created_selected', task_name=task_name, project_name=project_name)
            )
        # If added_id is None, _create_task_logic already sent an error message.
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            _(user_id, 'task_create_prompt', project_name=project_name)
        )
        return WAITING_TASK_NAME

async def receive_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the task name from the user during the conversation."""
    user = update.message.from_user
    user_id = user.id
    task_name = update.message.text.strip()
    log.debug(f"Received potential task name '{task_name}' from user {user_id} in conversation.")

    if not task_name or len(task_name) > 100: # Basic validation
        await update.message.reply_text(_(user_id, 'task_create_invalid_name'))
        return WAITING_TASK_NAME # Stay in the same state

    added_id = await _create_task_logic(user, context, task_name)
    if added_id:
        project_name = database.get_project_name(database.get_current_project(user_id)) or _(user_id, 'text_the_project') # Fallback text
        await update.message.reply_text(
            _(user_id, 'task_created_selected', task_name=task_name, project_name=project_name)
        )
    # If added_id is None, _create_task_logic already sent an error message.
    return ConversationHandler.END

# --- Generic Cancel Handler for Conversations ---
async def cancel_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current creation conversation."""
    user_id = update.message.from_user.id
    log.info(f"User {user_id} cancelled the creation process.")
    await update.message.reply_text(_(user_id, 'creation_cancelled'))
    return ConversationHandler.END

async def select_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Selects a task by name or lists tasks if no name is given."""
    user_id = update.message.from_user.id
    task_name = ' '.join(context.args)
    log.debug(f"User {user_id} attempting to select task '{task_name}' (or list)")
    
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            await update.message.reply_text(_(user_id, 'task_create_no_project'))
            return
            
        project_name = database.get_project_name(current_project_id) or _(user_id, 'text_selected_project') # Fallback

        if not task_name:
            await list_tasks(update, context)
            return
            
        tasks = database.get_tasks(current_project_id)
        task_found = False
        for task_id, t_name_db in tasks:
            if t_name_db.lower() == task_name.lower(): 
                database.set_current_task(user_id, task_id)
                log.info(f"User {user_id} selected task {task_id} ('{t_name_db}') via command.")
                await update.message.reply_text(
                    _(user_id, 'task_selected', task_name=t_name_db, project_name=project_name)
                )
                task_found = True
                break
                
        if not task_found:
            await update.message.reply_text(
                _(user_id, 'task_not_found', project_name=project_name)
            )
            
    except sqlite3.Error as e:
        log.error(f"DB Error in select_task for user {user_id}: {e}")
        await update.message.reply_text(_(user_id, 'error_accessing_data'))
    except Exception as e:
        log.error(f"Error in select_task command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'error_unexpected'))

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists active tasks in the current project with selection/done buttons."""
    user_id = update.effective_user.id
    log.debug(f"User {user_id} requested active task list.")
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
             message_text = _(user_id, 'task_create_no_project') 
             if update.callback_query: await update.callback_query.edit_message_text(text=message_text) 
             else: await update.message.reply_text(text=message_text)
             return
            
        project_name = database.get_project_name(current_project_id) or _(user_id, 'text_current_project') # Fallback
        # Fetch only active tasks for the current project
        tasks = database.get_tasks(current_project_id, status=STATUS_ACTIVE)
        
        keyboard = []
        list_title = _(user_id, 'task_list_title', project_name=project_name)
        
        if not tasks:
            keyboard.append([InlineKeyboardButton(
                _(user_id, 'task_none_found_in_project', project_name=project_name), 
                callback_data="noop_create_task"
            )]) 
        else:
            current_task_id = database.get_current_task(user_id)
            for task_id, task_name in tasks:
                button_text = task_name
                if task_id == current_task_id:
                     button_text = f"➡️ {task_name}"
                # Row: [Select Button, Mark Done Button]
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data=f"select_task:{task_id}"),
                    InlineKeyboardButton(_(user_id, 'button_mark_task_done'), callback_data=f"mark_task_done:{task_id}")
                ])
                
        # Add button to view archived tasks for this project
        keyboard.append([InlineKeyboardButton(_(user_id, 'button_view_archived_tasks'), callback_data="list_tasks_done")])
        # Add button to create a new task in the current project
        keyboard.append([InlineKeyboardButton(_(user_id, 'button_create_new_task'), callback_data="create_new_task")])
        # Add button to go back to project list
        keyboard.append([InlineKeyboardButton(_(user_id, 'button_back_to_projects'), callback_data="list_projects_active")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.edit_message_text(text=list_title, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text=list_title, reply_markup=reply_markup)
        
        log.debug(f"Displayed active task list for user {user_id}")
    except Exception as e:
        log.error(f"Error listing/editing tasks for user {user_id}: {e}", exc_info=True)
        error_msg = _(user_id, 'error_unexpected') # Generic error
        if update.callback_query:
             try: await update.callback_query.message.reply_text(error_msg) 
             except: pass
        else: 
             await update.message.reply_text(error_msg)

async def delete_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates the task deletion process."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} initiated task deletion process.")
    try:
        current_project_id = database.get_current_project(user_id) 
        if not current_project_id:
            await update.message.reply_text(_(user_id, 'delete_task_no_project'))
            return
            
        tasks = database.get_tasks(current_project_id)
        project_name = database.get_project_name(current_project_id) or _(user_id, 'text_current_project') # Fallback
        
        if not tasks:
            await update.message.reply_text(_(user_id, 'delete_task_none', project_name=project_name))
            return
            
        keyboard = []
        for task_id, task_name in tasks:
            keyboard.append([InlineKeyboardButton(f"🗑️ {task_name}", callback_data=f"confirm_delete_task:{task_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            _(user_id, 'delete_task_prompt', project_name=project_name), 
            reply_markup=reply_markup
        )
        
        log.debug(f"Displayed task deletion confirmation list for user {user_id}")
    except sqlite3.Error as e:
        log.error(f"DB Error in delete_task_command for user {user_id}: {e}")
        await update.message.reply_text(_(user_id, 'error_accessing_data'))
    except Exception as e:
        log.error(f"Error in delete_task_command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'error_unexpected'))

# --- Helper Function for Starting Timers ---
async def _start_timer_internal(context: ContextTypes.DEFAULT_TYPE, user_id: int, duration_minutes: int, session_type: str, project_name: str = None, task_name: str = None):
    """Internal helper to start a timer job (work or break)."""
    if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
        log.warning(f"Attempted to start timer for user {user_id} but another timer is active.")
        try:
             await context.bot.send_message(chat_id=user_id, text=_(user_id, 'timer_already_active'))
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
            await context.bot.send_message(chat_id=user_id, text=_(user_id, 'timer_schedule_failed'))
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
    keyboard = [[InlineKeyboardButton(_(user_id, 'timer_view_button'), web_app=WebAppInfo(url=timer_url))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = ""
    if session_type == 'work' and project_name and task_name:
        message = _(user_id, 'timer_work_started', task_name=task_name, project_name=project_name, duration_minutes=duration_minutes)
    elif session_type == 'work':
         message = _(user_id, 'timer_work_started_no_project', duration_minutes=duration_minutes)
    elif session_type == 'break':
        message = _(user_id, 'timer_break_started', duration_minutes=duration_minutes)

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
            await update.message.reply_text(_(user_id, 'timer_already_active'))
            return
            
        project_id = database.get_current_project(user_id)
        task_id = database.get_current_task(user_id)
        if not project_id or not task_id:
            await update.message.reply_text(_(user_id, 'timer_needs_project_task'))
            return
            
        # --- Check Project and Task Status --- 
        project_status = database.get_project_status(project_id)
        task_status = database.get_task_status(task_id)
        
        if project_status != database.STATUS_ACTIVE:
            log.warning(f"User {user_id} tried to start timer on inactive/done project {project_id}.")
            await update.message.reply_text(_(user_id, 'timer_project_archived'))
            database.clear_current_project(user_id) # Clear selection if inactive
            return
            
        if task_status != database.STATUS_ACTIVE:
            log.warning(f"User {user_id} tried to start timer on inactive/done task {task_id}.")
            await update.message.reply_text(_(user_id, 'timer_task_archived'))
            database.clear_current_task(user_id) # Clear selection if inactive
            return
        # --- End Status Check --- 
            
        project_name = database.get_project_name(project_id)
        task_name = database.get_task_name(task_id)
        
        if not project_name or not task_name:
            # This check might be redundant now with status check, but keep as fallback
            await update.message.reply_text(_(user_id, 'timer_project_task_missing'))
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
                    await update.message.reply_text(_(user_id, 'timer_invalid_duration'))
                    return
            except (ValueError, IndexError):
                await update.message.reply_text(_(user_id, 'timer_invalid_duration_fallback', default_duration=25))
        
        await _start_timer_internal(context, user_id, duration_minutes, 'work', project_name, task_name)

    except sqlite3.Error as e:
        log.error(f"DB Error in start_timer for user {user_id}: {e}")
        await update.message.reply_text(_(user_id, 'error_accessing_data'))
    except Exception as e:
        log.error(f"Error in start_timer command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'timer_error_starting'))

async def start_break_timer(context: ContextTypes.DEFAULT_TYPE, user_id: int, duration_minutes: int):
    log.debug(f"Starting break timer ({duration_minutes} min) for user {user_id}")
    try:
        await _start_timer_internal(context, user_id, duration_minutes, 'break')
    except Exception as e:
        log.error(f"Error in start_break_timer for user {user_id}: {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=user_id, text=_(user_id, 'timer_error_starting_break'))
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
                    await context.bot.send_message(
                        chat_id=user_id, 
                        text=_(user_id, 'timer_finished_work_unselected', duration_minutes=duration_minutes)
                    )
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
                success_message = _(user_id, 'timer_finished_work_success', 
                                    project_name=project_name, 
                                    task_name=task_name, 
                                    duration_minutes=duration_minutes)
                keyboard = [
                    [InlineKeyboardButton(_(user_id, 'timer_button_break_5'), callback_data="start_break:5")],
                    [InlineKeyboardButton(_(user_id, 'timer_button_break_15'), callback_data="start_break:15")] 
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
                 success_message = _(user_id, 'timer_finished_break_success', duration_minutes=duration_minutes)
                 await context.bot.send_message(chat_id=user_id, text=success_message)

            log.info(f"Session type '{session_type}' completed and logged for user {user_id}.")
            del timer_states[user_id] # Cleanup state after processing
                
        else:
            log.warning(f"Timer finished job executed for user {user_id}, but state was missing or job outdated.")

    except Exception as e: # Broader catch for unexpected errors during processing
        log.error(f"Unexpected error processing finished timer job for user {user_id}: {e}", exc_info=True)
        try: await context.bot.send_message(chat_id=user_id, text=_(user_id, 'timer_error_finishing'))
        except: pass
        # Ensure state cleanup even on error
        if user_id in timer_states: del timer_states[user_id]

async def pause_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log.debug(f"/pause_timer received from user {user_id}")
    try:
        state_data = timer_states.get(user_id)
        timer_type = state_data.get('session_type', 'timer') if state_data else 'timer'
        if not state_data or state_data['state'] != 'running':
            await update.message.reply_text(_(user_id, 'timer_not_running', timer_type=timer_type))
            return
            
        current_time = datetime.now()
        start_time = state_data.get('start_time')
        if not start_time:
             log.error(f"Missing start_time in timer state for user {user_id} during pause.")
             await update.message.reply_text(_(user_id, 'timer_state_inconsistent'))
             return

        time_worked = (current_time - start_time).total_seconds() / 60
        state_data['accumulated_time'] += time_worked
        state_data['state'] = 'paused'
        
        job = state_data.get('job')
        if job:
            job.schedule_removal()
            state_data['job'] = None 
            log.debug(f"Removed scheduled job for paused timer (user {user_id}).")
            
        await update.message.reply_text(
            _(user_id, 'timer_paused', 
              timer_type=timer_type.capitalize(), 
              accumulated_time=state_data.get("accumulated_time", 0))
        )
        log.info(f"Paused {timer_type} for user {user_id}.")

    except KeyError as e:
        log.error(f"KeyError accessing timer_states for user {user_id} in pause_timer: {e}")
        await update.message.reply_text(_(user_id, 'timer_state_inconsistent'))
    except Exception as e:
        log.error(f"Error in pause_timer command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'timer_error_pausing'))

async def resume_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log.debug(f"/resume_timer received from user {user_id}")
    try:
        state_data = timer_states.get(user_id)
        if not state_data or state_data['state'] != 'paused':
            await update.message.reply_text(_(user_id, 'timer_not_paused'))
            return
            
        duration_minutes = state_data['duration']
        accumulated_time = state_data['accumulated_time']
        session_type = state_data['session_type']
        initial_start_time = state_data['initial_start_time']
        remaining_time_minutes = duration_minutes - accumulated_time
        
        if remaining_time_minutes <= 0:
            log.info(f"Attempted to resume completed timer for user {user_id}. Cleaning up.")
            await update.message.reply_text(_(user_id, 'timer_already_completed'))
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
        
        await update.message.reply_text(
            _(user_id, 'timer_resumed', 
              timer_type=session_type.capitalize(), 
              remaining_time=remaining_time_minutes)
        )
        log.info(f"Resumed {session_type.capitalize()} timer for user {user_id}.")

    except KeyError as e:
        log.error(f"KeyError accessing timer_states for user {user_id} in resume_timer: {e}")
        await update.message.reply_text(_(user_id, 'timer_state_inconsistent'))
    except Exception as e:
        log.error(f"Error in resume_timer command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'timer_error_resuming'))

async def stop_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log.debug(f"/stop_timer received from user {user_id}")
    state_data = timer_states.get(user_id)
    
    if not state_data or state_data['state'] == 'stopped':
        await update.message.reply_text(_(user_id, 'timer_no_timer_active'))
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
        
        is_completed = 1 if final_accumulated_minutes >= (duration_minutes_target - 0.01) else 0 
        
        project_id, task_id, project_name, task_name = None, None, None, None
        message = ""

        if session_type == 'work':
            project_id = database.get_current_project(user_id)
            task_id = database.get_current_task(user_id)
            if project_id and task_id:
                project_name = database.get_project_name(project_id)
                task_name = database.get_task_name(task_id)
                if project_name and task_name:
                     message = _(user_id, 'timer_stopped_work', 
                                   project_name=project_name, task_name=task_name, 
                                   accumulated_time=final_accumulated_minutes, target_duration=duration_minutes_target)
                else: 
                    message = _(user_id, 'timer_stopped_work_missing', 
                                   accumulated_time=final_accumulated_minutes, target_duration=duration_minutes_target)
            else:
                message = _(user_id, 'timer_stopped_work_unselected', 
                               accumulated_time=final_accumulated_minutes, target_duration=duration_minutes_target)
                project_id, task_id = None, None # Ensure null if not properly selected
        else: 
            message = _(user_id, 'timer_stopped_break', 
                           accumulated_time=final_accumulated_minutes, target_duration=duration_minutes_target)

        # Add session to DB
        session_added_id = database.add_pomodoro_session(
            user_id=user_id, project_id=project_id, task_id=task_id,
            start_time=initial_start_time, duration_minutes=final_accumulated_minutes,
            session_type=session_type, completed=is_completed
        )
            
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
         await update.message.reply_text(_(user_id, 'timer_error_saving_session'))
    except KeyError as e:
        log.error(f"KeyError accessing timer_states for user {user_id} in stop_timer: {e}")
        await update.message.reply_text(_(user_id, 'timer_state_inconsistent'))
    except Exception as e:
        log.error(f"Error in stop_timer command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'timer_error_stopping'))
    finally:
        if user_id in timer_states:
            del timer_states[user_id]
            log.debug(f"Cleaned timer state for user {user_id}.")

# --- Helper Function for Report Titles --- 
def _get_report_title(user_id: int, report_type: str, report_date_str: str | None, offset: int) -> str:
    """Generates a user-friendly title with MarkdownV2 escaped content."""
    
    # Translate report type name if needed (e.g., "Daily" -> "Täglich")
    # For simplicity, we'll use the English type for the key but translate the output.
    title_base = _(user_id, 'report_title', report_type=report_type.capitalize())

    if report_date_str is None:
        return escape_markdown(_(user_id, 'report_title_error', report_type=report_type.capitalize()), version=2)
    
    try:
        report_date = datetime.fromisoformat(report_date_str)
        status_str = ""
        if report_type == 'daily':
            if offset == 0: status_str = _(user_id, 'report_date_today')
            elif offset == -1: status_str = _(user_id, 'report_date_yesterday')
            else: status_str = report_date.strftime('%a, %b %d, %Y') # Keep format universal for now
        elif report_type == 'weekly':
            if offset == 0: status_str = _(user_id, 'report_week_this')
            elif offset == -1: status_str = _(user_id, 'report_week_last')
            else:
                week_end_date = report_date + timedelta(days=6)
                # Format dates universally, translate the range pattern
                start_f = report_date.strftime('%b %d') 
                end_f = week_end_date.strftime('%b %d, %Y')
                status_str = _(user_id, 'report_week_range', start_date=start_f, end_date=end_f)
        elif report_type == 'monthly':
            # Format month/year universally, translate the pattern
            month_name = report_date.strftime('%B') # Consider locale-aware month names later if needed
            year = report_date.strftime('%Y')
            status_str = _(user_id, 'report_month_format', month_name=month_name, year=year)
        
        # Escape the generated status string and the base title
        escaped_status = escape_markdown(status_str, version=2)
        escaped_title_base = escape_markdown(title_base, version=2)
        # Combine, adding escaped parentheses
        return f"{escaped_title_base} \\({escaped_status}\\)" 
    except ValueError:
         return escape_markdown(_(user_id, 'report_title_date_error', report_type=report_type.capitalize()), version=2)
    
    # Fallback (shouldn't be reached often)
    return escape_markdown(title_base, version=2)

# --- Report Commands ---

async def report_daily(update: Update, context: ContextTypes.DEFAULT_TYPE, offset: int = 0):
    """Sends the daily report with navigation."""
    user_id = update.effective_user.id
    log.info(f"Generating daily report for user {user_id}, offset {offset}")
    report_date, total_minutes, detailed_breakdown = database.get_daily_report(user_id, offset=offset)
    
    # Get the correctly pre-escaped title from the helper
    title = _get_report_title(user_id, 'daily', report_date, offset) 
    report = f"📊 {title}\n\n"

    if report_date is None:
        report += escape_markdown(_(user_id, 'report_data_error'), version=2)
        # Send immediately if data error
        if update.callback_query:
            await update.callback_query.edit_message_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
        else:
            await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
        return
        
    if total_minutes == 0:
        report += escape_markdown(_(user_id, 'report_no_sessions_day'), version=2)
    else:
        total_mins_str = escape_markdown(str(round(total_minutes, 1)), version=2)
        # Use translated key, manually escape the '*' around the value
        report += _(user_id, 'report_total_time_minutes', total_minutes=f'*{total_mins_str}*') + "\n\n"
        
        if detailed_breakdown:
            report += escape_markdown(_(user_id, 'report_project_task_breakdown'), version=2) + "\n"
            for project_data in detailed_breakdown:
                proj_name = escape_markdown(project_data['project_name'], version=2)
                proj_mins_str = escape_markdown(str(round(project_data['project_minutes'], 1)), version=2)
                # Use translated key, manually escape '*' around project name
                report_line = _(user_id, 'report_project_line', project_name=f'*{proj_name}*', minutes=proj_mins_str)
                try:
                    percentage = (project_data['project_minutes'] / total_minutes) * 100 if total_minutes > 0 else 0
                    percentage_str = escape_markdown(f"{percentage:.1f}", version=2)
                    # Manually append escaped percentage and parentheses
                    report_line += f" ({percentage_str}%)" 
                except ZeroDivisionError:
                    pass 
                report += report_line + "\n"
                for task_data in project_data['tasks']:
                    task_name = escape_markdown(task_data['task_name'], version=2)
                    task_mins_str = escape_markdown(str(round(task_data['task_minutes'], 1)), version=2)
                    # Use translated key, manually escape the leading '-' for list item
                    report += _(user_id, 'report_task_line', task_name=task_name, minutes=task_mins_str).replace("-", "\\-") + "\n"
        else:
            report += escape_markdown(_(user_id, 'report_no_project_task_data'), version=2)

    # Navigation Buttons
    prev_offset = offset - 1
    next_offset = offset + 1
    keyboard = [[ # Use translated button text
        InlineKeyboardButton(_(user_id, 'report_button_prev_day'), callback_data=f"report_nav:daily:{prev_offset}"),
        InlineKeyboardButton(_(user_id, 'report_button_next_day'), callback_data=f"report_nav:daily:{next_offset}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send/edit message logic (with MarkdownV2 and fallback)
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        else:
            await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
    except Exception as e:
        log.error(f"Failed to send/edit daily report for user {user_id} with MarkdownV2: {e}")
        # Attempt fallback without Markdown
        fallback_report = report # Placeholder for unescaping if needed
        # A simple unescaper (might need refinement)
        fallback_report = fallback_report.replace("\\*", "*").replace("\\(", "(").replace("\\)", ")").replace("\\-", "-") 
        if not update.callback_query: 
             try: await update.effective_message.reply_text(fallback_report, reply_markup=reply_markup) 
             except Exception as fb_err: log.error(f"Fallback report sending failed: {fb_err}")

async def report_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE, offset: int = 0):
    """Sends the weekly report with navigation."""
    user_id = update.effective_user.id
    log.info(f"Generating weekly report for user {user_id}, offset {offset}")
    week_start_date, total_minutes, daily_breakdown, detailed_project_task_breakdown = database.get_weekly_report(user_id, offset=offset)
    
    # Get the correctly pre-escaped title from the helper
    title = _get_report_title(user_id, 'weekly', week_start_date, offset)
    report = f"📈 {title}\n\n"

    if week_start_date is None:
        report += escape_markdown(_(user_id, 'report_data_error'), version=2)
        if update.callback_query:
            await update.callback_query.edit_message_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
        else:
            await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    if total_minutes == 0:
        report += escape_markdown(_(user_id, 'report_no_sessions_week'), version=2)
    else:
        total_mins_str = escape_markdown(str(round(total_minutes, 1)), version=2)
        # Use translated key, manually escape '*'
        report += _(user_id, 'report_total_time_week', total_minutes=f'*{total_mins_str}*') + "\n\n"
        
        if daily_breakdown:
            report += escape_markdown(_(user_id, 'report_daily_breakdown'), version=2) + "\n"
            for date_str, minutes in daily_breakdown:
                minutes_str = escape_markdown(str(round(minutes, 1)), version=2)
                try:
                    # Format date universally, translate the line pattern
                    date_obj_str = escape_markdown(datetime.fromisoformat(date_str).strftime("%a, %b %d"), version=2)
                    report += _(user_id, 'report_daily_line', date=date_obj_str, minutes=minutes_str) + "\n"
                except (ValueError, TypeError):
                    report += _(user_id, 'report_daily_line', date=escape_markdown(date_str, version=2), minutes=minutes_str) + "\n"
            report += "\n"
        if detailed_project_task_breakdown:
            report += escape_markdown(_(user_id, 'report_project_task_breakdown'), version=2) + "\n"
            for project_data in detailed_project_task_breakdown:
                proj_name = escape_markdown(project_data['project_name'], version=2)
                proj_mins_str = escape_markdown(str(round(project_data['project_minutes'], 1)), version=2)
                # Use translated key, manually escape '*'
                report_line = _(user_id, 'report_project_line', project_name=f'*{proj_name}*', minutes=proj_mins_str)
                try:
                    percentage = (project_data['project_minutes'] / total_minutes) * 100 if total_minutes > 0 else 0
                    percentage_str = escape_markdown(f"{percentage:.1f}", version=2)
                    # Manually append escaped percentage and parentheses
                    report_line += f" ({percentage_str}%)"
                except ZeroDivisionError:
                    pass
                report += report_line + "\n"
                for task_data in project_data['tasks']:
                    task_name = escape_markdown(task_data['task_name'], version=2)
                    task_mins_str = escape_markdown(str(round(task_data['task_minutes'], 1)), version=2)
                    # Use translated key, manually escape leading '-'
                    report += _(user_id, 'report_task_line', task_name=task_name, minutes=task_mins_str).replace("-", "\\-") + "\n"
        else:
            report += escape_markdown(_(user_id, 'report_no_project_task_data'), version=2)

    # Navigation Buttons
    prev_offset = offset - 1
    next_offset = offset + 1
    keyboard = [[ # Use translated button text
        InlineKeyboardButton(_(user_id, 'report_button_prev_week'), callback_data=f"report_nav:weekly:{prev_offset}"),
        InlineKeyboardButton(_(user_id, 'report_button_next_week'), callback_data=f"report_nav:weekly:{next_offset}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send/edit message logic (with MarkdownV2 and fallback)
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        else:
            await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
    except Exception as e:
        log.error(f"Failed to send/edit weekly report for user {user_id} with MarkdownV2: {e}")
        # Attempt fallback without Markdown
        fallback_report = report # Placeholder for unescaping if needed
        fallback_report = fallback_report.replace("\\*", "*").replace("\\(", "(").replace("\\)", ")").replace("\\-", "-") 
        if not update.callback_query: 
             try: await update.effective_message.reply_text(fallback_report, reply_markup=reply_markup) 
             except Exception as fb_err: log.error(f"Fallback report sending failed: {fb_err}")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Initial call to report_command (no args or specific type) shows buttons
    user_id = update.effective_user.id
    log.info(f"/report command received from user {user_id} with args: {context.args}")
    try:
        if not context.args or len(context.args) == 0:
            keyboard = [ 
                # Change callback data to include offset 0 for initial view
                [InlineKeyboardButton(_(user_id, 'report_button_daily'), callback_data="report_nav:daily:0")],
                [InlineKeyboardButton(_(user_id, 'report_button_weekly'), callback_data="report_nav:weekly:0")],
                [InlineKeyboardButton(_(user_id, 'report_button_monthly'), callback_data="report_nav:monthly:0")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(_(user_id, 'report_select_prompt'), reply_markup=reply_markup)
            return
        
        # Handling direct calls like /report daily (less common now with buttons)
        report_type = context.args[0].lower()
        offset = 0 # Default to current period if called directly
        if report_type == "daily": await report_daily(update, context, offset=offset)
        elif report_type == "weekly": await report_weekly(update, context, offset=offset)
        elif report_type == "monthly": await report_monthly(update, context, offset=offset)
        else: await update.message.reply_text(_(user_id, 'report_unknown_type'))
    except Exception as e:
        log.error(f"Error in report_command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'report_error_processing'))

async def report_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE, offset: int = 0):
    """Sends the monthly report with navigation."""
    user_id = update.effective_user.id
    log.info(f"Generating monthly report for user {user_id}, offset {offset}")
    month_start_date, total_minutes, detailed_breakdown = database.get_monthly_report(user_id, offset=offset)
    
    # Get the correctly pre-escaped title from the helper
    title = _get_report_title(user_id, 'monthly', month_start_date, offset)
    report = f"📅 {title}\n\n"

    if month_start_date is None:
        report += escape_markdown(_(user_id, 'report_data_error'), version=2)
        if update.callback_query:
            await update.callback_query.edit_message_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
        else:
            await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    if total_minutes == 0:
        report += escape_markdown(_(user_id, 'report_no_sessions_month'), version=2)
    else:
        total_mins_str = escape_markdown(str(round(total_minutes, 1)), version=2)
        total_hours_str = escape_markdown(str(round(total_minutes/60, 1)), version=2)
        # Use translated key, manually escape '*' around minutes and parentheses/hours
        report += _(user_id, 'report_total_time_month', 
                    total_minutes=f'*{total_mins_str}*', 
                    total_hours=f'\\({total_hours_str} hours\\)') + "\n\n"
        
        if detailed_breakdown:
            report += escape_markdown(_(user_id, 'report_project_task_breakdown'), version=2) + "\n"
            for project_data in detailed_breakdown:
                proj_name = escape_markdown(project_data['project_name'], version=2)
                proj_mins_str = escape_markdown(str(round(project_data['project_minutes'], 1)), version=2)
                # Use translated key, manually escape '*'
                report_line = _(user_id, 'report_project_line', project_name=f'*{proj_name}*', minutes=proj_mins_str)
                try:
                    percentage = (project_data['project_minutes'] / total_minutes) * 100 if total_minutes > 0 else 0
                    percentage_str = escape_markdown(f"{percentage:.1f}", version=2)
                    # Manually append escaped percentage and parentheses
                    report_line += f" \\({percentage_str}%\\)"
                except ZeroDivisionError:
                    pass
                report += report_line + "\n"
                for task_data in project_data['tasks']:
                    task_name = escape_markdown(task_data['task_name'], version=2)
                    task_mins_str = escape_markdown(str(round(task_data['task_minutes'], 1)), version=2)
                    # Use translated key, manually escape leading '-'
                    report += _(user_id, 'report_task_line', task_name=task_name, minutes=task_mins_str).replace("-", "\\-") + "\n"
        else:
            report += escape_markdown(_(user_id, 'report_no_project_task_data'), version=2)

    # Navigation Buttons
    prev_offset = offset - 1
    next_offset = offset + 1
    keyboard = [[ # Use translated button text
        InlineKeyboardButton(_(user_id, 'report_button_prev_month'), callback_data=f"report_nav:monthly:{prev_offset}"),
        InlineKeyboardButton(_(user_id, 'report_button_next_month'), callback_data=f"report_nav:monthly:{next_offset}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send/edit message logic (with MarkdownV2 and fallback)
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        else:
            await update.effective_message.reply_text(report, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
    except Exception as e:
        log.error(f"Failed to send/edit monthly report for user {user_id} with MarkdownV2: {e}")
        # Attempt fallback without Markdown
        fallback_report = report # Placeholder for unescaping if needed
        fallback_report = fallback_report.replace("\\*", "*").replace("\\(", "(").replace("\\)", ")").replace("\\-", "-") 
        if not update.callback_query: 
             try: await update.effective_message.reply_text(fallback_report, reply_markup=reply_markup) 
             except Exception as fb_err: log.error(f"Fallback report sending failed: {fb_err}")

# --- Help Command ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log.info(f"User {user_id} requested /help")
    help_text = _(user_id, 'help_text') # Get translated help text
    try:
        # Use MarkdownV2 for better formatting if desired, but requires escaping special chars
        # The YAML uses Markdown, so we should be okay here, but be cautious.
        await update.message.reply_text(help_text, parse_mode='Markdown') 
    except Exception as e:
         log.error(f"Failed to send help message: {e}")
         try: # Fallback: send plain text
             await update.message.reply_text(help_text)
         except Exception as fb_e:
             log.error(f"Failed to send fallback help message: {fb_e}")

# --- Reply Keyboard Button Handlers ---

# IMPORTANT: The Regex filters in bot.py MUST now match the *translated* button texts.
# This is complex. A better approach is needed, perhaps using callback_data or a different handler type.
# For now, we'll leave the handle_***_button functions, but they likely won't work correctly
# until the Regex matching in bot.py is updated or the handling strategy changes.

async def handle_start_work_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Start Work' button press by calling start_timer."""
    # This will likely FAIL now because the regex in bot.py expects English
    log.debug(f"User {update.message.from_user.id} pressed translated 'start work' button")
    await start_timer(update, context)

async def handle_pause_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Pause' button press by calling pause_timer."""
    log.debug(f"User {update.message.from_user.id} pressed translated 'pause' button")
    await pause_timer(update, context)

async def handle_resume_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Resume' button press by calling resume_timer."""
    log.debug(f"User {update.message.from_user.id} pressed translated 'resume' button")
    await resume_timer(update, context)

async def handle_stop_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Stop' button press by calling stop_timer."""
    log.debug(f"User {update.message.from_user.id} pressed translated 'stop' button")
    await stop_timer(update, context)

async def handle_report_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Report' button press by calling report_command."""
    log.debug(f"User {update.message.from_user.id} pressed translated 'report' button")
    # Clear args for report_command when triggered by button
    context.args = []
    await report_command(update, context)

async def handle_break_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Break (5m)' button press by calling start_break_timer."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} pressed translated 'break' button")
    
    # Check if another timer is active before starting break
    if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
        log.warning(f"User {user_id} pressed break button while timer active.")
        await update.message.reply_text('Another timer is already active. Please /stop_timer first.')
        return

    # Start the break timer (using the internal function directly)
    await start_break_timer(context, user_id, 5) # 5 minute break

async def handle_list_projects_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Projects' button press by calling list_projects."""
    log.debug(f"User {update.message.from_user.id} pressed translated 'projects' button")
    await list_projects(update, context)

async def handle_list_tasks_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Tasks' button press by calling list_tasks."""
    log.debug(f"User {update.message.from_user.id} pressed translated 'tasks' button")
    await list_tasks(update, context)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages for creating projects and tasks from button interactions."""
    user_id = update.message.from_user.id
    text = update.message.text
    
    # Check if we're expecting a project name
    if context.user_data.get(user_id, {}).get('expecting_project_name'):
        log.debug(f"User {user_id} sent project name: {text}")
        # Clear the flag
        context.user_data[user_id]['expecting_project_name'] = False
        
        # Create the project
        result = await _create_project_logic(update.message.from_user, context, text)
        if result:
            await update.message.reply_text(f'Project "{text}" created and selected! Use /list_tasks to add tasks.')
        # Error handling done inside _create_project_logic
        
    # Check if we're expecting a task name
    elif context.user_data.get(user_id, {}).get('expecting_task_name'):
        log.debug(f"User {user_id} sent task name: {text}")
        # Clear the flag
        context.user_data[user_id]['expecting_task_name'] = False
        
        # Create the task
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            await update.message.reply_text('Please select a project first with /list_projects.')
            return
            
        result = await _create_task_logic(update.message.from_user, context, text)
        if result:
            project_name = database.get_project_name(current_project_id) or "Current Project"
            await update.message.reply_text(f'Task "{text}" added to project "{project_name}"!')
            
            # Refresh the task list to show the new task
            fake_update = Update(0, message=update.message)
            fake_update._effective_user = update.message.from_user
            await list_tasks(fake_update, context)
        # Error handling done inside _create_task_logic

# --- Language Selection Command ---
async def set_language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays language selection buttons."""
    user_id = update.effective_user.id
    log.debug(f"User {user_id} requested language change.")
    
    keyboard = []
    for lang_code in SUPPORTED_LANGUAGES:
        lang_name = get_language_name(lang_code)
        keyboard.append([InlineKeyboardButton(lang_name, callback_data=f"set_lang:{lang_code}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    select_message = _(user_id, 'select_language') # Get translated prompt
    await update.message.reply_text(select_message, reply_markup=reply_markup)

# --- Help Command --- (ensure it's the last command)
# ... existing help_command ... 