import asyncio
import json
import cv2
import time
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import numpy as np
from PIL import Image, ImageTk
import threading
import queue
import os
from datetime import datetime
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiohttp import ClientSession
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# WebRTC 配置
WEBRTC_URL = "webrtc://123.56.22.103/live/livestream"
SIGNALING_SERVER = "http://123.56.22.103:1985/rtc/v1/play/"
STREAM_NAME = "livestream"

# 主题颜色
THEME_COLORS = {
    'bg_main': '#1E1E1E',         # 主背景色
    'bg_secondary': '#252526',    # 次要背景色
    'text': '#CCCCCC',            # 文本颜色
    'button_bg': '#3C3C3C',       # 按钮背景色
    'button_hover': '#505050',    # 按钮悬停色
    'border': '#555555',          # 边框颜色
    'progress_bg': '#3C3C3C',     # 进度条背景色
    'progress_fg': '#007ACC',     # 进度条前景色
    'highlight': '#007ACC',       # 高亮颜色
}

pcs = set()
shutdown_event = asyncio.Event()

class WebRTCPlayer:
    def __init__(self, webrtc_url=WEBRTC_URL, signaling_server=SIGNALING_SERVER):
        self.webrtc_url = webrtc_url
        self.signaling_server = signaling_server
        self.pc = None
        self.is_playing = False
        self.is_connected = False
        self.frame_queue = queue.Queue(maxsize=2)
        self.frame_callback = None
        self.playback_callback = None
        self.frame_width = 0
        self.frame_height = 0
        self.loop = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
    
    def set_frame_callback(self, callback):
        self.frame_callback = callback
    
    def set_playback_callback(self, callback):
        self.playback_callback = callback
    
    def _notify_frame(self, frame):
        if self.frame_callback and frame is not None:
            self.frame_callback(frame)
    
    def _notify_playback(self, is_playing):
        if self.playback_callback:
            self.playback_callback(is_playing)
    
    async def _create_peer_connection(self):
        self.pc = RTCPeerConnection()
        pcs.add(self.pc)
        
        # 优化 ICE 配置，优先使用本地有效接口
        self.pc.addTransceiver("video", direction="recvonly")
        
        # 定义track处理函数
        async def on_track(track):
            if track.kind == "video":
                logging.info("Receiving video track")
                asyncio.create_task(self._process_video_track(track))
        
        # 定义连接状态变化处理函数
        async def on_connectionstatechange():
            logging.info(f"Connection state: {self.pc.connectionState}")
            if self.pc.connectionState == "connected":
                self.is_connected = True
                self.is_playing = True
                self.reconnect_attempts = 0
                self._notify_playback(True)
            elif self.pc.connectionState in ["failed", "closed"]:
                self.is_connected = False
                self.is_playing = False
                self._notify_playback(False)
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    logging.info("Attempting to reconnect...")
                    await asyncio.sleep(0.5)  # 缩短重连间隔
                    await self._connect()
                    self.reconnect_attempts += 1
        
        # 绑定事件处理函数
        self.pc.on("track", on_track)
        self.pc.on("connectionstatechange", on_connectionstatechange)
    
    async def _process_video_track(self, track):
        frame_count = 0
        start_time = time.time()
        
        while not shutdown_event.is_set():
            try:
                frame = await track.recv()
                # 确保使用bgr24格式获取原始帧，这样与OpenCV兼容
                img = frame.to_ndarray(format="bgr24")
                if not self.frame_width:
                    self.frame_height, self.frame_width = img.shape[:2]
                    logging.info(f"First frame: {self.frame_width}x{self.frame_height}")
                
                frame_count += 1
                if frame_count % 30 == 0:
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed
                    logging.info(f"Received {frame_count} frames, FPS: {fps:.2f}")
                    frame_count = 0
                    start_time = time.time()
                
                # 将帧发送到回调函数(保持BGR格式，由UI负责转换)
                self._notify_frame(img)
                
                # 更新帧队列 - 使用clear+put策略确保始终有最新的帧
                while not self.frame_queue.empty():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        break
                
                try:
                    self.frame_queue.put_nowait(img)
                except queue.Full:
                    # 如果队列满了，先清除旧帧，确保有新帧可用
                    try:
                        self.frame_queue.get_nowait()
                        self.frame_queue.put_nowait(img)
                    except:
                        logging.warning("帧队列操作失败")
            except Exception as e:
                logging.warning(f"Frame decode error: {e}")
                await asyncio.sleep(0.01)
    
    async def _offer(self):
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        
        request_data = {
            "api": "webrtc-player",
            "streamurl": self.webrtc_url,
            "sdp": self.pc.localDescription.sdp,
            "tiebreaker": int(time.time() * 1000),
            "codec": "vp8,h264",  # 优先 VP8
            "enable_audio": False
        }
        
        async with ClientSession() as session:
            # 缩短超时时间并优化请求
            async with session.post(self.signaling_server, json=request_data, ssl=False, timeout=2) as resp:
                if resp.status != 200:
                    raise Exception(f"Signaling failed ({resp.status}): {await resp.text()}")
                response = await resp.json()
                if response.get("code", -1) != 0:
                    raise Exception(f"Server error: {response.get('msg', 'Unknown')}")
                answer = RTCSessionDescription(sdp=response["sdp"], type="answer")
                await self.pc.setRemoteDescription(answer)
                logging.info("Remote description set")
                return True
    
    async def _connect(self):
        await self._create_peer_connection()
        return await self._offer()
    
    def open(self):
        async def start_async():
            try:
                success = await self._connect()
                if success:
                    logging.info("WebRTC连接成功建立")
                    await shutdown_event.wait()
                
                # 无论连接是否成功，都需要关闭PC连接
                if self.pc:
                    await self.pc.close()
                    pcs.discard(self.pc)
            except Exception as e:
                logging.error(f"Connection error: {e}")
            
        def run_async_thread():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(start_async())
            except Exception as e:
                logging.error(f"WebRTC异步运行错误: {e}")
            finally:
                if not self.loop.is_closed():
                    self.loop.close()
        
        shutdown_event.clear()
        threading.Thread(target=run_async_thread, daemon=True).start()
        return True
    
    def close(self):
        self.is_playing = False
        self._notify_playback(False)
        shutdown_event.set()
        if self.pc and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.pc.close(), self.loop)
        while not self.frame_queue.empty():
            self.frame_queue.get_nowait()
        return True

