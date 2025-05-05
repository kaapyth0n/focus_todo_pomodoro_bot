import os
import yaml
import re
import logging
from flask_babel import gettext
from config import SUPPORTED_LANGUAGES

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def ensure_dir(directory):
    """Make sure directory exists"""
    if not os.path.exists(directory):
        os.makedirs(directory)
        log.info(f"Created directory: {directory}")

def convert_yaml_to_po():
    """Convert YAML translations to PO format for Flask-Babel"""
    for lang in SUPPORTED_LANGUAGES:
        # Create Babel translation directories
        translations_dir = os.path.join('translations', lang, 'LC_MESSAGES')
        ensure_dir(translations_dir)
        
        # Load YAML translations
        yaml_path = os.path.join('locales', f'{lang}.yml')
        if not os.path.exists(yaml_path):
            log.warning(f"YAML file not found: {yaml_path}")
            continue
            
        with open(yaml_path, 'r', encoding='utf-8') as file:
            yaml_data = yaml.safe_load(file)
            
        # Create PO file content
        po_content = f'''msgid ""
msgstr ""
"Project-Id-Version: Focus Pomodoro Bot\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: 2023-05-01 12:00+0000\\n"
"PO-Revision-Date: 2023-05-01 12:00+0000\\n"
"Last-Translator: \\n"
"Language-Team: \\n"
"Language: {lang}\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
'''
        
        # Extract web app translations
        web_keys = [
            'pomodoro_timer', 'loading_timer', 'loading', 'focus_running', 'break_running',
            'focus_timer', 'break_timer', 'web_timer_paused', 'focus_paused', 'break_paused',
            'web_timer_stopped', 'web_times_up', 'focus_finished', 'break_finished',
            'error_connection', 'timer_error', 'minute', 'mute', 'unmute',
            'browser_no_audio_support'
        ]
        
        translations = yaml_data.get(lang, {})
        for key in web_keys:
            if key in translations:
                value = translations[key]
                po_content += f'\nmsgid "{key}"\nmsgstr "{value}"\n'
        
        # Write PO file
        po_path = os.path.join(translations_dir, 'messages.po')
        with open(po_path, 'w', encoding='utf-8') as file:
            file.write(po_content)
        log.info(f"Created PO file: {po_path}")
        
        # Compile MO file
        mo_path = os.path.join(translations_dir, 'messages.mo')
        os.system(f'pybabel compile -d translations -f')
        log.info(f"Compiled MO file: {mo_path}")

if __name__ == "__main__":
    convert_yaml_to_po() 