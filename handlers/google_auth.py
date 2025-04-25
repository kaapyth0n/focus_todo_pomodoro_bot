import logging
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
import database
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, GOOGLE_SCOPES
import json # Needed for loading credentials
from datetime import datetime # Needed for formatting date
import re # Import regex for escaping

# Check if Google libraries are available
try:
    from google_auth_oauthlib.flow import Flow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from google.auth.exceptions import RefreshError, GoogleAuthError
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False
    Flow, Request, Credentials, build, HttpError, RefreshError, GoogleAuthError = [None] * 7 # Assign None to all
    
log = logging.getLogger(__name__)

# Conversation states
WAITING_CODE = 0

# --- Helper to build the OAuth Flow ---
def _build_google_flow():
    """Builds the Google OAuth Flow object from configuration."""
    if not GOOGLE_LIBS_AVAILABLE:
        log.error("Google Auth libraries not installed. Cannot build OAuth flow.")
        return None
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        log.error("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in config. Cannot build OAuth flow.")
        return None

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI], # Needs to match Google Cloud Console config
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        }
    }
    
    try:
        # Note: We use 'offline' access type to get a refresh token
        flow = Flow.from_client_config(
            client_config, scopes=GOOGLE_SCOPES, redirect_uri=GOOGLE_REDIRECT_URI
        )
        return flow
    except Exception as e:
        log.error(f"Error creating Google OAuth Flow: {e}", exc_info=True)
        return None

# --- Helper to get Sheets API Service ---
def _get_sheets_service(user_id: int):
    """
    Gets an authorized Google Sheets API service object for the user.
    Handles loading credentials, refreshing tokens, and potential errors.
    Returns the service object or None if failed.
    """
    if not GOOGLE_LIBS_AVAILABLE:
        log.error("Google API libraries not installed. Cannot get Sheets service.")
        return None

    credentials_json = database.get_google_credentials(user_id)
    if not credentials_json:
        log.debug(f"No Google credentials found in DB for user {user_id}.")
        return None

    try:
        credentials = Credentials.from_authorized_user_info(json.loads(credentials_json), GOOGLE_SCOPES)

        # Check if token needs refreshing
        if credentials.expired and credentials.refresh_token:
            log.info(f"Refreshing Google token for user {user_id}...")
            try:
                credentials.refresh(Request())
                # Persist the refreshed credentials
                refreshed_json = credentials.to_json()
                database.store_google_credentials(user_id, refreshed_json)
                log.info(f"Successfully refreshed and stored Google token for user {user_id}.")
            except RefreshError as e:
                log.error(f"Failed to refresh Google token for user {user_id}: {e}. Clearing stored credentials.")
                database.store_google_credentials(user_id, None) # Clear invalid credentials
                return None # Indicate failure, user needs to re-authenticate
            except Exception as e:
                log.error(f"Unexpected error during token refresh for user {user_id}: {e}")
                return None # Indicate failure
                
        # Check if credentials are valid after potential refresh
        if not credentials or not credentials.valid:
             log.warning(f"Invalid Google credentials for user {user_id} after load/refresh.")
             return None

        # Build the Sheets API service
        service = build('sheets', 'v4', credentials=credentials)
        log.debug(f"Successfully obtained Google Sheets service for user {user_id}.")
        return service

    except json.JSONDecodeError as e:
        log.error(f"Error decoding stored Google credentials for user {user_id}: {e}. Clearing.")
        database.store_google_credentials(user_id, None)
        return None
    except Exception as e:
        log.error(f"Error building Google Sheets service for user {user_id}: {e}", exc_info=True)
        return None

