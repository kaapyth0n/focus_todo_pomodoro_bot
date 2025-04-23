from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database
from config import timer_states # timer_states might be needed if we check active timers here
from .commands import report_daily, report_weekly, report_monthly, start_break_timer # Import report functions and break starter
import logging # Added previously
import sqlite3 # Need this for the exception type
import traceback

log = logging.getLogger(__name__)

# --- Callback Query Handler ---

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Acknowledge the button press immediately
    try:
        await query.answer()
    except Exception as e:
        log.warning(f"Failed to answer callback query {query.id}: {e}")

    data = query.data
    user_id = query.from_user.id
    log.debug(f"Callback received from user {user_id}: {data}")

    try:
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