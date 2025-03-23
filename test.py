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