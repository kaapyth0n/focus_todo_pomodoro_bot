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
    # Always render the main timer template. 
    # Initial state will be fetched by JavaScript.
    try:
        # Pass initial user_id to the template
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
                            transition: background-color 0.5s ease;
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
                            transition: color 0.5s ease;
                        }
                        .status.loading { color: #999; }
                        .status.running { color: #4CAF50; } /* Green */
                        .status.paused { color: #FFC107; } /* Yellow */
                        .status.stopped { color: #666; } /* Grey */
                        .status.finished { color: #F44336; } /* Red */
                        .status.error { color: #D32F2F; font-weight: bold; } /* Error color */

                        /* Background color changes based on state */
                        body.running { background-color: #e8f5e9; } /* Light Green */
                        body.paused { background-color: #fffde7; } /* Light Yellow */
                        body.stopped { background-color: #f5f5f5; } /* Light Grey */
                        body.finished { background-color: #ffebee; } /* Light Red */
                        body.error { background-color: #fce4ec; } /* Light Pink */

                    </style>
                </head>
                <body id="body-status" class="loading">
                    <div class="timer-container">
                        <h1 id="timer-title">Focus Timer</h1>
                        <div id="status" class="status loading">Loading...</div>
                        <div id="countdown" class="timer">--:--</div>
                    </div>
                    <script>
                        const userId = {{ user_id }};
                        const statusElem = document.getElementById('status');
                        const countdownElem = document.getElementById('countdown');
                        const titleElem = document.getElementById('timer-title');
                        const bodyElem = document.getElementById('body-status');

                        let localRemainingSeconds = 0;
                        let currentState = 'loading'; // loading, running, paused, stopped, finished, error
                        let currentDuration = 25; // Default duration
                        let localIntervalId = null;
                        let syncIntervalId = null;
                        const SYNC_INTERVAL_MS = 5000; // Sync with server every 5 seconds

                        function formatTime(totalSeconds) {
                            if (isNaN(totalSeconds) || totalSeconds < 0) totalSeconds = 0;
                            const minutes = Math.floor(totalSeconds / 60);
                            const seconds = Math.floor(totalSeconds % 60);
                            return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
                        }

                        function updateDisplay() {
                            // Update countdown text
                            countdownElem.innerText = formatTime(localRemainingSeconds);
                            
                            // Update status text and body class
                            let statusText = 'Unknown';
                            switch (currentState) {
                                case 'loading': statusText = 'Loading...'; break;
                                case 'running': statusText = 'Timer Running'; break;
                                case 'paused': statusText = 'Timer Paused'; break;
                                case 'stopped': statusText = 'Timer Stopped'; break;
                                case 'finished': statusText = "Time's up!"; break;
                                case 'error': statusText = 'Error / Connection Issue'; break;
                            }
                            statusElem.innerText = statusText;
                            statusElem.className = `status ${currentState}`;
                            bodyElem.className = currentState; // Update body class for background color etc.
                            titleElem.innerText = `Focus Timer (${currentDuration} min)`;
                        }

                        function stopLocalCountdown() {
                            if (localIntervalId !== null) {
                                clearInterval(localIntervalId);
                                localIntervalId = null;
                                web_log.debug('Local countdown stopped.');
                            }
                        }

                        function startLocalCountdown() {
                            stopLocalCountdown(); // Ensure no duplicate intervals
                            web_log.debug(`Starting local countdown from ${localRemainingSeconds}s`);
                            localIntervalId = setInterval(() => {
                                if (currentState === 'running' && localRemainingSeconds > 0) {
                                    localRemainingSeconds--;
                                    updateDisplay();
                                } else if (localRemainingSeconds <= 0) {
                                    // Timer reached zero locally
                                    web_log.debug('Local countdown reached zero.');
                                    currentState = 'finished'; 
                                    localRemainingSeconds = 0; // Ensure it's 0
                                    stopLocalCountdown();
                                    updateDisplay();
                                    // Rely on next sync to confirm final state from server
                                } else {
                                     // State changed to non-running during interval
                                     stopLocalCountdown();
                                }
                            }, 1000);
                        }

                        function updateState(newState, newRemainingSeconds, newDuration) {
                            web_log.debug(`Updating state: ${newState}, remaining: ${newRemainingSeconds}s, duration: ${newDuration}min`);
                            const stateChanged = currentState !== newState;
                            const timeChangedSignificantly = Math.abs(localRemainingSeconds - newRemainingSeconds) > 5; // Allow for small drift

                            currentState = newState;
                            currentDuration = newDuration || 25; // Use fetched duration or default

                            // Update local time only if significantly different or state changed
                            // or if the local countdown is not running (e.g., was paused)
                            if (stateChanged || timeChangedSignificantly || localIntervalId === null) {
                                localRemainingSeconds = newRemainingSeconds;
                            }

                            updateDisplay();

                            if (currentState === 'running') {
                                if (localIntervalId === null) { // Start local countdown if not already running
                                    startLocalCountdown();
                                }
                            } else { // Paused, stopped, finished, error
                                stopLocalCountdown();
                                if (currentState === 'finished') {
                                    localRemainingSeconds = 0; // Ensure display shows 00:00
                                    updateDisplay();
                                }
                            }
                        }

                        async function syncWithServer() {
                            web_log.debug(`Syncing with server for user ${userId}...`);
                            try {
                                const response = await fetch(`/api/timer_status/${userId}`);
                                if (!response.ok) {
                                    throw new Error(`API Error: ${response.status}`);
                                }
                                const data = await response.json();
                                web_log.debug('Received data from server:', data);

                                // Determine the effective state
                                let effectiveState = data.state;
                                if (data.state === 'stopped' && data.remaining_seconds <= 1) {
                                     effectiveState = 'finished'; // Treat stopped near 0 as finished
                                } else if (data.state === 'running' && data.remaining_seconds <= 0) {
                                     effectiveState = 'finished'; // Treat running but 0 time as finished
                                }

                                updateState(effectiveState, data.remaining_seconds, data.duration);

                            } catch (error) {
                                web_log.error('Sync error:', error);
                                // Avoid overwriting a finished state with error
                                if (currentState !== 'finished') { 
                                     updateState('error', localRemainingSeconds, currentDuration); // Keep last known time on error
                                }
                            }
                        }

                        function initTimer() {
                            web_log.info(`Initializing timer UI for user ${userId}`);
                            // Initial sync
                            syncWithServer(); 
                            // Setup periodic sync
                            if (syncIntervalId) clearInterval(syncIntervalId); // Clear previous interval if any
                            syncIntervalId = setInterval(syncWithServer, SYNC_INTERVAL_MS);
                            web_log.info(`Periodic sync started (${SYNC_INTERVAL_MS}ms).`);
                        }
                        
                        // Add console logging for debugging on the web page itself
                        const originalLog = console.log;
                        const originalDebug = console.debug;
                        const originalError = console.error;
                        const web_log = {
                            log: function(...args) { originalLog.apply(console, ['[WEB]', ...args]); },
                            debug: function(...args) { originalDebug.apply(console, ['[WEB DEBUG]', ...args]); },
                            error: function(...args) { originalError.apply(console, ['[WEB ERROR]', ...args]); },
                            info: function(...args) { originalLog.apply(console, ['[WEB INFO]', ...args]); } 
                        };
                        
                        // Start initialization
                        initTimer();

                    </script>
                </body>
            </html>
        """, user_id=user_id)

    except Exception as e:
        web_log.error(f"Error rendering timer page shell for user {user_id}: {e}\\n{traceback.format_exc()}")
        # Return a generic error page
        return render_template_string("<html><body><h1>Server Error</h1><p>Sorry, an error occurred loading the timer page.</p></body></html>"), 500

@app.route('/api/timer_status/<int:user_id>')
def api_timer_status(user_id):
    web_log.debug(f"API request for timer status for user {user_id}")
    try:
        state_data = timer_states.get(user_id)

        if not state_data:
            web_log.debug(f"API: No timer state found for user {user_id}")
            return jsonify({'state': 'stopped', 'remaining_seconds': 0, 'duration': 25}) # Return default duration

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
            
        elif current_state == 'stopped':
            # If stopped, report the last known accumulated time as remaining time 'worked'
            # Or perhaps better to report 0 remaining? Let's report 0 remaining.
            accumulated_time_minutes = state_data.get('accumulated_time', 0)
             # If stopped early, remaining is technically duration - accumulated, but display-wise 0 makes sense.
            remaining_minutes = duration_minutes - accumulated_time_minutes
            remaining_seconds = max(0, round(remaining_minutes * 60)) 
            # Let's actually return 0 if stopped, unless it finished fully
            is_completed = 1 if state_data.get('accumulated_time', 0) >= (duration_minutes - 0.01) else 0
            if not is_completed:
                remaining_seconds = 0 # If stopped early, show 0 time remaining on the clock.

        web_log.debug(f"API: Returning state={current_state}, remaining={remaining_seconds}, duration={duration_minutes} for user {user_id}")
        return jsonify({
            'state': current_state,
            'remaining_seconds': remaining_seconds,
            'duration': duration_minutes 
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