async def _fetch_and_store_token(user_id: int, auth_code: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Helper function to fetch token using auth code and store it."""
    flow = _build_google_flow()
    if not flow:
        await context.bot.send_message(chat_id=user_id, text="Sorry, Google integration is not configured correctly.")
        return False

    try:
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        
        if not credentials or not credentials.valid:
             await context.bot.send_message(chat_id=user_id, text="Failed to obtain valid credentials from Google. Please try authorizing again with /connect_google.")
             return False
             
        if not credentials.refresh_token:
            log.warning(f"No refresh token received for user {user_id}. Full access might expire.")
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Warning: Could not obtain a long-term refresh token. You might need to reconnect periodically. "
                    "Try /connect_google again, ensuring you grant offline access if prompted."
                )
            )
                
        credentials_json = credentials.to_json()
        success = database.store_google_credentials(user_id, credentials_json)
        
        if success:
            await context.bot.send_message(chat_id=user_id, text="✅ Successfully connected to Google Sheets!")
            log.info(f"Successfully stored Google credentials for user {user_id}.")
            return True
        else:
            await context.bot.send_message(chat_id=user_id, text="❌ Failed to save Google connection details to the database.")
            log.error(f"Failed to store Google credentials in DB for user {user_id}.")
            return False

    except GoogleAuthError as e:
        log.error(f"Google Authentication error for user {user_id}: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=f"Authentication error: {e}. Please ensure the code is correct and try /connect_google again.")
        return False
    except Exception as e:
        log.error(f"Error fetching/storing token for user {user_id}: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text="An unexpected error occurred processing the code. Please try /connect_google again.")
        return False

async def _append_single_session_to_sheet(user_id: int, session_data: dict) -> bool:
    """
    Appends a single session's data to the user's default Google Sheet.
    
    Args:
        user_id: The user's Telegram ID.
        session_data: A dictionary containing session details like 
                      'start_time', 'duration_minutes', 'completed', 
                      'session_type', 'project_id', 'task_id'.
                      
    Returns:
        True if the append was successful, False otherwise.
    """
    log.debug(f"Attempting automatic append to sheet for user {user_id}.")
    if not GOOGLE_LIBS_AVAILABLE:
        log.warning(f"Google libs not available, cannot auto-append for user {user_id}.")
        return False # Should not happen if export works, but safety check
        
    sheet_id = database.get_google_sheet_id(user_id)
    if not sheet_id:
        log.debug(f"No default Google Sheet ID found for user {user_id}. Skipping auto-append.")
        return False # User hasn't set up or created a default sheet yet
        
    service = _get_sheets_service(user_id)
    if not service:
        log.warning(f"Failed to get Sheets service for user {user_id}. Skipping auto-append.")
        # _get_sheets_service handles logging credential errors and clearing if refresh fails
        return False
        
    # Prepare the data row
    try:
        start_time: datetime = session_data['start_time']
        project_id = session_data.get('project_id')
        task_id = session_data.get('task_id')
        
        date_str = start_time.strftime("%Y-%m-%d")
        project_name = database.get_project_name(project_id) if project_id else 'N/A'
        task_name = database.get_task_name(task_id) if task_id else 'N/A'
        duration = round(session_data.get('duration_minutes', 0), 2)
        session_type = session_data.get('session_type', 'work').capitalize()
        completed_str = 'Yes' if session_data.get('completed', 0) == 1 else 'No'
        
        row_values = [[date_str, project_name, task_name, duration, session_type, completed_str]]
        
        body = {'values': row_values}
        sheet_name = "Sheet1"
        range_name = f"'{sheet_name}'!A1"
        
        # Append the row
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=range_name, # Use quoted sheet name
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        log.info(f"Successfully auto-appended session to sheet {sheet_id} for user {user_id}.")
        return True
        
    except HttpError as e:
        log.error(f"Auto-append API error for user {user_id} to sheet {sheet_id}: {e}")
        # Don't notify user to avoid spam, just log
        return False
    except RefreshError:
        # Should be caught by _get_sheets_service, but catch as fallback
        log.error(f"Auto-append refresh error for user {user_id}. Credentials likely cleared.")
        return False
    except KeyError as e:
        log.error(f"Missing expected key in session_data for auto-append (user {user_id}): {e}")
        return False
    except Exception as e:
        log.error(f"Unexpected error during auto-append for user {user_id}: {e}", exc_info=True)
        return False

def escape_markdown_v2(text: str) -> str:
    """Helper function to escape text for MarkdownV2."""
    escape_chars = r'_\*[]()~`>#+-=|{}.!'
    # Simpler pattern: Match any character in the set
    pattern = f'[{re.escape(escape_chars)}]'
    # Replacement: Prepend a backslash to the matched character
    replacement = r'\\\g<0>' # Use \g<0> to reference the whole match
    return re.sub(pattern, replacement, str(text))

# --- Conversation Handlers ---
async def connect_google(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the Google OAuth flow and enters the WAITING_CODE state."""
    user_id = update.message.from_user.id
    log.info(f"User {user_id} initiated Google connection conversation.")

    if not GOOGLE_LIBS_AVAILABLE:
        await update.message.reply_text("Google integration libraries are not installed on the server.")
        return ConversationHandler.END
        
    flow = _build_google_flow()
    if not flow:
        await update.message.reply_text("Sorry, Google integration is not configured correctly on the server.")
        return ConversationHandler.END

    try:
        authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
        message = (
            "Please authorize access to Google Sheets:\n\n"
            f"1. Visit this URL: {authorization_url}\n\n"
            "2. Grant access to your Google account.\n\n"
            "3. Copy the authorization code provided after granting access.\n\n"
            "4. Paste the code directly into this chat. Use /cancel to abort."
        )
        await update.message.reply_text(message)
        log.debug(f"Sent authorization URL to user {user_id}, entering WAITING_CODE state.")
        return WAITING_CODE # Transition to the next state
        
    except Exception as e:
        log.error(f"Error generating authorization URL for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while trying to connect to Google. Please try again later.")
        return ConversationHandler.END

async def receive_oauth_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the pasted OAuth code and attempts to fetch the token."""
    user_id = update.message.from_user.id
    auth_code = update.message.text # Assume the entire message is the code
    log.info(f"Received potential OAuth code via text from user {user_id}.")

    if not auth_code:
        await update.message.reply_text("Did not receive a code. Please paste the code or use /cancel.")
        return WAITING_CODE # Stay in the same state

    # Call the helper to handle fetching and storing
    success = await _fetch_and_store_token(user_id, auth_code, context)
    
    # End the conversation regardless of success/failure in storing the token
    return ConversationHandler.END

async def cancel_oauth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the Google OAuth conversation."""
    user_id = update.message.from_user.id
    log.info(f"User {user_id} cancelled the Google OAuth flow.")
    await update.message.reply_text(
        "Google connection process cancelled.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# --- Standalone Command Handlers (like export) ---
async def export_to_sheets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exports all user Pomodoro sessions to a Google Sheet. Creates one if needed."""
    user_id = update.message.from_user.id
    log.info(f"User {user_id} initiated /export_to_sheets.")

    if not GOOGLE_LIBS_AVAILABLE:
        await update.message.reply_text("Google integration libraries are not installed on the server.")
        return

    # --- Determine Spreadsheet ID --- 
    spreadsheet_id = None
    sheet_name = "Sheet1"
    user_provided_id = None
    
    if context.args and len(context.args) > 0:
        user_provided_id = context.args[0]
        spreadsheet_id = user_provided_id
        if len(context.args) > 1:
            sheet_name = context.args[1].replace("!'", "")
        log.debug(f"User {user_id} provided Spreadsheet ID: {spreadsheet_id}, Sheet Name: {sheet_name}")
    else:
        log.debug(f"No Spreadsheet ID provided by user {user_id}. Checking DB.")
        spreadsheet_id = database.get_google_sheet_id(user_id)
        if spreadsheet_id:
            log.debug(f"Found stored Spreadsheet ID {spreadsheet_id} for user {user_id}.")
        else:
            log.debug(f"No stored Spreadsheet ID found for user {user_id}. Will attempt creation.")
            # spreadsheet_id remains None, triggering creation logic below

    # --- Get Sheets Service --- 
    service = _get_sheets_service(user_id)
    if not service:
        await update.message.reply_text(
            "Could not connect to Google Sheets. Have you authorized using `/connect_google`? "
            "Your access might have expired - try connecting again."
        )
        return

    # --- Create Spreadsheet if needed --- 
    if not spreadsheet_id:
        log.info(f"Creating new Google Sheet for user {user_id}.")
        await update.message.reply_text("No default sheet found. Creating a new Google Sheet for export...")
        try:
            spreadsheet_body = {
                'properties': {
                    'title': f'Focus Pomodoro Bot Export - User {user_id}'
                }
            }
            spreadsheet = service.spreadsheets().create(body=spreadsheet_body, fields='spreadsheetId').execute()
            spreadsheet_id = spreadsheet.get('spreadsheetId')
            if spreadsheet_id:
                database.store_google_sheet_id(user_id, spreadsheet_id)
                sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                
                # Escape variables for MarkdownV2
                escaped_sheet_id = escape_markdown_v2(spreadsheet_id)
                escaped_sheet_url = escape_markdown_v2(sheet_url)
                
                await update.message.reply_text(
                    f"✅ New Google Sheet created! ID: `{escaped_sheet_id}`\n"
                    f"URL: {escaped_sheet_url}\n"
                    f"This ID has been saved for future exports. Exporting data now...",
                    parse_mode='MarkdownV2' # Use MarkdownV2
                )
                log.info(f"Created and stored new sheet ID {spreadsheet_id} for user {user_id}.")
            else:
                raise ValueError("Spreadsheet creation API call did not return an ID.")
        except HttpError as e:
            log.error(f"Failed to create Google Sheet for user {user_id}: {e}", exc_info=True)
            await update.message.reply_text("❌ Failed to create a new Google Sheet. Please check bot permissions or try providing an existing sheet ID.")
            return
        except Exception as e:
            log.error(f"Unexpected error creating Google Sheet for user {user_id}: {e}", exc_info=True)
            await update.message.reply_text("❌ An unexpected error occurred while creating the Google Sheet.")
            return

    # --- Get Data and Export --- 
    export_data = database.get_all_user_sessions_for_export(user_id)
    if not export_data or len(export_data) <= 1: 
        await update.message.reply_text("No session data found to export.")
        return

    num_rows_to_export = len(export_data) - 1
    # Ensure sheet_name used here is also quoted in the range string
    escaped_sheet_id_md = escape_markdown_v2(spreadsheet_id)
    escaped_sheet_name_md = escape_markdown_v2(sheet_name)
    message_text = f"Found {num_rows_to_export} sessions\\. Attempting to export to Google Sheet \\`{escaped_sheet_id_md}\\` \\(Sheet: \\`{escaped_sheet_name_md}\\`\\)\\.\\.\\."
    await update.message.reply_text(message_text, parse_mode='MarkdownV2') 

    body = {'values': export_data}
    # Ensure range name uses the potentially overridden sheet_name
    range_name = f"'{sheet_name}'!A1"

    try:
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name, # Use quoted sheet name
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        updates = result.get('updates', {})
        rows_appended = updates.get('updatedRows', 0)
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        escaped_sheet_url = escape_markdown_v2(sheet_url)
        log.info(f"Successfully exported {rows_appended} rows for user {user_id} to sheet {spreadsheet_id}/{sheet_name}")
        # Escape the exclamation mark in the success message
        await update.message.reply_text(f"✅ Successfully exported {rows_appended} sessions\\!\\nSheet URL: {escaped_sheet_url}", parse_mode='MarkdownV2')

    except HttpError as e:
        log.error(f"Google Sheets API error for user {user_id} exporting to {spreadsheet_id}: {e}", exc_info=True)
        error_content = json.loads(e.content.decode('utf-8')).get('error', {})
        error_message = escape_markdown_v2(error_content.get('message', 'Unknown API error'))
        escaped_sheet_id_err = escape_markdown_v2(spreadsheet_id)
        if e.resp.status == 404:
             await update.message.reply_text(
                 f"❌ Error: Spreadsheet not found \\(ID: \\`{escaped_sheet_id_err}\\`\\)\\. Please check the ID and ensure the bot has access\\." 
                 f"If this was the default ID, try \\/connect\\_google again or provide an ID manually\\.",
                 parse_mode='MarkdownV2'
             )
        elif e.resp.status == 403:
             await update.message.reply_text(
                 f"❌ Error: Permission denied\\. Ensure the bot has edit access to the spreadsheet \\(ID: \\`{escaped_sheet_id_err}\\`\\)\\.",
                 parse_mode='MarkdownV2'
             )
        else:
             await update.message.reply_text(f"❌ Google Sheets API error: {error_message}", parse_mode='MarkdownV2')
             
    except RefreshError:
        log.error(f"Token refresh failed during export for user {user_id}. Instructing to re-auth.")
        await update.message.reply_text(
            "❌ Your Google connection has expired or been revoked. Please reconnect using `/connect_google` and try again."
        )
        database.store_google_credentials(user_id, None) 
         
    except Exception as e:
        log.error(f"Unexpected error during Google Sheets export for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred during export.") 