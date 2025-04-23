from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database
from datetime import datetime, timedelta
from config import timer_states, DOMAIN_URL

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and adds user to database."""
    user = update.message.from_user
    database.add_user(user.id, user.first_name, user.last_name)
    # Initialize current project/task in DB if not set (optional, but good practice)
    if database.get_current_project(user.id) is None:
        database.clear_current_project(user.id) # Ensures both are NULL initially
    await update.message.reply_text('Welcome to your Focus To-Do List Bot! Use /create_project or /help to get started.')

# --- Project Management Commands ---
async def create_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a new project."""
    user_id = update.message.from_user.id
    project_name = ' '.join(context.args)
    if not project_name:
        await update.message.reply_text('Please provide a project name. Usage: /create_project "Project Name"')
        return
    # Check if project with the same name already exists for the user
    existing_projects = database.get_projects(user_id)
    for _, existing_name in existing_projects:
        if existing_name.lower() == project_name.lower():
            await update.message.reply_text(f'Project "{existing_name}" already exists.')
            return
    database.add_project(user_id, project_name)
    await update.message.reply_text(f'Project "{project_name}" created! Select it with /select_project or /list_projects.')

async def select_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Selects a project by name or lists projects if no name is given."""
    user_id = update.message.from_user.id
    project_name = ' '.join(context.args)
    if not project_name:
        await list_projects(update, context)
        return
        
    projects = database.get_projects(user_id)
    project_found = False
    for proj_id, proj_name in projects:
        if proj_name.lower() == project_name.lower(): # Case-insensitive comparison
            database.set_current_project(user_id, proj_id) # Use DB function
            # set_current_project automatically clears the task
            await update.message.reply_text(f'Project "{proj_name}" selected.')
            project_found = True
            break
            
    if not project_found:
        await update.message.reply_text('Project not found. Use /list_projects to see available projects or /create_project to create it.')

async def list_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists user's projects with inline buttons for selection."""
    user_id = update.message.from_user.id
    projects = database.get_projects(user_id)
    if not projects:
        await update.message.reply_text("You don't have any projects yet. Create one with /create_project.")
        return
        
    keyboard = []
    current_project_id = database.get_current_project(user_id) # Get current for marking
    for project_id, project_name in projects:
        button_text = project_name
        if project_id == current_project_id:
            button_text = f"➡️ {project_name}" # Indicate current selection
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"select_project:{project_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a project (currently selected: ➡️):", reply_markup=reply_markup)

async def delete_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates the project deletion process by showing a list of projects."""
    user_id = update.message.from_user.id
    projects = database.get_projects(user_id)
    if not projects:
        await update.message.reply_text("You don't have any projects to delete.")
        return
        
    keyboard = []
    for project_id, project_name in projects:
        keyboard.append([InlineKeyboardButton(f"🗑️ {project_name}", callback_data=f"confirm_delete_project:{project_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Which project do you want to delete? (This action is irreversible!)", reply_markup=reply_markup)

# --- Task Management Commands ---
async def create_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a task to the currently selected project."""
    user_id = update.message.from_user.id
    current_project_id = database.get_current_project(user_id) # Use DB function
    if not current_project_id:
        await update.message.reply_text('Please select a project first with /list_projects.')
        return
        
    task_name = ' '.join(context.args)
    if not task_name:
        await update.message.reply_text('Please provide a task name. Usage: /create_task "Task Name"')
        return
        
    # Check if task with the same name already exists in the current project
    existing_tasks = database.get_tasks(current_project_id)
    for _, existing_name in existing_tasks:
        if existing_name.lower() == task_name.lower():
            await update.message.reply_text(f'Task "{existing_name}" already exists in this project.')
            return
            
    project_name = database.get_project_name(current_project_id)
    database.add_task(current_project_id, task_name)
    await update.message.reply_text(f'Task "{task_name}" added to project "{project_name}"!')

