import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Telegram Bot Configuration ---
TOKEN = os.getenv('BOT_TOKEN')
DOMAIN_URL = os.getenv('DOMAIN_URL', 'http://127.0.0.1:8080') # Default for local testing
FLASK_PORT = int(os.getenv('FLASK_PORT', 5002))
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID') # Optional Admin User ID

# Validate required environment variables
if not TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")
if not DOMAIN_URL:
    print("Warning: DOMAIN_URL not found in environment variables. Using localhost as fallback.")
    DOMAIN_URL = f"http://localhost:{FLASK_PORT}"

print(f"Configuration loaded: DOMAIN_URL={DOMAIN_URL}, FLASK_PORT={FLASK_PORT}")

# --- Google API Configuration ---
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
# Use 'urn:ietf:wg:oauth:2.0:oob' for the code copy/paste flow if no web server redirect is set up
GOOGLE_REDIRECT_URI = f"{DOMAIN_URL}/oauth2callback" # Matches the one in web_app.py and Google Console
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/spreadsheets'] # Scope for accessing Sheets

if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    print("Warning: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not found in environment variables. Google Sheets integration will not work.")
    # Set them to None or empty strings to avoid errors later if they are used without being set
    GOOGLE_CLIENT_ID = None
    GOOGLE_CLIENT_SECRET = None

print(f"Google Config: Client ID {'set' if GOOGLE_CLIENT_ID else 'MISSING'}, Secret {'set' if GOOGLE_CLIENT_SECRET else 'MISSING'}, Redirect URI: {GOOGLE_REDIRECT_URI}")

# --- Shared State ---
# Note: timer_states is still in-memory and not persistent across restarts.
timer_states = {} # {user_id: {'start_time': datetime, 'accumulated_time': int, 'state': 'running'/'paused'/'stopped', 'job': Job, 'initial_start_time': datetime}} 

# --- i18n Settings ---
SUPPORTED_LANGUAGES = ['en', 'de', 'ru']
DEFAULT_LANGUAGE = 'en'
# --- End i18n Settings ---

# You might want to add more specific checks for other variables if they are critical 