class VideoPlayer:
    """视频播放器，负责本地视频文件的加载与播放"""
    def __init__(self, source=None):
        self.source = source
        self.cap = None
        self.is_open = False
        self.is_playing = False
        self.is_paused = False
        self.is_source = False
        self.current_frame = None
        self.frame_count = 0
        self.fps = 0
        self.duration = 0
        self.position = 0
        self.frame_callbacks = []
        self.playback_callbacks = []
        self.progress_callbacks = []
        self.lock = threading.Lock()
        self._play_thread = None
        self._user_seeking = False
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        
    def open(self):
        """打开视频源"""
        if self.is_open:
            self.close()
            
        if not self.source:
            return False
            
        try:
            self.cap = cv2.VideoCapture(self.source)
            if not self.cap.isOpened():
                logging.error(f"无法打开视频源: {self.source}")
                return False
                
            self.is_open = True
            self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            if self.fps <= 0:
                self.fps = 30.0
            
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            if self.frame_count > 0:
                self.duration = self.frame_count / self.fps
            else:
                self.duration = 0
                
            # 读取第一帧
            ret, self.current_frame = self.cap.read()
            if not ret:
                logging.error("无法读取第一帧")
                self.close()
                return False
                
            self.position = 0
            self._notify_callbacks()
            
            logging.info(f"已打开视频: {self.source}, 帧数: {self.frame_count}, FPS: {self.fps:.2f}")
            return True
            
        except Exception as e:
            logging.error(f"打开视频时发生错误: {str(e)}")
            if self.cap:
                self.cap.release()
                self.cap = None
            self.is_open = False
            return False
            
    def close(self):
        """关闭视频源"""
        self._stop_event.set()
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=1.0)
            
        if self.cap:
            self.cap.release()
            self.cap = None
            
        self.is_open = False
        self.is_playing = False
        self._pause_event.clear()
        self._stop_event.clear()
        return True
        
    def play(self):
        """开始播放视频"""
        if not self.is_open:
            return False
            
        if self.is_playing:
            if self.is_paused:
                self.is_paused = False
                self._pause_event.set()
                self._notify_playback_callback(True)
            return True
            
        self._stop_event.clear()
        self._pause_event.clear()
        self.is_playing = True
        self.is_paused = False
        
        # 启动播放线程
        self._play_thread = threading.Thread(target=self._play_thread_func)
        self._play_thread.daemon = True
        self._play_thread.start()
        
        self._notify_playback_callback(True)
        return True
        
    def pause(self):
        """暂停视频播放"""
        if not self.is_playing or self.is_paused:
            return False
            
        self.is_paused = True
        self._pause_event.clear()
        self._notify_playback_callback(False)
        return True
        
    def stop(self):
        """停止视频播放"""
        if not self.is_playing:
            return False
            
        self._stop_event.set()
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=1.0)
            
        self.is_playing = False
        self.is_paused = False
        self._pause_event.clear()
        
        # 重置到第一帧
        if self.cap and self.is_open:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, self.current_frame = self.cap.read()
            if ret:
                self.position = 0
                self._notify_callbacks()
                
        self._notify_playback_callback(False)
        return True
        
    def seek(self, position):
        """跳转到指定时间点(秒)"""
        if not self.is_open or not self.cap:
            return False
            
        position = max(0, min(position, self.duration))
        
        # 计算对应的帧位置
        frame_pos = int(position * self.fps)
        frame_pos = min(frame_pos, self.frame_count - 1) if self.frame_count > 0 else frame_pos
        
        with self.lock:
            self._user_seeking = True
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, self.current_frame = self.cap.read()
            if ret:
                self.position = position
                self._notify_callbacks()
            else:
                logging.error(f"无法跳转到位置: {position}秒")
            self._user_seeking = False
            
        return ret
        
    def seek_frame(self, frame_pos):
        """跳转到指定帧号"""
        if not self.is_open or not self.cap:
            return False
            
        frame_pos = max(0, frame_pos)
        if self.frame_count > 0:
            frame_pos = min(frame_pos, self.frame_count - 1)
            
        with self.lock:
            self._user_seeking = True
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, self.current_frame = self.cap.read()
            if ret:
                self.position = frame_pos / self.fps if self.fps > 0 else 0
                self._notify_callbacks()
            else:
                logging.error(f"无法跳转到帧: {frame_pos}")
            self._user_seeking = False
            
        return ret
        
    def get_current_frame(self):
        """获取当前帧"""
        with self.lock:
            return self.current_frame.copy() if self.current_frame is not None else None
            
    def add_frame_callback(self, callback):
        """添加帧更新回调函数"""
        if callback not in self.frame_callbacks:
            self.frame_callbacks.append(callback)
            
    def add_playback_callback(self, callback):
        """添加播放状态回调函数"""
        if callback not in self.playback_callbacks:
            self.playback_callbacks.append(callback)
            
    def add_progress_callback(self, callback):
        """添加进度更新回调函数"""
        if callback not in self.progress_callbacks:
            self.progress_callbacks.append(callback)
            
    def remove_frame_callback(self, callback):
        """移除帧更新回调函数"""
        if callback in self.frame_callbacks:
            self.frame_callbacks.remove(callback)
            
    def remove_playback_callback(self, callback):
        """移除播放状态回调函数"""
        if callback in self.playback_callbacks:
            self.playback_callbacks.remove(callback)
            
    def remove_progress_callback(self, callback):
        """移除进度更新回调函数"""
        if callback in self.progress_callbacks:
            self.progress_callbacks.remove(callback)
            
    def _notify_frame_callback(self, frame):
        """通知帧更新回调函数"""
        for callback in self.frame_callbacks:
            try:
                callback(frame)
            except Exception as e:
                logging.error(f"帧回调函数错误: {str(e)}")
                
    def _notify_playback_callback(self, is_playing):
        """通知播放状态回调函数"""
        for callback in self.playback_callbacks:
            try:
                callback(is_playing, self.is_paused)
            except Exception as e:
                logging.error(f"播放回调函数错误: {str(e)}")
                
    def _notify_progress_callback(self):
        """通知进度更新回调函数"""
        for callback in self.progress_callbacks:
            try:
                callback(self.position, self.duration)
            except Exception as e:
                logging.error(f"进度回调函数错误: {str(e)}")
                
    def _notify_callbacks(self):
        """通知所有回调函数"""
        if self.current_frame is not None:
            self._notify_frame_callback(self.current_frame)
            self._notify_progress_callback()
            
    def _play_thread_func(self):
        """播放线程函数"""
        try:
            # 计算帧间隔时间
            frame_time = 1.0 / self.fps
            
            while not self._stop_event.is_set():
                # 处理暂停
                if self.is_paused:
                    self._pause_event.wait(0.1)
                    continue
                    
                if self._user_seeking:
                    time.sleep(0.01)
                    continue
                    
                with self.lock:
                    if not self.cap or not self.is_open:
                        break
                        
                    # 读取下一帧
                    start_time = time.time()
                    ret, frame = self.cap.read()
                    
                    if not ret:
                        # 到达视频末尾，重置到开始
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = self.cap.read()
                        if not ret:
                            break
                            
                    # 更新当前帧和位置
                    self.current_frame = frame
                    self.position = self.cap.get(cv2.CAP_PROP_POS_FRAMES) / self.fps
                    
                # 通知回调
                self._notify_callbacks()
                
                # 计算并等待下一帧的时间
                elapsed = time.time() - start_time
                sleep_time = max(0, frame_time - elapsed)
                time.sleep(sleep_time)
                
        except Exception as e:
            logging.error(f"播放线程错误: {str(e)}")
        finally:
            self.is_playing = False
            self.is_paused = False
            self._notify_playback_callback(False)

