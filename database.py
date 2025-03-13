import sqlite3

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
            work_duration INTEGER,  -- in minutes
            completed INTEGER,      -- 0 or 1
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (project_id) REFERENCES projects(project_id),
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
    ''')
    
    conn.commit()
    conn.close()

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
    conn.commit()
    conn.close()

def add_task(project_id, task_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tasks (project_id, task_name) VALUES (?, ?)', 
                   (project_id, task_name))
    conn.commit()
    conn.close()

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

if __name__ == '__main__':
    create_database()