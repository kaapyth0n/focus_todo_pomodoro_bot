import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get bot token and domain from environment variables
TOKEN = os.getenv('BOT_TOKEN')
DOMAIN_URL = os.getenv('DOMAIN_URL')
FLASK_PORT = int(os.getenv('FLASK_PORT', 5002))

# Validate required environment variables
if not TOKEN:
    raise ValueError("Missing BOT_TOKEN in environment variables. Please check your .env file.")
if not DOMAIN_URL:
    print("Warning: DOMAIN_URL not found in environment variables. Using localhost as fallback.")
    # Construct the default localhost URL using the Flask port
    DOMAIN_URL = f"http://localhost:{FLASK_PORT}"

print(f"Configuration loaded: DOMAIN_URL={DOMAIN_URL}, FLASK_PORT={FLASK_PORT}")

# Shared state dictionary for timer (user_data is now handled in DB)
# Note: timer_states is still in-memory and not persistent across restarts.
# Persisting timer state completely is more complex.
timer_states = {} # {user_id: {'start_time': datetime, 'accumulated_time': int, 'state': 'running'/'paused'/'stopped', 'job': Job, 'initial_start_time': datetime}} 