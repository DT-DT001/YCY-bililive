import asyncio
import blivedm
import logging
import aiohttp

logger = logging.getLogger(__name__)

class MyHandler(blivedm.BaseHandler):
    def __init__(self, log_callback, trigger_callback, trigger_words):
        super().__init__()
        self.log_callback = log_callback
        self.trigger_callback = trigger_callback
        self.trigger_words = trigger_words
        self.like_count = 0

    # 重写 _CMD_CALLBACK_DICT 添加原生点赞支持
    def handle(self, client: blivedm.BLiveClient, command: dict):
        cmd = command.get('cmd', '')
        pos = cmd.find(':')
        if pos != -1:
            cmd = cmd[:pos]

        if cmd == 'LIKE_INFO_V3_CLICK':
            # 恢复单次点赞的触发！并且抓取用户的连击数(click_count)
            data = command.get('data', {})
            uname = data.get('uname', '未知用户')
            click_count = data.get('click_count', 1)
            self.log_callback(f"👍 [{uname}] 为主播点赞了 {click_count} 次!", "system")
            # 将事件作为 "like" 类型传递出去，value 为该用户的点赞连击数
            self.trigger_callback("like", "点赞", uname, 0, click_count)
            return
            
        if cmd == 'LIKE_INFO_V3_UPDATE':
            # UPDATE 的触发太容易被B站服务器限流或者状态卡死，这里我们完全废弃 UPDATE 触发，
            # 仅用于在后台同步日志，不往主程序传递触发事件。
            return

        super().handle(client, command)

    def _on_danmaku(self, client: blivedm.BLiveClient, message: blivedm.models.web.DanmakuMessage):
        msg = f"[{message.uname}] {message.msg}"
        self.log_callback(msg, "danmaku")
        
        # 提取舰队身份 (1:总督, 2:提督, 3:舰长)
        guard_level = message.privilege_type
        
        # 检查是否包含触发词
        for word in self.trigger_words:
            if word in message.msg:
                self.trigger_callback("word", word, message.uname, guard_level)
                break

    def _on_gift(self, client: blivedm.BLiveClient, message: blivedm.models.web.GiftMessage):
        battery = int(message.total_coin / 100)
        yuan = int(message.total_coin / 1000)
        if message.coin_type != 'gold':
            return # 只处理付费礼物
        msg = f"🎁 [{message.uname}] 赠送了 {message.gift_name} x {message.num} (价值: {yuan}元 / {battery}电池)"
        self.log_callback(msg, "gift")
        
        # 传递 身份 与 价值(电池)
        guard_level = message.guard_level if hasattr(message, 'guard_level') else 0
        self.trigger_callback("gift", message.gift_name, message.uname, guard_level, battery)

    def _on_buy_guard(self, client: blivedm.BLiveClient, message: blivedm.models.web.GuardBuyMessage):
        num = getattr(message, 'num', 1)
        msg = f"[{message.username}] 购买了 {message.gift_name} x {num}个月"
        self.log_callback(msg, "guard")
        self.trigger_callback("buy_guard", message.gift_name, message.username, message.guard_level, num)
        
    def _on_super_chat(self, client: blivedm.BLiveClient, message: blivedm.models.web.SuperChatMessage):
        msg = f"[{message.uname}] 发送了醒目留言: {message.message} (￥{message.price})"
        self.log_callback(msg, "sc")
        self.trigger_callback("sc", message.message, message.uname, message.price)


class BiliMonitor:
    def __init__(self, log_callback, trigger_callback):
        self.client = None
        self.session = None
        self.log_callback = log_callback
        self.trigger_callback = trigger_callback
        self.is_running = False
        
    def start(self, room_id, trigger_words):
        if self.is_running:
            return
            
        self.room_id = room_id
        
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.client = blivedm.BLiveClient(room_id, session=self.session)
        handler = MyHandler(self.log_callback, self.trigger_callback, trigger_words)
        self.client.set_handler(handler)
        self.is_running = True
        
        self.client.start()
        self.log_callback(f"已开始监听直播间: {room_id}", "system")

    def stop(self):
        if self.client and self.is_running:
            self.client.stop()
            if self.session:
                asyncio.create_task(self.session.close())
            self.is_running = False
            self.log_callback("已停止监听直播间", "system")
