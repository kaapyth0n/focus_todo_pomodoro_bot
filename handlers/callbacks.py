from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database
from config import timer_states # timer_states might be needed if we check active timers here
from .commands import report_daily, report_weekly, report_monthly, start_break_timer # Import report functions and break starter

# --- Callback Query Handler ---

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Acknowledge the button press
    
    data = query.data
    user_id = query.from_user.id

    # --- Report Callbacks ---
    if data == "report_daily":
        # Create a fake update to reuse the report command logic
        # Note: This approach might be simplified later
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
        
    # --- Selection Callbacks ---
    elif data.startswith("select_project:"):
        try:
            project_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            await query.edit_message_text('Error: Invalid project selection data.')
            return
            
        # Set current project in DB
        database.set_current_project(user_id, project_id)
        project_name = database.get_project_name(project_id) # Get name after setting
        
        if project_name:
            await query.edit_message_text(f'Project "{project_name}" selected.')
        else:
            # This case should be less likely if delete clears selection, but handle defensively
            await query.edit_message_text('Error: Project not found or could not be selected.')
            database.clear_current_project(user_id) # Clear selection if project invalid
            
    elif data.startswith("select_task:"):
        current_project_id = database.get_current_project(user_id)
        if not current_project_id:
            # Edit message first, then send follow-up if needed
            await query.edit_message_text('Please select a project first.')
            # Optionally send a new message prompting /list_projects
            # await context.bot.send_message(chat_id=user_id, text='Use /list_projects to select a project.')
            return
            
        try:
            task_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            await query.edit_message_text('Error: Invalid task selection data.')
            return
            
        # Set current task in DB
        database.set_current_task(user_id, task_id)
        task_name = database.get_task_name(task_id)
        
        if task_name:
            await query.edit_message_text(f'Task "{task_name}" selected.')
        else:
            await query.edit_message_text('Error: Task not found or could not be selected.')
            database.clear_current_task(user_id) # Clear selection if task invalid

    # --- Deletion Callbacks ---
    elif data == "cancel_delete":
        await query.edit_message_text("Deletion cancelled.")
        
    elif data.startswith("confirm_delete_project:"):
        try:
            project_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            await query.edit_message_text('Error: Invalid project deletion data.')
            return
            
        project_name = database.get_project_name(project_id) or "Unknown Project"
        keyboard = [
            [InlineKeyboardButton("🔴 Yes, DELETE it!", callback_data=f"delete_project:{project_id}")],
            [InlineKeyboardButton("🟢 No, cancel", callback_data="cancel_delete")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"❗️ Are you ABSOLUTELY SURE you want to delete project '{project_name}'?\n"
            f"This will delete all its tasks and recorded time entries.", 
            reply_markup=reply_markup
        )
        
    elif data.startswith("delete_project:"):
        try:
            project_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            await query.edit_message_text('Error: Invalid project deletion data.')
            return
            
        project_name = database.get_project_name(project_id) or "Unknown Project"
        deleted = database.delete_project(project_id)
        if deleted:
            await query.edit_message_text(f"✅ Project '{project_name}' and all associated data have been deleted.")
        else:
            await query.edit_message_text(f"❌ Failed to delete project '{project_name}'. Check logs or it might not exist.")
            
    elif data.startswith("confirm_delete_task:"):
        try:
            task_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            await query.edit_message_text('Error: Invalid task deletion data.')
            return
            
        task_name = database.get_task_name(task_id) or "Unknown Task"
        keyboard = [
            [InlineKeyboardButton("🔴 Yes, DELETE it!", callback_data=f"delete_task:{task_id}")],
            [InlineKeyboardButton("🟢 No, cancel", callback_data="cancel_delete")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"❗️ Are you ABSOLUTELY SURE you want to delete task '{task_name}'?\n"
            f"This will delete all its recorded time entries.", 
            reply_markup=reply_markup
        )
        
    elif data.startswith("delete_task:"):
        try:
            task_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            await query.edit_message_text('Error: Invalid task deletion data.')
            return
            
        task_name = database.get_task_name(task_id) or "Unknown Task"
        deleted = database.delete_task(task_id)
        if deleted:
            await query.edit_message_text(f"✅ Task '{task_name}' and its time entries have been deleted.")
        else:
            await query.edit_message_text(f"❌ Failed to delete task '{task_name}'. Check logs or it might not exist.")

    # --- Break Timer Callback ---
    elif data.startswith("start_break:"):
        # Check if another timer is already running
        if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
            await query.answer('Another timer is already active!', show_alert=True) # Show alert on button
            # Optionally edit message to remove buttons if timer started elsewhere
            try:
                await query.edit_message_text(f"{query.message.text}\n\n_(Another timer is active.)_", parse_mode='Markdown')
            except Exception: # Ignore if message can't be edited
                pass
            return
            
        try:
            duration_str = data.split(":")[1]
            duration_minutes = int(duration_str)
            if duration_minutes not in [5, 15]: # Example: only allow 5 or 15 min breaks via buttons
                raise ValueError("Invalid break duration from button")
        except (IndexError, ValueError):
            await query.edit_message_text('Error: Invalid break duration data.')
            return
            
        # Call the function to start the break timer
        # Pass context and user_id, let the function handle messaging
        started = await start_break_timer(context, user_id, duration_minutes)
        
        if started:
            # Edit the original message to remove the break buttons
            await query.edit_message_text(f"{query.message.text}\n\n*Starting {duration_minutes}-minute break...*", parse_mode='Markdown')
        else:
            # If start_break_timer failed (e.g., race condition with timer start), 
            # edit message to indicate failure
            await query.edit_message_text(f"{query.message.text}\n\n_Could not start break timer (maybe another timer started?)._", parse_mode='Markdown')

    else:
        # Handle unknown callback data gracefully
        await query.edit_message_text("Sorry, I didn't understand that button press.")
        print(f"Warning: Unhandled callback data: {data}") 