from flask import Flask, render_template, jsonify, send_from_directory, request, g
import os
from datetime import datetime, timezone
from config import timer_states, DOMAIN_URL, FLASK_PORT, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, TOKEN
import logging
import traceback # Import traceback for detailed error logging
from flask_babel import Babel
from i18n_utils import get_user_lang, _
import hmac
import hashlib
import time
import urllib.parse as up
import database
from handlers import commands as cmd_handlers  # For scheduling PTB job callbacks (timer_finished)

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
        return text # Return original text if no user_id (e.g. for static pages)
    return dict(_=translate)

# --- Integration: Inject PTB JobQueue into Flask ---
def set_job_queue(job_queue):
    """Allows the Telegram bot to pass its JobQueue instance to Flask for scheduling resume jobs."""
    app.config['JOB_QUEUE'] = job_queue
    web_log.info("JobQueue injected into Flask app config.")

def _get_job_queue():
    jq = app.config.get('JOB_QUEUE')
    if not jq:
        web_log.error("JobQueue is not set in Flask app config. Resume operations will fail.")
    return jq

# --- Telegram Web App initData verification ---
def _verify_tg_init_data(init_data: str, max_age_sec: int = 3600) -> dict | None:
    """Verify Telegram Mini App initData per spec. Returns parsed dict (without hash) on success, else None."""
    try:
        if not init_data:
            return None
        parsed = dict(up.parse_qsl(init_data, keep_blank_values=True))
        recv_hash = parsed.pop('hash', None)
        if not recv_hash:
            return None
        parts = [f"{k}={parsed[k]}" for k in sorted(parsed.keys())]
        data_check_string = "\n".join(parts)
        # secret_key per TMA spec: HMAC_SHA256("WebAppData", bot_token)
        # Note: "WebAppData" is the key, bot_token is the message
        secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, recv_hash):
            web_log.warning("Verification failed: hash mismatch")
            return None
        auth_date = int(parsed.get('auth_date', '0'))
        current_time = int(time.time())
        time_diff = abs(current_time - auth_date)
        if auth_date <= 0 or time_diff > max_age_sec:
            web_log.warning(f"Verification failed: timestamp too old or invalid (diff={time_diff}s)")
            return None
        return parsed
    except Exception as e:
        web_log.error(f"Error verifying Telegram initData: {e}")
        return None

def _require_tg_user(user_id_from_path: int) -> tuple[bool, int | None, str | None]:
    """Reads initData from header or form, verifies it, and ensures the user matches the path param."""
    init_data = request.headers.get('X-Telegram-Init-Data') or request.form.get('initData') or request.args.get('initData')
    parsed = _verify_tg_init_data(init_data)
    if not parsed:
        return False, None, 'Unauthorized'
    # user field is JSON; for safety, accept both serialized dict or string
    user_raw = parsed.get('user')
    try:
        # If user_raw is JSON, leave as is; if not, it may already be a dict-like string
        import json
        user_obj = json.loads(user_raw) if isinstance(user_raw, str) else user_raw
        verified_user_id = int(user_obj.get('id')) if isinstance(user_obj, dict) else None
    except Exception:
        verified_user_id = None
    if verified_user_id != user_id_from_path:
        return False, verified_user_id, 'Forbidden'
    return True, verified_user_id, None

# --- Static Information Pages ---
@app.route('/')
def home_page():
    web_log.debug(f"Request received for home page")
    # Set g.user_id to None or a default if you want translated headers/footers common to all pages
    # For now, these pages are mostly static English content.
    g.user_id = None 
    try:
        return render_template('home.html')
    except Exception as e:
        web_log.error(f"Error rendering home page: {e}\\n{traceback.format_exc()}")
        return "<html><body><h1>Server Error</h1><p>Could not load home page.</p></body></html>", 500

@app.route('/privacy')
def privacy_policy_page():
    web_log.debug(f"Request received for privacy policy page")
    g.user_id = None 
    try:
        return render_template('privacy_policy.html')
    except Exception as e:
        web_log.error(f"Error rendering privacy policy page: {e}\\n{traceback.format_exc()}")
        return "<html><body><h1>Server Error</h1><p>Could not load privacy policy.</p></body></html>", 500