async def select_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Selects a task by name or lists tasks if no name is given."""
    user_id = update.message.from_user.id
    current_project_id = database.get_current_project(user_id) # Use DB function
    if not current_project_id:
        await update.message.reply_text('Please select a project first with /list_projects.')
        return
        
    task_name = ' '.join(context.args)
    project_name = database.get_project_name(current_project_id)

    if not task_name:
        await list_tasks(update, context)
        return
        
    tasks = database.get_tasks(current_project_id)
    task_found = False
    for task_id, t_name in tasks:
        if t_name.lower() == task_name.lower(): # Case-insensitive comparison
            database.set_current_task(user_id, task_id) # Use DB function
            await update.message.reply_text(f'Task "{t_name}" selected in project "{project_name}".')
            task_found = True
            break
            
    if not task_found:
        await update.message.reply_text(f'Task not found in project "{project_name}". Use /list_tasks to see available tasks or /create_task to add it.')

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists tasks in the current project with inline buttons for selection."""
    user_id = update.message.from_user.id
    current_project_id = database.get_current_project(user_id) # Use DB function
    if not current_project_id:
        await update.message.reply_text('Please select a project first using /list_projects.')
        return
        
    tasks = database.get_tasks(current_project_id)
    project_name = database.get_project_name(current_project_id)
    
    if not tasks:
        await update.message.reply_text(f"No tasks found for project '{project_name}'. Create one with /create_task.")
        return
        
    keyboard = []
    current_task_id = database.get_current_task(user_id) # Get current for marking
    for task_id, task_name in tasks:
        button_text = task_name
        if task_id == current_task_id:
             button_text = f"➡️ {task_name}" # Indicate current selection
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"select_task:{task_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Select a task in project '{project_name}' (currently selected: ➡️):", reply_markup=reply_markup)

async def delete_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates the task deletion process by showing a list of tasks in the current project."""
    user_id = update.message.from_user.id
    current_project_id = database.get_current_project(user_id) # Use DB function
    if not current_project_id:
        await update.message.reply_text('Please select a project first using /list_projects before deleting tasks.')
        return
        
    tasks = database.get_tasks(current_project_id)
    project_name = database.get_project_name(current_project_id)
    
    if not tasks:
        await update.message.reply_text(f"No tasks found in project '{project_name}' to delete.")
        return
        
    keyboard = []
    for task_id, task_name in tasks:
        keyboard.append([InlineKeyboardButton(f"🗑️ {task_name}", callback_data=f"confirm_delete_task:{task_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Which task in '{project_name}' do you want to delete? (This action is irreversible!)", reply_markup=reply_markup)

# --- Helper Function for Starting Timers ---
async def _start_timer_internal(context: ContextTypes.DEFAULT_TYPE, user_id: int, duration_minutes: int, session_type: str, project_name: str = None, task_name: str = None):
    """Internal helper to start a timer job (work or break)."""
    if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
        # This check might be redundant if called carefully, but good defense
        await context.bot.send_message(chat_id=user_id, text='Another timer is already active. Please /stop_timer first.')
        return False

    job_data = {'user_id': user_id, 'duration': duration_minutes, 'session_type': session_type}
    job = context.job_queue.run_once(timer_finished, duration_minutes * 60, data=job_data, name=f"timer_{user_id}")

    now = datetime.now()
    timer_states[user_id] = {
        'state': 'running',
        'accumulated_time': 0,
        'start_time': now,
        'initial_start_time': now,
        'duration': duration_minutes,
        'session_type': session_type, # Store session type
        'job': job
    }

    # Send confirmation message
    timer_url = f'{DOMAIN_URL}/timer/{user_id}'
    keyboard = [[InlineKeyboardButton("View Timer", url=timer_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if session_type == 'work':
        message = f'Work timer started for task "{task_name}" in project "{project_name}" ({duration_minutes} minutes).'
    else: # break
        message = f'Break timer started ({duration_minutes} minutes).'
        
    await context.bot.send_message(chat_id=user_id, text=message, reply_markup=reply_markup)
    return True

# --- Timer Commands ---
async def start_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts a WORK Pomodoro timer for the selected task, with optional duration."""
    user_id = update.message.from_user.id
    
    # Check for existing timer BEFORE database checks
    if user_id in timer_states and timer_states[user_id]['state'] != 'stopped':
        await update.message.reply_text('A timer is already running or paused. Please /stop_timer it first.')
        return
        
    project_id = database.get_current_project(user_id)
    task_id = database.get_current_task(user_id)
    if not project_id or not task_id:
        await update.message.reply_text('Please select a project (/list_projects) and task (/list_tasks) first.')
        return
        
    project_name = database.get_project_name(project_id)
    task_name = database.get_task_name(task_id)
    
    if not task_name:
        await update.message.reply_text(f'Error: The selected task no longer exists. Please select another task with /list_tasks.')
        database.clear_current_task(user_id)
        return

    duration_minutes = 25 
    if context.args:
        try:
            requested_duration = int(context.args[0])
            if 1 <= requested_duration <= 120: 
                duration_minutes = requested_duration
            else:
                await update.message.reply_text("Please provide a duration between 1 and 120 minutes.")
                return
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid duration. Using default 25 minutes.")
            # Fall through

    # Call internal helper
    await _start_timer_internal(context, user_id, duration_minutes, 'work', project_name, task_name)

