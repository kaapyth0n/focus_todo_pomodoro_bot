import sqlite3
from datetime import datetime

DB_NAME = 'focus_pomodoro.db'

def create_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT
        )
    ''')
    
    # Projects table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            project_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            project_name TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    
    # Tasks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            task_name TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
    ''')
    
    # Pomodoro sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pomodoro_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            project_id INTEGER,
            task_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            work_duration REAL,  -- in minutes (using REAL for decimal precision)
            completed INTEGER,   -- 0 or 1 (boolean)
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (project_id) REFERENCES projects(project_id),
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

# Helper functions
def add_user(user_id, first_name, last_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, first_name, last_name) VALUES (?, ?, ?)', 
                   (user_id, first_name, last_name))
    conn.commit()
    conn.close()

def add_project(user_id, project_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO projects (user_id, project_name) VALUES (?, ?)', 
                   (user_id, project_name))
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return project_id

def add_task(project_id, task_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tasks (project_id, task_name) VALUES (?, ?)', 
                   (project_id, task_name))
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id

def get_projects(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT project_id, project_name FROM projects WHERE user_id = ?', (user_id,))
    projects = cursor.fetchall()
    conn.close()
    return projects

def get_tasks(project_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT task_id, task_name FROM tasks WHERE project_id = ?', (project_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def get_project_name(project_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT project_name FROM projects WHERE project_id = ?', (project_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_task_name(task_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT task_name FROM tasks WHERE task_id = ?', (task_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def add_pomodoro_session(user_id, project_id, task_id, start_time, work_duration, completed=0):
    """
    Add a completed Pomodoro session to the database
    
    Parameters:
    user_id (int): Telegram user ID
    project_id (int): ID of the project
    task_id (int): ID of the task
    start_time (datetime): When the timer was started
    work_duration (float): Time worked in minutes
    completed (int): 1 if the full 25 minutes was completed, 0 otherwise
    
    Returns:
    int: The ID of the inserted session
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Convert datetime to string for SQLite storage
    start_time_str = start_time.isoformat()
    end_time_str = datetime.now().isoformat()
    
    cursor.execute('''
        INSERT INTO pomodoro_sessions 
        (user_id, project_id, task_id, start_time, end_time, work_duration, completed)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, project_id, task_id, start_time_str, end_time_str, work_duration, completed))
    
    session_id = cursor.lastrowid
    conn.commit()
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
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Get today's date
    today = datetime.now().date().isoformat()
    
    # Get total minutes worked today
    cursor.execute('''
        SELECT SUM(work_duration) 
        FROM pomodoro_sessions
        WHERE user_id = ? AND DATE(start_time) = ?
    ''', (user_id, today))
    
    total_minutes = cursor.fetchone()[0] or 0
    
    # Get breakdown by project
    cursor.execute('''
        SELECT p.project_name, SUM(ps.work_duration)
        FROM pomodoro_sessions ps
        JOIN projects p ON ps.project_id = p.project_id
        WHERE ps.user_id = ? AND DATE(ps.start_time) = ?
        GROUP BY ps.project_id
    ''', (user_id, today))
    
    project_breakdown = cursor.fetchall()
    
    conn.close()
    return (total_minutes, project_breakdown)

def get_weekly_report(user_id):
    """
    Get the total time worked this week for a user
    
    Parameters:
    user_id (int): Telegram user ID
    
    Returns:
    tuple: (total_minutes, daily_breakdown, project_breakdown)
        total_minutes (float): Total minutes worked this week
        daily_breakdown (list): List of (date, minutes) tuples
        project_breakdown (list): List of (project_name, minutes) tuples
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # This allows accessing columns by name
    cursor = conn.cursor()
    
    # Get total minutes worked this week
    cursor.execute('''
        SELECT SUM(work_duration) as total
        FROM pomodoro_sessions
        WHERE user_id = ? 
        AND DATE(start_time) >= date('now', 'weekday 0', '-6 days')
        AND DATE(start_time) <= date('now')
    ''', (user_id,))
    
    result = cursor.fetchone()
    total_minutes = result['total'] if result and result['total'] else 0
    
    # Get breakdown by day
    cursor.execute('''
        SELECT DATE(start_time) as day, SUM(work_duration) as minutes
        FROM pomodoro_sessions
        WHERE user_id = ?
        AND DATE(start_time) >= date('now', 'weekday 0', '-6 days')
        AND DATE(start_time) <= date('now')
        GROUP BY DATE(start_time)
        ORDER BY DATE(start_time)
    ''', (user_id,))
    
    daily_breakdown = [(row['day'], row['minutes']) for row in cursor.fetchall()]
    
    # Get breakdown by project
    cursor.execute('''
        SELECT p.project_name, SUM(ps.work_duration) as minutes
        FROM pomodoro_sessions ps
        JOIN projects p ON ps.project_id = p.project_id
        WHERE ps.user_id = ?
        AND DATE(ps.start_time) >= date('now', 'weekday 0', '-6 days')
        AND DATE(ps.start_time) <= date('now')
        GROUP BY ps.project_id
        ORDER BY minutes DESC
    ''', (user_id,))
    
    project_breakdown = [(row['project_name'], row['minutes']) for row in cursor.fetchall()]
    
    conn.close()
    return (total_minutes, daily_breakdown, project_breakdown)

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
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get the current month's start and end dates
    cursor.execute("SELECT date('now', 'start of month') as start_date, date('now', 'start of month', '+1 month', '-1 day') as end_date")
    date_range = cursor.fetchone()
    start_date = date_range['start_date']
    end_date = date_range['end_date']
    
    # Get total minutes worked this month
    cursor.execute('''
        SELECT SUM(work_duration) as total
        FROM pomodoro_sessions
        WHERE user_id = ? 
        AND DATE(start_time) >= ?
        AND DATE(start_time) <= ?
    ''', (user_id, start_date, end_date))
    
    result = cursor.fetchone()
    total_minutes = result['total'] if result and result['total'] else 0
    
    # Get breakdown by project
    cursor.execute('''
        SELECT p.project_name, SUM(ps.work_duration) as minutes
        FROM pomodoro_sessions ps
        JOIN projects p ON ps.project_id = p.project_id
        WHERE ps.user_id = ?
        AND DATE(ps.start_time) >= ?
        AND DATE(ps.start_time) <= ?
        GROUP BY ps.project_id
        ORDER BY minutes DESC
    ''', (user_id, start_date, end_date))
    
    project_breakdown = [(row['project_name'], row['minutes']) for row in cursor.fetchall()]
    
    conn.close()
    return (total_minutes, project_breakdown)

def delete_project(project_id):
    """Deletes a project and all associated tasks and sessions."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Get associated task IDs first
        cursor.execute("SELECT task_id FROM tasks WHERE project_id = ?", (project_id,))
        task_ids = [row[0] for row in cursor.fetchall()]
        
        # Delete sessions associated with those tasks
        if task_ids:
            placeholders = ',' .join('?' * len(task_ids))
            cursor.execute(f"DELETE FROM pomodoro_sessions WHERE task_id IN ({placeholders})", task_ids)
            
        # Delete tasks associated with the project
        cursor.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
        
        # Delete the project itself
        cursor.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
        
        conn.commit()
        print(f"Project {project_id} and related data deleted successfully.")
        return True
    except sqlite3.Error as e:
        print(f"Database error during project deletion: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def delete_task(task_id):
    """Deletes a task and all associated sessions."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Delete sessions associated with the task
        cursor.execute("DELETE FROM pomodoro_sessions WHERE task_id = ?", (task_id,))
        
        # Delete the task itself
        cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        
        conn.commit()
        print(f"Task {task_id} and related sessions deleted successfully.")
        return True
    except sqlite3.Error as e:
        print(f"Database error during task deletion: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == '__main__':
    create_database()