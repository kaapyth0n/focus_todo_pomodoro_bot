import sqlite3
from datetime import datetime
import logging # Add logging
import traceback
import json # Needed for credentials handling
from collections import defaultdict # Import defaultdict

DB_NAME = 'focus_pomodoro.db'

# Get a logger instance
log = logging.getLogger(__name__)

# Status Constants
STATUS_ACTIVE = 0
STATUS_DONE = 1

# --- Database Initialization and Schema Management ---
def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row # Return rows as dictionary-like objects
    conn.execute("PRAGMA foreign_keys = ON;") # Enforce foreign key constraints
    return conn

def _check_add_columns(conn, table_name: str, columns_to_add: dict):
    """Generic helper to add missing columns to a table."""
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = [column[1] for column in cursor.fetchall()]
        
        added_any = False
        for col_name, col_definition in columns_to_add.items():
            if col_name not in existing_columns:
                log.info(f"Adding column '{col_name}' to table '{table_name}'.")
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}")
                log.info(f"Column '{col_name}' added.")
                added_any = True
            else:
                log.debug(f"Column '{col_name}' already exists in table '{table_name}'.")
                
        if added_any:
            conn.commit()
            
    except sqlite3.Error as e:
        log.error(f"Failed to check/add columns to '{table_name}' table: {e}")
        conn.rollback() 

def _create_bot_settings_table(conn):
    """Helper to create the bot_settings table if it doesn't exist."""
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT
            )
        ''')
        conn.commit()
        log.info("Table 'bot_settings' checked/created successfully.")
    except sqlite3.Error as e:
        log.error(f"Failed to create 'bot_settings' table: {e}")
        conn.rollback()

def create_database():
    """Creates the database tables if they don't exist and applies migrations."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # --- Create Tables ---\n        # Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                current_project_id INTEGER DEFAULT NULL, 
                current_task_id INTEGER DEFAULT NULL,
                google_credentials_json TEXT DEFAULT NULL, 
                google_sheet_id TEXT DEFAULT NULL, -- Added column
                is_admin INTEGER DEFAULT 0, -- Added column
                language_code TEXT DEFAULT 'en', -- Added language preference
                jira_credentials_json TEXT DEFAULT NULL,
                jira_cloud_id TEXT DEFAULT NULL,
                FOREIGN KEY (current_project_id) REFERENCES projects(project_id) ON DELETE SET NULL,
                FOREIGN KEY (current_task_id) REFERENCES tasks(task_id) ON DELETE SET NULL
            )
        ''')
        
        # Check and add missing columns
        _check_add_columns(conn, 'users', { 
            'google_credentials_json': 'TEXT DEFAULT NULL', 
            'google_sheet_id': 'TEXT DEFAULT NULL', 
            'is_admin': 'INTEGER DEFAULT 0', 
            'language_code': 'TEXT DEFAULT \'en\'',
            'jira_credentials_json': 'TEXT DEFAULT NULL',
            'jira_cloud_id': 'TEXT DEFAULT NULL'
        })
        
        # --- Projects Table --- 
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS projects (
                project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                project_name TEXT,
                status INTEGER DEFAULT {STATUS_ACTIVE}, -- Added status
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # Check and add missing columns
        _check_add_columns(conn, 'projects', {'status': f'INTEGER DEFAULT {STATUS_ACTIVE}'})
        
        # --- Tasks Table --- 
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                task_name TEXT,
                status INTEGER DEFAULT {STATUS_ACTIVE}, -- Added status
                FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            )
        ''')
        
        # Check and add missing columns
        _check_add_columns(conn, 'tasks', {'status': f'INTEGER DEFAULT {STATUS_ACTIVE}'})
        
        # --- Pomodoro Sessions Table --- 
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
        
        # --- Bot Settings Table --- 
        _create_bot_settings_table(conn)
        
        # --- Forwarded Messages Table ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS forwarded_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                project_id INTEGER,
                message_text TEXT,
                original_sender_name TEXT,
                forwarded_date TEXT,
                tg_message_id INTEGER,
                tg_chat_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL
            )
        ''')
        
        log.info("Database tables ensured.")

        # --- Schema Migrations ---
        _apply_migrations(cursor)

        conn.commit()

    except sqlite3.Error as e:
        log.error(f"Database error during creation/migration: {e}", exc_info=True)
        conn.rollback() # Rollback changes on error
        raise # Re-raise the exception to be handled by the caller
    finally:
        conn.close()

