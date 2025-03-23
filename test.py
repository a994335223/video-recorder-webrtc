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