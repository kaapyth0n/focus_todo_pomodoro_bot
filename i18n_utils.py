import i18n
import os
import database
from config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
import logging

log = logging.getLogger(__name__)

# Configure i18n
# LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'locales')) # Corrected path based on __file__
LOCALE_DIR = os.path.abspath('locales') # Simpler path assuming execution from project root
# i18n.set('file_format', 'yaml') # Old format
i18n.set('file_format', 'yml')   # Use 'yml' to match file extensions
i18n.set('filename_format', '{locale}.{format}')
i18n.set('locale', DEFAULT_LANGUAGE) # Default locale
i18n.set('fallback', DEFAULT_LANGUAGE) # Fallback locale if translation missing
i18n.set('available_locales', SUPPORTED_LANGUAGES)
# i18n.set('skip_locale_root_data', True) # Keep commented out
i18n.load_path.append(LOCALE_DIR)

log.info(f"i18n configured. Load path: {LOCALE_DIR}, Supported: {SUPPORTED_LANGUAGES}, Default: {DEFAULT_LANGUAGE}")

# Cache for user languages to reduce DB lookups
user_language_cache = {}

def get_user_lang(user_id):
    """Gets the user's language, checking cache first, then DB."""
    if user_id in user_language_cache:
        return user_language_cache[user_id]
    
    lang = database.get_user_language(user_id)
    if lang and lang in SUPPORTED_LANGUAGES:
        user_language_cache[user_id] = lang
        return lang
    else:
        # If DB returns None or an unsupported language, use default and cache it
        user_language_cache[user_id] = DEFAULT_LANGUAGE 
        return DEFAULT_LANGUAGE

def set_user_lang(user_id, lang_code):
    """Sets the user's language in DB and updates cache."""
    if lang_code in SUPPORTED_LANGUAGES:
        if database.set_user_language(user_id, lang_code):
            user_language_cache[user_id] = lang_code
            return True
    return False

def _(user_id, key, **kwargs):
    """Translates a key using the user's preferred language."""
    locale = get_user_lang(user_id)
    return i18n.t(key, locale=locale, **kwargs)

# Function to get language name (e.g., English, Deutsch, Русский)
def get_language_name(lang_code):
    """Returns the native name of a supported language."""
    names = {
        'en': 'English',
        'de': 'Deutsch',
        'ru': 'Русский'
    }
    return names.get(lang_code, lang_code) # Fallback to code if name unknown 