def _apply_migrations(cursor):
    """Applies necessary schema changes."""
    log.info("Applying database migrations if needed...")
    # --- Add language_code column to users table (Migration 1) ---
    try:
        cursor.execute("SELECT language_code FROM users LIMIT 1;")
        log.info("Column 'language_code' already exists in 'users' table.")
    except sqlite3.OperationalError:
        log.info("Adding 'language_code' column to 'users' table...")
        cursor.execute("ALTER TABLE users ADD COLUMN language_code TEXT DEFAULT 'en';")
        log.info("Column 'language_code' added successfully.")

    # --- Add admin_notify column to users table (Migration 2) ---
    # ... existing migration logic ...

    # --- Add is_admin column to users table (Migration 3 - Check if needed) ---
    # ... existing migration logic ...

    log.info("Database migrations complete.")

# --- User Management ---
# Moved these functions up to ensure get_db_connection is defined before use

def add_user(user_id, first_name, last_name):
    """Adds or updates a user in the database."""
    conn = None
    try:
        conn = get_db_connection() # Use helper function
        cursor = conn.cursor()
        # Use INSERT OR IGNORE to handle existing users gracefully
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, first_name, last_name, language_code)
            VALUES (?, ?, ?, ?)
        ''', (user_id, first_name, last_name, 'en')) # Default to 'en' on creation
        conn.commit()
        if cursor.rowcount > 0:
             log.info(f"Added user {user_id}.")
        else:
             log.info(f"User {user_id} already exists, ignored insert.")
             # Optionally, update first/last name here if needed
             # cursor.execute("UPDATE users SET first_name = ?, last_name = ? WHERE user_id = ?", 
             #                (first_name, last_name, user_id))
             # conn.commit()
             # log.info(f"Updated names for existing user {user_id}")

    except sqlite3.Error as e:
        log.error(f"Error adding/updating user {user_id}: {e}", exc_info=True)
        if conn: conn.rollback()
    finally:
        if conn:
            conn.close()

def get_user_language(user_id):
    """Gets the preferred language code for a user."""
    conn = None
    try:
        conn = get_db_connection() # Use helper function
        cursor = conn.cursor()
        cursor.execute("SELECT language_code FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        # conn.row_factory = sqlite3.Row is set by get_db_connection()
        if result and result['language_code']:
            return result['language_code']
        return 'en' # Return default language 'en'
    except sqlite3.Error as e:
        log.error(f"Error getting language for user {user_id}: {e}", exc_info=True)
        return 'en' # Return default on error
    except TypeError as e: # Catch potential Row factory issue explicitly
        log.error(f"TypeError accessing language for user {user_id}. DB row format issue? Error: {e}", exc_info=True)
        return 'en' # Return default on this error too
    finally:
        if conn:
            conn.close()

def set_user_language(user_id, language_code):
    """Sets the preferred language code for a user."""
    conn = None
    try:
        conn = get_db_connection() # Use helper function
        cursor = conn.cursor()
        # Optional: Validate if language_code is in SUPPORTED_LANGUAGES from config?
        cursor.execute("UPDATE users SET language_code = ? WHERE user_id = ?", (language_code, user_id))
        conn.commit()
        if cursor.rowcount > 0:
            log.info(f"Set language to '{language_code}' for user {user_id}")
            return True
        else:
            log.warning(f"Attempted to set language for non-existent user {user_id}")
            return False # User not found
    except sqlite3.Error as e:
        log.error(f"Error setting language for user {user_id}: {e}", exc_info=True)
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# --- Rest of the original file ...

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
    """Adds a new active project for a user."""
    conn = None
    project_id = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Insert with default status (active)
        cursor.execute('INSERT INTO projects (user_id, project_name, status) VALUES (?, ?, ?)', 
                       (user_id, project_name, STATUS_ACTIVE))
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

def get_projects(user_id, status: int = STATUS_ACTIVE):
    """Gets projects for a user, filtered by status (default: active)."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT project_id, project_name FROM projects WHERE user_id = ? AND status = ?', 
                       (user_id, status))
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

def rename_project(project_id, new_name):
    """Renames a project. Returns True on success, False on failure."""
    conn = None
    renamed = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Get the user_id for this project to check for duplicates
        cursor.execute('SELECT user_id FROM projects WHERE project_id = ?', (project_id,))
        result = cursor.fetchone()
        if not result:
            log.warning(f"Attempted to rename non-existent project {project_id}")
            return False
        user_id = result[0]

        # Check for duplicate names (case-insensitive)
        cursor.execute('SELECT project_id FROM projects WHERE user_id = ? AND LOWER(project_name) = LOWER(?) AND project_id != ?',
                       (user_id, new_name, project_id))
        if cursor.fetchone():
            log.info(f"Rename project {project_id} failed: duplicate name '{new_name}' for user {user_id}")
            return False

        # Update the project name
        cursor.execute('UPDATE projects SET project_name = ? WHERE project_id = ?', (new_name, project_id))
        conn.commit()
        log.info(f"Project {project_id} renamed to '{new_name}' successfully.")
        renamed = True
    except sqlite3.Error as e:
        log.error(f"Database error renaming project {project_id}: {e}")
        if conn: conn.rollback()
        renamed = False
    finally:
        if conn:
            conn.close()
    return renamed

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
    """Adds a new active task to a specific project."""
    conn = None
    task_id = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Insert with default status (active)
        cursor.execute('INSERT INTO tasks (project_id, task_name, status) VALUES (?, ?, ?)', 
                       (project_id, task_name, STATUS_ACTIVE))
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

def get_tasks(project_id, status: int = STATUS_ACTIVE):
    """Gets tasks for a specific project, filtered by status (default: active)."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT task_id, task_name FROM tasks WHERE project_id = ? AND status = ?', 
                       (project_id, status))
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

def rename_task(task_id, new_name):
    """Renames a task. Returns True on success, False on failure."""
    conn = None
    renamed = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Get the project_id for this task to check for duplicates
        cursor.execute('SELECT project_id FROM tasks WHERE task_id = ?', (task_id,))
        result = cursor.fetchone()
        if not result:
            log.warning(f"Attempted to rename non-existent task {task_id}")
            return False
        project_id = result[0]

        # Check for duplicate names (case-insensitive) within the same project
        cursor.execute('SELECT task_id FROM tasks WHERE project_id = ? AND LOWER(task_name) = LOWER(?) AND task_id != ?',
                       (project_id, new_name, task_id))
        if cursor.fetchone():
            log.info(f"Rename task {task_id} failed: duplicate name '{new_name}' in project {project_id}")
            return False

        # Update the task name
        cursor.execute('UPDATE tasks SET task_name = ? WHERE task_id = ?', (new_name, task_id))
        conn.commit()
        log.info(f"Task {task_id} renamed to '{new_name}' successfully.")
        renamed = True
    except sqlite3.Error as e:
        log.error(f"Database error renaming task {task_id}: {e}")
        if conn: conn.rollback()
        renamed = False
    finally:
        if conn:
            conn.close()
    return renamed

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

# Helper function to structure report data
def _structure_report_data(rows):
    """Structures flat SQL rows into a nested project/task breakdown."""
    detailed_breakdown = defaultdict(lambda: {'project_minutes': 0.0, 'tasks': []})
    total_minutes = 0.0
    for proj_name, task_name, task_mins in rows:
        if task_mins is None: continue # Skip if duration is somehow NULL
        task_mins = float(task_mins) # Ensure float
        total_minutes += task_mins
        detailed_breakdown[proj_name]['project_minutes'] += task_mins
        detailed_breakdown[proj_name]['tasks'].append({'task_name': task_name or 'Unnamed Task', 'task_minutes': task_mins})

    # Convert dict to list of dicts, sorted by project time
    final_breakdown = sorted(
        [
            {
                'project_name': name,
                'project_minutes': data['project_minutes'],
                # Sort tasks within project by time
                'tasks': sorted(data['tasks'], key=lambda x: x['task_minutes'], reverse=True)
            }
            for name, data in detailed_breakdown.items()
        ],
        key=lambda x: x['project_minutes'],
        reverse=True
    )
    return total_minutes, final_breakdown

def get_daily_report(user_id: int, offset: int = 0):
    """
    Get the total time worked for a specific day and detailed breakdown.
    
    Args:
        user_id (int): Telegram user ID.
        offset (int): 0 for today, -1 for yesterday, 1 for tomorrow, etc.

    Returns:
    tuple: (report_date, total_minutes, detailed_breakdown)
        report_date (str): The date the report is for (YYYY-MM-DD).
        total_minutes (float): Total minutes worked for that day.
        detailed_breakdown (list): Project/task breakdown for that day.
    """
    conn = None
    report_date = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Calculate the target date based on the offset
        cursor.execute("SELECT DATE('now', ?, 'localtime')", (f"{offset} days",))
        target_date_result = cursor.fetchone()
        if not target_date_result:
            log.error(f"Could not calculate target date for offset {offset}")
            return None, 0.0, []
        report_date = target_date_result[0]
        
        # Get detailed breakdown by project and task for the target date
        cursor.execute('''
            SELECT 
                p.project_name, 
                t.task_name, 
                SUM(COALESCE(ps.work_duration, 0)) as task_minutes
            FROM pomodoro_sessions ps
            JOIN projects p ON ps.project_id = p.project_id
            JOIN tasks t ON ps.task_id = t.task_id
            WHERE ps.user_id = ? 
              AND DATE(ps.start_time) = ? 
              AND ps.session_type = 'work'
              AND ps.project_id IS NOT NULL
              AND ps.task_id IS NOT NULL
            GROUP BY ps.project_id, ps.task_id, p.project_name, t.task_name
            ORDER BY p.project_name, task_minutes DESC
        ''', (user_id, report_date))
        
        rows = cursor.fetchall()
        total_minutes, detailed_breakdown = _structure_report_data(rows)
        
        log.debug(f"Generated daily report for user {user_id}, date {report_date}, offset {offset}")
        return (report_date, total_minutes, detailed_breakdown)
        
    except sqlite3.Error as e:
        log.error(f"Database error getting daily report for user {user_id}, offset {offset}: {e}", exc_info=True)
        return None, 0.0, [] 
    finally:
        if conn:
            conn.close()

def get_weekly_report(user_id: int, offset: int = 0):
    """
    Get weekly time worked for a specific week.

    Args:
        user_id (int): Telegram user ID.
        offset (int): 0 for current week, -1 for last week, 1 for next week, etc.

    Returns:
    tuple: (week_start_date, total_minutes, daily_breakdown, detailed_project_task_breakdown)
        week_start_date (str): The start date (Monday) of the reported week (YYYY-MM-DD).
        total_minutes (float): Total minutes worked for that week.
        daily_breakdown (list): List of (date_str, minutes) tuples for that week.
        detailed_project_task_breakdown (list): Project/task breakdown for that week.
    """
    conn = None
    week_start_date = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Calculate week start/end based on offset
        # offset * 7 days shifts to the target week, 'weekday 0' finds Monday, '-6 days' adjusts to start of week
        week_start_modifier = f"{offset * 7 - 6} days"
        week_end_modifier = f"{offset * 7 + 1} days"
        cursor.execute("SELECT DATE('now', 'weekday 0', ?, 'localtime')", (week_start_modifier,))
        week_start_result = cursor.fetchone()
        cursor.execute("SELECT DATE('now', 'weekday 0', ?, 'localtime')", (week_end_modifier,))
        week_end_result = cursor.fetchone()

        if not week_start_result or not week_end_result:
            log.error(f"Could not calculate week dates for offset {offset}")
            return None, 0.0, [], []
        week_start_date = week_start_result[0]
        week_end_date_exclusive = week_end_result[0]

        # Get WORK breakdown by day
        conn.row_factory = sqlite3.Row  # Use Row factory for daily breakdown
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DATE(start_time) as day, SUM(COALESCE(work_duration, 0)) as minutes
            FROM pomodoro_sessions
            WHERE user_id = ?
            AND DATE(start_time) >= ?
            AND DATE(start_time) < ?
            AND session_type = 'work'
            GROUP BY day
            ORDER BY day
        ''', (user_id, week_start_date, week_end_date_exclusive))
        daily_breakdown = [(row['day'], row['minutes']) for row in cursor.fetchall()]
        
        # Reset row_factory to get tuples for project/task breakdown
        conn.row_factory = None 
        cursor = conn.cursor() 

        # Get detailed project/task breakdown for the week
        cursor.execute('''
            SELECT 
                p.project_name, 
                t.task_name, 
                SUM(COALESCE(ps.work_duration, 0)) as task_minutes
            FROM pomodoro_sessions ps
            JOIN projects p ON ps.project_id = p.project_id
            JOIN tasks t ON ps.task_id = t.task_id
            WHERE ps.user_id = ? 
              AND DATE(ps.start_time) >= ?
              AND DATE(ps.start_time) < ?
              AND ps.session_type = 'work'
              AND ps.project_id IS NOT NULL
              AND ps.task_id IS NOT NULL
            GROUP BY ps.project_id, ps.task_id, p.project_name, t.task_name
            ORDER BY p.project_name, task_minutes DESC
        ''', (user_id, week_start_date, week_end_date_exclusive))
        
        rows = cursor.fetchall()
        total_minutes, detailed_project_task_breakdown = _structure_report_data(rows)

        log.debug(f"Generated weekly report for user {user_id}, week starting {week_start_date}, offset {offset}")
        return (week_start_date, total_minutes, daily_breakdown, detailed_project_task_breakdown)

    except sqlite3.Error as e:
        log.error(f"Database error getting weekly report for user {user_id}, offset {offset}: {e}", exc_info=True)
        return None, 0.0, [], []
    finally:
        if conn:
            conn.close()

