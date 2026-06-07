import asyncio
import blivedm
import aiohttp
import json
import urllib.request

class TestHandler(blivedm.BaseHandler):
    def handle(self, client, command):
        cmd = command.get('cmd', '')
        if cmd.startswith('LIKE'):
            print("RAW LIKE CMD:", command)
        super().handle(client, command)

async def main():
    try:
        req = urllib.request.Request('https://api.live.bilibili.com/room/v1/Room/get_area_room_list?area_id=0&sort_type=online&page_size=1')
        req.add_header('User-Agent', 'Mozilla/5.0')
        resp = urllib.request.urlopen(req).read()
        room_id = json.loads(resp)['data'][0]['roomid']
    except Exception as e:
        room_id = 1775719573 # fallback

    print("Connecting to room:", room_id)
    session = aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'})
    client = blivedm.BLiveClient(room_id, session=session)
    handler = TestHandler()
    client.set_handler(handler)
    client.start()
    
    print("Listening to room", room_id, "for likes...")
    await asyncio.sleep(20)
    
    client.stop()
    await session.close()
    print("Done.")

if __name__ == '__main__':
    asyncio.run(main())