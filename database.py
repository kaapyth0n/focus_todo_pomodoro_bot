import sqlite3
from datetime import datetime
import logging # Add logging
import traceback

DB_NAME = 'focus_pomodoro.db'

# Configure basic logging for the database module
# This could be more sophisticated, e.g., using the main app logger
# For now, just get logger by name
log = logging.getLogger(__name__)

def create_database():
    """Creates or ensures the database schema exists."""
    conn = None # Initialize conn to None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Users table - Add current_project_id and current_task_id
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                current_project_id INTEGER DEFAULT NULL, 
                current_task_id INTEGER DEFAULT NULL,
                FOREIGN KEY (current_project_id) REFERENCES projects(project_id) ON DELETE SET NULL,
                FOREIGN KEY (current_task_id) REFERENCES tasks(task_id) ON DELETE SET NULL
            )
        ''')
        
        # Projects table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                project_name TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                task_name TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            )
        ''')
        
        # Pomodoro sessions table - Add session_type
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pomodoro_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                project_id INTEGER, -- Can be NULL for breaks
                task_id INTEGER,    -- Can be NULL for breaks
                start_time TEXT,
                end_time TEXT,
                work_duration REAL,  -- Changed to duration_minutes
                session_type TEXT DEFAULT 'work', -- Add session_type ('work', 'break')
                completed INTEGER,   
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
        log.info("Database schema checked/created successfully.")
    except sqlite3.Error as e:
        log.error(f"Database error during schema creation: {e}")
        # Optionally raise the error again if it's critical
        # raise e 
    finally:
        if conn:
            conn.close()