def get_monthly_report(user_id: int, offset: int = 0):
    """
    Get the total time worked for a specific month and detailed breakdown.

    Args:
        user_id (int): Telegram user ID.
        offset (int): 0 for current month, -1 for last month, 1 for next month, etc.

    Returns:
    tuple: (month_start_date, total_minutes, detailed_breakdown)
        month_start_date (str): The start date of the reported month (YYYY-MM-01).
        total_minutes (float): Total minutes worked for that month.
        detailed_breakdown (list): Project/task breakdown for that month.
    """
    conn = None
    month_start_date = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Calculate the target month's start and end dates
        month_start_modifier = f"{offset} months"
        next_month_start_modifier = f"{offset + 1} months"
        cursor.execute("SELECT DATE('now', 'start of month', ?, 'localtime')", (month_start_modifier,))
        month_start_result = cursor.fetchone()
        cursor.execute("SELECT DATE('now', 'start of month', ?, 'localtime')", (next_month_start_modifier,))
        next_month_start_result = cursor.fetchone()
        
        if not month_start_result or not next_month_start_result:
            log.error(f"Could not calculate month dates for offset {offset}")
            return None, 0.0, []
        month_start_date = month_start_result[0]
        next_month_start_date = next_month_start_result[0]

        # Get detailed project/task breakdown for the month
        cursor.execute('''
            SELECT 
                p.project_name, 
                t.task_name, 
                SUM(COALESCE(ps.work_duration, 0)) as task_minutes
            FROM pomodoro_sessions ps
            JOIN projects p ON ps.project_id = p.project_id
            JOIN tasks t ON ps.task_id = t.task_id
            WHERE ps.user_id = ? 
              AND DATE(ps.start_time) >= ?
              AND DATE(ps.start_time) < ?
              AND ps.session_type = 'work'
              AND ps.project_id IS NOT NULL
              AND ps.task_id IS NOT NULL
            GROUP BY ps.project_id, ps.task_id, p.project_name, t.task_name
            ORDER BY p.project_name, task_minutes DESC
        ''', (user_id, month_start_date, next_month_start_date))
        
        rows = cursor.fetchall()
        total_minutes, detailed_breakdown = _structure_report_data(rows)
        
        log.debug(f"Generated monthly report for user {user_id}, month starting {month_start_date}, offset {offset}")
        return (month_start_date, total_minutes, detailed_breakdown)

    except sqlite3.Error as e:
        log.error(f"Database error getting monthly report for user {user_id}, offset {offset}: {e}", exc_info=True)
        return None, 0.0, []
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

