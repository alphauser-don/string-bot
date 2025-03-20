from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from config import Config
from database.db_handler import Database
from utilities.crypto import Crypto

class SessionGenerator:
    def __init__(self):
        self.db = Database()
        self.crypto = Crypto(Config.ENCRYPTION_KEY)

    async def generate_session(self, user_id: int, api_id: int, api_hash: str, phone: str):
        client = None
        try:
            # Initialize temporary client
            client = TelegramClient(
                session=StringSession(),
                api_id=api_id,
                api_hash=api_hash,
                device_model="SessionGenerator"
            )
            
            await client.connect()
            sent_code = await client.send_code_request(phone)
            
            return {
                'phone_code_hash': sent_code.phone_code_hash,
                'client': client,
                'api_id': api_id,
                'api_hash': api_hash,
                'phone': phone
            }
            
        except Exception as e:
            if client:
                await client.disconnect()
            raise e

    async def finalize_session(self, temp_data, code: str, password: str = None):
        client = temp_data['client']
        try:
            await client.sign_in(
                phone=temp_data['phone'],
                code=code,
                phone_code_hash=temp_data['phone_code_hash'],
                password=password,
                in_background=True  # Preserve existing sessions
            )
            
            # Verify session validity
            me = await client.get_me()
            if not me:
                raise ValueError("Session validation failed")
            
            session_string = client.session.save()
            
            # Encrypt sensitive data
            encrypted_session = self.crypto.encrypt(session_string)
            encrypted_phone = self.crypto.encrypt(temp_data['phone'])
            
            # Store session
            await self.db.store_session(
                user_id=me.id,
                session=encrypted_session,
                phone=encrypted_phone
            )
            
            return session_string
            
        finally:
            await client.disconnect()
