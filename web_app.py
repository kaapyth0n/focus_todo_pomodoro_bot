from flask import Flask, render_template_string, jsonify
import os
from datetime import datetime, timezone
from config import timer_states, DOMAIN_URL, FLASK_PORT
import logging 
import traceback # Import traceback for detailed error logging

app = Flask(__name__)

# Configure Flask logging to be less verbose or integrate with main logging if needed
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING) # Reduce werkzeug noise

# Get logger for this module
web_log = logging.getLogger(__name__)

@app.route('/timer/<int:user_id>')
def timer_page(user_id):
    web_log.debug(f"Request received for timer page for user {user_id}")
    try:
        state_data = timer_states.get(user_id)

        if not state_data or state_data.get('state') == 'stopped':
            web_log.debug(f"No active timer found for user {user_id}, rendering stopped page.")
            return render_template_string("""
                <html>
                    <head>
                        <title>Focus Pomodoro Timer</title>
                        <style>
                            body {
                                font-family: Arial, sans-serif;
                                text-align: center;
                                margin-top: 50px;
                            }
                            .message {
                                color: #666;
                                font-size: 18px;
                            }
                        </style>
                    </head>
                    <body>
                        <h1>No Active Timer</h1>
                        <p class="message">There is no active timer for this user, or the timer has finished.</p>
                    </body>
                </html>
            """)

        current_state = state_data.get('state')
        duration_minutes = state_data.get('duration', 25) # Default if missing

        if current_state == 'running':
            web_log.debug(f"Rendering running timer page for user {user_id}")
            return render_template_string("""
                <html>
                    <head>
                        <title>Focus Pomodoro Timer</title>
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <style>
                            body {
                                font-family: Arial, sans-serif;
                                text-align: center;
                                margin-top: 50px;
                                background-color: #f7f9fc;
                            }
                            .timer-container {
                                max-width: 500px;
                                margin: 0 auto;
                                padding: 20px;
                                border-radius: 10px;
                                background-color: white;
                                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                            }
                            .timer {
                                font-size: 60px;
                                font-weight: bold;
                                color: #333;
                                margin: 30px 0;
                            }
                            .status {
                                font-size: 18px;
                                margin-bottom: 20px;
                            }
                            .status.running { color: #4CAF50; } /* Green */
                            .status.paused { color: #FFC107; } /* Yellow */
                            .status.finished { color: #F44336; } /* Red */
                            .status.error { color: #D32F2F; font-weight: bold; } /* Error color */
                        </style>
                    </head>
                    <body>
                        <div class="timer-container">
                            <h1>Focus Timer ({{ duration }} min)</h1>
                            <div id="status" class="status running">Timer Running</div>
                            <div id="countdown" class="timer">--:--</div>
                        </div>
                        <script>
                            const userId = {{ user_id }};
                            let timerInterval = null;
                            let initialFetchDone = false;

                            function formatTime(totalSeconds) {
                                if (totalSeconds < 0) totalSeconds = 0;
                                const minutes = Math.floor(totalSeconds / 60);
                                const seconds = Math.floor(totalSeconds % 60);
                                return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
                            }

                            function updateDisplay(state, remainingSeconds) {
                                const countdownElem = document.getElementById('countdown');
                                const statusElem = document.getElementById('status');
                                
                                countdownElem.innerText = formatTime(remainingSeconds);

                                if (state === 'running') {
                                    statusElem.innerText = 'Timer Running';
                                    statusElem.className = 'status running';
                                    if (!timerInterval) {
                                        startFetching(); 
                                    }
                                } else if (state === 'paused') {
                                    statusElem.innerText = 'Timer Paused';
                                    statusElem.className = 'status paused';
                                    stopFetching();
                                } else if (state === 'stopped') {
                                    statusElem.innerText = remainingSeconds <= 1 ? "Time's up!" : 'Timer Stopped';
                                    statusElem.className = 'status finished';
                                    stopFetching();
                                }
                            }

                            function stopFetching() {
                                if (timerInterval) {
                                    clearInterval(timerInterval);
                                    timerInterval = null;
                                    console.log('Polling stopped.');
                                }
                            }
                            
                            function startFetching() {
                                 if (!timerInterval) {
                                     timerInterval = setInterval(fetchTimerUpdate, 2000);
                                     console.log('Polling started.');
                                 }
                            }

                            async function fetchTimerUpdate() {
                                console.log(`Fetching update for user ${userId}...`);
                                try {
                                    const response = await fetch(`/api/timer_status/${userId}`);
                                    
                                    if (!response.ok) {
                                        console.error('API Error:', response.status, await response.text());
                                        document.getElementById('status').innerText = 'Server Error';
                                        document.getElementById('status').className = 'status error';
                                        stopFetching();
                                        return;
                                    }
                                    
                                    const data = await response.json();
                                    console.log('Received data:', data);
                                    updateDisplay(data.state, data.remaining_seconds);
                                    initialFetchDone = true;
                                    
                                } catch (error) {
                                    console.error('Network or fetch error:', error);
                                    if (initialFetchDone) {
                                         document.getElementById('status').innerText = 'Connection Issue';
                                         document.getElementById('status').className = 'status error';
                                    }
                                }
                            }

                            fetchTimerUpdate();
                           
                        </script>
                    </body>
                </html>
            """, user_id=user_id, duration=duration_minutes)

        elif current_state == 'paused':
            web_log.debug(f"Rendering paused timer page for user {user_id}")
            accumulated_time = state_data.get('accumulated_time', 0)
            remaining = duration_minutes - accumulated_time
            minutes = int(remaining)
            seconds = int((remaining - minutes) * 60)
            return render_template_string("""
                <html>
                    <head>
                        <title>Focus Pomodoro Timer</title>
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <style>
                            body {
                                font-family: Arial, sans-serif;
                                text-align: center;
                                margin-top: 50px;
                                background-color: #f7f9fc;
                            }
                            .timer-container {
                                max-width: 500px;
                                margin: 0 auto;
                                padding: 20px;
                                border-radius: 10px;
                                background-color: white;
                                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                            }
                            .timer {
                                font-size: 60px;
                                font-weight: bold;
                                color: #333;
                                margin: 30px 0;
                            }
                            .status {
                                font-size: 18px;
                                margin-bottom: 20px;
                                color: #FFC107; /* Yellow */
                            }
                        </style>
                    </head>
                    <body>
                        <div class="timer-container">
                            <h1>Focus Timer ({{ duration }} min)</h1>
                            <div class="status">Timer Paused</div>
                            <div class="timer">{{ minutes }}:{{ seconds }}</div>
                        </div>
                    </body>
                </html>
            """, minutes=f"{minutes:02d}", seconds=f"{seconds:02d}", duration=duration_minutes)

        else: 
            web_log.warning(f"Rendering timer page with unexpected state '{current_state}' for user {user_id}")
            return render_template_string("<html><body><h1>Error: Invalid Timer State</h1></body></html>")

    except Exception as e:
        web_log.error(f"Error rendering timer page for user {user_id}: {e}\n{traceback.format_exc()}")
        # Return a generic error page
        return render_template_string("<html><body><h1>Server Error</h1><p>Sorry, an error occurred loading the timer page.</p></body></html>"), 500

@app.route('/api/timer_status/<int:user_id>')
def api_timer_status(user_id):
    web_log.debug(f"API request for timer status for user {user_id}")
    try:
        state_data = timer_states.get(user_id)

        if not state_data:
            web_log.debug(f"API: No timer state found for user {user_id}")
            return jsonify({'state': 'stopped', 'remaining_seconds': 0})

        current_state = state_data.get('state', 'stopped') # Default to stopped if state key missing
        duration_minutes = state_data.get('duration', 25) 
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
            
        web_log.debug(f"API: Returning state={current_state}, remaining={remaining_seconds} for user {user_id}")
        return jsonify({
            'state': current_state,
            'remaining_seconds': remaining_seconds,
            'duration': duration_minutes 
        })

    except Exception as e:
        web_log.error(f"Error in API endpoint /api/timer_status/{user_id}: {e}\n{traceback.format_exc()}")
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