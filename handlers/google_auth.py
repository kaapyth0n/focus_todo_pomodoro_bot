import logging
from telegram import Update
from telegram.ext import ContextTypes
import database
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, GOOGLE_SCOPES

# Check if Google libraries are available
try:
    from google_auth_oauthlib.flow import Flow
    from google.auth.exceptions import RefreshError, GoogleAuthError
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False
    Flow = None # Define Flow as None if libs are missing
    RefreshError = None
    GoogleAuthError = None
    
log = logging.getLogger(__name__)

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

# --- Command Handlers ---
async def connect_google(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the Google OAuth flow."""
    user_id = update.message.from_user.id
    log.info(f"User {user_id} initiated Google connection.")

    if not GOOGLE_LIBS_AVAILABLE:
        await update.message.reply_text("Google integration libraries are not installed on the server.")
        return
        
    flow = _build_google_flow()
    if not flow:
        await update.message.reply_text("Sorry, Google integration is not configured correctly on the server.")
        return

    # Generate the authorization URL
    try:
        # We ask for offline access to get a refresh token
        authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
        
        # Store the state in user_data to verify during callback (optional but recommended)
        # context.user_data['oauth_state'] = state
        
        message = (
            "Please authorize access to Google Sheets:\n\n"
            f"1. Visit this URL: {authorization_url}\n\n"
            "2. Grant access to your Google account.\n\n"
            "3. Copy the authorization code provided after granting access.\n\n"
            "4. Send the code back to me using the command: `/oauth_code YOUR_CODE_HERE`"
        )
        await update.message.reply_text(message)
        log.debug(f"Sent authorization URL to user {user_id}.")
        
    except Exception as e:
        log.error(f"Error generating authorization URL for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while trying to connect to Google. Please try again later.")

async def handle_oauth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the authorization code provided by the user."""
    user_id = update.message.from_user.id
    log.info(f"Received OAuth code from user {user_id}.")

    if not GOOGLE_LIBS_AVAILABLE:
        await update.message.reply_text("Google integration libraries are not installed on the server.")
        return
        
    if not context.args or len(context.args) == 0:
        await update.message.reply_text("Please provide the authorization code. Usage: `/oauth_code YOUR_CODE_HERE`")
        return
        
    auth_code = context.args[0]
    
    flow = _build_google_flow()
    if not flow:
        await update.message.reply_text("Sorry, Google integration is not configured correctly on the server.")
        return

    try:
        # Verify state if stored previously (optional)
        # stored_state = context.user_data.pop('oauth_state', None)
        # if not stored_state or state != stored_state:
        #     await update.message.reply_text("OAuth state mismatch. Please try /connect_google again.")
        #     return

        # Exchange the authorization code for credentials
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        
        if not credentials or not credentials.valid:
             await update.message.reply_text("Failed to obtain valid credentials from Google. Please try authorizing again.")
             return
             
        if not credentials.refresh_token:
            log.warning(f"No refresh token received for user {user_id}. Full access might expire.")
            # This can happen if the user has previously authorized without 'prompt=consent'
            # or if the application type in Google Cloud doesn't support refresh tokens well.
            await update.message.reply_text(
                "Warning: Could not obtain a long-term refresh token. You might need to reconnect periodically. "
                "Try /connect_google again, ensuring you grant offline access if prompted."
                )
                
        # Store the credentials (contains access_token, refresh_token, scopes, etc.)
        credentials_json = credentials.to_json()
        success = database.store_google_credentials(user_id, credentials_json)
        
        if success:
            await update.message.reply_text("✅ Successfully connected to Google Sheets!")
            log.info(f"Successfully stored Google credentials for user {user_id}.")
        else:
            await update.message.reply_text("❌ Failed to save Google connection details to the database.")
            log.error(f"Failed to store Google credentials in DB for user {user_id}.")

    except GoogleAuthError as e:
        log.error(f"Google Authentication error for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"Authentication error: {e}. Please ensure the code is correct and try again.")
    except Exception as e:
        log.error(f"Error handling OAuth code for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred while processing the authorization code. Please try again later.") 