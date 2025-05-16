import logging
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import config
import database
import requests
import json

log = logging.getLogger(__name__)

# Conversation states
WAITING_JIRA_CODE = 0

# Jira OAuth 2.0 endpoints and scopes
JIRA_AUTH_URL = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
JIRA_API_BASE = "https://api.atlassian.com"
JIRA_SCOPES = [
    "read:jira-work",
    "write:jira-work",
    "read:jira-user",
    "offline_access"
]

# --- Helper to build the Jira OAuth URL ---
def build_jira_auth_url(user_id):
    if not config.JIRA_CLIENT_ID:
        log.error("JIRA_CLIENT_ID not set in config.")
        return None
    redirect_uri = f"{config.DOMAIN_URL}/oauth2callback/jira"
    scope = " ".join(JIRA_SCOPES)
    state = str(user_id)  # Use Telegram user_id as state for CSRF protection
    params = {
        "audience": "api.atlassian.com",
        "client_id": config.JIRA_CLIENT_ID,
        "scope": scope,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent"
    }
    from urllib.parse import urlencode
    return f"{JIRA_AUTH_URL}?{urlencode(params)}"

# --- Command handler to start Jira OAuth ---
async def connect_jira(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    log.info(f"User {user_id} initiated Jira connection.")
    if not config.JIRA_CLIENT_ID or not config.JIRA_CLIENT_SECRET:
        await update.message.reply_text("Jira integration is not configured on the server.")
        return ConversationHandler.END
    auth_url = build_jira_auth_url(user_id)
    if not auth_url:
        await update.message.reply_text("Failed to build Jira authorization URL. Contact the admin.")
        return ConversationHandler.END
    message = (
        "Please authorize access to your Jira account:\n\n"
        f"1. Visit this URL: {auth_url}\n\n"
        "2. Grant access to your Atlassian account.\n\n"
        "3. Copy the authorization code provided after granting access.\n\n"
        "4. Paste the code directly into this chat. Use /cancel to abort."
    )
    await update.message.reply_text(message)
    return WAITING_JIRA_CODE

# --- Handler to receive the pasted Jira OAuth code ---
async def receive_jira_oauth_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    auth_code = update.message.text.strip()
    log.info(f"Received Jira OAuth code from user {user_id}.")
    if not auth_code:
        await update.message.reply_text("Did not receive a code. Please paste the code or use /cancel.")
        return WAITING_JIRA_CODE
    # Exchange code for tokens
    redirect_uri = f"{config.DOMAIN_URL}/oauth2callback/jira"
    data = {
        "grant_type": "authorization_code",
        "client_id": config.JIRA_CLIENT_ID,
        "client_secret": config.JIRA_CLIENT_SECRET,
        "code": auth_code,
        "redirect_uri": redirect_uri
    }
    try:
        resp = requests.post(JIRA_TOKEN_URL, json=data, timeout=10)
        if resp.status_code != 200:
            log.error(f"Jira token exchange failed: {resp.text}")
            await update.message.reply_text(f"Failed to exchange code for tokens. Jira API error: {resp.text}")
            return ConversationHandler.END
        token_data = resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            await update.message.reply_text("Failed to obtain access token from Jira.")
            return ConversationHandler.END
        # Fetch cloudId for the user
        headers = {"Authorization": f"Bearer {access_token}"}
        cloud_resp = requests.get(f"{JIRA_API_BASE}/oauth/token/accessible-resources", headers=headers, timeout=10)
        if cloud_resp.status_code != 200:
            log.error(f"Failed to fetch Jira cloudId: {cloud_resp.text}")
            await update.message.reply_text(f"Failed to fetch Jira cloudId: {cloud_resp.text}")
            return ConversationHandler.END
        resources = cloud_resp.json()
        if not resources or not isinstance(resources, list) or not resources:
            await update.message.reply_text("No accessible Jira Cloud resources found for your account.")
            return ConversationHandler.END
        # For now, pick the first accessible resource
        cloud_id = resources[0].get("id")
        if not cloud_id:
            await update.message.reply_text("Could not determine your Jira Cloud ID.")
            return ConversationHandler.END
        # Store credentials and cloud_id
        credentials_json = json.dumps(token_data)
        success = database.store_jira_credentials(user_id, credentials_json, cloud_id)
        if success:
            await update.message.reply_text("✅ Successfully connected to Jira Cloud!")
            log.info(f"Stored Jira credentials and cloudId for user {user_id}.")
        else:
            await update.message.reply_text("❌ Failed to save Jira connection details to the database.")
            log.error(f"Failed to store Jira credentials in DB for user {user_id}.")
    except Exception as e:
        log.error(f"Error during Jira OAuth token exchange: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred during Jira connection. Please try again.")
    return ConversationHandler.END

# --- Handler to cancel the Jira OAuth flow ---
async def cancel_jira_oauth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    log.info(f"User {user_id} cancelled the Jira OAuth flow.")
    await update.message.reply_text(
        "Jira connection process cancelled.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# --- Command handler to disconnect Jira ---
async def disconnect_jira(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    database.clear_jira_credentials(user_id)
    await update.message.reply_text("Disconnected from Jira Cloud. Your credentials have been removed.")

# --- Command handler to fetch Jira projects ---
async def fetch_jira_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    creds_json, cloud_id = database.get_jira_credentials(user_id)
    if not creds_json or not cloud_id:
        await update.message.reply_text("You are not connected to Jira. Use /connect_jira first.")
        return
    try:
        creds = json.loads(creds_json)
        access_token = creds.get("access_token")
        refresh_token = creds.get("refresh_token")
        expires_in = creds.get("expires_in")
        # TODO: Handle token refresh if needed (for now, assume valid)
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        # JQL: assigned to current user, unresolved
        jql = "assignee = currentUser() AND resolution = Unresolved"
        url = f"{JIRA_API_BASE}/ex/jira/{cloud_id}/rest/api/3/search?jql={jql}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            await update.message.reply_text(f"Failed to fetch Jira issues: {resp.text}")
            return
        data = resp.json()
        issues = data.get("issues", [])
        if not issues:
            await update.message.reply_text("No open Jira issues assigned to you were found.")
            return
        # Extract unique project names
        projects = {}
        for issue in issues:
            proj = issue.get("fields", {}).get("project", {})
            proj_id = proj.get("id")
            proj_name = proj.get("name")
            if proj_id and proj_name:
                projects[proj_id] = proj_name
        if not projects:
            await update.message.reply_text("No Jira projects found for your assigned issues.")
            return
        # Display as buttons
        keyboard = [[InlineKeyboardButton(name, callback_data=f"jira_project:{pid}")] for pid, name in projects.items()]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Jira Projects with your open issues:", reply_markup=reply_markup)
    except Exception as e:
        log.error(f"Error fetching Jira projects: {e}", exc_info=True)
        await update.message.reply_text("An error occurred fetching Jira projects. Please try again.")

# --- Callback query handler for jira_project:<project_id> ---
async def jira_project_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if not data.startswith("jira_project:"):
        return
    project_id = data.split(":")[1]
    creds_json, cloud_id = database.get_jira_credentials(user_id)
    if not creds_json or not cloud_id:
        await query.edit_message_text("You are not connected to Jira. Use /connect_jira first.")
        return
    try:
        creds = json.loads(creds_json)
        access_token = creds.get("access_token")
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        # JQL: assigned to current user, unresolved, in selected project
        jql = f"assignee = currentUser() AND resolution = Unresolved AND project = {project_id}"
        url = f"{JIRA_API_BASE}/ex/jira/{cloud_id}/rest/api/3/search?jql={jql}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            await query.edit_message_text(f"Failed to fetch Jira issues: {resp.text}")
            return
        data = resp.json()
        issues = data.get("issues", [])
        if not issues:
            await query.edit_message_text("No open Jira issues assigned to you in this project.")
            return
        # Display issues as buttons
        keyboard = []
        for issue in issues:
            key = issue.get("key")
            summary = issue.get("fields", {}).get("summary", "(No summary)")
            keyboard.append([InlineKeyboardButton(f"[{key}] {summary}", callback_data=f"jira_issue:{key}")])
        # Add 'Add All Tasks' button
        keyboard.append([InlineKeyboardButton("➕ Add All Tasks", callback_data=f"jira_add_all:{project_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Open Jira issues assigned to you in this project:", reply_markup=reply_markup)
    except Exception as e:
        log.error(f"Error fetching Jira issues for project: {e}", exc_info=True)
        await query.edit_message_text("An error occurred fetching Jira issues. Please try again.")

# --- Callback query handler for jira_add_all:<project_id> ---
async def jira_add_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if not data.startswith("jira_add_all:"):
        return
    project_id = data.split(":")[1]
    creds_json, cloud_id = database.get_jira_credentials(user_id)
    if not creds_json or not cloud_id:
        await query.edit_message_text("You are not connected to Jira. Use /connect_jira first.")
        return
    try:
        creds = json.loads(creds_json)
        access_token = creds.get("access_token")
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        # JQL: assigned to current user, unresolved, in selected project
        jql = f"assignee = currentUser() AND resolution = Unresolved AND project = {project_id}"
        url = f"{JIRA_API_BASE}/ex/jira/{cloud_id}/rest/api/3/search?jql={jql}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            await query.edit_message_text(f"Failed to fetch Jira issues: {resp.text}")
            return
        data = resp.json()
        issues = data.get("issues", [])
        if not issues:
            await query.edit_message_text("No open Jira issues assigned to you in this project.")
            return
        # Get or create the bot project
        project_name = None
        if issues:
            project_name = issues[0].get("fields", {}).get("project", {}).get("name")
        if not project_name:
            await query.edit_message_text("Could not determine Jira project name.")
            return
        projects = database.get_projects(user_id)
        project_id_db = None
        for pid, pname in projects:
            if pname == project_name:
                project_id_db = pid
                break
        if not project_id_db:
            project_id_db = database.add_project(user_id, project_name)
        # Import all issues as tasks
        tasks = database.get_tasks(project_id_db)
        existing_task_names = set(t[1] for t in tasks)
        imported = 0
        for issue in issues:
            key = issue.get("key")
            summary = issue.get("fields", {}).get("summary", "(No summary)")
            jira_task_name = f"[{key}] {summary}"
            if jira_task_name not in existing_task_names:
                database.add_task(project_id_db, jira_task_name)
                imported += 1
        await query.edit_message_text(f"Imported {imported} Jira issues as tasks into project '{project_name}'.")
    except Exception as e:
        log.error(f"Error importing all Jira issues as tasks: {e}", exc_info=True)
        await query.edit_message_text("An error occurred importing Jira issues as tasks. Please try again.")

# --- Callback query handler for jira_issue:<issue_key> ---
async def jira_issue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if not data.startswith("jira_issue:"):
        return
    issue_key = data.split(":")[1]
    creds_json, cloud_id = database.get_jira_credentials(user_id)
    if not creds_json or not cloud_id:
        await query.edit_message_text("You are not connected to Jira. Use /connect_jira first.")
        return
    try:
        creds = json.loads(creds_json)
        access_token = creds.get("access_token")
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        # Fetch issue details
        url = f"{JIRA_API_BASE}/ex/jira/{cloud_id}/rest/api/3/issue/{issue_key}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            await query.edit_message_text(f"Failed to fetch Jira issue details: {resp.text}")
            return
        issue = resp.json()
        summary = issue.get("fields", {}).get("summary", "(No summary)")
        project = issue.get("fields", {}).get("project", {})
        project_name = project.get("name")
        if not project_name:
            await query.edit_message_text("Could not determine Jira project name for this issue.")
            return
        # Check if bot project exists, else create
        projects = database.get_projects(user_id)
        project_id = None
        for pid, pname in projects:
            if pname == project_name:
                project_id = pid
                break
        if not project_id:
            project_id = database.add_project(user_id, project_name)
        # Check if task already exists (by name prefix)
        tasks = database.get_tasks(project_id)
        jira_task_name = f"[{issue_key}] {summary}"
        for tid, tname in tasks:
            if tname == jira_task_name:
                await query.edit_message_text(f"Task already imported: {jira_task_name}")
                return
        # Create the task
        task_id = database.add_task(project_id, jira_task_name)
        if task_id:
            await query.edit_message_text(f"✅ Imported Jira issue as task: {jira_task_name}")
        else:
            await query.edit_message_text(f"❌ Failed to import Jira issue as task.")
    except Exception as e:
        log.error(f"Error importing Jira issue as task: {e}", exc_info=True)
        await query.edit_message_text("An error occurred importing the Jira issue. Please try again.")

# --- Callback query handler for log_jira:<jira_key>:<minutes> ---
async def log_jira_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if data == "log_jira:skip":
        await query.edit_message_text("Jira worklog skipped.")
        return
    if not data.startswith("log_jira:"):
        return
    try:
        _, jira_key, minutes = data.split(":")
        minutes = float(minutes)
        creds_json, cloud_id = database.get_jira_credentials(user_id)
        if not creds_json or not cloud_id:
            await query.edit_message_text("You are not connected to Jira. Use /connect_jira first.")
            return
        creds = json.loads(creds_json)
        access_token = creds.get("access_token")
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json", "Content-Type": "application/json"}
        # Jira expects timeSpent in format like "25m"
        time_spent = f"{int(round(minutes))}m"
        worklog_url = f"{JIRA_API_BASE}/ex/jira/{cloud_id}/rest/api/3/issue/{jira_key}/worklog"
        body = {"timeSpent": time_spent, "comment": "Logged from Focus Pomodoro Bot"}
        resp = requests.post(worklog_url, headers=headers, json=body, timeout=10)
        if resp.status_code in (200, 201):
            await query.edit_message_text(f"✅ Work logged to Jira issue {jira_key} ({time_spent})")
        else:
            await query.edit_message_text(f"❌ Failed to log work to Jira: {resp.text}")
    except Exception as e:
        log.error(f"Error logging work to Jira: {e}", exc_info=True)
        await query.edit_message_text("An error occurred logging work to Jira. Please try again.") 