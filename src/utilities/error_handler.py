import logging
import traceback
from telethon import events

class ErrorHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle(self, event: events.NewMessage.Event, error: Exception):
        error_id = str(uuid.uuid4())[:8]
        self.logger.error(f"Error {error_id}: {str(error)}")
        
        await event.respond(
            f"⚠️ Error {error_id}\n"
            "Please contact @rishabh_zz for support"
        )
        
        traceback_msg = f"```{traceback.format_exc()}```"
        await event.client.send_message(
            Config.LOG_GROUP,
            f"🚨 Error {error_id} from {event.sender_id}\n{traceback_msg}",
            parse_mode='md'
        )
