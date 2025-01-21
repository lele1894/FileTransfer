import os
import socket
import threading
import json
import time
import hashlib
import customtkinter as ctk
from tkinter import ttk
import sys
from PIL import Image
import io
import re

class FileTransferSignals:
    """自定义信号类"""
    def __init__(self):
        self._callbacks = {
            'progress_updated': [],
            'transfer_completed': [],
            'error_occurred': [],
            'remote_files_updated': [],
            'speed_updated': [],
            'status_updated': []  # 添加状态更新信号
        }
    
    def connect(self, signal, callback):
        """连接信号到回调函数"""
        if signal in self._callbacks:
            self._callbacks[signal].append(callback)
    
    def emit(self, signal, *args):
        """发送信号"""
        if signal in self._callbacks:
            for callback in self._callbacks[signal]:
                callback(*args)

def get_resource_path(relative_path):
    """获取资源文件的绝对路径"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 创建临时文件夹，将路径存储在 _MEIPASS 中
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

class FileTransferThread(threading.Thread):
    """文件传输线程"""
    def __init__(self, socket, file_path, save_path, is_upload=True, signals=None):
        super().__init__()
        self.socket = socket
        self.file_path = file_path
        self.save_path = save_path
        self.is_upload = is_upload
        self.running = True
        self.signals = signals or FileTransferSignals()
        self._last_time = time.time()
        self._last_update = time.time()
        self._update_interval = 0.5
        self._last_bytes = 0
        self._chunk_size = 262144  # 增加到256KB的块大小
        self._progress_update_interval = 0.2  # 降低进度更新频率

    def run(self):
        try:
            if self.is_upload:
                self._upload_file()
            else:
                self._download_file()
        except Exception as e:
            self.signals.emit('error_occurred', str(e))

    def _upload_file(self):
        try:
            file_size = os.path.getsize(self.file_path)
            file_name = os.path.basename(self.file_path)
            
            self.signals.emit('status_updated', f"正在发送: {file_name}")
            self.signals.emit('status_updated', "计算文件MD5...")
            md5_value = self._calculate_md5()

            # 发送文件信息
            header = f"{file_name}|{file_size}|{self.save_path}|{md5_value}<<END>>"
            self.socket.sendall(header.encode())

            # 优化socket配置
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 524288)  # 512KB发送缓冲区
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # 禁用Nagle算法
            
            # 发送文件内容
            bytes_sent = 0
            last_progress_update = time.time()
            self._last_bytes = 0
            self._last_update = time.time()
            
            with open(self.file_path, 'rb') as f:
                while bytes_sent < file_size and self.running:
                    chunk = f.read(self._chunk_size)
                    if not chunk:
                        break
                        
                    self.socket.sendall(chunk)
                    bytes_sent += len(chunk)
                    
                    # 降低进度更新频率
                    current_time = time.time()
                    if current_time - last_progress_update >= self._progress_update_interval:
                        progress = int((bytes_sent / file_size) * 100)
                        self.signals.emit('progress_updated', progress)
                        self._update_speed(bytes_sent)
                        last_progress_update = current_time

            if bytes_sent == file_size:
                self.signals.emit('progress_updated', 100)
                self._update_speed(bytes_sent)
                self.signals.emit('transfer_completed', f"已发送: {file_name}")
                self.signals.emit('status_updated', "传输完成")
            else:
                raise Exception("传输未完成")
            
        except Exception as e:
            self.signals.emit('error_occurred', f"上传失败: {str(e)}")
            self.signals.emit('status_updated', "传输失败")

    def _calculate_md5(self):
        md5_hash = hashlib.md5()
        with open(self.file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def _update_speed(self, total_bytes):
        """计算实际每秒传输速度"""
        current_time = time.time()
        
        # 检查是否达到更新间隔
        if current_time - self._last_update >= self._update_interval:
            # 计算这个间隔内传输的字节数
            bytes_diff = total_bytes - self._last_bytes
            time_diff = current_time - self._last_update
            
            if time_diff > 0:
                # 计算实际每秒速度
                speed = bytes_diff / time_diff
                speed_mb = speed / (1024 * 1024)
                speed_str = f"{speed_mb:.2f} MB/s"
                self.signals.emit('speed_updated', speed_str)
            
            # 更新记录
            self._last_bytes = total_bytes
            self._last_update = current_time

    def _download_file(self):
        """处理文件下载"""
        try:
            if not os.path.exists(self.file_path):
                raise Exception("文件不存在")
            
            file_size = os.path.getsize(self.file_path)
            file_name = os.path.basename(self.file_path)
            
            self.signals.emit('status_updated', f"正在下载: {file_name}")
            
            # 创建保存目录
            os.makedirs(self.save_path, exist_ok=True)
            save_file_path = os.path.join(self.save_path, file_name)
            
            # 优化socket配置
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 524288)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            
            with open(save_file_path, 'wb', buffering=262144) as f:
                bytes_received = 0
                last_progress_update = time.time()
                self._last_bytes = 0
                self._last_update = time.time()
                
                while bytes_received < file_size and self.running:
                    chunk = self.socket.recv(min(262144, file_size - bytes_received))
                    if not chunk:
                        break
                    
                    f.write(chunk)
                    bytes_received += len(chunk)
                    
                    # 更新进度
                    current_time = time.time()
                    if current_time - last_progress_update >= self._progress_update_interval:
                        progress = int((bytes_received / file_size) * 100)
                        self.signals.emit('progress_updated', progress)
                        self._update_speed(bytes_received)
                        last_progress_update = current_time
                
                if bytes_received == file_size:
                    self.signals.emit('progress_updated', 100)
                    self._update_speed(bytes_received)
                    self.signals.emit('transfer_completed', f"已下载: {file_name}")
                    self.signals.emit('status_updated', "下载完成")
                else:
                    raise Exception("下载未完成")
                
        except Exception as e:
            self.signals.emit('error_occurred', f"下载失败: {str(e)}")
            self.signals.emit('status_updated', "下载失败")

class FileTransferWindow(ctk.CTk):
    def __init__(self, port=5000):
        super().__init__()
        self.port = port
        self.signals = FileTransferSignals()
        self.client_socket = None
        self.connected = False
        self.is_server = True
        self.save_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.remote_files = []
        self.buffer = ""
        self.current_remote_directory = ""  # 初始为空，显示所有驱动器
        self.current_local_directory = ""   # 初始为空，显示所有驱动器
        self.last_transfer_time = time.time()
        self.transfer_thread = None
        self.last_speed_update = time.time()
        self.speed_update_interval = 0.5
        self.last_bytes = 0
        
        # IP 历史记录
        self.ip_history = []
        self.load_ip_history()
        
        # 设置窗口图标
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tb.jpeg')
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
                img = img.resize((32, 32), Image.Resampling.LANCZOS)
                temp_ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_icon.ico')
                img.save(temp_ico, format='ICO', sizes=[(32, 32)])
                self.after(100, lambda: self.iconbitmap(temp_ico))
                self.after(1000, lambda: os.remove(temp_ico) if os.path.exists(temp_ico) else None)
        except Exception as e:
            print(f"设置图标失败: {str(e)}")
            
        self.setup_ui()  # 先设置UI
        
        # 在UI设置完成后，再进行其他初始化
        self.after(100, self.post_init)  # 使用after延迟执行其他初始化操作

    def post_init(self):
        """UI加载完成后的初始化操作"""
        try:
            # 更新驱动器列表
            self.update_drive_list(self.local_drive_combo)
            
            # 更新本地文件列表显示所有驱动器
            self.update_local_files("")
            
            # 启动服务器
            self.start_server()
            
            # 设置信号连接
            self.setup_signals()
        except Exception as e:
            print(f"初始化失败: {str(e)}")

    def setup_ui(self):
        self.title("文件快传")
        self.geometry("1200x700")
        
        # 顶部连接区域
        top_frame = ctk.CTkFrame(self)
        top_frame.pack(fill="x", padx=10, pady=5)
        
        self.ip_label = ctk.CTkLabel(top_frame, text=f"本机IP: {self.get_local_ip()}")
        self.ip_label.pack(side="left")
        
        # IP输入下拉框
        self.ip_combo = ctk.CTkComboBox(top_frame, width=200)
        self.ip_combo.pack(side="right", padx=5)
        self.ip_combo.set("输入对方IP地址")
        if self.ip_history:  # 修改这里，确保有历史记录时才设置
            self.ip_combo.configure(values=list(self.ip_history))
        
        self.connect_button = ctk.CTkButton(
            top_frame, 
            text="连接",
            command=self.connect_to_peer
        )
        self.connect_button.pack(side="right", padx=5)
        
        # 状态显示
        status_frame = ctk.CTkFrame(self)
        status_frame.pack(fill="x", padx=10, pady=5)
        
        self.status_label = ctk.CTkLabel(status_frame, text="等待连接...")
        self.status_label.pack(side="left")
        
        self.error_label = ctk.CTkLabel(status_frame, text="", text_color="red")
        self.error_label.pack(side="left", padx=10)
        
        # 文件浏览区域
        browser_frame = ctk.CTkFrame(self)
        browser_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 左侧本地文件
        left_frame = ctk.CTkFrame(browser_frame, width=400)  # 设置固定宽度
        left_frame.pack(side="left", fill="both", expand=True, padx=(0,5))
        left_frame.pack_propagate(False)  # 防止子组件影响frame大小
        
        ctk.CTkLabel(left_frame, text="本地设备").pack()
        
        # 本地导航栏
        local_nav = ctk.CTkFrame(left_frame)
        local_nav.pack(fill="x")
        
        self.local_drive_combo = ctk.CTkComboBox(
            local_nav,
            width=100,
            command=self.on_local_drive_changed
        )
        self.local_drive_combo.pack(side="left", padx=5)
        
        self.local_back_btn = ctk.CTkButton(
            local_nav,
            text="返回上级",
            command=self.local_go_to_parent_directory
        )
        self.local_back_btn.pack(side="left", padx=5)
        
        self.current_local_path = ctk.CTkLabel(local_nav, text="")
        self.current_local_path.pack(side="left", padx=5)
        
        # 本地文件列表
        local_list_frame = ctk.CTkFrame(left_frame)
        local_list_frame.pack(fill="both", expand=True)
        
        # 添加滚动条
        local_scrollbar_y = ttk.Scrollbar(local_list_frame)
        local_scrollbar_y.pack(side="right", fill="y")
        
        local_scrollbar_x = ttk.Scrollbar(local_list_frame, orient="horizontal")
        local_scrollbar_x.pack(side="bottom", fill="x")
        
        self.local_list = ttk.Treeview(
            local_list_frame,
            selectmode="extended",
            columns=("type", "name", "size"),
            show="headings",
            yscrollcommand=local_scrollbar_y.set,
            xscrollcommand=local_scrollbar_x.set
        )
        self.local_list.heading("type", text="类型", command=lambda: self.treeview_sort_column(self.local_list, "type", False))
        self.local_list.heading("name", text="名称", command=lambda: self.treeview_sort_column(self.local_list, "name", False))
        self.local_list.heading("size", text="大小", command=lambda: self.treeview_sort_column(self.local_list, "size", False))
        
        # 设置列宽
        self.local_list.column("type", width=80, minwidth=60)
        self.local_list.column("name", width=200, minwidth=100)
        self.local_list.column("size", width=100, minwidth=80)
        
        self.local_list.pack(fill="both", expand=True)
        self.local_list.bind("<Double-1>", self.local_item_double_clicked)
        
        # 配置滚动条
        local_scrollbar_y.config(command=self.local_list.yview)
        local_scrollbar_x.config(command=self.local_list.xview)
        
        # 添加本地刷新按钮
        refresh_local_btn = ctk.CTkButton(
            left_frame,
            text="刷新本地文件",
            command=self.refresh_local_files
        )
        refresh_local_btn.pack(pady=5)
        
        # 中间按钮区域
        middle_frame = ctk.CTkFrame(browser_frame)
        middle_frame.pack(side="left", padx=10)
        
        self.transfer_btn = ctk.CTkButton(
            middle_frame,
            text="推送 →",
            command=self.transfer_selected_file
        )
        self.transfer_btn.pack(pady=5)
        
        self.pull_btn = ctk.CTkButton(
            middle_frame,
            text="← 拉取",
            command=self.pull_selected_file
        )
        self.pull_btn.pack(pady=5)
        
        # 右侧远程文件
        right_frame = ctk.CTkFrame(browser_frame, width=400)  # 设置固定宽度
        right_frame.pack(side="right", fill="both", expand=True, padx=(5,0))
        right_frame.pack_propagate(False)  # 防止子组件影响frame大小
        
        ctk.CTkLabel(right_frame, text="远程设备").pack()
        
        # 远程导航栏
        remote_nav = ctk.CTkFrame(right_frame)
        remote_nav.pack(fill="x")
        
        self.remote_drive_combo = ctk.CTkComboBox(
            remote_nav,
            width=100,
            command=self.on_remote_drive_changed
        )
        self.remote_drive_combo.pack(side="left", padx=5)
        self.remote_drive_combo.set("选择驱动器")  # 设置默认提示文本
        
        self.back_btn = ctk.CTkButton(
            remote_nav,
            text="返回上级",
            command=self.go_to_parent_directory
        )
        self.back_btn.pack(side="left", padx=5)
        
        self.current_remote_path = ctk.CTkLabel(remote_nav, text="")
        self.current_remote_path.pack(side="left", padx=5)
        
        # 远程文件列表
        remote_list_frame = ctk.CTkFrame(right_frame)
        remote_list_frame.pack(fill="both", expand=True)
        
        # 添加滚动条
        remote_scrollbar_y = ttk.Scrollbar(remote_list_frame)
        remote_scrollbar_y.pack(side="right", fill="y")
        
        remote_scrollbar_x = ttk.Scrollbar(remote_list_frame, orient="horizontal")
        remote_scrollbar_x.pack(side="bottom", fill="x")
        
        self.remote_list = ttk.Treeview(
            remote_list_frame,
            selectmode="extended",
            columns=("type", "name", "size"),
            show="headings",
            yscrollcommand=remote_scrollbar_y.set,
            xscrollcommand=remote_scrollbar_x.set
        )
        self.remote_list.heading("type", text="类型", command=lambda: self.treeview_sort_column(self.remote_list, "type", False))
        self.remote_list.heading("name", text="名称", command=lambda: self.treeview_sort_column(self.remote_list, "name", False))
        self.remote_list.heading("size", text="大小", command=lambda: self.treeview_sort_column(self.remote_list, "size", False))
        
        # 设置列宽
        self.remote_list.column("type", width=80, minwidth=60)
        self.remote_list.column("name", width=200, minwidth=100)
        self.remote_list.column("size", width=100, minwidth=80)
        
        self.remote_list.pack(fill="both", expand=True)
        self.remote_list.bind("<Double-1>", self.remote_item_double_clicked)
        
        # 配置滚动条
        remote_scrollbar_y.config(command=self.remote_list.yview)
        remote_scrollbar_x.config(command=self.remote_list.xview)
        
        refresh_btn = ctk.CTkButton(
            right_frame,
            text="刷新远程文件",
            command=self.request_file_list
        )
        refresh_btn.pack(pady=5)
        
        # 底部进度显示
        progress_frame = ctk.CTkFrame(self)
        progress_frame.pack(fill="x", padx=10, pady=5)
        
        self.current_file_label = ctk.CTkLabel(progress_frame, text="当前文件: 无")
        self.current_file_label.pack(side="left")
        
        self.transfer_status = ctk.CTkLabel(progress_frame, text="传输速度: 0 MB/s")
        self.transfer_status.pack(side="left", padx=10)
        
        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.pack(fill="x", expand=True, padx=10)
        self.progress_bar.set(0)
        
    def setup_signals(self):
        """设置所有信号连接"""
        # 进度更新信号
        self.signals.connect('progress_updated', 
            lambda value: self.after(0, lambda: self.progress_bar.set(value / 100.0)))
        
        # 传输完成信号
        self.signals.connect('transfer_completed', 
            lambda msg: self.after(0, lambda: self.on_transfer_completed(msg)))
        
        # 错误信号
        self.signals.connect('error_occurred', 
            lambda msg: self.after(0, lambda: self.on_error(msg)))
        
        # 远程文件列表更新信号
        self.signals.connect('remote_files_updated', 
            lambda files, path: self.after(0, lambda: self.update_remote_files(files, path)))
        
        # 速度更新信号
        self.signals.connect('speed_updated', 
            lambda speed: self.after(0, lambda: self.transfer_status.configure(text=speed)))
        
        # 状态更新信号
        self.signals.connect('status_updated',
            lambda status: self.after(0, lambda: self.current_file_label.configure(text=status)))

    def transfer_selected_file(self):
        """处理文件传输"""
        if not self.connected:
            self.error_label.configure(text="请先连接到对方")
            return
        
        # 获取所有选中的文件
        selected_items = self.local_list.selection()
        if not selected_items:
            return
        
        # 处理选中的文件
        for item in selected_items:
            values = self.local_list.item(item)['values']
            if not values or values[0] != "文件":  # 检查是否为文件
                continue
            
            file_name = values[1]  # 获取文件名
            file_path = os.path.join(self.current_local_directory, file_name)
            
            if not os.path.isfile(file_path):
                continue
            
            # 创建并启动传输线程
            self.transfer_thread = FileTransferThread(
                self.client_socket,
                file_path,
                self.current_remote_directory or os.path.join(os.path.expanduser("~"), "Downloads"),
                is_upload=True,
                signals=self.signals
            )
            
            # 启动线程
            self.transfer_thread.start()

    def send_file(self, file_path):
        try:
            if not self.connected or not self.client_socket:
                raise Exception("未连接到对方")
                
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            
            if file_size == 0:
                raise Exception("文件为空")
                
            # 计算文件MD5
            md5_value = self.calculate_md5(file_path)
            self.current_file_label.configure(text=f"正在发送: {file_name}")
            
            save_path = self.current_remote_directory
            if not save_path:
                save_path = os.path.join(os.path.expanduser("~"), "Downloads")
            
            # 发送文件信息（包含MD5值）
            header = f"{file_name}|{file_size}|{save_path}|{md5_value}<<END>>".encode()
            self.client_socket.send(header)
            
            self.last_transfer_time = time.time()
            with open(file_path, 'rb') as f:
                bytes_sent = 0
                while bytes_sent < file_size:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    self.client_socket.send(chunk)
                    bytes_sent += len(chunk)
                    progress = int((bytes_sent / file_size) * 100)
                    self.signals.emit('progress_updated', progress)
                    self.calculate_speed(bytes_sent)
                    
            self.signals.emit('transfer_completed', f"已发送: {file_name}")
            self.signals.emit('speed_updated', "传输速度: 0 B/s")
            
        except Exception as e:
            self.signals.emit('error_occurred', str(e))
            self.disconnect_peer()
            
    def request_file_list(self):
        """请求远程文件列表"""
        if not self.connected:
            self.error_label.configure(text="未连接到对方")
            return
        try:
            print("发送文件列表请求")  # 添加调试信息
            request = {
                'type': 'list_request'
            }
            message = json.dumps(request) + "<<END>>"
            self.client_socket.send(message.encode())
        except Exception as e:
            print(f"请求文件列表失败: {str(e)}")  # 添加调试信息
            self.error_label.configure(text=f"请求文件列表失败: {str(e)}")

    def send_file_list(self):
        """发送本地文件列表给对方"""
        try:
            # 获取所有驱动器
            drives = []
            if os.name == 'nt':  # Windows系统
                import win32api
                drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
                drives = [drive.rstrip('\\') for drive in drives if drive]  # 移除空值并去掉反斜杠
            else:  # Linux/Mac系统
                drives = ['/']

            files = []
            current_path = self.current_local_directory
            
            # 如果是驱动器根目录（如 D:\）或空路径，显示驱动器列表
            if os.name == 'nt':
                if not current_path or current_path == "":
                    # 显示驱动器列表
                    for drive in drives:
                        files.append(f"[驱动器] {drive}")
                    print(f"发送驱动器列表: {files}")
                    current_path = ""  # 重置为空字符串表示根目录
                else:
                    # 显示当前目录的内容
                    try:
                        for item in os.listdir(current_path):
                            item_path = os.path.join(current_path, item)
                            try:
                                if os.path.isfile(item_path):
                                    size = os.path.getsize(item_path)
                                    size_str = self.format_size(size)
                                    files.append(f"[文件] {item} ({size_str})")
                                else:
                                    files.append(f"[文件夹] {item}")
                            except Exception as e:
                                print(f"处理文件 {item} 时出错: {str(e)}")
                                continue
                    except Exception as e:
                        print(f"读取目录 {current_path} 失败: {str(e)}")
                        # 如果读取失败，返回到驱动器列表
                        for drive in drives:
                            files.append(f"[驱动器] {drive}")
                        current_path = ""
            else:
                # Linux/Mac 系统的处理逻辑
                if not current_path or current_path == "/":
                    files.append("[驱动器] /")
                    current_path = "/"
                else:
                    # 显示当前目录的内容
                    try:
                        for item in os.listdir(current_path):
                            item_path = os.path.join(current_path, item)
                            try:
                                if os.path.isfile(item_path):
                                    size = os.path.getsize(item_path)
                                    size_str = self.format_size(size)
                                    files.append(f"[文件] {item} ({size_str})")
                                else:
                                    files.append(f"[文件夹] {item}")
                            except Exception as e:
                                print(f"处理文件 {item} 时出错: {str(e)}")
                                continue
                    except Exception as e:
                        print(f"读取目录 {current_path} 失败: {str(e)}")
                        files.append("[驱动器] /")
                        current_path = "/"
            
            print(f"准备发送文件列表: {files}, 当前路径: {current_path}")
            response = {
                'type': 'file_list',
                'files': files,
                'path': current_path
            }
            message = json.dumps(response) + "<<END>>"
            self.client_socket.send(message.encode())
            print("文件列表已发送")
        except Exception as e:
            print(f"发送文件列表失败: {str(e)}")
            self.error_label.configure(text=f"发送文件列表失败: {str(e)}")
            
    def format_size(self, size):
        """格式化文件大小显示"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"

    def update_remote_files(self, files, current_path=""):
        """更新远程文件列表显示"""
        try:
            self.remote_list.delete(*self.remote_list.get_children())
            self.remote_files = files
            self.current_remote_directory = current_path
            
            # 更新当前路径显示
            if current_path:
                self.current_remote_path.configure(text=f"当前位置: {current_path}")
                # 更新驱动器下拉框
                if os.name == 'nt':
                    drive = os.path.splitdrive(current_path)[0]
                    if drive:
                        self.remote_drive_combo.set(drive)
                else:
                    drives = []
                    for file in files:
                        if file.startswith("[驱动器]"):
                            drive = file.split("] ")[1].strip().rstrip('\\')
                            drives.append(drive)
                    self.remote_drive_combo.configure(values=drives)
                    if drives:
                        self.remote_drive_combo.set(drives[0])
            else:
                self.current_remote_path.configure(text="当前位置: 根目录")
                # 更新远程驱动器列表
                drives = []
                for file in files:
                    if file.startswith("[驱动器]"):
                        drive = file.split("] ")[1].strip()
                        drives.append(drive)
                self.remote_drive_combo.configure(values=drives)
                if drives:
                    self.remote_drive_combo.set(drives[0])
            
            # 更新文件列表
            for file in files:
                if file.startswith("[驱动器]"):
                    drive = file.split("] ")[1].strip()
                    self.remote_list.insert("", "end", values=("驱动器", drive.rstrip('\\'), ""))
                elif file.startswith("[文件夹]"):
                    folder = file.split("] ")[1].strip()
                    self.remote_list.insert("", "end", values=("文件夹", folder, ""))
                elif file.startswith("[文件]"):
                    parts = file.split("] ")[1].split(" (")
                    name = parts[0].strip()
                    size = parts[1].rstrip(")")
                    self.remote_list.insert("", "end", values=("文件", name, size))
                
        except Exception as e:
            print(f"更新远程文件列表失败: {str(e)}")
            self.error_label.configure(text=f"更新远程文件列表失败: {str(e)}")

    def handle_json_message(self, msg_data):
        """处理JSON格式的消息"""
        try:
            if msg_data['type'] == 'list_request':
                print("收到文件列表请求")
                path = msg_data.get('path', '')
                if path:
                    self.current_local_directory = path
                self.send_file_list()
            elif msg_data['type'] == 'file_list':
                print(f"收到文件列表: {msg_data['files']}")
                self.signals.emit('remote_files_updated', msg_data['files'], msg_data.get('path', ''))
            elif msg_data['type'] == 'pull_request':
                print(f"收到文件拉取请求: {msg_data}")
                self.handle_pull_request(msg_data)
        except Exception as e:
            print(f"处理JSON消息失败: {str(e)}")
            self.signals.emit('error_occurred', str(e))

    def handle_file_transfer(self, message, remaining):
        """处理文件传输消息"""
        try:
            # 解析文件信息
            file_info = message.split('|')
            if len(file_info) != 4:
                raise ValueError("无效的文件信息格式")

            file_name, file_size, save_path, md5_value = file_info
            file_size = int(file_size)

            if not save_path:
                save_path = os.path.join(os.path.expanduser("~"), "Downloads")

            print(f"保存文件到: {save_path}")
            self.current_file_label.configure(text=f"正在接收: {file_name}")

            # 创建保存目录
            os.makedirs(save_path, exist_ok=True)
            full_save_path = os.path.join(save_path, file_name)

            # 优化socket配置
            self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 524288)  # 512KB接收缓冲区
            self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # 禁用Nagle算法
            
            # 接收文件内容
            self.last_transfer_time = time.time()
            with open(full_save_path, 'wb', buffering=262144) as f:  # 使用256KB的文件缓冲区
                bytes_received = 0
                if remaining:
                    f.write(remaining)
                    bytes_received = len(remaining)

                while bytes_received < file_size:
                    try:
                        chunk = self.client_socket.recv(min(262144, file_size - bytes_received))
                        if not chunk:
                            raise ConnectionError("连接已断开")
                        f.write(chunk)
                        bytes_received += len(chunk)
                        
                        # 降低进度更新频率
                        if bytes_received % (262144 * 4) == 0:  # 每接收1MB更新一次进度
                            progress = int((bytes_received / file_size) * 100)
                            self.signals.emit('progress_updated', progress)
                            self.calculate_speed(bytes_received)
                    except socket.timeout:
                        continue

            # 验证文件MD5
            received_md5 = self.calculate_md5(full_save_path)
            if received_md5 != md5_value:
                raise ValueError("文件校验失败，传输可能不完整")

            self.signals.emit('transfer_completed', f"已接收: {file_name}")
            self.signals.emit('speed_updated', "传输速度: 0 B/s")

            if not self.is_server:
                print("文件接收完成，请求更新文件列表")
                self.request_file_list()

        except Exception as e:
            print(f"文件接收失败: {str(e)}")
            self.signals.emit('error_occurred', f"文件接收失败: {str(e)}")
            raise

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
        
    def start_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(1)
            threading.Thread(target=self.accept_connections, daemon=True).start()
        except Exception as e:
            self.signals.emit('error_occurred', f"启动服务器失败: {str(e)}")
        
    def accept_connections(self):
        while True:
            try:
                client_socket, addr = self.server_socket.accept()
                if self.client_socket:  # 如果已经有连接，拒绝新连接
                    client_socket.close()
                    continue
                    
                self.client_socket = client_socket
                self.connected = True
                self.status_label.configure(text=f"已连接到: {addr[0]}")
                threading.Thread(target=self.receive_files, daemon=True).start()
            except Exception as e:
                self.signals.emit('error_occurred', str(e))
                break
            
    def connect_to_peer(self):
        if self.connected:
            self.disconnect_peer()
            return
            
        try:
            ip = self.ip_combo.get()
            if not ip:
                self.error_label.configure(text="请输入对方IP地址")
                self.after(3000, lambda: self.error_label.configure(text=""))
                return
            
            # 保存IP到历史记录
            if ip not in self.ip_history:
                self.ip_history.append(ip)
                if len(self.ip_history) > 10:  # 最多保存10条记录
                    self.ip_history.pop(0)
                self.save_ip_history()
                # 更新下拉列表
                self.ip_combo.configure(values=list(self.ip_history))
                
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, self.port))
            self.connected = True
            self.is_server = False
            self.status_label.configure(text=f"已连接到: {ip}")
            self.connect_button.configure(text="断开连接")
            self.ip_combo.configure(state="disabled")
            
            threading.Thread(target=self.receive_files, daemon=True).start()
            self.after(500, self.request_file_list)
            
        except Exception as e:
            self.signals.emit('error_occurred', str(e))
            self.client_socket = None

    def load_ip_history(self):
        """加载IP历史记录"""
        try:
            history_file = os.path.join(os.path.expanduser("~"), ".file_transfer_history")
            if os.path.exists(history_file):
                with open(history_file, "r", encoding="utf-8") as f:
                    self.ip_history = [line.strip() for line in f.readlines() if line.strip()]
        except Exception as e:
            print(f"加载IP历史记录失败: {str(e)}")

    def save_ip_history(self):
        """保存IP历史记录"""
        try:
            history_file = os.path.join(os.path.expanduser("~"), ".file_transfer_history")
            with open(history_file, "w", encoding="utf-8") as f:
                for ip in self.ip_history:
                    f.write(f"{ip}\n")
        except Exception as e:
            print(f"保存IP历史记录失败: {str(e)}")

    def disconnect_peer(self):
        if self.transfer_thread and self.transfer_thread.is_alive():
            self.transfer_thread.running = False
            self.transfer_thread.join()
            
        self.connected = False
        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
                self.client_socket.close()
            except:
                pass
            self.client_socket = None

        self.status_label.configure(text="等待连接...")
        self.connect_button.configure(text="连接")
        self.ip_combo.configure(state="normal")
        self.progress_bar.set(0)
        self.current_file_label.configure(text="当前文件: 无")
        self.transfer_status.configure(text="传输速度: 0 MB/s")
        self.error_label.configure(text="")
        self.is_server = True
        
    def on_transfer_completed(self, message):
        """传输完成处理"""
        self.current_file_label.configure(text=message)
        self.progress_bar.set(100)
        self.transfer_status.configure(text="传输速度: 0 MB/s")
        
    def on_error(self, error_msg):
        # 根据错误类型显示不同的提示
        if "10053" in error_msg:  # 连接断开
            self.error_label.configure(text="连接已断开")
        elif "10061" in error_msg:  # 连接被拒绝
            self.error_label.configure(text="连接被拒绝")
        else:
            self.error_label.configure(text="传输错误")
        
        # 3秒后清除错误提示
        self.after(3000, lambda: self.error_label.configure(text=""))
        
        # 重置状态
        self.progress_bar.set(0)
        self.current_file_label.configure(text="当前文件: 无")
        self.disconnect_peer()
        
    def close(self):
        """关闭窗口时保存IP历史记录"""
        self.save_ip_history()
        if self.client_socket:
            self.client_socket.close()
        if hasattr(self, 'server_socket'):
            self.server_socket.close()
        self.destroy()
        
    def select_save_directory(self):
        dir_path = ctk.CTk.askdirectory(self, title="选择保存位置", initialdir=self.save_dir)
        if dir_path:
            self.save_dir = dir_path
            self.current_local_path.configure(text=f"当前位置: {self.save_dir}")
            
    def local_item_double_clicked(self, event):
        """处理本地文件列表的双击事件"""
        try:
            selected_item = self.local_list.selection()[0]
            values = self.local_list.item(selected_item)['values']
            item_type = values[0]  # 第一列是类型
            item_name = values[1]  # 第二列是名称
            
            if item_type == "驱动器":
                # 如果是驱动器，直接使用驱动器路径
                path = item_name
                if os.name == 'nt' and not path.endswith('\\'):
                    path = path + '\\'
                print(f"打开本地驱动器: {path}")
                self.update_local_files(path)
            elif item_type == "文件夹":
                # 如果是文件夹，拼接完整路径
                if self.current_local_directory:
                    path = os.path.join(self.current_local_directory, item_name)
                else:
                    path = item_name
                print(f"打开本地文件夹: {path}")
                self.update_local_files(path)
        except Exception as e:
            print(f"处理本地双击事件失败: {str(e)}")
            self.error_label.configure(text=f"打开本地文件夹失败: {str(e)}")

    def remote_item_double_clicked(self, event):
        """处理远程文件列表的双击事件"""
        try:
            selected_item = self.remote_list.selection()[0]
            values = self.remote_list.item(selected_item)['values']
            if not values:  # 检查是否有选中的项目
                return
            
            item_type = values[0]  # 第一列是类型
            item_name = values[1]  # 第二列是名称
            
            if item_type == "驱动器":
                # 如果是驱动器，直接使用驱动器路径
                path = item_name
                if os.name == 'nt' and not path.endswith('\\'):
                    path = path + '\\'
                print(f"请求打开远程驱动器: {path}")
                self.current_remote_directory = path
            elif item_type == "文件夹":
                # 如果是文件夹，拼接完整路径
                if self.current_remote_directory:
                    path = os.path.join(self.current_remote_directory, item_name)
                else:
                    path = item_name
                print(f"请求打开远程文件夹: {path}")
                self.current_remote_directory = path
            else:
                return

            # 发送请求获取该路径下的文件列表
            request = {
                'type': 'list_request',
                'path': path
            }
            message = json.dumps(request) + "<<END>>"
            try:
                self.client_socket.send(message.encode())
            except Exception as e:
                print(f"发送远程文件列表请求失败: {str(e)}")
                self.error_label.configure(text=f"请求远程文件列表失败: {str(e)}")
                self.after(3000, lambda: self.error_label.configure(text=""))
            
        except Exception as e:
            print(f"处理远程双击事件失败: {str(e)}")
            self.error_label.configure(text=f"打开远程文件夹失败: {str(e)}")
            self.after(3000, lambda: self.error_label.configure(text=""))

    def go_to_parent_directory(self):
        """返回远程上级目录"""
        try:
            if not self.current_remote_directory:
                return
            
            if os.name == 'nt':  # Windows 系统
                drive, path = os.path.splitdrive(self.current_remote_directory)
                # 如果当前是驱动器根目录（如 C:\），返回驱动器列表
                if path in ['\\', '/', '']:
                    parent_path = ""  # 返回驱动器列表
                else:
                    parent_path = os.path.dirname(self.current_remote_directory)
                    # 如果返回到驱动器根目录，确保路径格式正确
                    if parent_path == drive:
                        parent_path = drive + '\\'
            else:  # Linux/Mac 系统
                if self.current_remote_directory == '/':
                    return
                parent_path = os.path.dirname(self.current_remote_directory)
                if not parent_path:  # 如果是根目录
                    parent_path = '/'
            
            print(f"返回上级目录: 当前={self.current_remote_directory}, 父级={parent_path}")
            request = {
                'type': 'list_request',
                'path': parent_path
            }
            message = json.dumps(request) + "<<END>>"
            try:
                self.client_socket.send(message.encode())
            except Exception as e:
                print(f"返回上级目录失败: {str(e)}")
                self.error_label.configure(text=f"返回上级目录失败: {str(e)}")
                self.after(3000, lambda: self.error_label.configure(text=""))
        except Exception as e:
            print(f"返回上级目录操作失败: {str(e)}")
            self.error_label.configure(text=f"返回上级目录操作失败: {str(e)}")
            self.after(3000, lambda: self.error_label.configure(text=""))

    def update_local_files(self, path):
        """更新本地文件列表显示"""
        try:
            self.local_list.delete(*self.local_list.get_children())
            self.current_local_directory = path
            
            # 更新当前路径显示
            if path:
                self.current_local_path.configure(text=f"当前位置: {path}")
            else:
                self.current_local_path.configure(text="当前位置: 根目录")
            
            # 获取驱动器列表
            if os.name == 'nt':  # Windows系统
                import win32api
                drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
                drives = [drive.rstrip('\\') for drive in drives if drive]
            else:  # Linux/Mac系统
                drives = ['/']
            
            # 如果是空路径或根目录，显示驱动器列表
            if not path:
                for drive in drives:
                    self.local_list.insert("", "end", values=("驱动器", drive, ""))
                return
            
            # 显示当前目录的文件和文件夹
            try:
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    try:
                        if os.path.isfile(item_path):
                            size = os.path.getsize(item_path)
                            size_str = self.format_size(size)
                            self.local_list.insert("", "end", values=("文件", item, size_str))
                        else:
                            self.local_list.insert("", "end", values=("文件夹", item, ""))
                    except Exception as e:
                        print(f"处理文件 {item} 时出错: {str(e)}")
                        continue
            except Exception as e:
                print(f"读取目录 {path} 失败: {str(e)}")
                # 如果读取失败，显示驱动器列表
                for drive in drives:
                    self.local_list.insert("", "end", values=("驱动器", drive, ""))
                self.current_local_directory = ""
                self.current_local_path.configure(text="当前位置: 根目录")
            
        except Exception as e:
            print(f"更新本地文件列表失败: {str(e)}")
            self.error_label.configure(text=f"更新本地文件列表失败: {str(e)}")

    def local_go_to_parent_directory(self):
        """返回本地上级目录"""
        if not self.current_local_directory:
            return
            
        if os.name == 'nt':  # Windows 系统
            drive, path = os.path.splitdrive(self.current_local_directory)
            # 如果路径只有驱动器号（如 C:) 或者驱动器根目录（如 C:\），返回驱动器列表
            if not path or path == '\\' or path == '/':
                self.update_local_files("")
            else:
                parent_path = os.path.dirname(self.current_local_directory)
                self.update_local_files(parent_path)
        else:  # Linux/Mac 系统
            if self.current_local_directory == '/':
                return
            parent_path = os.path.dirname(self.current_local_directory)
            if not parent_path:  # 如果是根目录
                parent_path = '/'
            self.update_local_files(parent_path)

    def pull_selected_file(self):
        """处理文件拉取"""
        if not self.connected:
            self.error_label.configure(text="请先连接到对方")
            return
        
        # 获取所有选中的远程文件
        selected_items = self.remote_list.selection()
        if not selected_items:
            return
        
        # 直接处理选中的文件
        for item in selected_items:
            values = self.remote_list.item(item)['values']
            if not values or values[0] != "文件":  # 检查是否为文件
                continue
            
            file_name = values[1]  # 获取文件名
            
            # 构造拉取请求
            request = {
                'type': 'pull_request',
                'file_names': [file_name],
                'paths': [self.current_remote_directory],
                'save_paths': [self.current_local_directory or os.path.join(os.path.expanduser("~"), "Downloads")]
            }
            
            try:
                message = json.dumps(request) + "<<END>>"
                self.client_socket.send(message.encode())
            except Exception as e:
                print(f"发送拉取请求失败: {str(e)}")
                self.error_label.configure(text=f"发送拉取请求失败: {str(e)}")
                self.after(3000, lambda: self.error_label.configure(text=""))

    def handle_pull_request(self, msg_data):
        """处理文件拉取请求"""
        try:
            file_names = msg_data['file_names']
            paths = msg_data.get('paths', [])
            save_paths = msg_data.get('save_paths', [])

            if not paths:
                raise Exception("无效的文件路径")

            for file_name, path, save_path in zip(file_names, paths, save_paths):
                file_path = os.path.join(path, file_name)
                if not os.path.isfile(file_path):
                    raise Exception(f"文件 {file_name} 不存在")

                # 创建并启动传输线程
                self.transfer_thread = FileTransferThread(
                    self.client_socket, 
                    file_path, 
                    save_path, 
                    is_upload=True,
                    signals=self.signals
                )
                
                # 启动线程
                self.transfer_thread.start()

        except Exception as e:
            print(f"处理拉取请求失败: {str(e)}")
            self.error_label.configure(text=f"处理拉取请求失败: {str(e)}")
            self.after(3000, lambda: self.error_label.configure(text=""))

    def update_status(self, status):
        """更新状态显示"""
        self.current_file_label.configure(text=status)

    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.set(value / 100.0)  # customtkinter进度条值范围是0-1

    def update_speed_display(self, speed):
        """更新速度显示"""
        self.transfer_status.configure(text=speed)

    def calculate_speed(self, total_bytes):
        """计算实际每秒传输速度"""
        current_time = time.time()
        
        # 检查是否达到更新间隔
        if current_time - self.last_speed_update >= self.speed_update_interval:
            # 计算这个间隔内传输的字节数
            bytes_diff = total_bytes - self.last_bytes
            time_diff = current_time - self.last_speed_update
            
            if time_diff > 0:
                # 计算实际每秒速度
                speed = bytes_diff / time_diff
                speed_mb = speed / (1024 * 1024)
                speed_str = f"{speed_mb:.2f} MB/s"
                self.signals.emit('speed_updated', speed_str)
            
            # 更新记录
            self.last_bytes = total_bytes
            self.last_speed_update = current_time

    def calculate_md5(self, file_path):
        """计算文件MD5值"""
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def receive_files(self):
        while self.connected and self.client_socket:
            try:
                data = b""
                # 添加超时设置
                self.client_socket.settimeout(60)  # 60秒超时
                
                # 接收消息头
                while b"<<END>>" not in data:
                    try:
                        chunk = self.client_socket.recv(1024)
                        if not chunk:
                            raise ConnectionError("连接已断开")
                        data += chunk
                    except socket.timeout:
                        continue
                    except Exception as e:
                        raise ConnectionError(f"接收数据失败: {str(e)}")

                if not data:
                    break

                # 处理消息
                if b"<<END>>" in data:
                    parts = data.split(b"<<END>>", 1)
                    message = parts[0].decode('utf-8', errors='ignore')
                    remaining = parts[1] if len(parts) > 1 else b""

                    try:
                        # 尝试解析为JSON消息
                        msg_data = json.loads(message)
                        self.handle_json_message(msg_data)
                    except json.JSONDecodeError:
                        # 不是JSON消息，尝试处理为文件传输
                        self.handle_file_transfer(message, remaining)

            except ConnectionError as e:
                print(f"连接错误: {str(e)}")
                self.signals.emit('error_occurred', str(e))
                break
            except Exception as e:
                print(f"接收错误: {str(e)}")
                self.signals.emit('error_occurred', str(e))
                break

        self.disconnect_peer()

    def update_drive_list(self, combo_box):
        """更新驱动器列表"""
        if os.name == 'nt':  # Windows系统
            import win32api
            drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
            drives = [drive.rstrip('\\') for drive in drives if drive]  # 移除空值并去掉反斜杠
            combo_box.configure(values=drives)  # 设置所有驱动器为下拉选项
            
            # 不设置默认值，让用户自己选择
            combo_box.set("选择驱动器")
            
            # 如果是本地驱动器列表，立即更新文件列表显示所有驱动器
            if combo_box == self.local_drive_combo:
                self.update_local_files("")  # 传入空字符串显示所有驱动器
        else:  # Linux/Mac系统
            combo_box.configure(values=['/'])
            combo_box.set('/')
            if combo_box == self.local_drive_combo:
                self.update_local_files('/')

    def on_local_drive_changed(self, drive):
        """处理本地驱动器选择变化"""
        if drive:
            if os.name == 'nt':
                drive = drive + '\\'
            self.update_local_files(drive)

    def on_remote_drive_changed(self, drive):
        """处理远程驱动器选择变化"""
        if drive and self.connected:
            if os.name == 'nt':
                # 确保驱动器路径格式正确
                drive = drive.rstrip('\\') + '\\'
            else:
                drive = '/'
            
            print(f"切换到远程驱动器: {drive}")
            self.current_remote_directory = drive  # 更新当前远程目录
            
            # 发送请求获取该驱动器的文件列表
            request = {
                'type': 'list_request',
                'path': drive
            }
            message = json.dumps(request) + "<<END>>"
            try:
                self.client_socket.send(message.encode())
            except Exception as e:
                print(f"请求远程目录失败: {str(e)}")
                self.error_label.configure(text=f"请求远程目录失败: {str(e)}")

    def refresh_local_files(self):
        """刷新本地文件列表"""
        try:
            # 如果当前目录为空，显示驱动器列表
            if not self.current_local_directory:
                self.update_local_files("")
            else:
                # 刷新当前目录
                self.update_local_files(self.current_local_directory)
        except Exception as e:
            print(f"刷新本地文件列表失败: {str(e)}")
            self.error_label.configure(text=f"刷新本地文件列表失败: {str(e)}")
            self.after(3000, lambda: self.error_label.configure(text="")) 

    def treeview_sort_column(self, tree, col, reverse):
        """排序 Treeview 的列"""
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        
        # 自定义排序函数
        def convert_size(size_str):
            if not size_str:
                return 0
            try:
                # 提取数字和单位
                match = re.match(r"([\d.]+)([KMGT]?B)", size_str)
                if not match:
                    return 0
                    
                number = float(match.group(1))
                unit = match.group(2)
                
                # 转换到字节
                multipliers = {
                    'B': 1,
                    'KB': 1024,
                    'MB': 1024 ** 2,
                    'GB': 1024 ** 3,
                    'TB': 1024 ** 4
                }
                
                return number * multipliers.get(unit, 1)
            except:
                return 0
        
        # 根据列类型选择排序方法
        if col == "size":
            l.sort(key=lambda x: convert_size(x[0]), reverse=reverse)
        else:
            l.sort(reverse=reverse)
        
        # 重新排列项目
        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)
        
        # 切换排序方向
        tree.heading(col, command=lambda: self.treeview_sort_column(tree, col, not reverse)) 