from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database
from database import STATUS_ACTIVE, STATUS_DONE # Import status constants
from config import timer_states # timer_states might be needed if we check active timers here
from . import commands as cmd_handlers # Import commands module to call list handlers
from .commands import report_daily, report_weekly, report_monthly, start_break_timer # Import report functions and break starter
import logging # Added previously
import sqlite3 # Need this for the exception type
import traceback

log = logging.getLogger(__name__)

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
                text="Use the `/create_project \"Project Name\"` command to add your first project.",
                reply_markup=None # Remove buttons
            )
            return
        elif data == "noop_create_task":
            log.debug(f"Handling create task instruction callback: {data}")
            current_project_id = database.get_current_project(user_id)
            project_name = database.get_project_name(current_project_id) if current_project_id else "the current project"
            await query.edit_message_text(
                text=f"Use the `/create_task \"Task Name\"` command to add a task to '{project_name}'.",
                reply_markup=None # Remove buttons
            )
            return
            
        # --- Generic No-op Callbacks (e.g., for archived item names) ---
        elif data.startswith("noop_"):
            log.debug(f"Handled generic no-op callback: {data}")
            # Just acknowledge, don't change the message or remove buttons
            return 

        # --- Report Callbacks ---
        if data == "report_daily":
            log.info(f"User {user_id} triggered daily report via callback.")
            fake_update = Update(0, message=query.message) # Correct way to init Update
            fake_update._effective_user = query.from_user # Pass user info
            await report_daily(fake_update, context)
        elif data == "report_weekly":
            log.info(f"User {user_id} triggered weekly report via callback.")
            fake_update = Update(0, message=query.message)
            fake_update._effective_user = query.from_user
            await report_weekly(fake_update, context)
        elif data == "report_monthly":
            log.info(f"User {user_id} triggered monthly report via callback.")
            fake_update = Update(0, message=query.message)
            fake_update._effective_user = query.from_user
            await report_monthly(fake_update, context)
        
        # --- Selection Callbacks ---
        elif data.startswith("select_project:"):
            try:
                project_id = int(data.split(":")[1])
                project_name = database.get_project_name(project_id) or "Unknown Project"

                database.set_current_project(user_id, project_id)
                database.set_current_task(user_id, None)
                log.info(f"User {user_id} selected project {project_id} ('{project_name}') via callback.")
                await query.edit_message_text(text=f"Project '{project_name}' selected. Use /list_tasks to see or add tasks.")
            except (IndexError, ValueError) as e:
                log.warning(f"Error parsing select_project callback data '{data}' for user {user_id}: {e}")
                await query.edit_message_text(text="Error processing selection.")
            except sqlite3.Error as e:
                log.error(f"DB Error selecting project via callback for user {user_id}: {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="Database error during project selection.")
            except Exception as e:
                log.error(f"Unexpected error handling select_project callback for user {user_id}: {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="An unexpected error occurred.")
        
        elif data.startswith("select_task:"):
            try:
                task_id = int(data.split(":")[1])
                current_project_id = database.get_current_project(user_id)
                if not current_project_id:
                     log.warning(f"User {user_id} tried to select task via callback with no project selected.")
                     await query.edit_message_text(text="Please select a project first using /select_project.")
                     return
                    
                task_name = database.get_task_name(task_id)
                if task_name is None:
                    log.warning(f"User {user_id} tried to select non-existent/mismatched task ID {task_id} via callback.")
                    await query.edit_message_text(text="Task not found or doesn't belong to the current project.")
                    return
                    
                database.set_current_task(user_id, task_id)
                log.info(f"User {user_id} selected task {task_id} ('{task_name}') via callback.")
                await query.edit_message_text(text=f"Task '{task_name}' selected.")
            except (IndexError, ValueError) as e:
                 log.warning(f"Error parsing select_task callback data '{data}' for user {user_id}: {e}")
                 await query.edit_message_text(text="Error processing task selection.")
            except sqlite3.Error as e:
                log.error(f"DB Error selecting task via callback for user {user_id}: {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="Database error during task selection.")
            except Exception as e:
                log.error(f"Unexpected error handling select_task callback for user {user_id}: {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="An unexpected error occurred.")

        # --- Deletion Callbacks ---
        elif data == "cancel_delete":
            log.debug(f"User {user_id} cancelled deletion via callback.")
            await query.edit_message_text(text="Deletion cancelled.")
            
        elif data.startswith("confirm_delete_project:"):
            try:
                project_id_str = data.split(":")[1]
                project_id = int(project_id_str)
            except (IndexError, ValueError):
                log.warning(f"Invalid confirm_delete_project data from user {user_id}: {data}")
                await query.edit_message_text('Error: Invalid deletion data.')
                return
            
            project_name = database.get_project_name(project_id) or "Unknown Project"
            keyboard = [
                [InlineKeyboardButton("🔴 Yes, DELETE!", callback_data=f"delete_project:{project_id}")],
                [InlineKeyboardButton("🟢 No, cancel", callback_data="cancel_delete")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"❗️ FINAL CONFIRMATION: Delete project '{project_name}'?\n(This deletes ALL associated tasks and time entries!) ", 
                reply_markup=reply_markup
            )
            log.debug(f"Sent final project deletion confirmation for project {project_id} to user {user_id}")

        elif data.startswith("delete_project:"):
            project_id = None
            project_name_for_log = "unknown"
            try:
                project_id = int(data.split(":")[1])
                project_name = database.get_project_name(project_id)
                project_name_for_log = project_name or "unknown"
                if project_name is None:
                    log.warning(f"Attempt to delete non-existent project ID {project_id} by user {user_id} via callback")
                    await query.answer("Error: Project not found.", show_alert=True)
                    await query.edit_message_text(text="Error finding project to delete.")
                    return

                deleted = database.delete_project(project_id)
                if deleted:
                    log.info(f"User {user_id} deleted project {project_id} ('{project_name}') via callback.")
                    await query.edit_message_text(text=f"Project '{project_name}' and its tasks deleted.")
                else:
                    log.warning(f"Failed to delete project {project_id} ('{project_name}') for user {user_id} via callback. DB function returned false.")
                    await query.edit_message_text(text=f"Failed to delete project '{project_name}'. Database error likely.")
            except (IndexError, ValueError) as e:
                 log.warning(f"Error parsing delete_project callback data '{data}' for user {user_id}: {e}")
                 await query.edit_message_text(text="Error processing deletion command.")
            except sqlite3.Error as e:
                log.error(f"DB Error deleting project via callback for user {user_id}, project_id {project_id}: {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="Database error during project deletion.")
                await query.answer("Database error occurred.", show_alert=True)
            except Exception as e:
                log.error(f"Unexpected error handling delete_project callback for user {user_id}, project_id {project_id} ('{project_name_for_log}'): {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="An unexpected error occurred during deletion.")
                await query.answer("An unexpected error occurred.", show_alert=True)
            
        elif data.startswith("confirm_delete_task:"):
            try:
                task_id_str = data.split(":")[1]
                task_id = int(task_id_str)
            except (IndexError, ValueError):
                log.warning(f"Invalid confirm_delete_task data from user {user_id}: {data}")
                await query.edit_message_text('Error: Invalid deletion data.')
                return
            
            task_name = database.get_task_name(task_id) or "Unknown Task"
            keyboard = [
                [InlineKeyboardButton("🔴 Yes, DELETE!", callback_data=f"delete_task:{task_id}")],
                [InlineKeyboardButton("🟢 No, cancel", callback_data="cancel_delete")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"❗️ FINAL CONFIRMATION: Delete task '{task_name}'?\n(This deletes its recorded time entries!) ", 
                reply_markup=reply_markup
            )
            log.debug(f"Sent final task deletion confirmation for task {task_id} to user {user_id}")

        elif data.startswith("delete_task:"):
            task_id = None
            task_name_for_log = "unknown"
            try:
                task_id = int(data.split(":")[1])
                task_name = database.get_task_name(task_id)
                task_name_for_log = task_name or "unknown"
                if task_name is None:
                    log.warning(f"Attempt to delete non-existent task ID {task_id} by user {user_id} via callback")
                    await query.answer("Error: Task not found.", show_alert=True)
                    await query.edit_message_text(text="Error finding task to delete.")
                    return
                
                deleted = database.delete_task(task_id)
                if deleted:
                    log.info(f"User {user_id} deleted task {task_id} ('{task_name}') via callback.")
                    await query.edit_message_text(text=f"Task '{task_name}' deleted.")
                else:
                    log.warning(f"Failed to delete task {task_id} ('{task_name}') for user {user_id} via callback. DB function returned false.")
                    await query.edit_message_text(text=f"Failed to delete task '{task_name}'. Database error likely.")
            except (IndexError, ValueError) as e:
                 log.warning(f"Error parsing delete_task callback data '{data}' for user {user_id}: {e}")
                 await query.edit_message_text(text="Error processing deletion command.")
            except sqlite3.Error as e:
                log.error(f"DB Error deleting task via callback for user {user_id}, task_id {task_id}: {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="Database error during task deletion.")
                await query.answer("Database error occurred.", show_alert=True)
            except Exception as e:
                log.error(f"Unexpected error handling delete_task callback for user {user_id}, task_id {task_id} ('{task_name_for_log}'): {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="An unexpected error occurred during deletion.")
                await query.answer("An unexpected error occurred.", show_alert=True)

        # --- Break Timer Callback ---
        elif data.startswith("start_break:"):
            log.debug(f"Handling start_break callback for user {user_id}")
            timer_states = context.bot_data.setdefault('timer_states', {})
            if user_id in timer_states and timer_states[user_id].get('status') in ['running', 'paused']:
                log.warning(f"User {user_id} tried to start a break timer via callback while another timer is active.")
                await query.answer("Another timer is already active! Stop it first.", show_alert=True)
                return

            try:
                duration_minutes = int(data.split(":")[1])
                log.info(f"User {user_id} starting {duration_minutes} min break via callback.")
                await start_break_timer(context, user_id, duration_minutes)
                await query.edit_message_text(text=f"Break timer started for {duration_minutes} minutes!", reply_markup=None)
            except (IndexError, ValueError) as e:
                log.warning(f"Error parsing break duration from callback '{data}' for user {user_id}: {e}")
                await query.edit_message_text(text="Error starting break timer.")
            except Exception as e:
                log.error(f"Unexpected error handling start_break callback for user {user_id}: {e}\\n{traceback.format_exc()}")
                await query.edit_message_text(text="An unexpected error occurred while starting the break.")
                await query.answer("An unexpected error occurred.", show_alert=True)

        # --- Done/Archive Callbacks --- 
        elif data.startswith("mark_project_done:"):
            try:
                project_id = int(data.split(":")[1])
                project_name = database.get_project_name(project_id) or "Unknown Project"
                success = database.mark_project_status(project_id, STATUS_DONE)
                if success:
                    log.info(f"User {user_id} marked project {project_id} ('{project_name}') as done.")
                    # Refresh the list by calling the list command handler
                    fake_update = Update(0, message=query.message)
                    fake_update._effective_user = query.from_user
                    await cmd_handlers.list_projects(fake_update, context)
                    await query.answer(f"Project '{project_name}' marked done & archived.") # Show toast
                else:
                    await query.answer("Failed to mark project as done.", show_alert=True)
            except Exception as e:
                log.error(f"Error marking project done for user {user_id}, data {data}: {e}", exc_info=True)
                await query.answer("An error occurred.", show_alert=True)
        
        elif data.startswith("mark_task_done:"):
            try:
                task_id = int(data.split(":")[1])
                task_name = database.get_task_name(task_id) or "Unknown Task"
                success = database.mark_task_status(task_id, STATUS_DONE)
                if success:
                    log.info(f"User {user_id} marked task {task_id} ('{task_name}') as done.")
                    # Refresh the list
                    fake_update = Update(0, message=query.message)
                    fake_update._effective_user = query.from_user
                    await cmd_handlers.list_tasks(fake_update, context)
                    await query.answer(f"Task '{task_name}' marked done & archived.") # Show toast
                else:
                    await query.answer("Failed to mark task as done.", show_alert=True)
            except Exception as e:
                log.error(f"Error marking task done for user {user_id}, data {data}: {e}", exc_info=True)
                await query.answer("An error occurred.", show_alert=True)
        
        elif data == "list_projects_done":
            log.debug(f"User {user_id} requested archived projects list.")
            try:
                projects = database.get_projects(user_id, status=STATUS_DONE)
                keyboard = []
                if not projects:
                     keyboard.append([InlineKeyboardButton("No archived projects found.", callback_data="noop_no_archive")])
                else:
                     for project_id, project_name in projects:
                         # Row: [Project Name (no action), Reactivate Button]
                         keyboard.append([
                             InlineKeyboardButton(project_name, callback_data=f"noop_project:{project_id}"), 
                             InlineKeyboardButton("↩️ Reactivate", callback_data=f"mark_project_active:{project_id}")
                         ])
                # Add button to go back to active list
                keyboard.append([InlineKeyboardButton("« Back to Active Projects", callback_data="list_projects_active")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("Archived Projects:", reply_markup=reply_markup)
            except Exception as e:
                log.error(f"Error listing archived projects for user {user_id}: {e}", exc_info=True)
                await query.edit_message_text("An error occurred listing archived projects.")
        
        elif data == "list_tasks_done":
            log.debug(f"User {user_id} requested archived tasks list.")
            try:
                current_project_id = database.get_current_project(user_id)
                if not current_project_id:
                     await query.edit_message_text("Please select an active project first.")
                     return
                project_name = database.get_project_name(current_project_id) or "Selected Project"
                tasks = database.get_tasks(current_project_id, status=STATUS_DONE)
                keyboard = []
                if not tasks:
                    keyboard.append([InlineKeyboardButton("No archived tasks found.", callback_data="noop_no_archive")])
                else:
                     for task_id, task_name in tasks:
                         keyboard.append([
                             InlineKeyboardButton(task_name, callback_data=f"noop_task:{task_id}"),
                             InlineKeyboardButton("↩️ Reactivate", callback_data=f"mark_task_active:{task_id}")
                         ])
                keyboard.append([InlineKeyboardButton("« Back to Active Tasks", callback_data="list_tasks_active")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(f"Archived Tasks in '{project_name}':", reply_markup=reply_markup)
            except Exception as e:
                log.error(f"Error listing archived tasks for user {user_id}: {e}", exc_info=True)
                await query.edit_message_text("An error occurred listing archived tasks.")

        elif data.startswith("mark_project_active:"):
            try:
                project_id = int(data.split(":")[1])
                project_name = database.get_project_name(project_id) or "Unknown Project"
                success = database.mark_project_status(project_id, STATUS_ACTIVE)
                if success:
                    log.info(f"User {user_id} reactivated project {project_id} ('{project_name}').")
                    # Refresh the archived list view
                    fake_update = Update(0, message=query.message)
                    fake_update._effective_user = query.from_user
                    # Temporarily set data to re-trigger the archived list handler
                    context.callback_data_override = "list_projects_done" 
                    await button_callback(fake_update, context) 
                    del context.callback_data_override # Clean up override
                    await query.answer(f"Project '{project_name}' reactivated.")
                else:
                    await query.answer("Failed to reactivate project.", show_alert=True)
            except Exception as e:
                log.error(f"Error reactivating project for user {user_id}, data {data}: {e}", exc_info=True)
                await query.answer("An error occurred.", show_alert=True)

        elif data.startswith("mark_task_active:"):
            try:
                task_id = int(data.split(":")[1])
                task_name = database.get_task_name(task_id) or "Unknown Task"
                success = database.mark_task_status(task_id, STATUS_ACTIVE)
                if success:
                    log.info(f"User {user_id} reactivated task {task_id} ('{task_name}').")
                    # Refresh the archived list view
                    fake_update = Update(0, message=query.message)
                    fake_update._effective_user = query.from_user
                    context.callback_data_override = "list_tasks_done"
                    await button_callback(fake_update, context)
                    del context.callback_data_override
                    await query.answer(f"Task '{task_name}' reactivated.")
                else:
                    await query.answer("Failed to reactivate task.", show_alert=True)
            except Exception as e:
                log.error(f"Error reactivating task for user {user_id}, data {data}: {e}", exc_info=True)
                await query.answer("An error occurred.", show_alert=True)
                
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

        # --- Default Case --- 
        else:
            log.warning(f"Unhandled callback data from user {user_id}: {data}")
            await query.answer("Unknown action.")

    # Catch broader errors, including DB errors during the callback processing
    except sqlite3.Error as e:
        log.error(f"DB Error processing callback '{data}' for user {user_id}: {e}\\n{traceback.format_exc()}")
        try: await query.edit_message_text("A database error occurred.")
        except Exception: await query.answer("Database error", show_alert=True)
    except Exception as e:
        log.error(f"Unexpected error processing callback '{data}' for user {user_id}: {e}", exc_info=True)
        try: await query.edit_message_text("An unexpected error occurred.")
        except Exception: await query.answer("Unexpected error", show_alert=True) 