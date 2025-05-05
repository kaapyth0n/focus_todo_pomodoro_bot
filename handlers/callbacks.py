from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
import database
from database import STATUS_ACTIVE, STATUS_DONE # Import status constants
from config import timer_states # timer_states might be needed if we check active timers here
from . import commands as cmd_handlers # Import commands module to call list handlers
from .commands import report_daily, report_weekly, report_monthly, start_break_timer # Import report functions and break starter
from i18n_utils import _, set_user_lang, get_language_name # Import i18n utils
import logging # Added previously
import sqlite3 # Need this for the exception type
import traceback

log = logging.getLogger(__name__)

# --- Helper Functions for Displaying Lists --- 

async def _display_archived_projects(query: CallbackQuery, user_id: int):
    """Helper to fetch and display the archived projects list."""
    try:
        projects = database.get_projects(user_id, status=STATUS_DONE)
        keyboard = []
        title = _(user_id, 'archived_projects_title')
        if not projects:
             keyboard.append([InlineKeyboardButton(_(user_id, 'archived_project_no_archive'), callback_data="noop_no_archive")])
        else:
             for project_id, project_name in projects:
                 keyboard.append([
                     InlineKeyboardButton(project_name, callback_data=f"noop_project:{project_id}"), 
                     InlineKeyboardButton(_(user_id, 'button_reactivate'), callback_data=f"mark_project_active:{project_id}")
                 ])
        keyboard.append([InlineKeyboardButton(_(user_id, 'button_back_to_active_projects'), callback_data="list_projects_active")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(title, reply_markup=reply_markup)
        log.debug(f"Displayed archived projects for user {user_id}.")
    except Exception as e:
        log.error(f"Error displaying archived projects for user {user_id}: {e}", exc_info=True)
        try: await query.edit_message_text(_(user_id, 'error_list_archived_projects'))
        except Exception: pass # Ignore if edit fails

async def _display_archived_tasks(query: CallbackQuery, user_id: int):
    """Helper to fetch and display the archived tasks list for the current project."""
    try:
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
             await query.edit_message_text(_(user_id, 'task_create_no_project'))
             return
        project_name = database.get_project_name(current_project_id) or _(user_id, 'text_selected_project')
        tasks = database.get_tasks(current_project_id, status=STATUS_DONE)
        keyboard = []
        title = _(user_id, 'archived_tasks_title', project_name=project_name)
        if not tasks:
            keyboard.append([InlineKeyboardButton(_(user_id, 'archived_task_no_archive'), callback_data="noop_no_archive")])
        else:
             for task_id, task_name in tasks:
                 keyboard.append([
                     InlineKeyboardButton(task_name, callback_data=f"noop_task:{task_id}"),
                     InlineKeyboardButton(_(user_id, 'button_reactivate'), callback_data=f"mark_task_active:{task_id}")
                 ])
        keyboard.append([InlineKeyboardButton(_(user_id, 'button_back_to_active_tasks'), callback_data="list_tasks_active")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(title, reply_markup=reply_markup)
        log.debug(f"Displayed archived tasks for user {user_id} in project {current_project_id}.")
    except Exception as e:
        log.error(f"Error displaying archived tasks for user {user_id}: {e}", exc_info=True)
        try: await query.edit_message_text(_(user_id, 'error_list_archived_tasks'))
        except Exception: pass

# --- Callback Query Handler ---

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Acknowledge immediately

    data = query.data
    user_id = query.from_user.id
    log.debug(f"Callback received from user {user_id}: {data}")

    try:
        # --- Specific No-op Callbacks with Instructions --- 
        if data == "noop_create_project":
            log.debug(f"Handling create project instruction callback: {data}")
            await query.edit_message_text(
                text=_(user_id, 'instruction_create_project'),
                reply_markup=None 
            )
            return
        elif data == "noop_create_task":
            log.debug(f"Handling create task instruction callback: {data}")
            current_project_id = database.get_current_project(user_id)
            project_name = database.get_project_name(current_project_id) if current_project_id else _(user_id, 'text_current_project')
            await query.edit_message_text(
                text=_(user_id, 'instruction_create_task', project_name=project_name),
                reply_markup=None 
            )
            return
            
        # --- Generic No-op Callbacks (e.g., for archived item names) ---
        elif data.startswith("noop_"):
            log.debug(f"Handled generic no-op callback: {data}")
            # Just acknowledge, don't change the message or remove buttons
            return 

        # --- Report Navigation Callback --- 
        elif data.startswith("report_nav:"):
            try:
                parts = data.split(':')
                report_type = parts[1]
                offset = int(parts[2])
                log.info(f"Handling report navigation: type={report_type}, offset={offset} for user {user_id}")
                
                if report_type == "daily":
                    await cmd_handlers.report_daily(update, context, offset=offset)
                elif report_type == "weekly":
                    await cmd_handlers.report_weekly(update, context, offset=offset)
                elif report_type == "monthly":
                    await cmd_handlers.report_monthly(update, context, offset=offset)
                else:
                    log.warning(f"Unknown report type '{report_type}' in callback data: {data}")
                    await query.answer("Unknown report type for navigation.")
            except (IndexError, ValueError) as e:
                log.error(f"Error parsing report navigation callback '{data}': {e}")
                await query.answer("Error processing navigation.")
            except Exception as e:
                # Catch other potential errors during report generation
                log.error(f"Error during report navigation callback '{data}': {e}", exc_info=True)
                await query.answer("An error occurred generating the report.")
                # Attempt to edit the message to show error, might fail if original message deleted
                try: await query.edit_message_text("An error occurred generating the report.")
                except Exception: pass 
            return # Handled this callback type
            
        # --- Deprecated Report Callbacks (kept for safety, but should be unused now) ---
        elif data == "report_daily":
            log.info(f"User {user_id} triggered DEPRECATED daily report via callback. Redirecting.")
            await cmd_handlers.report_daily(update, context, offset=0) # Call with offset 0
        elif data == "report_weekly":
            log.info(f"User {user_id} triggered DEPRECATED weekly report via callback. Redirecting.")
            await cmd_handlers.report_weekly(update, context, offset=0) 
        elif data == "report_monthly":
            log.info(f"User {user_id} triggered DEPRECATED monthly report via callback. Redirecting.")
            await cmd_handlers.report_monthly(update, context, offset=0)
        
        # --- Selection Callbacks ---
        elif data.startswith("select_project:"):
            try:
                project_id = int(data.split(":")[1])
                project_name = database.get_project_name(project_id) or _(user_id, 'text_unknown_project') # New key

                database.set_current_project(user_id, project_id)
                database.set_current_task(user_id, None)
                log.info(f"User {user_id} selected project {project_id} ('{project_name}') via callback.")
                await query.edit_message_text(text=_(user_id, 'project_selected_callback', project_name=project_name)) # New key
            except (IndexError, ValueError) as e:
                log.warning(f"Error parsing select_project callback data '{data}' for user {user_id}: {e}")
                await query.edit_message_text(text=_(user_id, 'error_processing_selection'))
            except sqlite3.Error as e:
                log.error(f"DB Error selecting project via callback for user {user_id}: {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_selecting_project_db'))
            except Exception as e:
                log.error(f"Unexpected error handling select_project callback for user {user_id}: {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_selecting_project_unexpected'))
        
        elif data.startswith("select_task:"):
            try:
                task_id = int(data.split(":")[1])
                current_project_id = database.get_current_project(user_id)
                if not current_project_id:
                     log.warning(f"User {user_id} tried to select task via callback with no project selected.")
                     await query.edit_message_text(text=_(user_id, 'error_selecting_task_no_project'))
                     return
                    
                task_name = database.get_task_name(task_id)
                if task_name is None:
                    log.warning(f"User {user_id} tried to select non-existent/mismatched task ID {task_id} via callback.")
                    await query.edit_message_text(text=_(user_id, 'error_task_not_found_or_mismatch'))
                    return
                    
                database.set_current_task(user_id, task_id)
                log.info(f"User {user_id} selected task {task_id} ('{task_name}') via callback.")
                await query.edit_message_text(text=_(user_id, 'task_selected_callback', task_name=task_name)) # New key
            except (IndexError, ValueError) as e:
                 log.warning(f"Error parsing select_task callback data '{data}' for user {user_id}: {e}")
                 await query.edit_message_text(text=_(user_id, 'error_processing_selection'))
            except sqlite3.Error as e:
                log.error(f"DB Error selecting task via callback for user {user_id}: {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_selecting_task_db'))
            except Exception as e:
                log.error(f"Unexpected error handling select_task callback for user {user_id}: {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_selecting_task_unexpected'))

        # --- Deletion Callbacks ---
        elif data == "cancel_delete":
            log.debug(f"User {user_id} cancelled deletion via callback.")
            await query.edit_message_text(text=_(user_id, 'deletion_cancelled'))
            
        elif data.startswith("confirm_delete_project:"):
            try:
                project_id_str = data.split(":")[1]
                project_id = int(project_id_str)
            except (IndexError, ValueError):
                log.warning(f"Invalid confirm_delete_project data from user {user_id}: {data}")
                await query.edit_message_text(_(user_id, 'error_invalid_delete_data'))
                return
            
            project_name = database.get_project_name(project_id) or _(user_id, 'text_unknown_project') # New key
            keyboard = [
                [InlineKeyboardButton(_(user_id, 'button_confirm_delete'), callback_data=f"delete_project:{project_id}")], # New key
                [InlineKeyboardButton(_(user_id, 'button_cancel_delete'), callback_data="cancel_delete")] # New key
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                _(user_id, 'delete_confirm_project', project_name=project_name), 
                reply_markup=reply_markup
            )
            log.debug(f"Sent final project deletion confirmation for project {project_id} to user {user_id}")

        elif data.startswith("delete_project:"):
            project_id = None
            project_name_for_log = "unknown"
            try:
                project_id = int(data.split(":")[1])
                project_name = database.get_project_name(project_id)
                project_name_for_log = project_name or _(user_id, 'text_unknown_project')
                if project_name is None:
                    log.warning(f"Attempt to delete non-existent project ID {project_id} by user {user_id} via callback")
                    await query.answer(_(user_id, 'error_project_not_found_delete'), show_alert=True)
                    await query.edit_message_text(text=_(user_id, 'error_finding_project_delete'))
                    return

                deleted = database.delete_project(project_id)
                if deleted:
                    log.info(f"User {user_id} deleted project {project_id} ('{project_name}') via callback.")
                    await query.edit_message_text(text=_(user_id, 'project_deleted_success', project_name=project_name))
                else:
                    log.warning(f"Failed to delete project {project_id} ('{project_name}') for user {user_id} via callback. DB function returned false.")
                    await query.edit_message_text(text=_(user_id, 'project_deleted_fail', project_name=project_name))
            except (IndexError, ValueError) as e:
                 log.warning(f"Error parsing delete_project callback data '{data}' for user {user_id}: {e}")
                 await query.edit_message_text(text=_(user_id, 'error_processing_delete'))
            except sqlite3.Error as e:
                log.error(f"DB Error deleting project via callback for user {user_id}, project_id {project_id}: {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_db_delete_project'))
                await query.answer(_(user_id, 'error_db_short'), show_alert=True)
            except Exception as e:
                log.error(f"Unexpected error handling delete_project callback for user {user_id}, project_id {project_id} ('{project_name_for_log}'): {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_unexpected_delete_project'))
                await query.answer(_(user_id, 'error_unexpected_short'), show_alert=True)
            
        elif data.startswith("confirm_delete_task:"):
            try:
                task_id_str = data.split(":")[1]
                task_id = int(task_id_str)
            except (IndexError, ValueError):
                log.warning(f"Invalid confirm_delete_task data from user {user_id}: {data}")
                await query.edit_message_text(_(user_id, 'error_invalid_delete_data'))
                return
            
            task_name = database.get_task_name(task_id) or _(user_id, 'text_unknown_task') # New key
            keyboard = [
                [InlineKeyboardButton(_(user_id, 'button_confirm_delete'), callback_data=f"delete_task:{task_id}")],
                [InlineKeyboardButton(_(user_id, 'button_cancel_delete'), callback_data="cancel_delete")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                _(user_id, 'delete_confirm_task', task_name=task_name), 
                reply_markup=reply_markup
            )
            log.debug(f"Sent final task deletion confirmation for task {task_id} to user {user_id}")

        elif data.startswith("delete_task:"):
            task_id = None
            task_name_for_log = "unknown"
            try:
                task_id = int(data.split(":")[1])
                task_name = database.get_task_name(task_id)
                task_name_for_log = task_name or _(user_id, 'text_unknown_task')
                if task_name is None:
                    log.warning(f"Attempt to delete non-existent task ID {task_id} by user {user_id} via callback")
                    await query.answer(_(user_id, 'error_task_not_found_delete'), show_alert=True)
                    await query.edit_message_text(text=_(user_id, 'error_finding_task_delete'))
                    return
                
                deleted = database.delete_task(task_id)
                if deleted:
                    log.info(f"User {user_id} deleted task {task_id} ('{task_name}') via callback.")
                    await query.edit_message_text(text=_(user_id, 'task_deleted_success', task_name=task_name))
                else:
                    log.warning(f"Failed to delete task {task_id} ('{task_name}') for user {user_id} via callback. DB function returned false.")
                    await query.edit_message_text(text=_(user_id, 'task_deleted_fail', task_name=task_name))
            except (IndexError, ValueError) as e:
                 log.warning(f"Error parsing delete_task callback data '{data}' for user {user_id}: {e}")
                 await query.edit_message_text(text=_(user_id, 'error_processing_delete'))
            except sqlite3.Error as e:
                log.error(f"DB Error deleting task via callback for user {user_id}, task_id {task_id}: {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_db_delete_task'))
                await query.answer(_(user_id, 'error_db_short'), show_alert=True)
            except Exception as e:
                log.error(f"Unexpected error handling delete_task callback for user {user_id}, task_id {task_id} ('{task_name_for_log}'): {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_unexpected_delete_task'))
                await query.answer(_(user_id, 'error_unexpected_short'), show_alert=True)

        # --- Break Timer Callback ---
        elif data.startswith("start_break:"):
            log.debug(f"Handling start_break callback for user {user_id}")
            timer_states = context.bot_data.setdefault('timer_states', {}) # Should this use config.timer_states?
            if user_id in timer_states and timer_states[user_id].get('status') in ['running', 'paused']:
                log.warning(f"User {user_id} tried to start a break timer via callback while another timer is active.")
                await query.answer(_(user_id, 'error_timer_active_break'), show_alert=True)
                return

            try:
                duration_minutes = int(data.split(":")[1])
                log.info(f"User {user_id} starting {duration_minutes} min break via callback.")
                await start_break_timer(context, user_id, duration_minutes)
                await query.edit_message_text(text=_(user_id, 'break_started', duration_minutes=duration_minutes), reply_markup=None)
            except (IndexError, ValueError) as e:
                log.warning(f"Error parsing break duration from callback '{data}' for user {user_id}: {e}")
                await query.edit_message_text(text=_(user_id, 'error_start_break'))
            except Exception as e:
                log.error(f"Unexpected error handling start_break callback for user {user_id}: {e}\n{traceback.format_exc()}")
                await query.edit_message_text(text=_(user_id, 'error_start_break_unexpected'))
                await query.answer(_(user_id, 'error_unexpected_short'), show_alert=True)

        # --- Done/Archive Callbacks --- 
        elif data.startswith("mark_project_done:"):
            try:
                project_id = int(data.split(":")[1])
                project_name = database.get_project_name(project_id) or _(user_id, 'text_unknown_project')
                success = database.mark_project_status(project_id, STATUS_DONE)
                if success:
                    log.info(f"User {user_id} marked project {project_id} ('{project_name}') as done.")
                    fake_update = Update(0, message=query.message)
                    fake_update._effective_user = query.from_user
                    await cmd_handlers.list_projects(fake_update, context)
                    await query.answer(_(user_id, 'project_archived_toast', project_name=project_name))
                else:
                    await query.answer(_(user_id, 'project_archive_fail'), show_alert=True)
            except Exception as e:
                log.error(f"Error marking project done for user {user_id}, data {data}: {e}", exc_info=True)
                await query.answer(_(user_id, 'error_generic'), show_alert=True)
        
        elif data.startswith("mark_task_done:"):
            try:
                task_id = int(data.split(":")[1])
                task_name = database.get_task_name(task_id) or _(user_id, 'text_unknown_task')
                success = database.mark_task_status(task_id, STATUS_DONE)
                if success:
                    log.info(f"User {user_id} marked task {task_id} ('{task_name}') as done.")
                    fake_update = Update(0, message=query.message)
                    fake_update._effective_user = query.from_user
                    await cmd_handlers.list_tasks(fake_update, context)
                    await query.answer(_(user_id, 'task_archived_toast', task_name=task_name))
                else:
                    await query.answer(_(user_id, 'task_archive_fail'), show_alert=True)
            except Exception as e:
                log.error(f"Error marking task done for user {user_id}, data {data}: {e}", exc_info=True)
                await query.answer(_(user_id, 'error_generic'), show_alert=True)
        
        elif data == "list_projects_done":
            log.debug(f"User {user_id} requested archived projects list.")
            await _display_archived_projects(query, user_id) # Use helper
        
        elif data == "list_tasks_done":
            log.debug(f"User {user_id} requested archived tasks list.")
            await _display_archived_tasks(query, user_id) # Use helper

        elif data.startswith("mark_project_active:"):
            try:
                project_id = int(data.split(":")[1])
                project_name = database.get_project_name(project_id) or _(user_id, 'text_unknown_project')
                success = database.mark_project_status(project_id, STATUS_ACTIVE)
                if success:
                    log.info(f"User {user_id} reactivated project {project_id} ('{project_name}').")
                    await _display_archived_projects(query, user_id)
                    await query.answer(_(user_id, 'project_reactivated_toast', project_name=project_name))
                else:
                    await query.answer(_(user_id, 'project_reactivate_fail'), show_alert=True)
            except Exception as e:
                log.error(f"Error reactivating project for user {user_id}, data {data}: {e}", exc_info=True)
                await query.answer(_(user_id, 'error_generic'), show_alert=True)

        elif data.startswith("mark_task_active:"):
            try:
                task_id = int(data.split(":")[1])
                task_name = database.get_task_name(task_id) or _(user_id, 'text_unknown_task')
                success = database.mark_task_status(task_id, STATUS_ACTIVE)
                if success:
                    log.info(f"User {user_id} reactivated task {task_id} ('{task_name}').")
                    await _display_archived_tasks(query, user_id)
                    await query.answer(_(user_id, 'task_reactivated_toast', task_name=task_name))
                else:
                    await query.answer(_(user_id, 'task_reactivate_fail'), show_alert=True)
            except Exception as e:
                log.error(f"Error reactivating task for user {user_id}, data {data}: {e}", exc_info=True)
                await query.answer(_(user_id, 'error_generic'), show_alert=True)
                
        elif data == "list_projects_active":
            log.debug(f"User {user_id} requested switch back to active projects list.")
            fake_update = Update(0, message=query.message)
            fake_update._effective_user = query.from_user
            await cmd_handlers.list_projects(fake_update, context)
            
        elif data == "list_tasks_active":
            log.debug(f"User {user_id} requested switch back to active tasks list.")
            fake_update = Update(0, message=query.message)
            fake_update._effective_user = query.from_user
            await cmd_handlers.list_tasks(fake_update, context)
            
        # --- Create New Project/Task Callbacks --- (Handled by prompting user_data flags)
        elif data == "create_new_project":
            log.debug(f"User {user_id} requested to create a new project via button.")
            await query.edit_message_text(_(user_id, 'callback_create_project_prompt'))
            context.user_data[user_id] = context.user_data.get(user_id, {})
            context.user_data[user_id]['expecting_project_name'] = True
            
        elif data == "create_new_task":
            log.debug(f"User {user_id} requested to create a new task via button.")
            current_project_id = database.get_current_project(user_id)
            if not current_project_id:
                await query.edit_message_text(_(user_id, 'task_create_no_project'))
                return
                
            project_name = database.get_project_name(current_project_id) or _(user_id, 'text_current_project')
            await query.edit_message_text(_(user_id, 'callback_create_task_prompt', project_name=project_name))
            context.user_data[user_id] = context.user_data.get(user_id, {})
            context.user_data[user_id]['expecting_task_name'] = True

        # --- Language Selection Callback ---
        elif data.startswith("set_lang:"):
            try:
                lang_code = data.split(":")[1]
                if set_user_lang(user_id, lang_code):
                    lang_name = get_language_name(lang_code)
                    success_message = _(user_id, 'language_set', language_name=lang_name)
                    log.info(f"User {user_id} set language to {lang_code}")
                    await query.edit_message_text(text=success_message)
                    # Resend the main menu prompt with the translated keyboard
                    main_menu_text = _(user_id, 'main_menu_prompt')
                    reply_markup = cmd_handlers.get_main_keyboard(user_id) # Get translated keyboard
                    await context.bot.send_message(user_id, main_menu_text, reply_markup=reply_markup) 
                else:
                    log.warning(f"Failed to set language to {lang_code} for user {user_id} (unsupported or DB error)")
                    await query.edit_message_text(text=_(user_id, 'error_set_language_fail')) # Use generic error in default lang
            except IndexError:
                 log.warning(f"Invalid set_lang callback data from user {user_id}: {data}")
                 await query.edit_message_text(_(user_id, 'error_set_language_invalid'))
            except Exception as e:
                 log.error(f"Unexpected error handling set_lang callback for user {user_id}: {e}", exc_info=True)
                 await query.edit_message_text(_(user_id, 'error_set_language_unexpected'))

        # --- Default Case --- 
        else:
            log.warning(f"Unhandled callback data from user {user_id}: {data}")
            await query.answer(_(user_id, 'action_unknown'))

    # Catch broader errors, including DB errors during the callback processing
    except sqlite3.Error as e:
        log.error(f"DB Error processing callback '{data}' for user {user_id}: {e}\n{traceback.format_exc()}")
        try: await query.edit_message_text(_(user_id, 'error_db')) # Use i18n error message
        except Exception: await query.answer(_(user_id, 'error_db_short'), show_alert=True) # Short i18n alert
    except Exception as e:
        log.error(f"Unexpected error processing callback '{data}' for user {user_id}: {e}\n{traceback.format_exc()}")
        try: await query.edit_message_text(_(user_id, 'error_unexpected')) # Use i18n error message
        except Exception: await query.answer(_(user_id, 'error_unexpected_short'), show_alert=True) # Short i18n alert 