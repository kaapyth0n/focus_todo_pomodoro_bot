import logging
from telegram import Update
from telegram.ext import ContextTypes
import database
from functools import wraps # For the decorator
from .google_auth import escape_markdown_v2 

log = logging.getLogger(__name__)

ADMIN_COMMAND_PREFIX = "/claim_admin_role_" # Obscure prefix
INITIAL_ADMIN_COMMAND = ADMIN_COMMAND_PREFIX + "734a" # Example full command

# --- Decorator for Admin Commands ---
def require_admin(func):
    """Decorator to check if the user executing the command is an admin."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if not database.is_user_admin(user_id):
            log.warning(f"User {user_id} attempted to use admin command {func.__name__} without permission.")
            await update.message.reply_text("Sorry, this command is only available to the bot admin.")
            return None # Indicate command should not proceed
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- Admin Command Handlers ---
async def set_initial_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows the first user to run this command to become the admin."""
    user = update.effective_user
    log.info(f"User {user.id} attempted command {INITIAL_ADMIN_COMMAND}")
    
    if database.check_if_admin_exists():
        log.warning(f"User {user.id} tried to claim admin role, but an admin already exists.")
        await update.message.reply_text("An admin for this bot has already been set.")
        return
        
    success = database.set_admin(user.id)
    if success:
        log.info(f"User {user.id} ({user.username or user.first_name}) successfully claimed the admin role.")
        await update.message.reply_text(f"Congratulations {user.first_name}! You are now the bot admin.")
        # Send notification to the new admin
        await send_admin_notification(context, f"Admin role claimed by user {user.id} ({user.username or user.first_name}).")
    else:
        log.error(f"Failed to set user {user.id} as admin in the database.")
        await update.message.reply_text("An error occurred trying to set the admin role. Please check the logs.")

@require_admin
async def admin_notify_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles admin notifications for user actions."""
    user_id = update.effective_user.id
    log.info(f"Admin {user_id} toggling notifications.")
    
    current_value = database.get_setting('admin_notifications_enabled', '0')
    new_value = '1' if current_value == '0' else '0'
    
    success = database.set_setting('admin_notifications_enabled', new_value)
    
    if success:
        status = "ENABLED" if new_value == '1' else "DISABLED"
        await update.message.reply_text(f"Admin notifications are now {status}.")
        log.info(f"Admin notifications set to {status} by user {user_id}.")
    else:
        await update.message.reply_text("Failed to update notification setting in the database.")

@require_admin
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays bot usage statistics to the admin."""
    user_id = update.effective_user.id
    log.info(f"Admin {user_id} requested stats.")
    
    try:
        total_users = database.get_total_users()
        total_projects = database.get_total_projects()
        total_tasks = database.get_total_tasks()
        total_minutes = database.get_total_work_minutes()
        total_hours = total_minutes / 60
        
        # Format and escape the time values
        formatted_minutes = f"{total_minutes:.1f}"
        formatted_hours = f"{total_hours:.1f}"
        escaped_minutes = escape_markdown_v2(formatted_minutes)
        escaped_hours = escape_markdown_v2(formatted_hours)
        
        # Construct the message using escaped values
        stats_message = (
            f"📊 *Bot Usage Statistics* 📊\n\n"
            f"👤 Total Users: {total_users}\n"
            f"🗂️ Total Projects: {total_projects}\n"
            f"📋 Total Tasks: {total_tasks}\n"
            f"⏱️ Total Work Time Logged: {escaped_minutes} minutes \\({escaped_hours} hours\\)"
        )
        
        await update.message.reply_text(stats_message, parse_mode='MarkdownV2')
    except Exception as e:
        log.error(f"Error fetching stats for admin {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while fetching statistics.")

# --- Notification Helper --- 
async def send_admin_notification(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Sends a message to the admin user if notifications are enabled."""
    try:
        notifications_enabled = database.get_setting('admin_notifications_enabled', '0') == '1'
        if not notifications_enabled:
            log.debug("Admin notifications disabled, skipping message.")
            return
            
        admin_id = database.get_admin_user_id()
        if not admin_id:
            log.warning("Admin notifications enabled, but no admin user found.")
            return
            
        log.debug(f"Sending notification to admin {admin_id}: {message[:50]}...") # Log snippet
        # Use a multi-line f-string for the text parameter
        notification_text = f"""🔔 Admin Notification:
{message}"""
        await context.bot.send_message(chat_id=admin_id, text=notification_text)
        
    except Exception as e:
        log.error(f"Failed to send admin notification: {e}", exc_info=True) 