@app.route('/terms')
def terms_of_service_page():
    web_log.debug(f"Request received for terms of service page")
    g.user_id = None 
    try:
        return render_template('terms_of_service.html')
    except Exception as e:
        web_log.error(f"Error rendering terms of service page: {e}\\n{traceback.format_exc()}")
        return "<html><body><h1>Server Error</h1><p>Could not load terms of service.</p></body></html>", 500

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

@app.route('/tasks/<int:user_id>')
def task_manager_page(user_id):
    web_log.debug(f"Request received for task manager page for user {user_id}")
    # Set user_id in Flask global g for babel localeselector
    g.user_id = user_id
    try:
        # Pass the user_id to the template
        return render_template('task_manager.html', user_id=user_id)
    except Exception as e:
        web_log.error(f"Error rendering task manager page for user {user_id}: {e}\\n{traceback.format_exc()}")
        # Return a generic error page
        return "<html><body><h1>Server Error</h1><p>Sorry, an error occurred loading the task manager page.</p></body></html>", 500

@app.route('/api/timer_status/<int:user_id>')
def api_timer_status(user_id):
    web_log.debug(f"API request for timer status for user {user_id}")
    try:
        # Best-effort auth: if initData present and mismatched user, reject; otherwise allow public status
        init_data = request.headers.get('X-Telegram-Init-Data') or request.args.get('initData')
        if init_data:
            parsed = _verify_tg_init_data(init_data)
            if parsed:
                try:
                    import json
                    user_raw = parsed.get('user')
                    user_obj = json.loads(user_raw) if isinstance(user_raw, str) else user_raw
                    verified_user_id = int(user_obj.get('id')) if isinstance(user_obj, dict) else None
                except Exception:
                    verified_user_id = None
                if verified_user_id and verified_user_id != user_id:
                    return jsonify({'ok': False, 'error': 'Forbidden'}), 403
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

        # Fetch current project/task names for display
        project_id = database.get_current_project(user_id)
        task_id = database.get_current_task(user_id)
        project_name = database.get_project_name(project_id) if project_id else None
        task_name = database.get_task_name(task_id) if task_id else None

        web_log.debug(f"API: Returning state={current_state}, session={session_type}, remaining={remaining_seconds}, duration={duration_minutes} for user {user_id}")
        return jsonify({
            'state': current_state,
            'remaining_seconds': remaining_seconds,
            'duration': duration_minutes,
            'session_type': session_type,
            'project_name': project_name,
            'task_name': task_name
        })

    except Exception as e:
        web_log.error(f"Error in API endpoint /api/timer_status/{user_id}: {e}\\n{traceback.format_exc()}")
        # Return a JSON error response
        return jsonify({'state': 'error', 'message': 'Internal server error processing timer status'}), 500