# Helper functions
def add_user(user_id, first_name, last_name):
    """Adds or updates a user in the database."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Insert or ignore if user exists, but update names if provided
        cursor.execute('''
            INSERT INTO users (user_id, first_name, last_name) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name
            WHERE first_name != excluded.first_name OR last_name != excluded.last_name
        ''', (user_id, first_name, last_name))
        conn.commit()
        log.debug(f"User {user_id} added or updated.")
    except sqlite3.Error as e:
        log.error(f"Database error adding/updating user {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def set_current_project(user_id, project_id):
    """Sets the current project for a user, clearing the current task."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Also clear the current task when project changes
        cursor.execute("UPDATE users SET current_project_id = ?, current_task_id = NULL WHERE user_id = ?", (project_id, user_id))
        conn.commit()
        log.debug(f"Set current project for user {user_id} to {project_id}. Rows affected: {cursor.rowcount}")
    except sqlite3.Error as e:
        log.error(f"Database error setting current project for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def set_current_task(user_id, task_id):
    """Sets the current task for a user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET current_task_id = ? WHERE user_id = ?", (task_id, user_id))
        conn.commit()
        log.debug(f"Set current task for user {user_id} to {task_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error setting current task for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def get_current_project(user_id):
    """Gets the current project ID for a user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT current_project_id FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        log.debug(f"get_current_project for user {user_id} raw result: {result}")
        return result[0] if result and result[0] is not None else None
    except sqlite3.Error as e:
        log.error(f"Database error getting current project for user {user_id}: {e}")
        return None # Return None on error
    finally:
        if conn:
            conn.close()

def get_current_task(user_id):
    """Gets the current task ID for a user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT current_task_id FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result and result[0] is not None else None
    except sqlite3.Error as e:
        log.error(f"Database error getting current task for user {user_id}: {e}")
        return None # Return None on error
    finally:
        if conn:
            conn.close()

def clear_current_project(user_id):
    """Clears both current project and task for the user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET current_project_id = NULL, current_task_id = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        log.debug(f"Cleared current project/task for user {user_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error clearing current project/task for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def clear_current_task(user_id):
    """Clears only the current task for the user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET current_task_id = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        log.debug(f"Cleared current task for user {user_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error clearing current task for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def add_project(user_id, project_name):
    """Adds a new project for a user."""
    conn = None
    project_id = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO projects (user_id, project_name) VALUES (?, ?)', 
                       (user_id, project_name))
        project_id = cursor.lastrowid
        conn.commit()
        log.info(f"Added project '{project_name}' ({project_id}) for user {user_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error adding project '{project_name}' for user {user_id}: {e}")
        project_id = None # Ensure None is returned on error
    finally:
        if conn:
            conn.close()
    return project_id

def get_projects(user_id):
    """Gets all projects for a user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT project_id, project_name FROM projects WHERE user_id = ?', (user_id,))
        projects = cursor.fetchall()
        return projects
    except sqlite3.Error as e:
        log.error(f"Database error getting projects for user {user_id}: {e}")
        return [] # Return empty list on error
    finally:
        if conn:
            conn.close()

def get_project_name(project_id):
    """Gets the name of a specific project."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT project_name FROM projects WHERE project_id = ?', (project_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        log.error(f"Database error getting name for project {project_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def delete_project(project_id):
    """Deletes a project. Associated tasks/sessions are handled by CASCADE constraints."""
    conn = None
    deleted = False
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.execute("PRAGMA foreign_keys = ON") # Ensure constraints are enforced
        cursor = conn.cursor()
        # Clear this project as current project for any user
        cursor.execute("UPDATE users SET current_project_id = NULL, current_task_id = NULL WHERE current_project_id = ?", (project_id,))
        
        # Delete the project (CASCADE should handle tasks and sessions)
        cursor.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
        
        conn.commit()
        log.info(f"Project {project_id} deleted successfully (CASCADE handled related data).")
        deleted = True
    except sqlite3.Error as e:
        log.error(f"Database error during project deletion: {e}")
        if conn: conn.rollback()
        deleted = False
    finally:
        if conn:
            conn.close()
    return deleted

def add_task(project_id, task_name):
    """Adds a task to a specific project."""
    conn = None
    task_id = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO tasks (project_id, task_name) VALUES (?, ?)', 
                       (project_id, task_name))
        task_id = cursor.lastrowid
        conn.commit()
        log.info(f"Added task '{task_name}' ({task_id}) to project {project_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error adding task '{task_name}' to project {project_id}: {e}")
        task_id = None
    finally:
        if conn:
            conn.close()
    return task_id

def get_tasks(project_id):
    """Gets all tasks for a specific project."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT task_id, task_name FROM tasks WHERE project_id = ?', (project_id,))
        tasks = cursor.fetchall()
        return tasks
    except sqlite3.Error as e:
        log.error(f"Database error getting tasks for project {project_id}: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_task_name(task_id):
    """Gets the name of a specific task."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT task_name FROM tasks WHERE task_id = ?', (task_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        log.error(f"Database error getting name for task {task_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def delete_task(task_id):
    """Deletes a task. Associated sessions are handled by CASCADE constraints."""
    conn = None
    deleted = False
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.execute("PRAGMA foreign_keys = ON") # Ensure constraints are enforced
        cursor = conn.cursor()
        # Clear this task as current task for any user
        cursor.execute("UPDATE users SET current_task_id = NULL WHERE current_task_id = ?", (task_id,))

        # Delete the task (CASCADE should handle sessions)
        cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        
        conn.commit()
        log.info(f"Task {task_id} deleted successfully (CASCADE handled related sessions).")
        deleted = True
    except sqlite3.Error as e:
        log.error(f"Database error during task deletion: {e}")
        if conn: conn.rollback()
        deleted = False
    finally:
        if conn:
            conn.close()
    return deleted

def add_pomodoro_session(user_id, start_time, duration_minutes, completed=0, session_type='work', project_id=None, task_id=None):
    """
    Add a completed session (work or break) to the database.
    
    Parameters:
    user_id (int): Telegram user ID
    start_time (datetime): When the timer was started (initial start)
    duration_minutes (float): Time worked/break duration in minutes
    completed (int): 1 if the full duration was completed, 0 otherwise
    session_type (str): 'work' or 'break'
    project_id (int, optional): ID of the project (for work sessions)
    task_id (int, optional): ID of the task (for work sessions)
    
    Returns:
    int: The ID of the inserted session
    """
    conn = None
    session_id = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        start_time_str = start_time.isoformat()
        end_time_str = datetime.now().isoformat() 
        
        # Ensure project/task are NULL if it's a break session
        if session_type == 'break':
            project_id = None
            task_id = None

        cursor.execute('''
            INSERT INTO pomodoro_sessions 
            (user_id, project_id, task_id, start_time, end_time, work_duration, session_type, completed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, project_id, task_id, start_time_str, end_time_str, duration_minutes, session_type, completed))
        
        session_id = cursor.lastrowid
        conn.commit()
        log.info(f"Added {session_type} session {session_id} for user {user_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error adding {session_type} session for user {user_id}: {e}")
        session_id = None
    finally:
        if conn:
            conn.close()
    return session_id

def get_daily_report(user_id):
    """
    Get the total time worked today for a user
    
    Parameters:
    user_id (int): Telegram user ID
    
    Returns:
    tuple: (total_minutes, project_breakdown)
        total_minutes (float): Total minutes worked today
        project_breakdown (list): List of (project_name, minutes) tuples
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Get today's date in UTC to be safe
        today = datetime.utcnow().date().isoformat()
        
        # Get total WORK minutes worked today
        cursor.execute('''
            SELECT SUM(COALESCE(work_duration, 0)) 
            FROM pomodoro_sessions
            WHERE user_id = ? AND DATE(start_time) = DATE(?) AND session_type = 'work'
        ''', (user_id, today))
        
        total_minutes = cursor.fetchone()[0] or 0.0
        
        # Get breakdown by project (only for work sessions)
        cursor.execute('''
            SELECT p.project_name, SUM(COALESCE(ps.work_duration, 0))
            FROM pomodoro_sessions ps
            JOIN projects p ON ps.project_id = p.project_id
            WHERE ps.user_id = ? AND DATE(ps.start_time) = DATE(?) AND ps.session_type = 'work'
            GROUP BY ps.project_id, p.project_name
            ORDER BY SUM(COALESCE(ps.work_duration, 0)) DESC
        ''', (user_id, today))
        
        project_breakdown = cursor.fetchall()
        
        return (total_minutes, project_breakdown)
    except sqlite3.Error as e:
        log.error(f"Database error getting daily report for user {user_id}: {e}")
        return (0.0, []) # Return empty report on error
    finally:
        if conn:
            conn.close()

def get_weekly_report(user_id):
    """
    Get the total time worked this week (Mon-Sun) for a user
    
    Parameters:
    user_id (int): Telegram user ID
    
    Returns:
    tuple: (total_minutes, daily_breakdown, project_breakdown)
        total_minutes (float): Total minutes worked this week
        daily_breakdown (list): List of (date, minutes) tuples
        project_breakdown (list): List of (project_name, minutes) tuples
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row  # Allows accessing columns by name
        cursor = conn.cursor()
        
        # Get total WORK minutes worked this week
        cursor.execute('''
            SELECT SUM(COALESCE(work_duration, 0)) as total
            FROM pomodoro_sessions
            WHERE user_id = ? 
            AND DATE(start_time) >= DATE('now', 'weekday 0', '-6 days') -- Previous Monday
            AND DATE(start_time) < DATE('now', 'weekday 0', '+1 day') -- Next Monday
            AND session_type = 'work'
        ''', (user_id,))
        
        result = cursor.fetchone()
        total_minutes = result['total'] if result and result['total'] else 0.0
        
        # Get WORK breakdown by day
        cursor.execute('''
            SELECT DATE(start_time) as day, SUM(COALESCE(work_duration, 0)) as minutes
            FROM pomodoro_sessions
            WHERE user_id = ?
            AND DATE(start_time) >= DATE('now', 'weekday 0', '-6 days')
            AND DATE(start_time) < DATE('now', 'weekday 0', '+1 day')
            AND session_type = 'work'
            GROUP BY day
            ORDER BY day
        ''', (user_id,))
        
        daily_breakdown = [(row['day'], row['minutes']) for row in cursor.fetchall()]
        
        # Get WORK breakdown by project
        cursor.execute('''
            SELECT p.project_name, SUM(COALESCE(ps.work_duration, 0)) as minutes
            FROM pomodoro_sessions ps
            JOIN projects p ON ps.project_id = p.project_id
            WHERE ps.user_id = ?
            AND DATE(ps.start_time) >= DATE('now', 'weekday 0', '-6 days')
            AND DATE(ps.start_time) < DATE('now', 'weekday 0', '+1 day')
            AND ps.session_type = 'work'
            GROUP BY ps.project_id, p.project_name
            ORDER BY minutes DESC
        ''', (user_id,))
        
        project_breakdown = [(row['project_name'], row['minutes']) for row in cursor.fetchall()]
        
        return (total_minutes, daily_breakdown, project_breakdown)
    except sqlite3.Error as e:
        log.error(f"Database error getting weekly report for user {user_id}: {e}")
        return (0.0, [], [])
    finally:
        if conn:
            conn.close()

def get_monthly_report(user_id):
    """
    Get the total time worked this month for a user
    
    Parameters:
    user_id (int): Telegram user ID
    
    Returns:
    tuple: (total_minutes, project_breakdown)
        total_minutes (float): Total minutes worked this month
        project_breakdown (list): List of (project_name, minutes) tuples
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get the current month's start and end dates (using SQLite functions)
        cursor.execute("SELECT DATE('now', 'start of month') as start_date")
        start_date = cursor.fetchone()['start_date']
        cursor.execute("SELECT DATE('now', 'start of month', '+1 month') as next_month_start")
        next_month_start = cursor.fetchone()['next_month_start']
        
        # Get total WORK minutes worked this month
        cursor.execute('''
            SELECT SUM(COALESCE(work_duration, 0)) as total
            FROM pomodoro_sessions
            WHERE user_id = ? 
            AND DATE(start_time) >= ? 
            AND DATE(start_time) < ?
            AND session_type = 'work'
        ''', (user_id, start_date, next_month_start))
        
        result = cursor.fetchone()
        total_minutes = result['total'] if result and result['total'] else 0.0
        
        # Get WORK breakdown by project
        cursor.execute('''
            SELECT p.project_name, SUM(COALESCE(ps.work_duration, 0)) as minutes
            FROM pomodoro_sessions ps
            JOIN projects p ON ps.project_id = p.project_id
            WHERE ps.user_id = ?
            AND DATE(ps.start_time) >= ? 
            AND DATE(ps.start_time) < ?
            AND ps.session_type = 'work'
            GROUP BY ps.project_id, p.project_name
            ORDER BY minutes DESC
        ''', (user_id, start_date, next_month_start))
        
        project_breakdown = [(row['project_name'], row['minutes']) for row in cursor.fetchall()]
        
        return (total_minutes, project_breakdown)
    except sqlite3.Error as e:
        log.error(f"Database error getting monthly report for user {user_id}: {e}")
        return (0.0, [])
    finally:
        if conn:
            conn.close()

def get_last_session_details(user_id: int, task_id: int) -> tuple | None:
    """Fetches the details (session_id, start_time, type) of the most recent session for a given task and user."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT session_id, start_time, session_type
            FROM pomodoro_sessions
            WHERE user_id = ? AND task_id = ?
            ORDER BY start_time DESC
            LIMIT 1
            """,
            (user_id, task_id),
        )
        return cursor.fetchone()
    except sqlite3.Error as e:
        log.error(f"Error fetching last session details for user {user_id}, task {task_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

# --- Initialization ---
if __name__ == '__main__':
    # Ensure the logger is configured if running standalone
    logging.basicConfig(level=logging.INFO)
    create_database()
    # You might want to add ALTER TABLE statements here if needed for existing dbs
    # e.g., try adding columns and ignore errors if they exist
    print("Database checked/initialized.")