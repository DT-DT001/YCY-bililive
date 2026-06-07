import flet as ft
import asyncio
import threading
from bili_monitor import BiliMonitor
from ycy_bluetooth import YCYController
from bleak import BleakScanner
import os
import json
import time
import datetime
import logging
import re
from pulse_parser import parse_pulse_text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main(page: ft.Page):
    page.title = "YCY B站直播间互动控制器 V1.0"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.window.width = 1200
    page.window.height = 900
    
    # 在设置了 assets_dir 后，直接引用相对路径即可
    page.window.icon = "icon.png"
    
    # 日志列表
    # 去除 auto_scroll=True，彻底解决 Flutter 引擎在计算布局时导致的全局卡顿和输入法焦点丢失问题
    log_list = ft.ListView(expand=True, spacing=5, auto_scroll=False)
    
    # 使用异步队列和节流刷新，防止高频弹幕卡死 UI 和打断输入法/剪贴板
    log_queue = asyncio.Queue()

    async def log_updater_task():
        while True:
            updates = []
            while not log_queue.empty():
                try:
                    updates.append(log_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            
            if updates:
                for msg, color in updates:
                    log_list.controls.append(ft.Text(msg, color=color))
                
                # 使用 del 删除多余元素，而不是重新赋值切片，避免 Flet 重绘整个列表
                while len(log_list.controls) > 50:
                    del log_list.controls[0]
                    
                try:
                    log_list.update()
                except Exception:
                    pass
            
            await asyncio.sleep(0.1) # 改成 0.1 秒刷新一次，提升弹幕日志在视觉上的实时反馈速度

    # 启动后台刷新任务
    page.run_task(log_updater_task)
    
    def add_log(msg, log_type="system"):
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        color = ft.Colors.WHITE
        if log_type == "danmaku":
            color = ft.Colors.BLUE_200
        elif log_type == "gift":
            color = ft.Colors.PINK_300
        elif log_type == "guard" or log_type == "sc":
            color = ft.Colors.AMBER_400
        elif log_type == "error":
            color = ft.Colors.RED_400
        elif log_type == "system":
            color = ft.Colors.GREEN_300
            
        # 将日志放入队列，而不是直接操作 UI
        log_queue.put_nowait((f"[{time_str}] {msg}", color))

    # 初始化控制器
    # 注意：我们这里需要给 YCYController 添加一个回调用于更新实时状态面板
    
    # 状态面板 UI
    current_intensity_text = ft.Text("强度 A:0 | B:0", size=24, weight="bold", color=ft.Colors.YELLOW)
    remaining_time_text = ft.Text("剩余时间: 0.0s", size=16, color=ft.Colors.WHITE70)
    current_wave_name_text = ft.Text("输出波形: A:待机 B:待机", size=14, color=ft.Colors.CYAN_200)
    
    # 丝滑折线图/柱状图波形显示 (使用容器阵列实现伪折线面积图)
    import collections
    chart_data_a = collections.deque([0]*50, maxlen=50)
    chart_data_b = collections.deque([0]*50, maxlen=50)
    
    # 使用带有顶部边框和半透明背景的容器，拼接成类似任务管理器的面积折线图
    def create_waveform_bars(base_color, border_color):
        return [
            ft.Container(
                width=7.5, height=2, 
                bgcolor=base_color, 
                border=ft.Border(top=ft.BorderSide(2, border_color)),
                animate=ft.Animation(100, ft.AnimationCurve.LINEAR)
            ) for _ in range(50)
        ]
        
    chart_bars_a = create_waveform_bars(ft.Colors.CYAN_900, ft.Colors.CYAN_400)
    chart_bars_b = create_waveform_bars(ft.Colors.PURPLE_900, ft.Colors.PURPLE_400)
    
    # 生成背景网格线
    def create_grid_lines(height):
        gl = []
        for i in range(1, int(height/25)):
            gl.append(ft.Container(width=380, height=1, bgcolor=ft.Colors.WHITE_10, top=i * 25))
        for i in range(1, 10):
            gl.append(ft.Container(width=1, height=height, bgcolor=ft.Colors.WHITE_10, left=i * 38))
        return gl
        
    def create_waveform_chart(bars, title):
        h = 70
        return ft.Container(
            width=380, height=h,
            bgcolor=ft.Colors.GREY_900,
            border=ft.border.all(1, ft.Colors.GREY_700) if hasattr(ft.border, 'all') else ft.Border(
                top=ft.BorderSide(1, ft.Colors.GREY_700),
                bottom=ft.BorderSide(1, ft.Colors.GREY_700),
                left=ft.BorderSide(1, ft.Colors.GREY_700),
                right=ft.BorderSide(1, ft.Colors.GREY_700),
            ),
            border_radius=0,
            padding=0,
            content=ft.Stack(
                width=380, height=h,
                controls=[
                    *create_grid_lines(h),
                    ft.Text(title, size=12, color=ft.Colors.WHITE54, left=5, top=2),
                    ft.Row(
                        controls=bars,
                        spacing=0,
                        alignment=ft.MainAxisAlignment.START,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                        width=380, height=h
                    )
                ]
            )
        )

    waveform_chart_a = create_waveform_chart(chart_bars_a, "CH A")
    waveform_chart_b = create_waveform_chart(chart_bars_b, "CH B")
    
    status_panel = ft.Container(
        padding=15,
        bgcolor=ft.Colors.BLACK54,
        border_radius=10,
        content=ft.Column([
            ft.Text("⚡ 硬件实时监控", weight="bold"),
            ft.Row([current_intensity_text, remaining_time_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            current_wave_name_text,
            ft.Column([waveform_chart_a, waveform_chart_b], spacing=5)
        ])
    )

    def update_status(int_a, int_b, remaining, wave_name_a="A:待机", wave_name_b="B:待机", freq_a=0, freq_b=0):
        current_intensity_text.value = f"强度 A:{int(int_a)} | B:{int(int_b)}"
        remaining_time_text.value = f"剩余时间: {remaining:.1f}s"
        current_wave_name_text.value = f"波形 {wave_name_a}  {wave_name_b}"
        
        t_now = time.time()
        
        def update_bars(chart_bars, intensity, freq, color_cyan_or_purple):
            if intensity <= 0 or freq <= 0:
                for i in range(50):
                    chart_bars[i].height = 2
                    chart_bars[i].bgcolor = color_cyan_or_purple[0]
                    chart_bars[i].border = ft.Border(top=ft.BorderSide(2, color_cyan_or_purple[1]))
                return
                
            for i in range(50):
                # 视觉映射：为了避免高频混叠（50个柱体无法显示50Hz甚至更高的真实波形），
                # 我们将频率映射为屏幕上显示的周期数，并让波形以舒适的速度向左平滑滚动
                # 频率越高，屏幕上显示的脉冲越密集
                periods = max(1.0, freq / 10.0)
                
                # 固定的视觉滚动速度 (每秒向左滚动2个周期)
                scroll_offset = (t_now * 2.0)
                
                # 当前柱体在整个屏幕上的相对位置 (0.0 到 1.0)
                x = i / 50.0 
                
                # 计算当前柱体的相位
                phase = (x * periods + scroll_offset) % 1.0
                
                # 模拟电击器典型的尖锐脉冲波形
                if phase < 0.15:
                    val = intensity * (phase / 0.15) # 快速上升
                elif phase < 0.4:
                    val = intensity * (1 - (phase - 0.15) / 0.25) # 稍微慢一点下降
                else:
                    val = 0 # 脉冲间隙
                    
                h = 2 + (val / 180.0) * 66 # 最大强度 180，映射到最高 66 像素
                chart_bars[i].height = h
                
                # 颜色根据整体强度级别来决定，而不是瞬时波形高度，这样闪烁不会太乱
                if intensity > 150:
                    chart_bars[i].bgcolor = ft.Colors.RED_900
                    chart_bars[i].border = ft.Border(top=ft.BorderSide(2, ft.Colors.RED_400))
                elif intensity > 80:
                    chart_bars[i].bgcolor = ft.Colors.YELLOW_900
                    chart_bars[i].border = ft.Border(top=ft.BorderSide(2, ft.Colors.YELLOW_400))
                else:
                    chart_bars[i].bgcolor = color_cyan_or_purple[0]
                    chart_bars[i].border = ft.Border(top=ft.BorderSide(2, color_cyan_or_purple[1]))

        update_bars(chart_bars_a, int_a, freq_a, (ft.Colors.CYAN_900, ft.Colors.CYAN_400))
        update_bars(chart_bars_b, int_b, freq_b, (ft.Colors.PURPLE_900, ft.Colors.PURPLE_400))
        
        try:
            status_panel.update()
        except Exception:
            pass

    bili = BiliMonitor(log_callback=add_log, trigger_callback=lambda *args: asyncio.create_task(handle_trigger(*args)))
    
    def on_bluetooth_disconnect():
        btn_bt.text = "自动连接蓝牙"
        btn_bt.icon = ft.Icons.BLUETOOTH_DISABLED
        btn_bt.style = ft.ButtonStyle(color=ft.Colors.GREY)
        try:
            btn_bt.update()
        except Exception:
            pass
            
    ycy = YCYController(log_callback=add_log, status_callback=update_status, disconnect_callback=on_bluetooth_disconnect)

    def get_config_values(config_row):
        controls = config_row.controls
        
        # 辅助函数：从嵌套的 Column -> Container -> TextField 中安全提取数值
        def extract_value(col_control, default=0):
            try:
                # TextField 位于 Column(controls[1]) -> Container(content) -> TextField
                return float(col_control.controls[1].content.value or default)
            except Exception as e:
                print(f"Error parsing config value: {e}")
                return default

        base_int = extract_value(controls[1], 0)
        base_time = extract_value(controls[2], 0)
        inc_int = extract_value(controls[3], 0) if len(controls) > 3 else 0
        inc_time = extract_value(controls[4], 0) if len(controls) > 4 else 0
        max_int = extract_value(controls[5], 180) if len(controls) > 5 else 180
        return base_int, base_time, inc_int, inc_time, max_int

    global_like_counter = 0
    global_like_trigger_count = 0
    last_total_like_count = 0
    user_trigger_counters = {}

    async def handle_trigger(event_type, item_name, user, guard_level=0, value=0):
        """处理来自直播间的事件触发"""
        nonlocal global_like_counter, global_like_trigger_count, last_total_like_count
        
        # 检查当前设备是否还在放电，如果已经停机，则重置所有叠加计数（断掉连击）
        if ycy.get_max_remaining() <= 0:
            global_like_trigger_count = 0
            user_trigger_counters.clear()
            
        intensity = 0
        duration = 1
        
        user_counters = user_trigger_counters.setdefault(user, {"word": 0, "buy_guard": 0})
        
        if event_type == "word":
            user_counters["word"] += 1
            count = user_counters["word"]
            if guard_level == 1 or guard_level == 2:
                b_int, b_time, i_int, i_time, max_int = get_config_values(config_dm_admiral)
                prefix = "👑 提督/总督"
            elif guard_level == 3:
                b_int, b_time, i_int, i_time, max_int = get_config_values(config_dm_guard)
                prefix = "🚢 舰长"
            else:
                b_int, b_time, i_int, i_time, max_int = get_config_values(config_dm_normal)
                prefix = "⭐"
            intensity = b_int + i_int * (count - 1)
            duration = b_time + i_time * (count - 1)
            intensity = min(intensity, max_int)
            add_log(f"{prefix} [{user}] 触发词 [{item_name}] 激活电击! 强度:{intensity:.1f}", "system")
                
        elif event_type == "like_update":
            # 基于直播间总点赞数更新 (LIKE_INFO_V3_UPDATE)
            try:
                threshold = int(like_trigger_threshold.controls[1].content.value)
            except Exception:
                threshold = 10
                
            current_total_likes = value
            
            # 初始化基准点赞数，防止刚开播/刚连接时旧的点赞数瞬间触发海量电击
            if last_total_like_count == 0:
                last_total_like_count = current_total_likes
                return
                
            new_likes = current_total_likes - last_total_like_count
            if new_likes > 0:
                global_like_counter += new_likes
                last_total_like_count = current_total_likes
                
                # 计算新点赞数能触发多少次
                trigger_times = global_like_counter // threshold
                
                if trigger_times > 0:
                    # 循环逐次触发，避免合并触发导致强度溢出或跳档
                    for _ in range(trigger_times):
                        global_like_counter -= threshold
                        global_like_trigger_count += 1 
                        
                        b_int, b_time, i_int, i_time, max_int = get_config_values(config_like_global)
                        intensity = b_int + i_int * (global_like_trigger_count - 1)
                        duration = b_time + i_time * (global_like_trigger_count - 1)
                        intensity = min(intensity, max_int)
                        
                        add_log(f"💖 直播间点赞达到 {threshold} 次，激活电击! 强度:{intensity:.1f}", "system")
                        
                        # 立即下发该次触发
                        intensity_clamped = max(0, min(180, intensity))
                        if intensity_clamped > 0:
                            try:
                                config_a = {
                                    "enable": channel_a.enable_switch.value,
                                    "wave_list": list(channel_a.selected_waveforms),
                                    "mode_type": channel_a.play_mode_dropdown.value
                                }
                                config_b = {
                                    "enable": channel_b.enable_switch.value,
                                    "wave_list": list(channel_b.selected_waveforms),
                                    "mode_type": channel_b.play_mode_dropdown.value
                                }
                                await ycy.send_command(intensity_clamped, duration, config_a, config_b)
                            except Exception as e:
                                add_log(f"触发指令发送失败: {e}", "error")
                                
                        await asyncio.sleep(0.1)
                    return
                else:
                    return
            else:
                return
                
        elif event_type == "gift":
            battery = value
            if guard_level == 1 or guard_level == 2:
                b_int, b_time, m_int, m_time, max_int = get_config_values(config_gift_admiral)
                prefix = "👑 提督/总督"
            elif guard_level == 3:
                b_int, b_time, m_int, m_time, max_int = get_config_values(config_gift_guard)
                prefix = "🚢 舰长"
            else:
                b_int, b_time, m_int, m_time, max_int = get_config_values(config_gift_normal)
                prefix = "🎁"
            intensity = b_int + battery * m_int
            intensity = min(intensity, max_int)
            
            # 礼物触发不再累加之前剩余的时间，每次触发都基于当前计算出的时间进行独立重置
            duration = b_time + battery * m_time
            add_log(f"{prefix} [{user}] 赠送 {item_name}({battery}电池) 激活电击! 强度:{intensity:.1f}", "system")
            
        elif event_type == "buy_guard":
            user_counters["buy_guard"] += 1
            count = user_counters["buy_guard"]
            if guard_level == 1 or guard_level == 2:
                b_int, b_time, i_int, i_time, max_int = get_config_values(config_buy_admiral)
                prefix = "👑 上提督/总督"
            else:
                b_int, b_time, i_int, i_time, max_int = get_config_values(config_buy_guard)
                prefix = "🚢 上舰长"
            intensity = b_int + i_int * (count - 1)
            duration = b_time + i_time * (count - 1)
            intensity = min(intensity, max_int)
            add_log(f"{prefix} [{user}] 激活专属震撼电击! 强度:{intensity:.1f}", "system")

        # 限制强度在 0-180 之间
        intensity = max(0, min(180, intensity))

        if intensity > 0:
            try:
                config_a = {
                    "enable": channel_a.enable_switch.value,
                    "wave_list": list(channel_a.selected_waveforms),
                    "mode_type": channel_a.play_mode_dropdown.value
                }
                config_b = {
                    "enable": channel_b.enable_switch.value,
                    "wave_list": list(channel_b.selected_waveforms),
                    "mode_type": channel_b.play_mode_dropdown.value
                }
                await ycy.send_command(intensity, duration, config_a, config_b)
            except Exception as e:
                add_log(f"触发指令发送失败: {e}", "error")

    # --- UI 控件 ---
    # B站与蓝牙控制初始化
    room_id_input = ft.TextField(label="B站直播间号", value="123456", width=200)
    trigger_words_input = ft.TextField(label="触发弹幕词 (逗号分隔)", value="电,电击", expand=True)
    
    imported_waveforms = []
    
    def create_config_row(label, default_int, default_time, inc_int=None, inc_time=None, inc_labels=("增强", "增时"), max_int=180):
        def on_intensity_change(e):
            try:
                val = float(e.control.value)
                if val < 0:
                    e.control.value = "0"
            except ValueError:
                pass
            e.control.update()

        # 放弃使用原生的 TextField 外框，改用 Container 自绘边框并包裹纯文本输入
        def make_dense_field(lbl, val, on_change_cb=None):
            return ft.Column([
                ft.Text(lbl, size=13, color=ft.Colors.WHITE70, text_align=ft.TextAlign.CENTER, width=50),
                ft.Container(
                    width=50, height=28,
                    bgcolor=ft.Colors.BLACK45,
                    border=ft.Border(
                        top=ft.BorderSide(1, ft.Colors.WHITE24),
                        bottom=ft.BorderSide(1, ft.Colors.WHITE24),
                        left=ft.BorderSide(1, ft.Colors.WHITE24),
                        right=ft.BorderSide(1, ft.Colors.WHITE24)
                    ),
                    border_radius=4,
                    alignment=ft.Alignment(0, 0), # 绝对居中
                    content=ft.TextField(
                        value=str(val), 
                        text_size=14, 
                        border=ft.InputBorder.NONE, # 隐藏原生边框
                        content_padding=ft.Padding(0, 0, 0, 20), # 增加底部内边距，把数字再往上推一点
                        text_align=ft.TextAlign.CENTER,
                        on_change=on_change_cb,
                    )
                )
            ], spacing=2, alignment=ft.MainAxisAlignment.CENTER)

        controls = [
            ft.Text(label, width=65, size=14),
            make_dense_field("基强", default_int, on_intensity_change),
            make_dense_field("基时", default_time),
        ]
        
        # 强制补充增强和增时，如果传入None则填0，保证每个配置行都有5个框
        actual_inc_int = inc_int if inc_int is not None else 0
        actual_inc_time = inc_time if inc_time is not None else 0
        controls.append(make_dense_field(inc_labels[0], actual_inc_int, on_intensity_change))
        controls.append(make_dense_field(inc_labels[1], actual_inc_time))
            
        controls.append(make_dense_field("上限", max_int, on_intensity_change))
            
        # 这里之前使用了 row 并使用 wrap=True 导致多出来的项换行了，现在强制放一行并缩减间距
        return ft.Row(controls, spacing=15, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # 分类扁平化配置区
    config_dm_normal = create_config_row("普通弹幕", 10, 1, 2, 0, max_int=50)
    config_dm_guard = create_config_row("舰长弹幕", 15, 2, 2, 0, max_int=80)
    config_dm_admiral = create_config_row("提督弹幕", 25, 3, 2, 0, max_int=120)
    
    config_like_global = create_config_row("全局点赞", 5, 1, 1, 0, max_int=50)
    
    # 独立处理"每 N 赞触发"的输入框，使用无 Label 的纯文本加输入框方式，保证绝对对齐
    like_trigger_threshold = ft.Column([
        ft.Text("触发", size=13, color=ft.Colors.WHITE70, text_align=ft.TextAlign.CENTER, width=50),
        ft.Container(
            width=50, height=28,
            bgcolor=ft.Colors.BLACK45,
            border=ft.Border(
                top=ft.BorderSide(1, ft.Colors.WHITE24),
                bottom=ft.BorderSide(1, ft.Colors.WHITE24),
                left=ft.BorderSide(1, ft.Colors.WHITE24),
                right=ft.BorderSide(1, ft.Colors.WHITE24)
            ),
            border_radius=4,
            alignment=ft.Alignment(0, 0),
            content=ft.TextField(
                value="10", 
                text_size=14, 
                border=ft.InputBorder.NONE,
                content_padding=ft.Padding(0, 0, 0, 20),
                text_align=ft.TextAlign.CENTER,
            )
        )
    ], spacing=2, alignment=ft.MainAxisAlignment.CENTER)
    
    config_gift_normal = create_config_row("普通礼物", 0, 0, 0.1, 0.5, ("强倍", "时倍"), max_int=100)
    config_gift_guard = create_config_row("舰长礼物", 0, 0, 0.1, 0.5, ("强倍", "时倍"), max_int=120)
    config_gift_admiral = create_config_row("提督礼物", 0, 0, 0.1, 0.5, ("强倍", "时倍"), max_int=150)
    
    config_buy_guard = create_config_row("上舰长", 50, 10, 10, 5, max_int=180)
    config_buy_admiral = create_config_row("上提督", 80, 20, 20, 10, max_int=180)
    
    flat_config_panel = ft.Column([
        ft.Text("【弹幕】", size=14, weight="bold", color=ft.Colors.CYAN),
        config_dm_normal, config_dm_guard, config_dm_admiral,
        ft.Row([
            ft.Text("【点赞】 每", size=14, weight="bold", color=ft.Colors.CYAN),
            like_trigger_threshold,
            ft.Text("赞", size=14, weight="bold", color=ft.Colors.CYAN)
        ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        config_like_global,
        ft.Text("【礼物】", size=14, weight="bold", color=ft.Colors.CYAN),
        config_gift_normal, config_gift_guard, config_gift_admiral,
        ft.Text("【上舰】", size=14, weight="bold", color=ft.Colors.CYAN),
        config_buy_guard, config_buy_admiral
    ], spacing=12)
    
    # 波形选择配置 (多选 + 微信相册样式)
    imported_waveforms = []
    
    class ChannelUI:
        def __init__(self, name):
            self.name = name
            self.enable_switch = ft.Switch(label=f"启用 {name} 通道", value=True)
            self.selected_waveforms = [1]
            self.waveform_grid = ft.Row(wrap=True, width=380, spacing=10, run_spacing=10)
            self.play_mode_dropdown = ft.Dropdown(
                label="播放模式",
                options=[
                    ft.dropdown.Option("sequential", "顺序播放"),
                    ft.dropdown.Option("random", "随机播放"),
                ],
                value="sequential",
                width=180
            )
            
            self.container = ft.Container(
                content=ft.Column([
                    self.enable_switch,
                    ft.Text("点击选择波形 (数字代表播放顺序)", size=12, color=ft.Colors.WHITE70),
                    self.waveform_grid,
                    self.play_mode_dropdown
                ]),
                padding=10
            )
            self.render_waveform_selector()

        def toggle_waveform(self, wave_val):
            if wave_val in self.selected_waveforms:
                self.selected_waveforms.remove(wave_val)
            else:
                self.selected_waveforms.append(wave_val)
            if not self.selected_waveforms:
                self.selected_waveforms.append(wave_val) # 保证至少有一个
            self.render_waveform_selector()

        def render_waveform_selector(self):
            self.waveform_grid.controls.clear()
            
            # 渲染 1-12 固定模式
            fixed_mode_names = ["潮汐", "连击", "压缩", "快按", "渐强", "心跳", "节奏", "呼吸", "摩擦", "弹跳", "波浪", "敲击"]
            
            for i in range(1, 13):
                is_selected = i in self.selected_waveforms
                idx_text = str(self.selected_waveforms.index(i) + 1) if is_selected else ""
                
                check_circle = ft.Container(
                    width=16, height=16,
                    border_radius=8,
                    border=ft.Border(top=ft.BorderSide(1, ft.Colors.WHITE), bottom=ft.BorderSide(1, ft.Colors.WHITE), left=ft.BorderSide(1, ft.Colors.WHITE), right=ft.BorderSide(1, ft.Colors.WHITE)) if not is_selected else None,
                    bgcolor=ft.Colors.GREEN if is_selected else ft.Colors.TRANSPARENT,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text(idx_text, size=10, color=ft.Colors.WHITE, weight="bold") if is_selected else None
                )
                
                mode_name = fixed_mode_names[i-1]
                
                item = ft.Container(
                    content=ft.Row([ft.Text(mode_name, size=12), check_circle], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    width=75, height=30,
                    padding=ft.Padding(5, 0, 5, 0),
                    border_radius=5,
                    bgcolor=ft.Colors.GREY_800 if not is_selected else ft.Colors.BLUE_900,
                    on_click=lambda e, v=i: self.toggle_waveform(v)
                )
                self.waveform_grid.controls.append(item)
                
            # 渲染导入的 JSON 波形
            for wave_obj in imported_waveforms:
                is_selected = wave_obj in self.selected_waveforms
                idx_text = str(self.selected_waveforms.index(wave_obj) + 1) if is_selected else ""
                
                check_circle = ft.Container(
                    width=16, height=16,
                    border_radius=8,
                    border=ft.Border(top=ft.BorderSide(1, ft.Colors.WHITE), bottom=ft.BorderSide(1, ft.Colors.WHITE), left=ft.BorderSide(1, ft.Colors.WHITE), right=ft.BorderSide(1, ft.Colors.WHITE)) if not is_selected else None,
                    bgcolor=ft.Colors.GREEN if is_selected else ft.Colors.TRANSPARENT,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text(idx_text, size=10, color=ft.Colors.WHITE, weight="bold") if is_selected else None
                )
                
                item = ft.Container(
                    content=ft.Row([ft.Text(wave_obj["name"][:8]+"..", size=12, tooltip=wave_obj["name"]), check_circle], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    width=120, height=30,
                    padding=ft.Padding(5, 0, 5, 0),
                    border_radius=5,
                    bgcolor=ft.Colors.GREY_800 if not is_selected else ft.Colors.BLUE_900,
                    on_click=lambda e, v=wave_obj: self.toggle_waveform(v)
                )
                self.waveform_grid.controls.append(item)
                
            try:
                self.waveform_grid.update()
            except:
                pass

    channel_a = ChannelUI("A")
    channel_b = ChannelUI("B")
    
    btn_a = ft.ElevatedButton("A 通道", on_click=lambda e: select_channel("A"), style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.BLUE_700))
    btn_b = ft.ElevatedButton("B 通道", on_click=lambda e: select_channel("B"), style=ft.ButtonStyle(color=ft.Colors.WHITE70, bgcolor=ft.Colors.TRANSPARENT))
    
    channel_view = ft.Container(content=channel_a.container)
    
    def select_channel(ch):
        if ch == "A":
            btn_a.style = ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.BLUE_700)
            btn_b.style = ft.ButtonStyle(color=ft.Colors.WHITE70, bgcolor=ft.Colors.TRANSPARENT)
            channel_view.content = channel_a.container
        else:
            btn_a.style = ft.ButtonStyle(color=ft.Colors.WHITE70, bgcolor=ft.Colors.TRANSPARENT)
            btn_b.style = ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.BLUE_700)
            channel_view.content = channel_b.container
        btn_a.update()
        btn_b.update()
        channel_view.update()
        
    channel_tabs = ft.Column([
        ft.Row([btn_a, btn_b], spacing=0),
        channel_view
    ])
    
    # ---------------------------------------------------------
    # 因为用户的 Python 环境精简掉了 tkinter 库，
    # 且当前 Flet 版本的 FilePicker 在该环境下报 Unknown control。
    # 采用绝对稳定的方案：输入文件绝对路径。
    # ---------------------------------------------------------
    
    def on_json_path_submit(e):
        file_path = e.control.value.strip()
        if not file_path:
            return
        # 兼容用户复制出来的带双引号路径
        file_path = file_path.strip('"').strip("'")
        try:
            if os.path.exists(file_path):
                file_name = os.path.basename(file_path)
                with open(file_path, 'r', encoding='utf-8') as f:
                    if file_path.lower().endswith(".pulse"):
                        pulse_text = f.read()
                        wave_obj = parse_pulse_text(pulse_text)
                        # 郊狼 V3 pulse 的内嵌名字可能是乱码或参数，我们优先使用文件名
                        wave_obj["name"] = file_name.replace(".pulse", "")
                        imported_waveforms.append(wave_obj)
                        add_log(f"已成功加载 Pulse 波形: {file_name} ({len(wave_obj['data'])}个关键帧)", "system")
                        channel_a.render_waveform_selector()
                        channel_b.render_waveform_selector()
                        e.control.value = "" # 清空输入框
                        e.control.update()
                    else:
                        data = json.load(f)
                        if isinstance(data, list):
                            wave_obj = {"name": file_name, "data": data}
                            imported_waveforms.append(wave_obj)
                            add_log(f"已成功加载自定义波形: {file_name} ({len(data)}个关键帧)", "system")
                            channel_a.render_waveform_selector()
                            channel_b.render_waveform_selector()
                            e.control.value = "" # 清空输入框
                            e.control.update()
                        else:
                            add_log("波形文件格式错误，应为 JSON 数组", "error")
            else:
                add_log(f"文件不存在: {file_path}", "error")
        except Exception as ex:
            add_log(f"读取波形文件失败: {ex}", "error")

    json_path_input = ft.TextField(
        label="在此粘贴 .json 或 .pulse 波形文件路径并回车导入", 
        width=380,
        on_submit=on_json_path_submit,
        prefix_icon=ft.Icons.FILE_UPLOAD
    )
    
    btn_import_wave = json_path_input # 替换掉原来的按钮变量

    # 按钮事件
    async def toggle_bili(e):
        # 立即反馈：禁用按钮并让出事件循环，确保点击动画能瞬间渲染
        btn_bili.disabled = True
        btn_bili.update()
        await asyncio.sleep(0.01)
        
        try:
            if not bili.is_running:
                words = [w.strip() for w in re.split(r'[,，]', trigger_words_input.value) if w.strip()]
                bili.start(int(room_id_input.value), words)
                btn_bili.text = "停止监听 B站"
                btn_bili.icon = ft.Icons.STOP
                btn_bili.style = ft.ButtonStyle(color=ft.Colors.RED)
            else:
                bili.stop()
                btn_bili.text = "开始监听 B站"
                btn_bili.icon = ft.Icons.PLAY_ARROW
                btn_bili.style = ft.ButtonStyle(color=ft.Colors.BLUE)
        finally:
            btn_bili.disabled = False
            btn_bili.update()

    async def toggle_bluetooth(e):
        # 立即反馈：禁用按钮并让出事件循环
        btn_bt.disabled = True
        if not ycy.is_running:
            btn_bt.text = "正在搜索设备..."
        else:
            btn_bt.text = "正在断开..."
        btn_bt.update()
        await asyncio.sleep(0.01)
        
        try:
            if not ycy.is_running:
                success = await ycy.auto_connect()
                
                if success:
                    btn_bt.text = "断开蓝牙设备"
                    btn_bt.icon = ft.Icons.BLUETOOTH_CONNECTED
                    btn_bt.style = ft.ButtonStyle(color=ft.Colors.GREEN)
                else:
                    btn_bt.text = "自动连接蓝牙"
                    btn_bt.icon = ft.Icons.BLUETOOTH_DISABLED
                    btn_bt.style = ft.ButtonStyle(color=ft.Colors.GREY)
            else:
                await ycy.disconnect()
                btn_bt.text = "自动连接蓝牙"
                btn_bt.icon = ft.Icons.BLUETOOTH_DISABLED
                btn_bt.style = ft.ButtonStyle(color=ft.Colors.GREY)
        finally:
            btn_bt.disabled = False
            btn_bt.update()

    btn_bili = ft.ElevatedButton("开始监听 B站", icon=ft.Icons.PLAY_ARROW, on_click=toggle_bili)
    btn_bt = ft.ElevatedButton("自动连接蓝牙", icon=ft.Icons.BLUETOOTH_DISABLED, on_click=toggle_bluetooth, style=ft.ButtonStyle(color=ft.Colors.GREY))

    # 布局组装
    left_panel = ft.Container(
        width=550,
        padding=10,
        content=ft.Column(
            controls=[
                ft.Text("⚙️ 配置中心", size=20, weight="bold"),
                ft.Divider(),
                ft.Text("B站监听设置", weight="bold"),
                room_id_input,
                trigger_words_input,
                btn_bili,
                
                ft.Container(height=20),
                ft.Text("硬件控制设置", weight="bold"),
                btn_bt,
                channel_tabs,
                btn_import_wave,
                
                ft.Container(height=20),
                ft.Text("详细触发参数配置", weight="bold"),
                flat_config_panel,
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )

    right_panel = ft.Container(
        expand=True,
        padding=10,
        border=ft.Border.all(1, ft.Colors.OUTLINE),
        border_radius=10,
        content=ft.Column(
            controls=[
                status_panel,
                ft.Text("📋 运行日志", size=20, weight="bold"),
                ft.Divider(),
                log_list
            ]
        )
    )

    page.add(
        ft.Row(
            controls=[left_panel, ft.VerticalDivider(), right_panel],
            expand=True
        )
    )

    add_log("欢迎使用 YCY-bililive Python 版控制端。")
    add_log("请确保 YCY 设备已开机，然后点击自动连接。", "system")

if __name__ == "__main__":
    import sys
    import os
    import ctypes
    
    # 设置 Windows 应用程序用户模型 ID，确保任务栏图标能够独立显示并且不被系统默认缓存覆盖
    try:
        myappid = 'com.ycy.bililive.v1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    if getattr(sys, 'frozen', False):
        # 打包成 exe 后的运行环境，获取解压后的临时目录
        assets_path = os.path.join(sys._MEIPASS, "assets")
    else:
        # 源码运行环境
        assets_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets"))
        
    import flet.utils as ft_utils
    # 为了解决 Flet 原生限制导致的图标不生效问题，
    # 我们在调用前可以覆盖一下 flet app 的窗口配置 (由于Flet不提供直接改原生图标的API)
    ft.app(target=main, assets_dir=assets_path)
