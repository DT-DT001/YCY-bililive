import asyncio
import time
import random
from bleak import BleakClient, BleakScanner
import logging

logger = logging.getLogger(__name__)

# YSKJ_EMS_BLE 通信协议 V2.0 蓝牙特征 UUID
YCY_SERVICE_UUID = "0000ff30-0000-1000-8000-00805f9b34fb"
YCY_CHAR_WRITE_UUID = "0000ff31-0000-1000-8000-00805f9b34fb"
YCY_CHAR_NOTIFY_UUID = "0000ff32-0000-1000-8000-00805f9b34fb"

class YCYController:
    def __init__(self, log_callback, status_callback=None, disconnect_callback=None):
        self.client = None
        self.queue = asyncio.Queue()
        self.is_running = False
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.disconnect_callback = disconnect_callback
        self._task = None
        self.current_intensity_a = 0
        self.current_intensity_b = 0
        self.active_tasks = []

    def get_max_remaining(self):
        """获取当前活跃任务中的最长剩余时间"""
        now = time.time()
        active = [t for t in self.active_tasks if t["end_time"] > now]
        if not active:
            return 0.0
        return max(t["end_time"] - now for t in active)

    async def auto_connect(self):
        """自动扫描并连接符合协议的设备"""
        if self.client and self.client.is_connected:
            return True
            
        try:
            self.log_callback("开始扫描周边 YCY 蓝牙设备 (协议 V2.0)...", "system")
            # 扫描 5 秒
            devices = await BleakScanner.discover(timeout=5.0)
            target_device = None
            
            for d in devices:
                # 获取设备的元数据（在不同版本的 Bleak 中，uuids 存放位置不同）
                uuids = []
                if hasattr(d, 'metadata'):
                    uuids = d.metadata.get("uuids", [])
                elif hasattr(d, 'details') and isinstance(d.details, dict):
                    # 针对部分 Windows 蓝牙适配器
                    uuids = d.details.get("uuids", [])
                    
                # 兼容 BleakScanner 返回结果不包含 uuids 的情况
                if not uuids and d.name and ("YCY" in d.name.upper() or "YSKJ" in d.name.upper() or "YYC" in d.name.upper()):
                    # 如果拿不到 UUID，但名字里带 YCY 或 YSKJ 或 YYC，也可以作为备选
                    target_device = d
                    break
                    
                # 将 UUID 统一转换为小写进行匹配
                if any(YCY_SERVICE_UUID.lower() in str(u).lower() for u in uuids):
                    target_device = d
                    break
                    
            if not target_device:
                self.log_callback("未扫描到符合协议的 YCY 设备，请确保设备已开机且未被手机连接", "error")
                return False
                
            self.log_callback(f"发现设备: {target_device.name or '未知设备'} ({target_device.address})，正在连接...", "system")
            # 设置设备断开连接的回调
            def handle_disconnect(client):
                self.log_callback("蓝牙设备已意外断开连接！", "error")
                self.is_running = False
                if self.disconnect_callback:
                    # 使用 asyncio.run_coroutine_threadsafe 确保在正确的事件循环中调用异步或同步回调
                    try:
                        loop = asyncio.get_event_loop()
                        if asyncio.iscoroutinefunction(self.disconnect_callback):
                            asyncio.run_coroutine_threadsafe(self.disconnect_callback(), loop)
                        else:
                            loop.call_soon_threadsafe(self.disconnect_callback)
                    except Exception as ex:
                        logger.error(f"调用断开回调失败: {ex}")

            self.client = BleakClient(
                target_device.address,
                disconnected_callback=handle_disconnect
            )
            
            await self.client.connect()
            self.is_running = True
            
            # 开启指令队列处理任务
            self._task = asyncio.create_task(self._process_queue())
            self.log_callback(f"蓝牙设备连接成功!", "system")
            return True
        except Exception as e:
            self.log_callback(f"蓝牙连接失败: {str(e)}", "error")
            logger.error(f"蓝牙连接失败: {e}")
            return False

    async def disconnect(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            self.log_callback("蓝牙设备已断开", "system")

    async def send_command(self, intensity, duration, config_a=None, config_b=None):
        """
        发送电击任务到并发控制器
        :param intensity: 强度 (0-100)
        :param duration: 持续时间 (秒)
        :param config_a: A通道配置字典 {"enable": bool, "wave_list": list, "mode_type": str}
        :param config_b: B通道配置字典 {"enable": bool, "wave_list": list, "mode_type": str}
        """
        if not self.is_running:
            self.log_callback("蓝牙未连接，无法发送指令", "error")
            return
            
        await self.queue.put({
            "intensity": intensity,
            "duration": duration,
            "config_a": config_a or {"enable": True, "wave_list": [1], "mode_type": "single"},
            "config_b": config_b or {"enable": True, "wave_list": [1], "mode_type": "single"},
            "start_time": time.time(),
            "end_time": time.time() + duration
        })
        self.log_callback(f"任务已添加: 强度={intensity}, 持续={duration}s", "system")

    async def _process_queue(self):
        """处理防并发指令队列与并线输出逻辑"""
        # A, B 独立状态
        state_a = {"wave_index": 0, "switch_time": time.time(), "custom_frame": 0}
        state_b = {"wave_index": 0, "switch_time": time.time(), "custom_frame": 0}
        was_playing = False
        
        def get_selected_wave(config, state, now):
            wave_list = config["wave_list"] or [1]
            mode_type = config["mode_type"]
            
            if len(wave_list) == 1:
                mode_type = "single"
                
            if mode_type == "sequential":
                if now - state["switch_time"] > 5.0:
                    state["wave_index"] = (state["wave_index"] + 1) % len(wave_list)
                    state["switch_time"] = now
            elif mode_type == "random":
                if now - state["switch_time"] > 5.0:
                    state["wave_index"] = random.randint(0, len(wave_list) - 1)
                    state["switch_time"] = now
            else:
                state["wave_index"] = 0
                
            if state["wave_index"] >= len(wave_list):
                state["wave_index"] = 0
                
            return wave_list[state["wave_index"]]
        
        while self.is_running:
            try:
                try:
                    new_task = await asyncio.wait_for(self.queue.get(), timeout=0.05)
                    self.active_tasks.append(new_task)
                    self.queue.task_done()
                except asyncio.TimeoutError:
                    pass

                if not self.client or not self.client.is_connected:
                    self.active_tasks.clear()
                    continue

                now = time.time()
                self.active_tasks = [t for t in self.active_tasks if t["end_time"] > now]
                
                if not self.active_tasks:
                    if self.status_callback:
                        self.status_callback(0, 0, 0, "A:待机", "B:待机", 0, 0)
                    
                    if was_playing:
                        # 发送停止指令 (发送多次确保接收，并兼容0x01和0x02模式)
                        cmd1 = bytearray([0x35, 0x11, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                        cmd1.append(sum(cmd1) & 0xFF)
                        cmd2 = bytearray([0x35, 0x11, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                        cmd2.append(sum(cmd2) & 0xFF)
                        
                        async def send_stop_packets():
                            for _ in range(3):
                                try:
                                    await self.client.write_gatt_char(YCY_CHAR_WRITE_UUID, cmd1)
                                    await asyncio.sleep(0.05)
                                    await self.client.write_gatt_char(YCY_CHAR_WRITE_UUID, cmd2)
                                    await asyncio.sleep(0.05)
                                except Exception:
                                    pass
                                    
                        asyncio.create_task(send_stop_packets())
                        was_playing = False
                        
                    continue
                
                was_playing = True
                
                max_intensity = max(t["intensity"] for t in self.active_tasks)
                max_remaining = max(t["end_time"] - now for t in self.active_tasks)
                
                latest_task = self.active_tasks[-1]
                config_a = latest_task["config_a"]
                config_b = latest_task["config_b"]
                
                wave_a = get_selected_wave(config_a, state_a, now) if config_a["enable"] else None
                wave_b = get_selected_wave(config_b, state_b, now) if config_b["enable"] else None
                
                is_custom_a = isinstance(wave_a, dict)
                is_custom_b = isinstance(wave_b, dict)
                
                # 若任意通道启用自定义波形，则整个数据包使用 0x02 格式
                use_custom_packet = is_custom_a or is_custom_b
                
                cmd = bytearray([0x35, 0x11])
                
                actual_int_a_report = 0
                actual_int_b_report = 0
                freq_a_report = 0
                freq_b_report = 0
                
                if use_custom_packet:
                    cmd.append(0x02) # 0x02 模式
                    
                    # 组装 A 通道数据
                    if config_a["enable"] and wave_a:
                        actual_int_a = max_intensity
                        freq_a, pulse_a = 50, 50
                        if is_custom_a:
                            frame = wave_a.get("data", [])[state_a["custom_frame"] % max(1, len(wave_a.get("data", [])))]
                            state_a["custom_frame"] += 1
                            actual_int_a *= frame.get("intensity_scale", 1.0)
                            freq_a = int(frame.get("freq", 50))
                            pulse_a = int(frame.get("pulse", 50))
                            # 严格按照协议限制频率和脉宽
                            freq_a = max(1, min(100, freq_a))
                            pulse_a = max(0, min(100, pulse_a))
                            wave_name_a = wave_a.get("name", "自定义")
                        else:
                            fixed_mode_names = ["潮汐", "连击", "压缩", "快按", "渐强", "心跳", "节奏", "呼吸", "摩擦", "弹跳", "波浪", "敲击"]
                            wave_name_a = fixed_mode_names[int(wave_a) - 1] if 1 <= int(wave_a) <= 12 else f"固定 {wave_a}"
                            
                        actual_int_a_report = actual_int_a
                        freq_a_report = freq_a
                        val_a = int(actual_int_a) # 移除 2.76 倍率，实现 1:1 真实强度映射
                        val_a = max(0, min(276, val_a))
                        cmd.extend([(val_a >> 8) & 0xFF, val_a & 0xFF, freq_a, pulse_a])
                    else:
                        wave_name_a = "关闭"
                        cmd.extend([0x00, 0x00, 0x00, 0x00])
                        
                    # 组装 B 通道数据
                    if config_b["enable"] and wave_b:
                        actual_int_b = max_intensity
                        freq_b, pulse_b = 50, 50
                        if is_custom_b:
                            frame = wave_b.get("data", [])[state_b["custom_frame"] % max(1, len(wave_b.get("data", [])))]
                            state_b["custom_frame"] += 1
                            actual_int_b *= frame.get("intensity_scale", 1.0)
                            freq_b = int(frame.get("freq", 50))
                            pulse_b = int(frame.get("pulse", 50))
                            # 严格按照协议限制频率和脉宽
                            freq_b = max(1, min(100, freq_b))
                            pulse_b = max(0, min(100, pulse_b))
                            wave_name_b = wave_b.get("name", "自定义")
                        else:
                            fixed_mode_names = ["潮汐", "连击", "压缩", "快按", "渐强", "心跳", "节奏", "呼吸", "摩擦", "弹跳", "波浪", "敲击"]
                            wave_name_b = fixed_mode_names[int(wave_b) - 1] if 1 <= int(wave_b) <= 12 else f"固定 {wave_b}"
                            
                        actual_int_b_report = actual_int_b
                        freq_b_report = freq_b
                        val_b = int(actual_int_b) # 移除 2.76 倍率
                        val_b = max(0, min(276, val_b))
                        cmd.extend([(val_b >> 8) & 0xFF, val_b & 0xFF, freq_b, pulse_b])
                    else:
                        wave_name_b = "关闭"
                        cmd.extend([0x00, 0x00, 0x00, 0x00])
                        
                else:
                    cmd.append(0x01) # 0x01 模式
                    
                    fixed_mode_names = ["潮汐", "连击", "压缩", "快按", "渐强", "心跳", "节奏", "呼吸", "摩擦", "弹跳", "波浪", "敲击"]
                    
                    # 组装 A 通道数据
                    if config_a["enable"] and wave_a:
                        wave_name_a = fixed_mode_names[int(wave_a) - 1] if 1 <= int(wave_a) <= 12 else f"固定 {wave_a}"
                        actual_int_a_report = max_intensity
                        freq_a_report = 10 + int(wave_a) * 5
                        val_a = int(max_intensity) # 移除 2.76 倍率
                        val_a = max(0, min(276, val_a))
                        cmd.extend([(val_a >> 8) & 0xFF, val_a & 0xFF, int(wave_a)])
                    else:
                        wave_name_a = "关闭"
                        cmd.extend([0x00, 0x00, 0x00])
                        
                    # 组装 B 通道数据
                    if config_b["enable"] and wave_b:
                        wave_name_b = fixed_mode_names[int(wave_b) - 1] if 1 <= int(wave_b) <= 12 else f"固定 {wave_b}"
                        actual_int_b_report = max_intensity
                        freq_b_report = 10 + int(wave_b) * 5
                        val_b = int(max_intensity) # 移除 2.76 倍率
                        val_b = max(0, min(276, val_b))
                        cmd.extend([(val_b >> 8) & 0xFF, val_b & 0xFF, int(wave_b)])
                    else:
                        wave_name_b = "关闭"
                        cmd.extend([0x00, 0x00, 0x00])
                        
                cmd.append(sum(cmd) & 0xFF)
                
                try:
                    await self.client.write_gatt_char(YCY_CHAR_WRITE_UUID, cmd)
                    if self.status_callback:
                        self.status_callback(actual_int_a_report, actual_int_b_report, max_remaining, f"A:{wave_name_a}", f"B:{wave_name_b}", freq_a_report, freq_b_report)
                except Exception:
                    pass
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"处理任务异常: {e}")
                await asyncio.sleep(1)
