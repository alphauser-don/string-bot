import os
import logging
from telethon import TelegramClient, events
from config import Config
from database.db_handler import Database
from utilities.error_handler import ErrorHandler
from utilities.rate_limiter import RateLimiter
from commands import setup_commands

# Initialize core components
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
db = Database()
error_handler = ErrorHandler()
rate_limiter = RateLimiter()

client = TelegramClient(
    session=Config.SESSION_NAME,
    api_id=Config.API_ID,
    api_hash=Config.API_HASH
).start(bot_token=Config.BOT_TOKEN)

async def main():
    await db.initialize()
    setup_commands(client)
    
    logger.info("Bot started successfully")
    await client.run_until_disconnected()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