@app.route('/oauth2callback')
def oauth2callback():
    """Handle the OAuth2 callback from Google."""
    web_log.debug(f"Request received for OAuth2 callback: {request.args}")
    try:
        # Get the code from the query parameters
        code = request.args.get('code')
        if not code:
            web_log.error("OAuth2 callback received without code parameter")
            return "<html><body><h1>Error</h1><p>No authorization code found in the request.</p></body></html>", 400

        # Display a page with the code and instructions
        return f"""
        <html>
        <head>
            <title>Authorization Successful</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
                .code-box {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .code {{ font-family: monospace; font-size: 14px; word-break: break-all; }}
                .instructions {{ line-height: 1.5; }}
            </style>
        </head>
        <body>
            <h1>Authorization Successful</h1>
            <div class="instructions">
                <p>Please copy the following authorization code and paste it back into your Telegram chat with the bot:</p>
            </div>
            <div class="code-box">
                <div class="code">{code}</div>
            </div>
            <div class="instructions">
                <p>After copying the code:</p>
                <ol>
                    <li>Go back to your Telegram chat with Focus Pomodoro Bot</li>
                    <li>Paste the code into the chat</li>
                    <li>The bot will complete the connection to your Google account</li>
                </ol>
                <p>You can close this window after copying the code.</p>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        web_log.error(f"Error in OAuth2 callback: {e}\\n{traceback.format_exc()}")
        return "<html><body><h1>Server Error</h1><p>An error occurred processing the authorization.</p></body></html>", 500

@app.route('/oauth2callback/jira')
def oauth2callback_jira():
    """Handle the OAuth2 callback from Jira."""
    from flask import request
    web_log.debug(f"Request received for Jira OAuth2 callback: {request.args}")
    try:
        code = request.args.get('code')
        if not code:
            web_log.error("Jira OAuth2 callback received without code parameter")
            return "<html><body><h1>Error</h1><p>No authorization code found in the request.</p></body></html>", 400
        return f"""
        <html>
        <head>
            <title>Jira Authorization Successful</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
                .code-box {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .code {{ font-family: monospace; font-size: 14px; word-break: break-all; }}
                .instructions {{ line-height: 1.5; }}
            </style>
        </head>
        <body>
            <h1>Jira Authorization Successful</h1>
            <div class="instructions">
                <p>Please copy the following authorization code and paste it back into your Telegram chat with the bot:</p>
            </div>
            <div class="code-box">
                <div class="code">{code}</div>
            </div>
            <div class="instructions">
                <p>After copying the code:</p>
                <ol>
                    <li>Go back to your Telegram chat with Focus Pomodoro Bot</li>
                    <li>Paste the code into the chat</li>
                    <li>The bot will complete the connection to your Jira account</li>
                </ol>
                <p>You can close this window after copying the code.</p>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        web_log.error(f"Error in Jira OAuth2 callback: {e}")
        return "<html><body><h1>Error</h1><p>An unexpected error occurred.</p></body></html>", 500

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

# --- Protected control endpoints (Pause / Resume / Stop) ---
@app.post('/api/timer/<int:user_id>/pause')
def api_pause_timer(user_id: int):
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code
    state_data = timer_states.get(user_id)
    if not state_data or state_data.get('state') != 'running':
        return jsonify({'ok': False, 'error': 'No running timer'}), 400
    try:
        start_time = state_data.get('start_time')
        if not start_time:
            return jsonify({'ok': False, 'error': 'Inconsistent state'}), 500
        elapsed_min = (datetime.now() - start_time).total_seconds() / 60
        state_data['accumulated_time'] = state_data.get('accumulated_time', 0) + elapsed_min
        state_data['state'] = 'paused'
        job = state_data.get('job')
        if job:
            try:
                job.schedule_removal()
            except Exception:
                pass
            state_data['job'] = None
        # Respond with status-like payload
        duration_minutes = state_data.get('duration', 25)
        remaining_seconds = max(0, round((duration_minutes - state_data['accumulated_time']) * 60))
        return jsonify({'ok': True, 'state': 'paused', 'remaining_seconds': remaining_seconds})
    except Exception as e:
        web_log.error(f"Error pausing timer via API for {user_id}: {e}")
        return jsonify({'ok': False, 'error': 'Internal error'}), 500


@app.post('/api/timer/<int:user_id>/resume')
def api_resume_timer(user_id: int):
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code
    state_data = timer_states.get(user_id)
    if not state_data or state_data.get('state') != 'paused':
        return jsonify({'ok': False, 'error': 'No paused timer'}), 400
    try:
        duration_minutes = state_data.get('duration', 25)
        accumulated = state_data.get('accumulated_time', 0)
        session_type = state_data.get('session_type', 'work')
        remaining_min = duration_minutes - accumulated
        if remaining_min <= 0:
            # No time left: treat as completed
            state_data['state'] = 'stopped'
            return jsonify({'ok': True, 'state': 'finished', 'remaining_seconds': 0})
        job_queue = _get_job_queue()
        if not job_queue:
            return jsonify({'ok': False, 'error': 'Scheduler unavailable'}), 500
        # Schedule using the PTB callback to keep unified logic
        data = {'user_id': user_id, 'duration': duration_minutes, 'session_type': session_type}
        job = job_queue.run_once(cmd_handlers.timer_finished, remaining_min * 60, data=data, name=f"timer_{user_id}")
        state_data['state'] = 'running'
        state_data['start_time'] = datetime.now()
        state_data['job'] = job
        remaining_seconds = max(0, round(remaining_min * 60))
        return jsonify({'ok': True, 'state': 'running', 'remaining_seconds': remaining_seconds})
    except Exception as e:
        web_log.error(f"Error resuming timer via API for {user_id}: {e}")
        return jsonify({'ok': False, 'error': 'Internal error'}), 500


@app.post('/api/timer/<int:user_id>/stop')
def api_stop_timer(user_id: int):
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code
    state_data = timer_states.get(user_id)
    if not state_data:
        return jsonify({'ok': False, 'error': 'No active timer'}), 400
    try:
        # Accumulate if running
        if state_data.get('state') == 'running':
            start_time = state_data.get('start_time')
            if not start_time:
                return jsonify({'ok': False, 'error': 'Inconsistent state'}), 500
            elapsed = (datetime.now() - start_time).total_seconds() / 60
            state_data['accumulated_time'] = state_data.get('accumulated_time', 0) + elapsed

        duration = float(state_data.get('duration', 25))
        accumulated = float(state_data.get('accumulated_time', 0))
        completed = 1 if accumulated >= (duration - 0.01) else 0
        session_type = state_data.get('session_type', 'work')
        initial_start_time = state_data.get('initial_start_time') or state_data.get('start_time') or datetime.now()
        # Persist
        project_id = database.get_current_project(user_id) if session_type == 'work' else None
        task_id = database.get_current_task(user_id) if session_type == 'work' else None
        try:
            database.add_pomodoro_session(
                user_id=user_id,
                project_id=project_id,
                task_id=task_id,
                start_time=initial_start_time,
                duration_minutes=accumulated,
                session_type=session_type,
                completed=completed,
            )
        except Exception as db_err:
            web_log.error(f"DB error logging stop via API for {user_id}: {db_err}")

        # Cancel job
        job = state_data.get('job')
        if job:
            try:
                job.schedule_removal()
            except Exception:
                pass
        # Cleanup
        try:
            del timer_states[user_id]
        except Exception:
            pass

        return jsonify({'ok': True, 'state': 'stopped', 'accumulated_minutes': round(accumulated, 2)})
    except Exception as e:
        web_log.error(f"Error stopping timer via API for {user_id}: {e}")
        return jsonify({'ok': False, 'error': 'Internal error'}), 500

@app.post('/api/timer/<int:user_id>/start-break')
def api_start_break(user_id: int):
    """Start a break timer with specified duration."""
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code

    try:
        # Get duration from request body
        data = request.get_json() if request.is_json else {}
        duration = data.get('duration', 5)  # Default 5 minutes

        # Stop any existing timer
        state_data = timer_states.get(user_id)
        if state_data:
            # Stop the existing timer
            job = state_data.get('job')
            if job:
                try:
                    job.schedule_removal()
                except Exception:
                    pass
            try:
                del timer_states[user_id]
            except Exception:
                pass

        # Get the job queue
        job_queue = _get_job_queue()
        if not job_queue:
            return jsonify({'ok': False, 'error': 'Scheduler unavailable'}), 500

        # Schedule the timer completion callback
        job_data = {'user_id': user_id, 'duration': duration, 'session_type': 'break'}
        job = job_queue.run_once(cmd_handlers.timer_finished, duration * 60, data=job_data, name=f"timer_{user_id}")

        # Create timer state
        now = datetime.now()
        timer_states[user_id] = {
            'state': 'running',
            'accumulated_time': 0,
            'start_time': now,
            'initial_start_time': now,
            'duration': duration,
            'session_type': 'break',
            'job': job
        }

        return jsonify({'ok': True, 'duration': duration, 'session_type': 'break', 'state': 'running'})
    except Exception as e:
        web_log.error(f"Error starting break for {user_id}: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal error'}), 500

@app.post('/api/timer/<int:user_id>/start-next-pomodoro')
def api_start_next_pomodoro(user_id: int):
    """Start the next Pomodoro work session for the current task."""
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code

    try:
        # Get duration from request body or use default 25 minutes
        data = request.get_json() if request.is_json else {}
        duration = data.get('duration', 25)

        # Get current project and task
        project_id = database.get_current_project(user_id)
        task_id = database.get_current_task(user_id)

        if not project_id or not task_id:
            return jsonify({'ok': False, 'error': 'No active project/task selected'}), 400

        # Get task info for response
        task_name = database.get_task_name(task_id)
        project_name = database.get_project_name(project_id)

        # Stop any existing timer
        state_data = timer_states.get(user_id)
        if state_data:
            job = state_data.get('job')
            if job:
                try:
                    job.schedule_removal()
                except Exception:
                    pass
            try:
                del timer_states[user_id]
            except Exception:
                pass

        # Get the job queue
        job_queue = _get_job_queue()
        if not job_queue:
            return jsonify({'ok': False, 'error': 'Scheduler unavailable'}), 500

        # Schedule the timer completion callback
        job_data = {'user_id': user_id, 'duration': duration, 'session_type': 'work'}
        job = job_queue.run_once(cmd_handlers.timer_finished, duration * 60, data=job_data, name=f"timer_{user_id}")

        # Create timer state
        now = datetime.now()
        timer_states[user_id] = {
            'state': 'running',
            'accumulated_time': 0,
            'start_time': now,
            'initial_start_time': now,
            'duration': duration,
            'session_type': 'work',
            'job': job
        }

        return jsonify({
            'ok': True,
            'duration': duration,
            'session_type': 'work',
            'state': 'running',
            'task_name': task_name,
            'project_name': project_name
        })
    except Exception as e:
        web_log.error(f"Error starting next pomodoro for {user_id}: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal error'}), 500

# --- Task Manager API Endpoints ---
@app.route('/api/projects/<int:user_id>')
def api_get_projects(user_id: int):
    """Get all projects for a user with statistics."""
    web_log.debug(f"API request for projects list for user {user_id}")
    try:
        # Optionally verify auth - for now allow public read
        init_data = request.headers.get('X-Telegram-Init-Data') or request.args.get('initData')
        if init_data:
            parsed = _verify_tg_init_data(init_data)
            if parsed:
                try:
                    import json
                    user_raw = parsed.get('user')
                    user_obj = json.loads(user_raw) if isinstance(user_raw, str) else user_raw
                    verified_user_id = int(user_obj.get('id')) if isinstance(user_obj, dict) else None
                except Exception:
                    verified_user_id = None
                if verified_user_id and verified_user_id != user_id:
                    return jsonify({'ok': False, 'error': 'Forbidden'}), 403

        projects = database.get_projects(user_id, database.STATUS_ACTIVE)
        result = []
        for project in projects:
            project_id = project[0]
            project_name = project[1]
            stats = database.get_project_statistics(project_id)
            result.append({
                'project_id': project_id,
                'project_name': project_name,
                'total_minutes': stats['total_minutes'],
                'total_tasks': stats['total_tasks'],
                'completed_tasks': stats['completed_tasks'],
                'active_tasks': stats['active_tasks']
            })

        return jsonify({'ok': True, 'projects': result})
    except Exception as e:
        web_log.error(f"Error in API endpoint /api/projects/{user_id}: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500

@app.route('/api/projects/<int:user_id>/tasks')
def api_get_all_tasks(user_id: int):
    """Get all tasks for a user with statistics."""
    web_log.debug(f"API request for all tasks for user {user_id}")
    try:
        # Optionally verify auth
        init_data = request.headers.get('X-Telegram-Init-Data') or request.args.get('initData')
        if init_data:
            parsed = _verify_tg_init_data(init_data)
            if parsed:
                try:
                    import json
                    user_raw = parsed.get('user')
                    user_obj = json.loads(user_raw) if isinstance(user_raw, str) else user_raw
                    verified_user_id = int(user_obj.get('id')) if isinstance(user_obj, dict) else None
                except Exception:
                    verified_user_id = None
                if verified_user_id and verified_user_id != user_id:
                    return jsonify({'ok': False, 'error': 'Forbidden'}), 403

        tasks = database.get_all_tasks_with_stats(user_id)
        return jsonify({'ok': True, 'tasks': tasks})
    except Exception as e:
        web_log.error(f"Error in API endpoint /api/projects/{user_id}/tasks: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500

@app.route('/api/projects/<int:user_id>/<int:project_id>/tasks')
def api_get_project_tasks(user_id: int, project_id: int):
    """Get tasks for a specific project."""
    web_log.debug(f"API request for tasks for project {project_id}")
    try:
        tasks = database.get_tasks(project_id, database.STATUS_ACTIVE)
        result = []
        for task in tasks:
            task_id = task[0]
            task_name = task[1]
            stats = database.get_task_statistics(task_id)
            result.append({
                'task_id': task_id,
                'task_name': task_name,
                'project_id': project_id,
                'elapsed_minutes': stats['total_minutes'],
                'session_count': stats['session_count']
            })

        return jsonify({'ok': True, 'tasks': result})
    except Exception as e:
        web_log.error(f"Error in API endpoint /api/projects/{user_id}/{project_id}/tasks: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500

@app.post('/api/projects/<int:user_id>/create')
def api_create_project(user_id: int):
    """Create a new project."""
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code

    try:
        data = request.get_json()
        project_name = data.get('project_name', '').strip()
        if not project_name:
            return jsonify({'ok': False, 'error': 'Project name is required'}), 400

        project_id = database.add_project(user_id, project_name)
        if project_id:
            return jsonify({'ok': True, 'project_id': project_id, 'project_name': project_name})
        else:
            return jsonify({'ok': False, 'error': 'Failed to create project'}), 500
    except Exception as e:
        web_log.error(f"Error creating project for user {user_id}: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500

@app.post('/api/tasks/<int:user_id>/create')
def api_create_task(user_id: int):
    """Create a new task."""
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code

    try:
        data = request.get_json()
        task_name = data.get('task_name', '').strip()
        project_id = data.get('project_id')

        if not task_name:
            return jsonify({'ok': False, 'error': 'Task name is required'}), 400
        if not project_id:
            return jsonify({'ok': False, 'error': 'Project ID is required'}), 400

        task_id = database.add_task(project_id, task_name)
        if task_id:
            return jsonify({'ok': True, 'task_id': task_id, 'task_name': task_name})
        else:
            return jsonify({'ok': False, 'error': 'Failed to create task'}), 500
    except Exception as e:
        web_log.error(f"Error creating task for user {user_id}: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500

@app.post('/api/tasks/<int:user_id>/<int:task_id>/complete')
def api_complete_task(user_id: int, task_id: int):
    """Mark a task as completed."""
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code

    try:
        # Mark task as done
        success = database.mark_task_status(task_id, database.STATUS_DONE)
        if success:
            return jsonify({'ok': True, 'task_id': task_id, 'status': database.STATUS_DONE})
        else:
            return jsonify({'ok': False, 'error': 'Failed to mark task as completed'}), 500
    except Exception as e:
        web_log.error(f"Error marking task {task_id} as completed: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500

@app.post('/api/tasks/<int:user_id>/<int:task_id>/uncomplete')
def api_uncomplete_task(user_id: int, task_id: int):
    """Mark a task as active (uncomplete)."""
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code

    try:
        # Mark task as active
        success = database.mark_task_status(task_id, database.STATUS_ACTIVE)
        if success:
            return jsonify({'ok': True, 'task_id': task_id, 'status': database.STATUS_ACTIVE})
        else:
            return jsonify({'ok': False, 'error': 'Failed to mark task as active'}), 500
    except Exception as e:
        web_log.error(f"Error marking task {task_id} as active: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500

@app.post('/api/tasks/<int:user_id>/<int:task_id>/start')
def api_start_task_timer(user_id: int, task_id: int):
    """Start a timer for a specific task."""
    ok, verified_user_id, err = _require_tg_user(user_id)
    if not ok:
        code = 403 if verified_user_id else 401
        return jsonify({'ok': False, 'error': err}), code

    try:
        # Get task and project info
        task_name = database.get_task_name(task_id)
        if not task_name:
            return jsonify({'ok': False, 'error': 'Task not found'}), 404

        # Get project_id from task
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT project_id FROM tasks WHERE task_id = ?', (task_id,))
        result = cursor.fetchone()
        conn.close()

        if not result:
            return jsonify({'ok': False, 'error': 'Task not found'}), 404

        project_id = result[0]

        # Set current project and task
        database.set_current_project(user_id, project_id)
        database.set_current_task(user_id, task_id)

        # Get duration from request or use default
        data = request.get_json() if request.is_json else {}
        duration = data.get('duration', 25)  # Default 25 minutes

        # Stop any existing timer
        if user_id in timer_states:
            try:
                state_data = timer_states[user_id]
                job = state_data.get('job')
                if job:
                    job.schedule_removal()
            except Exception:
                pass
            del timer_states[user_id]

        # Start new timer
        job_queue = _get_job_queue()
        if not job_queue:
            return jsonify({'ok': False, 'error': 'Scheduler unavailable'}), 500

        timer_data = {'user_id': user_id, 'duration': duration, 'session_type': 'work'}
        job = job_queue.run_once(cmd_handlers.timer_finished, duration * 60, data=timer_data, name=f"timer_{user_id}")

        timer_states[user_id] = {
            'state': 'running',
            'start_time': datetime.now(),
            'initial_start_time': datetime.now(),
            'accumulated_time': 0,
            'duration': duration,
            'session_type': 'work',
            'job': job
        }

        return jsonify({
            'ok': True,
            'state': 'running',
            'duration': duration,
            'task_id': task_id,
            'task_name': task_name,
            'project_id': project_id
        })
    except Exception as e:
        web_log.error(f"Error starting timer for task {task_id}: {e}\n{traceback.format_exc()}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500