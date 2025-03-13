from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import database
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import JobQueue
import threading
from flask import Flask, render_template_string

# Replace with your bot token from BotFather
TOKEN = ''

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    database.add_user(user.id, user.first_name, user.last_name)
    await update.message.reply_text('Welcome to your Focus To-Do List Bot! Use /create_project to get started.')

# Dictionary to store user state (e.g., selected project)
user_data = {}  # {user_id: {'current_project': project_id}}
timer_states = {}  # {user_id: {'start_time': datetime, 'accumulated_time': int, 'state': 'running'/'paused', 'job': APScheduler job}}

async def create_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    project_name = ' '.join(context.args)
    if not project_name:
        await update.message.reply_text('Please provide a project name. Usage: /create_project "Project Name"')
        return
    database.add_project(user_id, project_name)
    await update.message.reply_text(f'Project "{project_name}" created! Select it with /select_project.')

async def select_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    project_name = ' '.join(context.args)
    if not project_name:
        await update.message.reply_text('Please provide a project name. Usage: /select_project "Project Name"')
        return
    projects = database.get_projects(user_id)
    for proj_id, proj_name in projects:
        if proj_name == project_name:
            user_data[user_id] = {'current_project': proj_id}
            await update.message.reply_text(f'Project "{project_name}" selected.')
            return
    await update.message.reply_text('Project not found. Create it with /create_project.')

async def create_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data or 'current_project' not in user_data[user_id]:
        await update.message.reply_text('Please select a project first with /select_project.')
        return
    task_name = ' '.join(context.args)
    if not task_name:
        await update.message.reply_text('Please provide a task name. Usage: /create_task "Task Name"')
        return
    project_id = user_data[user_id]['current_project']
    database.add_task(project_id, task_name)
    await update.message.reply_text(f'Task "{task_name}" added to project!')

async def select_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data or 'current_project' not in user_data[user_id]:
        await update.message.reply_text('Please select a project first with /select_project.')
        return
    task_name = ' '.join(context.args)
    if not task_name:
        await update.message.reply_text('Please provide a task name. Usage: /select_task "Task Name"')
        return
    project_id = user_data[user_id]['current_project']
    tasks = database.get_tasks(project_id)
    for task_id, t_name in tasks:
        if t_name == task_name:
            user_data[user_id]['current_task'] = task_id
            await update.message.reply_text(f'Task "{task_name}" selected.')
            return
    await update.message.reply_text('Task not found. Create it with /create_task.')

from datetime import datetime, timedelta

async def start_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in timer_states:
        await update.message.reply_text('A timer is already running or paused. Please stop it first.')
        return
    if user_id not in user_data or 'current_project' not in user_data[user_id] or 'current_task' not in user_data[user_id]:
        await update.message.reply_text('Please select a project and task first.')
        return
    timer_states[user_id] = {
        'state': 'running',
        'accumulated_time': 0,
        'start_time': datetime.now(),
        'job': context.job_queue.run_once(timer_finished, 25 * 60, data={'user_id': user_id})
    }
    await update.message.reply_text('Timer started for 25 minutes.')

async def timer_finished(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data['user_id']
    if user_id in timer_states:
        timer_states[user_id]['accumulated_time'] = 25
        timer_states[user_id]['state'] = 'stopped'
        # Save session to database
        # For now, just send message
        await context.bot.send_message(chat_id=user_id, text='Time\'s up! Pomodoro session completed.')
        del timer_states[user_id]

async def pause_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in timer_states or timer_states[user_id]['state'] != 'running':
        await update.message.reply_text('No timer is running.')
        return
    current_time = datetime.now()
    time_worked = (current_time - timer_states[user_id]['start_time']).total_seconds() / 60
    timer_states[user_id]['accumulated_time'] += time_worked
    timer_states[user_id]['state'] = 'paused'
    timer_states[user_id]['job'].remove()
    del timer_states[user_id]['job']
    await update.message.reply_text(f'Timer paused. Accumulated time: {timer_states[user_id]["accumulated_time"]:.2f} minutes.')

async def resume_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in timer_states or timer_states[user_id]['state'] != 'paused':
        await update.message.reply_text('No timer is paused.')
        return
    accumulated_time = timer_states[user_id]['accumulated_time']
    remaining_time = 25 - accumulated_time
    if remaining_time <= 0:
        await update.message.reply_text('Timer already completed.')
        del timer_states[user_id]
        return
    timer_states[user_id]['state'] = 'running'
    timer_states[user_id]['start_time'] = datetime.now()
    timer_states[user_id]['job'] = context.job_queue.run_once(timer_finished, remaining_time * 60, data={'user_id': user_id})
    await update.message.reply_text('Timer resumed.')

async def stop_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in timer_states:
        await update.message.reply_text('No timer is running or paused.')
        return
    if timer_states[user_id]['state'] == 'running':
        current_time = datetime.now()
        time_worked = (current_time - timer_states[user_id]['start_time']).total_seconds() / 60
        timer_states[user_id]['accumulated_time'] += time_worked
    # Save session to database with accumulated_time
    accumulated_time = timer_states[user_id]['accumulated_time']
    await update.message.reply_text(f'Timer stopped. Total time worked: {accumulated_time:.2f} minutes.')
    if 'job' in timer_states[user_id]:
        timer_states[user_id]['job'].remove()
    del timer_states[user_id]

def main():
    application = Application.builder().token(TOKEN).build()
    job_queue = application.job_queue
    
    # Register the start command
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('create_project', create_project))
    application.add_handler(CommandHandler('select_project', select_project))
    application.add_handler(CommandHandler('create_task', create_task))
    application.add_handler(CommandHandler('select_task', select_task))
    application.add_handler(CommandHandler('start_timer', start_timer))
    application.add_handler(CommandHandler('pause_timer', pause_timer))
    application.add_handler(CommandHandler('resume_timer', resume_timer))
    application.add_handler(CommandHandler('stop_timer', stop_timer))

    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()