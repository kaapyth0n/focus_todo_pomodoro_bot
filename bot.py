from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import database

# Replace with your bot token from BotFather
TOKEN = ''

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    database.add_user(user.id, user.first_name, user.last_name)
    await update.message.reply_text('Welcome to your Focus To-Do List Bot! Use /create_project to get started.')

# Dictionary to store user state (e.g., selected project)
user_data = {}  # {user_id: {'current_project': project_id}}

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

def main():
    application = Application.builder().token(TOKEN).build()
    
    # Register the start command
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('create_project', create_project))
    application.add_handler(CommandHandler('select_project', select_project))
    application.add_handler(CommandHandler('create_task', create_task))

    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()