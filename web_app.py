from flask import Flask, render_template, jsonify, send_from_directory, request, g
import os
from datetime import datetime, timezone
from config import timer_states, DOMAIN_URL, FLASK_PORT, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
import logging
import traceback # Import traceback for detailed error logging
from flask_babel import Babel
from i18n_utils import get_user_lang, _

app = Flask(__name__)

# Configure Flask logging to be less verbose or integrate with main logging if needed
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING) # Reduce werkzeug noise

# Get logger for this module
web_log = logging.getLogger(__name__)

# Configure Flask-Babel for internationalization
app.config['BABEL_DEFAULT_LOCALE'] = DEFAULT_LANGUAGE
babel = Babel(app)

# Define locale selector function
def get_locale():
    # Use the user_id from the route to determine language
    user_id = getattr(g, 'user_id', None)
    if user_id:
        web_log.debug(f"Setting locale for user {user_id} to {get_user_lang(user_id)}")
        return get_user_lang(user_id)
    web_log.debug(f"Using default locale: {DEFAULT_LANGUAGE}")
    return DEFAULT_LANGUAGE

# Configure babel to use the locale selector
babel.init_app(app, locale_selector=get_locale)

# Create our own translation function to use i18n directly
@app.context_processor
def inject_utilities():
    def translate(text):
        user_id = getattr(g, 'user_id', None)
        if user_id:
            return _(user_id, text)
        return text
    return dict(_=translate)

# --- Route to serve the audio file ---
# Assuming the mp3 is in the root directory alongside bot.py
@app.route('/audio/<path:filename>')
def serve_audio(filename):
    web_log.debug(f"Request received to serve audio file: {filename}")
    # Use send_from_directory for security, specifying the root directory
    # Get the absolute path of the project directory
    root_dir = os.path.dirname(os.path.abspath(__file__)) 
    try:
        return send_from_directory(root_dir, filename, as_attachment=False)
    except FileNotFoundError:
        web_log.error(f"Audio file not found: {filename} in {root_dir}")
        return "Audio file not found", 404
    except Exception as e:
        web_log.error(f"Error serving audio file {filename}: {e}")
        return "Error serving file", 500

@app.route('/timer/<int:user_id>')
def timer_page(user_id):
    web_log.debug(f"Request received for timer page for user {user_id}")
    # Set user_id in Flask global g for babel localeselector
    g.user_id = user_id
    try:
        # Pass the user_id to the template
        return render_template('timer.html', user_id=user_id)
    except Exception as e:
        web_log.error(f"Error rendering timer page shell for user {user_id}: {e}\\n{traceback.format_exc()}")
        # Return a generic error page
        return "<html><body><h1>Server Error</h1><p>Sorry, an error occurred loading the timer page.</p></body></html>", 500

@app.route('/api/timer_status/<int:user_id>')
def api_timer_status(user_id):
    web_log.debug(f"API request for timer status for user {user_id}")
    try:
        state_data = timer_states.get(user_id)

        if not state_data:
            web_log.debug(f"API: No timer state found for user {user_id}")
            # Return default values for a non-existent timer
            return jsonify({
                'state': 'stopped', 
                'remaining_seconds': 0, 
                'duration': 25, 
                'session_type': 'work' # Default session type
            })

        current_state = state_data.get('state', 'stopped') # Default to stopped if state key missing
        duration_minutes = state_data.get('duration', 25) 
        session_type = state_data.get('session_type', 'work') # Get session type, default to 'work'
        remaining_seconds = 0

        if current_state == 'running':
            start_time = state_data.get('start_time')
            accumulated_time_minutes = state_data.get('accumulated_time', 0)
            
            if not start_time:
                 web_log.error(f"API: Missing start_time for running timer, user {user_id}")
                 return jsonify({'state': 'error', 'message': 'Inconsistent timer state'}), 500
                 
            now = datetime.now() 
            elapsed_seconds = (now - start_time).total_seconds()
            total_worked_minutes = accumulated_time_minutes + (elapsed_seconds / 60)
            remaining_minutes = duration_minutes - total_worked_minutes
            remaining_seconds = max(0, round(remaining_minutes * 60)) 

        elif current_state == 'paused':
            accumulated_time_minutes = state_data.get('accumulated_time', 0)
            remaining_minutes = duration_minutes - accumulated_time_minutes
            remaining_seconds = max(0, round(remaining_minutes * 60))
            
        elif current_state == 'stopped':
            accumulated_time_minutes = state_data.get('accumulated_time', 0)
            is_completed = 1 if accumulated_time_minutes >= (duration_minutes - 0.01) else 0
            if is_completed:
                # If stopped but completed, report 0 seconds remaining
                remaining_seconds = 0 
            else:
                # If stopped early, also report 0 seconds remaining (clock stops)
                remaining_seconds = 0 

        web_log.debug(f"API: Returning state={current_state}, session={session_type}, remaining={remaining_seconds}, duration={duration_minutes} for user {user_id}")
        return jsonify({
            'state': current_state,
            'remaining_seconds': remaining_seconds,
            'duration': duration_minutes, 
            'session_type': session_type # Include session_type in the response
        })

    except Exception as e:
        web_log.error(f"Error in API endpoint /api/timer_status/{user_id}: {e}\\n{traceback.format_exc()}")
        # Return a JSON error response
        return jsonify({'state': 'error', 'message': 'Internal server error processing timer status'}), 500

def run_flask():
    # FLASK_PORT is now imported from config
    port = FLASK_PORT 
    web_log.info(f"Starting Flask server on host 0.0.0.0 port {port}")
    try:
        # Disable reloader when running in thread
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    except Exception as e:
        web_log.critical(f"Flask server failed to start: {e}", exc_info=True)
        # Exit? Or let the bot continue without the web UI?
        # For now, just log critical error. 