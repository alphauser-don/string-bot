import os
from decouple import config

class Config:
    # Telegram Configuration
    API_ID = config("API_ID", cast=int)
    API_HASH = config("API_HASH")
    BOT_TOKEN = config("BOT_TOKEN")
    SESSION_NAME = "session_bot"
    
    # Security Settings
    ENCRYPTION_KEY = config("ENCRYPTION_KEY")
    OWNER_ID = config("OWNER_ID", cast=int)
    LOG_GROUP = config("LOG_GROUP", cast=int)
    
    # Database Configuration
    DB_URI = config("DB_URI")
    
    # Rate Limiting
    RATE_LIMIT = config("RATE_LIMIT", default=5, cast=int)
    MAX_SESSIONS = config("MAX_SESSIONS", default=3, cast=int)
    
    # Session Settings
    SESSION_TIMEOUT = config("SESSION_TIMEOUT", default=3600, cast=int)
    ALLOW_MULTI_DEVICE = config("ALLOW_MULTI_DEVICE", default=True, cast=bool)