class MainWindow:
    """主应用窗口类，负责组织界面和处理控制逻辑"""
    def __init__(self, root):
        self.root = root
        self.root.title("视频录制与回放系统")
        self.root.geometry("1280x720")
        self.root.minsize(800, 600)
        self.root.configure(bg=THEME_COLORS['bg_main'])
        
        # 创建菜单
        self.create_menu()
        
        # 创建工具栏
        self.create_toolbar()
        
        # 主内容区域
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 创建视频画布
        self.create_video_canvas()
        
        # 创建控制区域
        self.create_control_panel()
        
        # 创建状态栏
        self.create_status_bar()
        
        # 录制相关变量
        self.is_recording = False
        self.record_start_time = None
        self.recorder = None
        self.videowriter = None
        self.recording_filename = None
        
        # WebRTC播放器
        self.webrtc_player = WebRTCPlayer()
        self.webrtc_player.set_frame_callback(self.on_webrtc_frame)
        self.webrtc_player.set_playback_callback(self.on_webrtc_playback_state)
        
        # 本地视频播放器
        self.video_player = VideoPlayer()
        self.video_player.add_frame_callback(self.on_video_frame)
        self.video_player.add_playback_callback(self.on_video_playback_state)
        self.video_player.add_progress_callback(self.on_video_progress)
        
        # 当前活动的播放器
        self.active_player = None
        
        # 锁定控制以避免竞争条件
        self.control_lock = threading.Lock()
        
        # 确保录像目录存在
        self.recordings_dir = "recordings"
        os.makedirs(self.recordings_dir, exist_ok=True)
        
        # 绑定键盘快捷键
        self.bind_shortcuts()
        
        # 启动计时器更新UI状态
        self.update_status()
        
        # 保存一个空白帧，用于显示"无视频"状态
        self.no_video_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(self.no_video_frame, "无视频信号", (220, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        
        # 用于记录关键点的变量
        self.keyframes = []
        self.keyframe_markers = []
        
        # 自动化测试变量
        self.recording_base_name = None  # 基本文件名（不含扩展名）
        self.auto_test_active = False     # 是否启动了自动测试
        self.test_commands = []           # 测试命令列表
        self.current_test_command = 0     # 当前执行的命令索引
        self.test_timer = None           # 测试定时器
        
        # 在启动应用后显示使用提示
        self.root.after(1000, self.show_startup_tips)