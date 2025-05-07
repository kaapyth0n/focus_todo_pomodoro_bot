from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, WebAppInfo, User, Message
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters
from telegram.helpers import escape_markdown # Import escape_markdown
from telegram import constants # For ParseMode
import database
from datetime import datetime, timedelta, timezone
from config import timer_states, DOMAIN_URL, SUPPORTED_LANGUAGES
import logging
import sqlite3
from . import google_auth as google_auth_handlers # Import the module itself
from . import admin as admin_handlers # Import admin handlers
from database import STATUS_ACTIVE, STATUS_DONE # Import status constants
import math # For formatting time
from i18n_utils import _, get_language_name, set_user_lang # Import the translation helper and name getter
import json
import re

log = logging.getLogger(__name__)

# Define constants for conversation states
NAME_PROJECT = 0
NAME_TASK = 1

# --- Conversation Handler States ---
WAITING_PROJECT_NAME, WAITING_TASK_NAME = range(2)

# --- Forwarded Message Handler ---
FORWARDED_MESSAGE_PROJECT_SELECT = 1000  # Arbitrary state constant
FORWARDED_MESSAGE_PROJECT_CREATE = 1001

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
    """Start command handler - sets up a new user and shows main keyboard."""
    user = update.effective_user
    user_id = user.id
    log.info(f"User {user_id} started the bot.")
    
    # Get user's language from Telegram client if available
    user_language = user.language_code
    if user_language and user_language in SUPPORTED_LANGUAGES:
        # Set the user's language in the database if it's a supported language
        if set_user_lang(user_id, user_language):
            log.info(f"User {user_id} language automatically set to {user_language} from Telegram client")
    
    # Add user to database (this will only insert if new, ignore if exists)
    first_name = getattr(user, 'first_name', '')
    last_name = getattr(user, 'last_name', '')
    database.add_user(user_id, first_name, last_name)
    
    # Show welcome message in user's language
    welcome_message = _(user_id, 'welcome')
    
    # Create the keyboard
    reply_markup = get_main_keyboard(user_id)
    
    # Send welcome message with keyboard
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    
    # Add version notice for users coming from older versions
    # This can be removed in future versions
    # await update.message.reply_text("ℹ️ Tip: Use /language to set your preferred language.") 

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
        
        # Pre-format accumulated and target times (round accumulated to 2 decimal places)
        accumulated_time_formatted = f"{final_accumulated_minutes:.2f}" 
        target_duration_formatted = f"{duration_minutes_target:.0f}" # Target is usually integer

        if session_type == 'work':
            project_id = database.get_current_project(user_id)
            task_id = database.get_current_task(user_id)
            if project_id and task_id:
                project_name = database.get_project_name(project_id)
                task_name = database.get_task_name(task_id)
                if project_name and task_name:
                     message = _(user_id, 'timer_stopped_work', 
                                   project_name=project_name, task_name=task_name, 
                                   accumulated_time=accumulated_time_formatted, target_duration=target_duration_formatted)
                else: 
                    message = _(user_id, 'timer_stopped_work_missing', 
                                   accumulated_time=accumulated_time_formatted, target_duration=target_duration_formatted)
            else:
                message = _(user_id, 'timer_stopped_work_unselected', 
                               accumulated_time=accumulated_time_formatted, target_duration=target_duration_formatted)
                project_id, task_id = None, None # Ensure null if not properly selected
        else: 
            message = _(user_id, 'timer_stopped_break', 
                           accumulated_time=accumulated_time_formatted, target_duration=target_duration_formatted)

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
        return f"{escaped_title_base} ({escaped_status})" 
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
    
    # Get base report title content
    if offset == 0:
        date_status = _(user_id, 'report_date_today')
    elif offset == -1:
        date_status = _(user_id, 'report_date_yesterday')
    else:
        try:
            report_date_obj = datetime.fromisoformat(report_date)
            date_status = report_date_obj.strftime('%a, %b %d, %Y')
        except (ValueError, TypeError):
            date_status = "Unknown Date"
    
    # Use a dedicated translation key for each report type
    report_type = _(user_id, 'report_type_daily')
    # Create title without requiring a new translation key
    title = f"{report_type} ({date_status})"
    
    # Start building report content
    report_lines = [f"📊 {title}"]

    if report_date is None:
        report_lines.append(_(user_id, 'report_data_error'))
    elif total_minutes == 0:
        report_lines.append(_(user_id, 'report_no_sessions_day'))
    else:
        # Format total time without asterisks in the code
        report_lines.append(_(user_id, 'report_total_time_minutes', total_minutes=f"{total_minutes:.1f}"))
        
        if detailed_breakdown:
            report_lines.append("\n" + _(user_id, 'report_project_task_breakdown'))
            for project_data in detailed_breakdown:
                proj_name = project_data['project_name']
                proj_mins = project_data['project_minutes']
                percentage = (proj_mins / total_minutes) * 100 if total_minutes > 0 else 0
                
                # Add project line without formatting in code
                report_lines.append(_(user_id, 'report_project_line_percentage', 
                                    project_name=proj_name, 
                                    minutes=f"{proj_mins:.1f}", 
                                    percentage=f"{percentage:.1f}"))
                
                # Add task lines
                for task_data in project_data['tasks']:
                    task_name = task_data['task_name']
                    task_mins = task_data['task_minutes']
                    report_lines.append(_(user_id, 'report_task_line', 
                                        task_name=task_name, 
                                        minutes=f"{task_mins:.1f}"))
        else:
            report_lines.append(_(user_id, 'report_no_project_task_data'))

    # Navigation Buttons
    prev_offset = offset - 1
    next_offset = offset + 1
    keyboard = [[ 
        InlineKeyboardButton(_(user_id, 'report_button_prev_day'), callback_data=f"report_nav:daily:{prev_offset}"),
        InlineKeyboardButton(_(user_id, 'report_button_next_day'), callback_data=f"report_nav:daily:{next_offset}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Join lines into final report
    final_report = "\n".join(report_lines)

    # Send/edit message with Markdown formatting
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                final_report, 
                parse_mode='Markdown',  # Use regular Markdown instead of MarkdownV2
                reply_markup=reply_markup
            )
        else:
            await update.effective_message.reply_text(
                final_report, 
                parse_mode='Markdown',  # Use regular Markdown instead of MarkdownV2
                reply_markup=reply_markup
            )
    except Exception as e:
        log.error(f"Failed to send/edit daily report for user {user_id}: {e}")
        # Fallback to plain text if Markdown fails
        try:
            plain_text = final_report.replace('*', '')  # Remove asterisks
            if update.callback_query:
                await update.callback_query.edit_message_text(plain_text, reply_markup=reply_markup)
            else:
                await update.effective_message.reply_text(plain_text, reply_markup=reply_markup)
        except Exception as fb_err:
            log.error(f"Fallback report sending failed: {fb_err}")

async def report_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE, offset: int = 0):
    """Sends the weekly report with navigation."""
    user_id = update.effective_user.id
    log.info(f"Generating weekly report for user {user_id}, offset {offset}")
    week_start_date, total_minutes, daily_breakdown, detailed_project_task_breakdown = database.get_weekly_report(user_id, offset=offset)
    
    # Get base report title content
    if offset == 0:
        date_status = _(user_id, 'report_week_this')
    elif offset == -1:
        date_status = _(user_id, 'report_week_last')
    else:
        try:
            report_date_obj = datetime.fromisoformat(week_start_date)
            week_end_date = report_date_obj + timedelta(days=6)
            start_f = report_date_obj.strftime('%b %d')
            end_f = week_end_date.strftime('%b %d, %Y')
            date_status = f"{start_f} - {end_f}"
        except (ValueError, TypeError):
            date_status = "Unknown Week"
    
    # Use a dedicated translation key for each report type
    report_type = _(user_id, 'report_type_weekly')
    # Create title without requiring a new translation key
    title = f"{report_type} ({date_status})"
    
    # Start building report content
    report_lines = [f"📈 {title}"]

    if week_start_date is None:
        report_lines.append(_(user_id, 'report_data_error'))
    elif total_minutes == 0:
        report_lines.append(_(user_id, 'report_no_sessions_week'))
    else:
        # Format total time
        report_lines.append(_(user_id, 'report_total_time_week', total_minutes=f"{total_minutes:.1f}"))
        
        if daily_breakdown:
            report_lines.append("\n" + _(user_id, 'report_daily_breakdown'))
            for date_str, minutes in daily_breakdown:
                try:
                    date_obj = datetime.fromisoformat(date_str)
                    date_display = date_obj.strftime("%a, %b %d")
                    report_lines.append(_(user_id, 'report_daily_line', 
                                        date=date_display, 
                                        minutes=f"{minutes:.1f}"))
                except (ValueError, TypeError):
                    report_lines.append(_(user_id, 'report_daily_line', 
                                        date=date_str, 
                                        minutes=f"{minutes:.1f}"))
        
        if detailed_project_task_breakdown:
            report_lines.append("\n" + _(user_id, 'report_project_task_breakdown'))
            for project_data in detailed_project_task_breakdown:
                proj_name = project_data['project_name']
                proj_mins = project_data['project_minutes']
                percentage = (proj_mins / total_minutes) * 100 if total_minutes > 0 else 0
                
                # Add project line without formatting in code
                report_lines.append(_(user_id, 'report_project_line_percentage', 
                                    project_name=proj_name, 
                                    minutes=f"{proj_mins:.1f}", 
                                    percentage=f"{percentage:.1f}"))
                
                # Add task lines
                for task_data in project_data['tasks']:
                    task_name = task_data['task_name']
                    task_mins = task_data['task_minutes']
                    report_lines.append(_(user_id, 'report_task_line', 
                                        task_name=task_name, 
                                        minutes=f"{task_mins:.1f}"))
        elif not daily_breakdown:
            report_lines.append(_(user_id, 'report_no_project_task_data'))

    # Navigation Buttons
    prev_offset = offset - 1
    next_offset = offset + 1
    keyboard = [[ 
        InlineKeyboardButton(_(user_id, 'report_button_prev_week'), callback_data=f"report_nav:weekly:{prev_offset}"),
        InlineKeyboardButton(_(user_id, 'report_button_next_week'), callback_data=f"report_nav:weekly:{next_offset}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Join lines into final report
    final_report = "\n".join(report_lines)

    # Send/edit message with Markdown formatting
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                final_report, 
                parse_mode='Markdown',  # Use regular Markdown instead of MarkdownV2
                reply_markup=reply_markup
            )
        else:
            await update.effective_message.reply_text(
                final_report, 
                parse_mode='Markdown',  # Use regular Markdown instead of MarkdownV2
                reply_markup=reply_markup
            )
    except Exception as e:
        log.error(f"Failed to send/edit weekly report for user {user_id}: {e}")
        # Fallback to plain text if Markdown fails
        try:
            plain_text = final_report.replace('*', '')  # Remove asterisks
            if update.callback_query:
                await update.callback_query.edit_message_text(plain_text, reply_markup=reply_markup)
            else:
                await update.effective_message.reply_text(plain_text, reply_markup=reply_markup)
        except Exception as fb_err:
            log.error(f"Fallback report sending failed: {fb_err}")

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
    
    # Get base report title content
    try:
        month_date = datetime.fromisoformat(month_start_date)
        date_status = month_date.strftime("%B %Y")
    except (ValueError, TypeError):
        date_status = "Unknown Month"
    
    # Use a dedicated translation key for each report type
    report_type = _(user_id, 'report_type_monthly')
    # Create title without requiring a new translation key
    title = f"{report_type} ({date_status})"
    
    # Start building report content
    report_lines = [f"📅 {title}"]

    if month_start_date is None:
        report_lines.append(_(user_id, 'report_data_error'))
    elif total_minutes == 0:
        report_lines.append(_(user_id, 'report_no_sessions_month'))
    else:
        # Format total time
        hours = total_minutes / 60
        report_lines.append(_(user_id, 'report_total_time_month', 
                             total_minutes=f"{total_minutes:.1f}", 
                             total_hours=f"{hours:.1f}"))
        
        if detailed_breakdown:
            report_lines.append("\n" + _(user_id, 'report_project_task_breakdown'))
            for project_data in detailed_breakdown:
                proj_name = project_data['project_name']
                proj_mins = project_data['project_minutes']
                percentage = (proj_mins / total_minutes) * 100 if total_minutes > 0 else 0
                
                # Add project line without formatting in code
                report_lines.append(_(user_id, 'report_project_line_percentage', 
                                    project_name=proj_name, 
                                    minutes=f"{proj_mins:.1f}", 
                                    percentage=f"{percentage:.1f}"))
                
                # Add task lines
                for task_data in project_data['tasks']:
                    task_name = task_data['task_name']
                    task_mins = task_data['task_minutes']
                    report_lines.append(_(user_id, 'report_task_line', 
                                        task_name=task_name, 
                                        minutes=f"{task_mins:.1f}"))
        else:
            report_lines.append(_(user_id, 'report_no_project_task_data'))

    # Navigation Buttons
    prev_offset = offset - 1
    next_offset = offset + 1
    keyboard = [[ 
        InlineKeyboardButton(_(user_id, 'report_button_prev_month'), callback_data=f"report_nav:monthly:{prev_offset}"),
        InlineKeyboardButton(_(user_id, 'report_button_next_month'), callback_data=f"report_nav:monthly:{next_offset}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Join lines into final report
    final_report = "\n".join(report_lines)

    # Send/edit message with Markdown formatting
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                final_report, 
                parse_mode='Markdown',  # Use regular Markdown instead of MarkdownV2
                reply_markup=reply_markup
            )
        else:
            await update.effective_message.reply_text(
                final_report, 
                parse_mode='Markdown',  # Use regular Markdown instead of MarkdownV2
                reply_markup=reply_markup
            )
    except Exception as e:
        log.error(f"Failed to send/edit monthly report for user {user_id}: {e}")
        # Fallback to plain text if Markdown fails
        try:
            plain_text = final_report.replace('*', '')  # Remove asterisks
            if update.callback_query:
                await update.callback_query.edit_message_text(plain_text, reply_markup=reply_markup)
            else:
                await update.effective_message.reply_text(plain_text, reply_markup=reply_markup)
        except Exception as fb_err:
            log.error(f"Fallback report sending failed: {fb_err}")

# --- Reply Keyboard Button Handlers ---

# IMPORTANT: The Regex filters in bot.py MUST now match the *translated* button texts.
# This is complex. A better approach is needed, perhaps using callback_data or a different handler type.
# For now, we'll leave the handle_***_button functions, but they likely won't work correctly
# until the Regex matching in bot.py is updated or the handling strategy changes.

# DEPRECATED: These individual handlers are no longer triggered by Regex in bot.py
# They might still be called internally by handle_text_message
async def handle_start_work_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Start Work' button press by calling start_timer."""
    log.debug(f"User {update.message.from_user.id} triggered 'start work' action via text")
    await start_timer(update, context)

async def handle_pause_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Pause' button press by calling pause_timer."""
    log.debug(f"User {update.message.from_user.id} triggered 'pause' action via text")
    await pause_timer(update, context)

async def handle_resume_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Resume' button press by calling resume_timer."""
    log.debug(f"User {update.message.from_user.id} triggered 'resume' action via text")
    await resume_timer(update, context)

async def handle_stop_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Stop' button press by calling stop_timer."""
    log.debug(f"User {update.message.from_user.id} triggered 'stop' action via text")
    await stop_timer(update, context)

async def handle_report_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Report' button press by calling report_command."""
    log.debug(f"User {update.message.from_user.id} triggered 'report' action via text")
    # Clear args for report_command when triggered by button
    context.args = []
    await report_command(update, context)

async def handle_break_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Break (5m)' button press by calling start_break_timer."""
    user_id = update.message.from_user.id
    log.debug(f"User {user_id} triggered 'break' action via text")
    
    # Check if another timer is active before starting break
    if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
        log.warning(f"User {user_id} pressed break button while timer active.")
        # Use translation for the error message
        await update.message.reply_text(_(user_id, 'error_timer_active_break')) 
        return

    # Start the break timer (using the internal function directly)
    await start_break_timer(context, user_id, 5) # 5 minute break

async def handle_list_projects_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Projects' button press by calling list_projects."""
    log.debug(f"User {update.message.from_user.id} triggered 'projects' action via text")
    await list_projects(update, context)

async def handle_list_tasks_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Tasks' button press by calling list_tasks."""
    log.debug(f"User {update.message.from_user.id} triggered 'tasks' action via text")
    await list_tasks(update, context)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages, mapping Reply Keyboard buttons and project/task creation."""
    user_id = update.message.from_user.id
    text = update.message.text
    
    # Map Reply Keyboard button text to actions based on user language
    button_map = {
        'button_start_work': handle_start_work_button,
        'button_pause': handle_pause_button,
        'button_resume': handle_resume_button,
        'button_stop': handle_stop_button,
        'button_report': handle_report_button,
        'button_break_5': handle_break_button,
        'button_list_projects': handle_list_projects_button,
        'button_list_tasks': handle_list_tasks_button,
    }
    
    button_pressed = False
    for key, handler_func in button_map.items():
        translated_text = _(user_id, key)
        if text == translated_text:
            log.info(f"User {user_id} pressed translated button: '{text}' (mapped to {key})")
            await handler_func(update, context)
            button_pressed = True
            break
            
    if button_pressed:
        return # Don't process further if it was a button press
        
    # Check if we're expecting a project name (for creation via callback button)
    if context.user_data.get(user_id, {}).get('expecting_project_name'):
        log.debug(f"User {user_id} sent project name: {text}")
        # Clear the flag
        context.user_data[user_id]['expecting_project_name'] = False
        
        # Create the project
        result = await _create_project_logic(update.message.from_user, context, text)
        if result:
            # Use the key that requires the project name parameter
            await update.message.reply_text(_(user_id, 'project_created_selected', project_name=text))
        # Error handling done inside _create_project_logic
        return # Handled as project name input
        
    # Check if we're expecting a task name (for creation via callback button)
    elif context.user_data.get(user_id, {}).get('expecting_task_name'):
        log.debug(f"User {user_id} sent task name: {text}")
        # Clear the flag
        context.user_data[user_id]['expecting_task_name'] = False
        
        # Create the task
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            await update.message.reply_text(_(user_id, 'task_create_no_project'))
            return
            
        result = await _create_task_logic(update.message.from_user, context, text)
        if result:
            project_name = database.get_project_name(current_project_id) or _(user_id, 'text_current_project')
            # Use the key that requires both task and project name
            await update.message.reply_text(_(user_id, 'task_created_selected', task_name=text, project_name=project_name))
            
            # Refresh the task list to show the new task
            fake_update = Update(0, message=update.message)
            fake_update._effective_user = update.message.from_user
            await list_tasks(fake_update, context)
        # Error handling done inside _create_task_logic
        return # Handled as task name input
        
    # If the text wasn't a button and wasn't expected input, maybe log or ignore
    log.debug(f"Received unhandled text message from user {user_id}: {text}")

# --- Forwarded Message Handler ---
async def handle_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info(f"handle_forwarded_message called. update: {update}")
    message = getattr(update, 'message', None)
    if not message:
        log.warning("No message found, returning early")
        return
        
    # Check for forward_date in api_kwargs or forward_origin
    has_forward = False
    if getattr(message, 'api_kwargs', {}).get('forward_date'):
        has_forward = True
    elif getattr(message, 'forward_origin', None):
        has_forward = True
    
    if not has_forward:
        log.warning("No forward_date or forward_origin found, returning early")
        return
        
    user_id = message.from_user.id
    log.info(f"Processing forwarded message for user {user_id}")
    
    # Store forwarded message data in user_data (temporary until project is chosen)
    try:
        context.user_data[user_id] = context.user_data.get(user_id, {})
        context.user_data[user_id]['pending_forwarded_message'] = {
            'message_text': message.text or message.caption or '',
            'original_sender_name': (getattr(message, 'api_kwargs', {}).get('forward_sender_name') or 
                                   (message.forward_from.full_name if getattr(message, 'forward_from', None) else '') or
                                   (message.forward_origin.sender_user.full_name if getattr(message, 'forward_origin', None) and hasattr(message.forward_origin, 'sender_user') else '')),
            'forwarded_date': datetime.now().isoformat(),  # Use current time if forward_date not available
            'tg_message_id': message.message_id,
            'tg_chat_id': message.chat_id,
        }
        
        # If forward_date is available in api_kwargs, use it
        if getattr(message, 'api_kwargs', {}).get('forward_date'):
            forward_timestamp = message.api_kwargs['forward_date']
            # Convert timestamp to datetime
            forward_date = datetime.fromtimestamp(forward_timestamp, tz=timezone.utc)
            context.user_data[user_id]['pending_forwarded_message']['forwarded_date'] = forward_date.isoformat()
        # If forward_origin is available, use its date
        elif getattr(message, 'forward_origin', None) and getattr(message.forward_origin, 'date', None):
            context.user_data[user_id]['pending_forwarded_message']['forwarded_date'] = message.forward_origin.date.isoformat()
            
        log.info(f"Stored forwarded message data: {context.user_data[user_id]['pending_forwarded_message']}")
        
        # Prompt for project selection
        projects = database.get_projects(user_id, status=STATUS_ACTIVE)
        log.info(f"Found {len(projects)} active projects for user {user_id}")
        
        keyboard = []
        for project_id, project_name in projects:
            keyboard.append([InlineKeyboardButton(project_name, callback_data=f"forwarded_select_project:{project_id}")])
        
        # Use the correct translation key that exists in the translation files
        keyboard.append([InlineKeyboardButton(_(user_id, 'create_new_project_button'), callback_data="forwarded_create_new_project")])
        # Add a cancel button
        keyboard.append([InlineKeyboardButton(_(user_id, 'button_cancel'), callback_data="cancel_forwarded_message")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        log.info(f"Built keyboard with {len(keyboard)} rows")
        
        log.info(f"About to send message with translation key 'forwarded_select_project_prompt' to user {user_id}")
        prompt_text = _(user_id, 'forwarded_select_project_prompt')
        log.info(f"Prompt text resolved to: '{prompt_text}'")
        
        await message.reply_text(prompt_text, reply_markup=reply_markup)
        log.info(f"Message sent successfully to user {user_id}")
        
    except Exception as e:
        log.error(f"Error in handle_forwarded_message for user {user_id}: {e}", exc_info=True)
        try:
            await message.reply_text(_(user_id, 'error_unexpected'))
        except Exception as send_error:
            log.error(f"Failed to send error message: {send_error}")
            
    return FORWARDED_MESSAGE_PROJECT_SELECT

# --- Callback handler for project selection (to be called from callbacks.py) ---
async def handle_forwarded_project_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, project_id: int) -> int:
    user_id = update.effective_user.id
    pending = context.user_data.get(user_id, {}).get('pending_forwarded_message')
    if not pending:
        await update.callback_query.edit_message_text(_(user_id, 'forwarded_no_pending'))
        return ConversationHandler.END
    
    try:
        # Set this as the current project
        database.set_current_project(user_id, project_id)
        
        # Save to forwarded_messages table
        database.add_forwarded_message(
            user_id=user_id,
            project_id=project_id,
            message_text=pending['message_text'],
            original_sender_name=pending['original_sender_name'],
            forwarded_date=pending['forwarded_date'],
            tg_message_id=pending['tg_message_id'],
            tg_chat_id=pending['tg_chat_id']
        )
        
        # Also create a task with this message content
        task_name = pending['message_text']
        if len(task_name) > 100:  # Truncate if too long
            task_name = task_name[:97] + "..."
        
        project_name = database.get_project_name(project_id) or _(user_id, 'text_unknown_project')
        
        # Add task to the project
        task_id = database.add_task(project_id, task_name)
        
        # Set as current task
        if task_id:
            database.set_current_task(user_id, task_id)
            
        log.info(f"Created task '{task_name}' from forwarded message for user {user_id} in project {project_id}")
        
        # Send admin notification
        await admin_handlers.send_admin_notification(
            context,
            f"Task created from forwarded message by {update.effective_user.first_name} ({user_id}) in project '{project_name}': '{task_name}'"
        )
        
        # Clear the pending message data
        if user_id in context.user_data and 'pending_forwarded_message' in context.user_data[user_id]:
            del context.user_data[user_id]['pending_forwarded_message']
        
        # Notify the user
        await update.callback_query.edit_message_text(
            _(user_id, 'forwarded_saved_success_with_task', project_name=project_name)
        )
        
        # Exit the conversation
        return ConversationHandler.END
        
    except Exception as e:
        log.error(f"Error saving forwarded message for user {user_id}: {e}", exc_info=True)
        await update.callback_query.edit_message_text(_(user_id, 'error_unexpected'))
        return ConversationHandler.END

# --- Callback handler for 'Create New Project' in forwarded workflow ---
async def handle_forwarded_create_new_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the request to create a new project for a forwarded message."""
    user_id = update.effective_user.id
    log.info(f"User {user_id} chose to create a new project for forwarded message")
    
    try:
        # Make sure we have a user_data dictionary
        context.user_data[user_id] = context.user_data.get(user_id, {})
        context.user_data[user_id]['expecting_forwarded_project_name'] = True
        
        # Store that we're expecting a project name for a forwarded message
        # Add instructions about using /cancel
        await update.callback_query.edit_message_text(_(user_id, 'forwarded_prompt_new_project_name_with_cancel'))
        log.info(f"Prompting user {user_id} to enter new project name for forwarded message")
        
        # Return the appropriate conversation state
        return FORWARDED_MESSAGE_PROJECT_CREATE
    except Exception as e:
        log.error(f"Error in handle_forwarded_create_new_project for user {user_id}: {e}", exc_info=True)
        await update.callback_query.edit_message_text(_(user_id, 'error_unexpected'))
        return ConversationHandler.END

async def handle_forwarded_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the project name entry in the forwarded message workflow."""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    log.info(f"Received project name '{message_text}' from user {user_id} for forwarded message")
    
    try:
        # Create the project
        project_id = database.add_project(user_id, message_text)
        if not project_id:
            await update.message.reply_text(_(user_id, 'error_create_project'))
            return ConversationHandler.END
        
        # Set as current project
        database.set_current_project(user_id, project_id)
        
        # Get the pending forwarded message
        pending = context.user_data.get(user_id, {}).get('pending_forwarded_message')
        if not pending:
            await update.message.reply_text(_(user_id, 'forwarded_no_pending'))
            return ConversationHandler.END
            
        # Save to forwarded_messages table
        database.add_forwarded_message(
            user_id=user_id,
            project_id=project_id,
            message_text=pending['message_text'],
            original_sender_name=pending['original_sender_name'],
            forwarded_date=pending['forwarded_date'],
            tg_message_id=pending['tg_message_id'],
            tg_chat_id=pending['tg_chat_id']
        )
        
        # Create a task with the forwarded message content
        task_name = pending['message_text']
        if len(task_name) > 100:  # Truncate if too long
            task_name = task_name[:97] + "..."
        
        task_id = database.add_task(project_id, task_name)
        
        # Set as current task
        if task_id:
            database.set_current_task(user_id, task_id)
        
        log.info(f"Created task '{task_name}' from forwarded message for user {user_id} in new project {project_id}")
        
        # Send admin notification
        await admin_handlers.send_admin_notification(
            context,
            f"New project '{message_text}' and task created from forwarded message by {update.message.from_user.first_name} ({user_id}): '{task_name}'"
        )
        
        # Clear the pending data - make sure we remove ALL flags
        if user_id in context.user_data:
            if 'pending_forwarded_message' in context.user_data[user_id]:
                del context.user_data[user_id]['pending_forwarded_message']
            if 'expecting_forwarded_project_name' in context.user_data[user_id]:
                del context.user_data[user_id]['expecting_forwarded_project_name']
        
        # Notify the user
        await update.message.reply_text(
            _(user_id, 'forwarded_saved_success_with_task', project_name=message_text)
        )
        
        # End the conversation
        return ConversationHandler.END
        
    except Exception as e:
        log.error(f"Error creating project from forwarded message for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(_(user_id, 'error_unexpected'))
        return ConversationHandler.END

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

# --- Help Command --- (Restored)
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