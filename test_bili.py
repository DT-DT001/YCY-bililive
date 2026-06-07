import asyncio
import blivedm
import aiohttp
import logging
from bili_monitor import BiliMonitor

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def log_cb(msg, t):
    print(f"[{t}] {msg}")

def trig_cb(event_type, item, user, val=0):
    print(f"TRIGGER: {event_type} {item} {user} {val}")

async def main():
    session = aiohttp.ClientSession(headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    # We need to hack BiliMonitor to accept session
    client = blivedm.BLiveClient(22625027, session=session)
    # wait just to test blivedm connection
    await client.init_room()
    print("Room ID:", client.room_id)
    await session.close()

if __name__ == '__main__':
    asyncio.run(main())