# --- Google Credentials --- 
def store_google_credentials(user_id, credentials_json: str):
    """Stores the user's Google OAuth credentials (as JSON string)."""
    conn = None
    success = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET google_credentials_json = ? WHERE user_id = ?", (credentials_json, user_id))
        conn.commit()
        if cursor.rowcount > 0:
            log.info(f"Stored Google credentials for user {user_id}.")
            success = True
        else:
             log.warning(f"Attempted to store Google credentials for non-existent user {user_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error storing Google credentials for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()
    return success

def get_google_credentials(user_id):
    """Retrieves the user's Google OAuth credentials JSON string."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT google_credentials_json FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
             log.debug(f"Retrieved Google credentials for user {user_id}.")
             return result[0] # Return the JSON string
        else:
            log.debug(f"No Google credentials found for user {user_id}.")
            return None
    except sqlite3.Error as e:
        log.error(f"Database error retrieving Google credentials for user {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def store_google_sheet_id(user_id: int, sheet_id: str):
    """Stores the user's default Google Sheet ID."""
    conn = None
    success = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET google_sheet_id = ? WHERE user_id = ?", (sheet_id, user_id))
        conn.commit()
        if cursor.rowcount > 0:
            log.info(f"Stored default Google Sheet ID {sheet_id} for user {user_id}.")
            success = True
        else:
            log.warning(f"Attempted to store Google Sheet ID for non-existent user {user_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error storing Google Sheet ID for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()
    return success

def get_google_sheet_id(user_id: int):
    """Retrieves the user's default Google Sheet ID."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT google_sheet_id FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            log.debug(f"Retrieved default Google Sheet ID {result[0]} for user {user_id}.")
            return result[0]
        else:
            log.debug(f"No default Google Sheet ID found for user {user_id}.")
            return None
    except sqlite3.Error as e:
        log.error(f"Database error retrieving Google Sheet ID for user {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

# --- Jira Credentials ---
def store_jira_credentials(user_id, credentials_json: str, cloud_id: str):
    """Stores the user's Jira OAuth credentials (as JSON string) and cloud_id."""
    conn = None
    success = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET jira_credentials_json = ?, jira_cloud_id = ? WHERE user_id = ?", (credentials_json, cloud_id, user_id))
        conn.commit()
        if cursor.rowcount > 0:
            log.info(f"Stored Jira credentials for user {user_id}.")
            success = True
        else:
            log.warning(f"Attempted to store Jira credentials for non-existent user {user_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error storing Jira credentials for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()
    return success

def get_jira_credentials(user_id):
    """Retrieves the user's Jira OAuth credentials JSON string and cloud_id."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT jira_credentials_json, jira_cloud_id FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            log.debug(f"Retrieved Jira credentials for user {user_id}.")
            return result[0], result[1] # Return the JSON string and cloud_id
        else:
            log.debug(f"No Jira credentials found for user {user_id}.")
            return None, None
    except sqlite3.Error as e:
        log.error(f"Database error retrieving Jira credentials for user {user_id}: {e}")
        return None, None
    finally:
        if conn:
            conn.close()

def clear_jira_credentials(user_id):
    """Removes the user's Jira OAuth credentials and cloud_id."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET jira_credentials_json = NULL, jira_cloud_id = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        log.info(f"Cleared Jira credentials for user {user_id}.")
    except sqlite3.Error as e:
        log.error(f"Database error clearing Jira credentials for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()

# --- Data Export Functions ---
def get_all_user_sessions_for_export(user_id):
    """
    Retrieves all session data for a user, joining project/task names.
    Returns a list of lists, suitable for CSV or Sheets export, including headers.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Select relevant columns, join with projects and tasks, handle NULLs
        cursor.execute('''
            SELECT 
                DATE(ps.start_time) as SessionDate,
                COALESCE(p.project_name, 'N/A') as ProjectName,
                COALESCE(t.task_name, 'N/A') as TaskName,
                ROUND(ps.work_duration, 2) as DurationMinutes,
                ps.session_type as SessionType,
                CASE ps.completed WHEN 1 THEN 'Yes' ELSE 'No' END as Completed
            FROM pomodoro_sessions ps
            LEFT JOIN projects p ON ps.project_id = p.project_id
            LEFT JOIN tasks t ON ps.task_id = t.task_id
            WHERE ps.user_id = ?
            ORDER BY ps.start_time ASC
        ''', (user_id,))
        
        rows = cursor.fetchall()
        
        # Add header row
        header = ['Date', 'Project', 'Task', 'Duration (min)', 'Type', 'Completed']
        export_data = [header] + [list(row) for row in rows]
        
        log.debug(f"Retrieved {len(rows)} sessions for export for user {user_id}.")
        return export_data
        
    except sqlite3.Error as e:
        log.error(f"Database error retrieving sessions for export for user {user_id}: {e}")
        return None # Return None on error
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
    print("Database checked/initialized (including Google columns).")

# --- Admin Functions ---
def set_admin(user_id: int) -> bool:
    """Sets the is_admin flag to 1 for the given user_id."""
    conn = None
    success = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Reset any other admins first to ensure only one (optional, depends on design)
        # cursor.execute("UPDATE users SET is_admin = 0 WHERE is_admin = 1")
        cursor.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        if cursor.rowcount > 0:
            log.info(f"User {user_id} set as admin.")
            success = True
        else:
            log.warning(f"Failed to set admin: User {user_id} not found.")
    except sqlite3.Error as e:
        log.error(f"DB error setting admin for user {user_id}: {e}")
        if conn: conn.rollback()
    finally:
        if conn:
            conn.close()
    return success

def is_user_admin(user_id: int) -> bool:
    """Checks if the given user_id has the is_admin flag set."""
    conn = None
    is_admin = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0] == 1:
            is_admin = True
    except sqlite3.Error as e:
        log.error(f"DB error checking admin status for user {user_id}: {e}")
    finally:
        if conn:
            conn.close()
    log.debug(f"Admin check for user {user_id}: {is_admin}")
    return is_admin

def check_if_admin_exists() -> bool:
    """Checks if any user in the database is marked as admin."""
    conn = None
    admin_exists = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Check if any row has is_admin = 1
        cursor.execute("SELECT 1 FROM users WHERE is_admin = 1 LIMIT 1")
        if cursor.fetchone():
            admin_exists = True
    except sqlite3.Error as e:
        log.error(f"DB error checking if admin exists: {e}")
    finally:
        if conn:
            conn.close()
    log.debug(f"Admin exists check: {admin_exists}")
    return admin_exists

def get_admin_user_id() -> int | None:
    """Gets the user_id of the admin user (assumes only one)."""
    conn = None
    admin_id = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE is_admin = 1 LIMIT 1")
        result = cursor.fetchone()
        if result:
            admin_id = result[0]
    except sqlite3.Error as e:
        log.error(f"DB error getting admin user ID: {e}")
    finally:
        if conn:
            conn.close()
    log.debug(f"Admin user ID found: {admin_id}")
    return admin_id

# --- Bot Settings Functions ---
def get_setting(key: str, default: str | None = None) -> str | None:
    """Gets a value from the bot_settings table."""
    conn = None
    value = default
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM bot_settings WHERE setting_key = ?", (key,))
        result = cursor.fetchone()
        if result:
            value = result[0]
    except sqlite3.Error as e:
        log.error(f"DB error getting setting '{key}': {e}")
    finally:
        if conn:
            conn.close()
    log.debug(f"Setting '{key}' value: {value}")
    return value

def set_setting(key: str, value: str) -> bool:
    """Sets a value in the bot_settings table (INSERT or REPLACE)."""
    conn = None
    success = False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)", (key, value))
        conn.commit()
        success = True
        log.info(f"Set setting '{key}' to '{value}'.")
    except sqlite3.Error as e:
        log.error(f"DB error setting '{key}' to '{value}': {e}")
        if conn: conn.rollback()
    finally:
        if conn:
            conn.close()
    return success

# --- Statistics Functions ---
def get_total_users() -> int:
    """Gets the total number of registered users."""
    conn = None
    count = 0
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        result = cursor.fetchone()
        if result:
            count = result[0]
    except sqlite3.Error as e:
        log.error(f"DB error getting total users: {e}")
    finally:
        if conn:
            conn.close()
    return count

def get_total_projects() -> int:
    """Gets the total number of projects across all users."""
    conn = None
    count = 0
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM projects")
        result = cursor.fetchone()
        if result:
            count = result[0]
    except sqlite3.Error as e:
        log.error(f"DB error getting total projects: {e}")
    finally:
        if conn:
            conn.close()
    return count

def get_total_tasks() -> int:
    """Gets the total number of tasks across all projects."""
    conn = None
    count = 0
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tasks")
        result = cursor.fetchone()
        if result:
            count = result[0]
    except sqlite3.Error as e:
        log.error(f"DB error getting total tasks: {e}")
    finally:
        if conn:
            conn.close()
    return count

def get_total_work_minutes() -> float:
    """Gets the total summed work duration (in minutes) across all work sessions."""
    conn = None
    total_minutes = 0.0
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Sum only 'work' sessions, handling NULL duration just in case
        cursor.execute("SELECT SUM(COALESCE(work_duration, 0)) FROM pomodoro_sessions WHERE session_type = 'work'")
        result = cursor.fetchone()
        if result and result[0] is not None:
            total_minutes = result[0]
    except sqlite3.Error as e:
        log.error(f"DB error getting total work minutes: {e}")
    finally:
        if conn:
            conn.close()
    return total_minutes

# --- Project Management ---
def mark_project_status(project_id: int, status: int) -> bool:
    """Updates the status of a project."""
    conn = None
    success = False
    if status not in [STATUS_ACTIVE, STATUS_DONE]:
        log.warning(f"Invalid status ({status}) provided for project {project_id}.")
        return False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET status = ? WHERE project_id = ?", (status, project_id))
        conn.commit()
        if cursor.rowcount > 0:
            log.info(f"Updated status for project {project_id} to {status}.")
            success = True
        else:
            log.warning(f"Project {project_id} not found for status update.")
    except sqlite3.Error as e:
        log.error(f"DB error updating status for project {project_id}: {e}")
        if conn: conn.rollback()
    finally:
        if conn:
            conn.close()
    return success

def get_project_status(project_id: int) -> int | None:
    """Gets the status of a specific project."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT status FROM projects WHERE project_id = ?', (project_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        log.error(f"Database error getting status for project {project_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

# --- Task Management ---
def mark_task_status(task_id: int, status: int) -> bool:
    """Updates the status of a task."""
    conn = None
    success = False
    if status not in [STATUS_ACTIVE, STATUS_DONE]:
        log.warning(f"Invalid status ({status}) provided for task {task_id}.")
        return False
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status, task_id))
        conn.commit()
        if cursor.rowcount > 0:
            log.info(f"Updated status for task {task_id} to {status}.")
            success = True
        else:
            log.warning(f"Task {task_id} not found for status update.")
    except sqlite3.Error as e:
        log.error(f"DB error updating status for task {task_id}: {e}")
        if conn: conn.rollback()
    finally:
        if conn:
            conn.close()
    return success

def get_task_status(task_id: int) -> int | None:
    """Gets the status of a specific task."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT status FROM tasks WHERE task_id = ?', (task_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        log.error(f"Database error getting status for task {task_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

# --- Forwarded Messages Management ---
def add_forwarded_message(user_id, project_id, message_text, original_sender_name, forwarded_date, tg_message_id, tg_chat_id):
    """Inserts a forwarded message into the database."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO forwarded_messages (user_id, project_id, message_text, original_sender_name, forwarded_date, tg_message_id, tg_chat_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, project_id, message_text, original_sender_name, forwarded_date, tg_message_id, tg_chat_id))
        conn.commit()
        log.info(f"Added forwarded message for user {user_id} to project {project_id}.")
        return cursor.lastrowid
    except sqlite3.Error as e:
        log.error(f"Database error adding forwarded message for user {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_forwarded_messages_by_project(project_id):
    """Retrieves all forwarded messages for a given project."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, user_id, message_text, original_sender_name, forwarded_date, tg_message_id, tg_chat_id
            FROM forwarded_messages WHERE project_id = ?
            ORDER BY forwarded_date DESC
        ''', (project_id,))
        return cursor.fetchall()
    except sqlite3.Error as e:
        log.error(f"Database error retrieving forwarded messages for project {project_id}: {e}")
        return []
    finally:
        if conn:
            conn.close()