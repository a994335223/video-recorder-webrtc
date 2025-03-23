# 视频录制与播放控制系统

一个基于Python的视频录制与回放系统，支持WebRTC实时流显示、录制以及视频回放功能。

## 功能特点

### 核心功能
- **WebRTC视频流显示**：实时显示WebRTC视频流
- **视频录制**：录制WebRTC视频流并保存为本地文件
- **视频回放**：支持录制视频的回放、快进快退及A/B点标记
- **双视图界面**：左侧显示实时WebRTC流，右侧用于录制视频回放

### 具体特性
- 视频回放控制（播放/暂停）
- 视频快进快退（左右方向键）
- A/B点标记与快速跳转（a/b键）
- 视频缩放与拖动（鼠标滚轮和拖拽）
- 精确时间显示（时:分:秒.毫秒）
- 自动管理录制文件（保留最新录制）

## 技术架构

### 主要组件

#### 1. WebRTCPlayer
WebRTC流管理和播放类，负责连接WebRTC流并处理视频帧。

主要方法：
- `open()` - 打开WebRTC连接
- `close()` - 关闭WebRTC连接
- `set_frame_callback()` - 设置帧处理回调
- `set_playback_callback()` - 设置播放状态回调

#### 2. VideoPlayer
本地视频文件播放器，处理视频文件的加载与播放控制。

主要方法：
- `open()` - 打开视频文件
- `close()` - 关闭视频文件
- `play()` - 播放视频
- `pause()` - 暂停视频
- `toggle_play()` - 切换播放/暂停状态
- `seek()` - 跳转到指定位置
- `seek_frame()` - 跳转到指定帧
- `add_frame_callback()` - 添加帧回调函数
- `add_playback_callback()` - 添加播放状态回调函数
- `add_progress_callback()` - 添加进度回调函数

#### 3. VideoPlayerFrame
视频显示UI组件，负责视频帧的显示与交互。

主要方法：
- `setup_ui()` - 设置UI组件
- `update_frame()` - 更新视频帧显示
- `show_loading()` - 显示/隐藏加载提示
- `update_status()` - 更新状态信息
- `set_video()` - 设置视频源
- `_on_mousewheel()` - 处理鼠标滚轮事件（缩放）
- `_on_drag_start/motion/end()` - 处理拖动事件

#### 4. VideoRecorder
视频录制功能，负责将实时视频流保存为视频文件。

主要方法：
- `start()` - 开始录制
- `stop()` - 停止录制
- `add_frame()` - 添加一帧到录制队列
- `_record_frames()` - 录制线程主函数

#### 5. MainWindow
主UI窗口，整合所有功能组件并处理用户交互。

主要方法：
- `_create_ui()` - 创建UI界面
- `_toggle_recording()` - 切换录制状态
- `_toggle_playback()` - 切换播放状态
- `_on_frame_received()` - 处理接收到的视频帧
- `_on_playback_progress()` - 更新播放进度
- `_format_time()` - 格式化时间显示
- `_start_fast_rewind()` - 开始快退操作
- `_start_fast_forward()` - 开始快进操作
- `_seek_to_exact_frame()` - 跳转到精确帧位置
- `on_jump_to_position_a/b()` - 跳转到A/B标记位置
- `_handle_key_press()` - 处理键盘事件

### 快捷键
- **空格**：播放/暂停
- **R**：开始/停止录制
- **左箭头**：快退
- **右箭头**：快进
- **A**：跳转到A点标记
- **B**：跳转到B点标记

## 环境要求
- Python 3.8+
- OpenCV (cv2)
- tkinter
- NumPy
- PIL (Pillow)
- aiortc
- aiohttp

## 使用说明

### 录制操作
1. 左侧显示WebRTC视频流连接后，点击"开始录制"按钮开始录制
2. 录制过程中可以查看录制时长
3. 点击"停止录制"结束录制，视频文件将自动在右侧加载并显示

### 回放操作
1. 录制结束后，视频会自动加载到右侧播放区
2. 使用"播放"按钮开始播放视频
3. 使用进度条调整播放位置
4. 使用左右方向键进行快退/快进控制
5. 按A/B键设置标记点并快速跳转

### 视频查看操作
- 使用鼠标滚轮调整右侧视频的缩放比例
- 按住鼠标左键拖动右侧视频的显示区域
- 使用鼠标中键双击重置视频查看状态