async def start_break_timer(context: ContextTypes.DEFAULT_TYPE, user_id: int, duration_minutes: int):
    """Starts a BREAK timer. Called by callback handler."""
    # Call internal helper
    await _start_timer_internal(context, user_id, duration_minutes, 'break')

# --- Timer Finish Callback (Handles Work and Break) ---
async def timer_finished(context: ContextTypes.DEFAULT_TYPE):
    """Callback function executed by JobQueue when timer completes."""
    job = context.job
    user_id = job.data['user_id']
    duration_minutes = job.data['duration'] 
    session_type = job.data['session_type'] # Get session type from job
    
    if user_id in timer_states and timer_states[user_id].get('job') == job:
        
        project_id = None
        task_id = None
        project_name = None
        task_name = None
        
        if session_type == 'work':
            project_id = database.get_current_project(user_id)
            task_id = database.get_current_task(user_id)
            if project_id and task_id:
                 project_name = database.get_project_name(project_id)
                 task_name = database.get_task_name(task_id)
            else:
                # Work timer finished but project/task somehow unselected during run
                 await context.bot.send_message(chat_id=user_id, text=f"⏱️ Work timer finished ({duration_minutes} min), but project/task was unselected. Time not logged.")
                 if user_id in timer_states: del timer_states[user_id]
                 return # Exit early, do not log or offer breaks
        
        # --- Log the session --- 
        timer_state_data = timer_states[user_id]
        timer_state_data['accumulated_time'] = duration_minutes
        timer_state_data['state'] = 'stopped' 
        initial_start_time = timer_state_data['initial_start_time']

        database.add_pomodoro_session(
            user_id=user_id,
            project_id=project_id, # Will be None for breaks
            task_id=task_id,       # Will be None for breaks
            start_time=initial_start_time,
            duration_minutes=duration_minutes, 
            session_type=session_type, # Pass session type
            completed=1       
        )
        
        # --- Send Confirmation Message --- 
        if session_type == 'work':
            success_message = (
                f"✅ Time's up! Work session completed.\n\n"
                f'Project: {project_name}\n'
                f'Task: {task_name}\n'
                f'Duration: {duration_minutes} minutes'
            )
            # Add break buttons
            keyboard = [
                [InlineKeyboardButton("☕️ Start 5-min Break", callback_data="start_break:5")],
                [InlineKeyboardButton("休息 Start 15-min Break", callback_data="start_break:15")] # Example with different emoji
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(chat_id=user_id, text=success_message, reply_markup=reply_markup)
        else: # Break finished
             success_message = f"🧘 Break finished ({duration_minutes} minutes). Time to get back to work!" 
             await context.bot.send_message(chat_id=user_id, text=success_message)

        # Clean up state AFTER logging and messaging
        del timer_states[user_id]
            
    else:
        print(f"Timer finished job executed for user {user_id} ({session_type}), but state was missing or job was outdated.")

async def pause_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pauses the currently running timer."""
    user_id = update.message.from_user.id
    if user_id not in timer_states or timer_states[user_id]['state'] != 'running':
        # Handle case where user tries to pause a break timer? 
        # For now, allow pausing breaks too.
        timer_type = timer_states.get(user_id, {}).get('session_type', 'timer') # Get type for message
        await update.message.reply_text(f'No {timer_type} is running.')
        return
        
    state_data = timer_states[user_id]
    current_time = datetime.now()
    time_worked = (current_time - state_data['start_time']).total_seconds() / 60
    state_data['accumulated_time'] += time_worked
    state_data['state'] = 'paused'
    
    job = state_data.get('job')
    if job:
        job.schedule_removal()
        state_data['job'] = None 
        
    timer_type = state_data.get('session_type', 'timer').capitalize()
    await update.message.reply_text(f'{timer_type} paused. Accumulated time: {state_data["accumulated_time"]:.2f} minutes.')

async def resume_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resumes a paused timer (work or break)."""
    user_id = update.message.from_user.id
    if user_id not in timer_states or timer_states[user_id]['state'] != 'paused':
        await update.message.reply_text('No timer is paused.')
        return
        
    state_data = timer_states[user_id]
    duration_minutes = state_data['duration']
    accumulated_time = state_data['accumulated_time']
    session_type = state_data['session_type']
    remaining_time_minutes = duration_minutes - accumulated_time
    
    if remaining_time_minutes <= 0:
        await update.message.reply_text('Timer already completed or has no time left.')
        # Attempt to log if not already logged (might happen if stopped just before end)
        project_id = database.get_current_project(user_id) if session_type == 'work' else None
        task_id = database.get_current_task(user_id) if session_type == 'work' else None
        database.add_pomodoro_session(
            user_id=user_id,
            project_id=project_id,
            task_id=task_id,
            start_time=state_data['initial_start_time'], 
            duration_minutes=accumulated_time,
            session_type=session_type,
            completed=1 
        )
        del timer_states[user_id] 
        return
        
    # Schedule the timer_finished job again
    job_data = {'user_id': user_id, 'duration': duration_minutes, 'session_type': session_type}
    job = context.job_queue.run_once(timer_finished, remaining_time_minutes * 60, data=job_data, name=f"timer_{user_id}")
    
    state_data['state'] = 'running'
    state_data['start_time'] = datetime.now() 
    state_data['job'] = job
    
    timer_type = session_type.capitalize()
    await update.message.reply_text(f'{timer_type} resumed. {remaining_time_minutes:.2f} minutes remaining.')

async def stop_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stops the timer (work or break) and logs the session."""
    user_id = update.message.from_user.id
    if user_id not in timer_states or timer_states[user_id]['state'] == 'stopped':
        await update.message.reply_text('No timer is running or paused.')
        return
    
    state_data = timer_states[user_id]
    current_state = state_data['state']
    accumulated_time = state_data['accumulated_time']
    start_time_current_interval = state_data['start_time'] 
    initial_start_time = state_data['initial_start_time']
    duration_minutes = state_data['duration'] 
    session_type = state_data['session_type'] # Get session type
    job = state_data.get('job')

    if job:
        job.schedule_removal()
        
    if current_state == 'running':
        current_time = datetime.now()
        time_worked_current_interval = (current_time - start_time_current_interval).total_seconds() / 60
        accumulated_time += time_worked_current_interval
    
    is_completed = 1 if accumulated_time >= (duration_minutes - 0.01) else 0 
    
    project_id = None
    task_id = None
    project_name = None
    task_name = None
    log_message_details = f"Duration: {accumulated_time:.2f} / {duration_minutes} minutes"

    if session_type == 'work':
        timer_type_display = "Work timer"
        project_id = database.get_current_project(user_id)
        task_id = database.get_current_task(user_id)
        if project_id and task_id:
            project_name = database.get_project_name(project_id)
            task_name = database.get_task_name(task_id)
            if project_name and task_name:
                 log_message_details = f'Project: {project_name}\nTask: {task_name}\nDuration: {accumulated_time:.2f} / {duration_minutes} minutes'
            else: # Handle case where project/task deleted during run
                log_message_details += " (Project/Task info missing)"        
        else:
            log_message_details += " (No project/task selected)"
    else: # Break
        timer_type_display = "Break timer"
        # No project/task needed for break message

    # Log session regardless of project/task selection for breaks
    database.add_pomodoro_session(
        user_id=user_id,
        project_id=project_id, # None for breaks
        task_id=task_id,       # None for breaks
        start_time=initial_start_time, 
        duration_minutes=accumulated_time,
        session_type=session_type, # Pass session type
        completed=is_completed
    )
        
    # Send message
    message = f'⏹️ {timer_type_display} stopped.\n\n{log_message_details}'
    await update.message.reply_text(message)
       
    # Clean up timer state completely AFTER logging and messaging
    if user_id in timer_states:
        del timer_states[user_id]

# --- Report Commands ---
# (Report commands remain largely the same, using DB queries)
async def report_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the daily report."""
    user_id = update.message.from_user.id
    total_minutes, project_breakdown = database.get_daily_report(user_id)
    
    if total_minutes == 0:
        await update.message.reply_text("You haven't completed any Pomodoro sessions today.")
        return
        
    report = f"📊 *Daily Report*\n\n"
    report += f"Total time today: *{total_minutes:.1f} minutes*\n\n"
    
    if project_breakdown:
        report += "*Project Breakdown:*\n"
        for project_name, minutes in project_breakdown:
            percentage = (minutes / total_minutes) * 100 if total_minutes > 0 else 0
            report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
    
    await update.message.reply_text(report, parse_mode='Markdown')

async def report_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the weekly report."""
    user_id = update.message.from_user.id
    total_minutes, daily_breakdown, project_breakdown = database.get_weekly_report(user_id)
    
    if total_minutes == 0:
        await update.message.reply_text("You haven't completed any Pomodoro sessions this week.")
        return
    
    report = f"📈 *Weekly Report*\n\n"
    report += f"Total time this week: *{total_minutes:.1f} minutes*\n\n"
    
    if daily_breakdown:
        report += "*Daily Breakdown:*\n"
        for date, minutes in daily_breakdown:
            try:
                date_obj = datetime.fromisoformat(date).strftime("%a, %b %d")
                report += f"• {date_obj}: {minutes:.1f} min\n"
            except (ValueError, TypeError):
                report += f"• {date}: {minutes:.1f} min\n"
    
    if project_breakdown:
        report += "\n*Project Breakdown:*\n"
        for project_name, minutes in project_breakdown:
            percentage = (minutes / total_minutes) * 100 if total_minutes > 0 else 0
            report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
    
    await update.message.reply_text(report, parse_mode='Markdown')

async def report_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the monthly report."""
    user_id = update.message.from_user.id
    total_minutes, project_breakdown = database.get_monthly_report(user_id)
    
    if total_minutes == 0:
        await update.message.reply_text("You haven't completed any Pomodoro sessions this month.")
        return
    
    current_month = datetime.now().strftime("%B %Y")
    report = f"📅 *Monthly Report: {current_month}*\n\n"
    report += f"Total time this month: *{total_minutes:.1f} minutes* ({total_minutes/60:.1f} hours)\n\n"
    
    if project_breakdown:
        report += "*Project Breakdown:*\n"
        for project_name, minutes in project_breakdown:
            percentage = (minutes / total_minutes) * 100 if total_minutes > 0 else 0
            report += f"• {project_name}: {minutes:.1f} min ({percentage:.1f}%)\n"
    
    await update.message.reply_text(report, parse_mode='Markdown')

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /report command, showing options or specific reports."""
    if not context.args or len(context.args) == 0:
        keyboard = [
            [InlineKeyboardButton("📊 Daily", callback_data="report_daily")],
            [InlineKeyboardButton("📈 Weekly", callback_data="report_weekly")],
            [InlineKeyboardButton("📅 Monthly", callback_data="report_monthly")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Which report would you like to see?", reply_markup=reply_markup)
        return
    
    report_type = context.args[0].lower()
    if report_type == "daily":
        await report_daily(update, context)
    elif report_type == "weekly":
        await report_weekly(update, context)
    elif report_type == "monthly":
        await report_monthly(update, context)
    else:
        await update.message.reply_text("Unknown report type. Available options: daily, weekly, monthly. Or use /report without arguments.")

# --- Help Command ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a message listing all available commands."""
    help_text = (
        "Here are the available commands:\n\n"
        "*Project Management:*\n"
        "  /create_project \"Project Name\" - Create a new project.\n"
        "  /list_projects - List and select projects (➡️ indicates current).\n"
        "  /select_project \"Project Name\" - Select a project by name.\n"
        "  /delete_project - Delete a project and its data.\n\n"
        "*Task Management:*\n"
        "  /create_task \"Task Name\" - Add task to the current project.\n"
        "  /list_tasks - List and select tasks in the current project (➡️ indicates current).\n"
        "  /select_task \"Task Name\" - Select a task by name.\n"
        "  /delete_task - Delete a task and its data.\n\n"
        "*Timer Control:*\n"
        "  /start_timer [minutes] - Start Pomodoro (default 25 min). E.g., `/start_timer 45`\n"
        "  /pause_timer - Pause the current timer.\n"
        "  /resume_timer - Resume the paused timer.\n"
        "  /stop_timer - Stop the timer early and log time.\n\n"
        "*Reporting:*\n"
        "  /report - Get daily, weekly, or monthly time reports.\n\n"
        "*Other:*\n"
        "  /help - Show this help message.\n"
        "  /start - Initialize or welcome message."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown') 