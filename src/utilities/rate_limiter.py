from datetime import datetime, timedelta
from collections import defaultdict

class RateLimiter:
    def __init__(self):
        self.user_activity = defaultdict(list)
    
    async def check(self, user_id: int):
        now = datetime.now()
        window_start = now - timedelta(minutes=1)
        
        # Cleanup old requests
        self.user_activity[user_id] = [
            t for t in self.user_activity[user_id] 
            if t > window_start
        ]
        
        if len(self.user_activity[user_id]) >= Config.RATE_LIMIT:
            raise Exception("Rate limit exceeded. Please try again later.")
        
        self.user_activity[user_id].append(now)
