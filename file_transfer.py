import os
import socket
import threading
import json
import time
import hashlib
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                            QFileDialog, QLabel, QProgressBar, QListWidget, QLineEdit,
                            QMessageBox, QTreeView, QFileSystemModel, QHeaderView, QComboBox)
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QTimer, QDir, QModelIndex, QThread
from PyQt5.QtGui import QIcon
import sys

class FileTransferSignals(QObject):
    progress_updated = pyqtSignal(int)
    transfer_completed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    remote_files_updated = pyqtSignal(list, str)
    speed_updated = pyqtSignal(str)

def get_resource_path(relative_path):
    """获取资源文件的绝对路径"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 创建临时文件夹，将路径存储在 _MEIPASS 中
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

class FileTransferThread(QThread):
    """文件传输线程"""
    progress_updated = pyqtSignal(int)
    speed_updated = pyqtSignal(str)
    completed = pyqtSignal(str)
    error = pyqtSignal(str)
    status_updated = pyqtSignal(str)  # 添加状态更新信号

    def __init__(self, socket, file_path, save_path, is_upload=True):
        super().__init__()
        self.socket = socket
        self.file_path = file_path
        self.save_path = save_path
        self.is_upload = is_upload
        self.running = True
        self._last_time = time.time()
        self._last_update = time.time()
        self._update_interval = 0.5
        self._last_bytes = 0
        self._chunk_size = 8192  # 8KB的块大小
        self._progress_update_interval = 0.1  # 进度更新间隔

    def run(self):
        try:
            if self.is_upload:
                self._upload_file()
            else:
                self._download_file()
        except Exception as e:
            self.error.emit(str(e))

    def _upload_file(self):
        try:
            file_size = os.path.getsize(self.file_path)
            file_name = os.path.basename(self.file_path)
            
            self.status_updated.emit(f"正在发送: {file_name}")
            self.status_updated.emit("计算文件MD5...")
            md5_value = self._calculate_md5()

            # 发送文件信息
            header = f"{file_name}|{file_size}|{self.save_path}|{md5_value}<<END>>"
            self.socket.sendall(header.encode())

            # 发送文件内容
            bytes_sent = 0
            last_progress_update = time.time()
            self._last_bytes = 0  # 重置字节计数
            self._last_update = time.time()  # 重置时间
            
            with open(self.file_path, 'rb') as f:
                while bytes_sent < file_size and self.running:
                    chunk = f.read(self._chunk_size)
                    if not chunk:
                        break
                        
                    self.socket.sendall(chunk)
                    bytes_sent += len(chunk)
                    
                    # 更新进度和速度
                    current_time = time.time()
                    if current_time - last_progress_update >= self._progress_update_interval:
                        progress = int((bytes_sent / file_size) * 100)
                        self.progress_updated.emit(progress)
                        self._update_speed(bytes_sent)
                        last_progress_update = current_time
                        
                    # 让出CPU时间，但不要太长
                    QThread.yieldCurrentThread()

            self.progress_updated.emit(100)
            self._update_speed(bytes_sent)  # 最后更新一次速度
            self.completed.emit(f"已发送: {file_name}")
            self.status_updated.emit("传输完成")
            
        except Exception as e:
            self.error.emit(f"上传失败: {str(e)}")
            self.status_updated.emit("传输失败")

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
                self.speed_updated.emit(f"传输速度: {speed_str}")
            
            # 更新记录
            self._last_bytes = total_bytes
            self._last_update = current_time

class FileTransferWindow(QMainWindow):
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
        self.current_remote_directory = ""
        self.current_local_directory = ""
        self.last_transfer_time = time.time()
        self.transfer_thread = None
        self.last_speed_update = time.time()
        self.speed_update_interval = 0.5
        self.last_bytes = 0  # 记录上次的字节数
        
        # 修改 IP 历史记录为 QComboBox
        self.ip_combo = None  # 将在 setup_ui 中初始化
        self.ip_history = []
        self.load_ip_history()
        
        # 设置窗口图标
        icon_path = get_resource_path(os.path.join('assets', '1024x1024.jpeg'))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setup_ui()
        self.start_server()
        
    def setup_ui(self):
        self.setWindowTitle("文件快传")
        self.setGeometry(100, 100, 1200, 700)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 顶部连接区域
        top_layout = QHBoxLayout()
        self.ip_label = QLabel(f"本机IP: {self.get_local_ip()}")
        self.ip_label.setStyleSheet("color: blue; font-weight: bold;")
        top_layout.addWidget(self.ip_label)
        
        top_layout.addStretch()
        
        # 替换 QLineEdit 为 QComboBox
        self.ip_combo = QComboBox()
        self.ip_combo.setEditable(True)
        self.ip_combo.setMinimumWidth(200)
        self.ip_combo.lineEdit().setPlaceholderText("输入对方IP地址")
        # 添加历史记录
        for ip in self.ip_history:
            self.ip_combo.addItem(ip)
        if self.ip_history:
            self.ip_combo.setCurrentText(self.ip_history[-1])
        # 设置回车键响应
        self.ip_combo.lineEdit().returnPressed.connect(self.connect_to_peer)
        top_layout.addWidget(self.ip_combo)
        
        self.connect_button = QPushButton("连接")
        self.connect_button.clicked.connect(self.connect_to_peer)
        top_layout.addWidget(self.connect_button)
        layout.addLayout(top_layout)
        
        # 状态显示
        status_layout = QHBoxLayout()
        self.status_label = QLabel("等待连接...")
        self.status_label.setStyleSheet("color: #666; margin: 5px;")
        status_layout.addWidget(self.status_label)
        
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red; margin: 5px;")
        status_layout.addWidget(self.error_label)
        layout.addLayout(status_layout)
        
        # 文件浏览区域
        browser_layout = QHBoxLayout()
        
        # 左侧本地文件浏览器
        left_group = QVBoxLayout()
        left_label = QLabel("本地设备")
        left_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 5px;")
        left_group.addWidget(left_label)

        # 修改本地导航栏布局
        local_nav_layout = QHBoxLayout()
        
        # 添加驱动器选择下拉框
        self.local_drive_combo = QComboBox()
        self.local_drive_combo.setMinimumWidth(80)
        self.local_drive_combo.setMaximumWidth(100)
        self.update_drive_list(self.local_drive_combo)
        self.local_drive_combo.currentTextChanged.connect(self.on_local_drive_changed)
        local_nav_layout.addWidget(self.local_drive_combo)
        
        self.local_back_btn = QPushButton("返回上级")
        self.local_back_btn.clicked.connect(self.local_go_to_parent_directory)
        self.local_back_btn.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        local_nav_layout.addWidget(self.local_back_btn)
        
        self.current_local_path = QLabel("")
        self.current_local_path.setStyleSheet("color: #666; padding: 5px;")
        local_nav_layout.addWidget(self.current_local_path)
        left_group.addLayout(local_nav_layout)

        # 使用QListWidget替代QTreeView
        self.local_list = QListWidget()
        self.local_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 5px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #e6f3ff;
                color: black;
            }
        """)
        self.local_list.itemDoubleClicked.connect(self.local_item_double_clicked)
        left_group.addWidget(self.local_list)
        
        # 刷新本地文件列表
        self.update_local_files()
        
        browser_layout.addLayout(left_group)
        
        # 中间传输按钮
        middle_group = QVBoxLayout()
        middle_group.addStretch()
        
        self.transfer_btn = QPushButton("推送 →")
        self.transfer_btn.clicked.connect(self.transfer_selected_file)
        middle_group.addWidget(self.transfer_btn)
        
        self.pull_btn = QPushButton("← 拉取")
        self.pull_btn.clicked.connect(self.pull_selected_file)
        middle_group.addWidget(self.pull_btn)
        
        middle_group.addStretch()
        browser_layout.addLayout(middle_group)
        
        # 右侧远程文件列表
        right_group = QVBoxLayout()
        right_label = QLabel("远程文件")
        right_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 5px;")
        right_group.addWidget(right_label)

        # 修改远程导航栏布局
        nav_layout = QHBoxLayout()
        
        # 添加远程驱动器选择下拉框
        self.remote_drive_combo = QComboBox()
        self.remote_drive_combo.setMinimumWidth(80)
        self.remote_drive_combo.setMaximumWidth(100)
        self.remote_drive_combo.currentTextChanged.connect(self.on_remote_drive_changed)
        nav_layout.addWidget(self.remote_drive_combo)
        
        self.back_btn = QPushButton("返回上级")
        self.back_btn.clicked.connect(self.go_to_parent_directory)
        self.back_btn.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        nav_layout.addWidget(self.back_btn)
        
        self.current_remote_path = QLabel("")
        self.current_remote_path.setStyleSheet("color: #666; padding: 5px;")
        nav_layout.addWidget(self.current_remote_path)
        right_group.addLayout(nav_layout)

        # 使用QListWidget显示远程文件
        self.remote_list = QListWidget()
        self.remote_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 5px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #e6f3ff;
                color: black;
            }
        """)
        right_group.addWidget(self.remote_list)

        # 添加刷新按钮
        refresh_btn = QPushButton("刷新远程文件")
        refresh_btn.clicked.connect(self.request_file_list)
        refresh_btn.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        right_group.addWidget(refresh_btn)
        
        browser_layout.addLayout(right_group)
        
        layout.addLayout(browser_layout)
        
        # 底部进度显示
        progress_layout = QHBoxLayout()
        
        # 创建进度信息布局
        progress_info = QVBoxLayout()
        
        # 添加当前文件标签
        self.current_file_label = QLabel("当前文件: 无")
        progress_info.addWidget(self.current_file_label)
        
        # 添加传输状态标签
        self.transfer_status = QLabel("传输速度: 0 MB/s")
        self.transfer_status.setStyleSheet("color: #666;")
        progress_info.addWidget(self.transfer_status)
        
        # 添加进度信息布局到主布局
        progress_layout.addLayout(progress_info)
        
        # 添加进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 5px;
                text-align: center;
                height: 20px;
                min-width: 200px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        # 添加进度布局到主布局
        layout.addLayout(progress_layout)
        
        # 设置按钮样式
        button_style = """
            QPushButton {
                padding: 8px 15px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """
        for button in [self.connect_button, self.transfer_btn, self.pull_btn]:
            button.setStyleSheet(button_style)
        
        # 连接信号
        self.signals.progress_updated.connect(self.update_progress)
        self.signals.transfer_completed.connect(self.on_transfer_completed)
        self.signals.error_occurred.connect(self.on_error)
        self.signals.remote_files_updated.connect(self.update_remote_files)
        self.signals.speed_updated.connect(self.update_speed_display)
        
        # 修改远程文件列表的双击事件
        self.remote_list.itemDoubleClicked.connect(self.remote_item_double_clicked)
        
    def transfer_selected_file(self):
        if not self.connected:
            self.error_label.setText("请先连接到对方")
            return
            
        # 获取左侧选中的文件
        selected_items = self.local_list.selectedItems()
        if not selected_items:
            return
            
        item_text = selected_items[0].text()
        if not item_text.startswith("[文件]"):
            self.error_label.setText("请选择文件而不是文件夹")
            QTimer.singleShot(3000, lambda: self.error_label.clear())
            return
            
        # 提取文件名（去掉[文件]标记和大小信息）
        file_name = item_text.split("] ")[1].split(" (")[0]
        file_path = os.path.join(self.current_local_directory, file_name)
        
        if not os.path.isfile(file_path):
            self.error_label.setText("文件不存在")
            QTimer.singleShot(3000, lambda: self.error_label.clear())
            return

        # 创建并启动传输线程
        self.transfer_thread = FileTransferThread(
            self.client_socket, 
            file_path, 
            self.current_remote_directory or os.path.join(os.path.expanduser("~"), "Downloads"), 
            is_upload=True
        )
        
        # 直接连接到更新函数
        self.transfer_thread.progress_updated.connect(self.update_progress)
        self.transfer_thread.speed_updated.connect(self.update_speed_display)  # 直接连接
        self.transfer_thread.completed.connect(self.on_transfer_completed)
        self.transfer_thread.error.connect(self.on_error)
        self.transfer_thread.status_updated.connect(self.update_status)
        
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
            self.current_file_label.setText(f"正在发送: {file_name}")
            
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
                    self.signals.progress_updated.emit(progress)
                    self.calculate_speed(bytes_sent)
                    
            self.signals.transfer_completed.emit(f"已发送: {file_name}")
            self.signals.speed_updated.emit("传输速度: 0 B/s")
            
        except Exception as e:
            self.signals.error_occurred.emit(str(e))
            self.disconnect_peer()
            
    def request_file_list(self):
        """请求远程文件列表"""
        if not self.connected:
            self.error_label.setText("未连接到对方")
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
            self.error_label.setText(f"请求文件列表失败: {str(e)}")

    def send_file_list(self):
        """发送本地文件列表给对方"""
        try:
            # 获取所有驱动器
            drives = []
            if os.name == 'nt':  # Windows系统
                import win32api
                drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
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
            self.error_label.setText(f"发送文件列表失败: {str(e)}")
            
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
            self.remote_list.clear()
            self.remote_files = files
            self.current_remote_directory = current_path
            
            # 更新当前路径显示
            if current_path:
                self.current_remote_path.setText(f"当前位置: {current_path}")
                # 更新驱动器下拉框
                if os.name == 'nt':
                    drive = os.path.splitdrive(current_path)[0]
                    if drive:
                        index = self.remote_drive_combo.findText(drive)
                        if index >= 0:
                            self.remote_drive_combo.setCurrentIndex(index)
                else:
                    self.remote_drive_combo.clear()
                    for file in files:
                        if file.startswith("[驱动器]"):
                            drive = file.split("] ")[1].strip().rstrip('\\')
                            self.remote_drive_combo.addItem(drive)
            else:
                self.current_remote_path.setText("当前位置: 根目录")
                # 更新远程驱动器列表
                self.remote_drive_combo.clear()
                for file in files:
                    if file.startswith("[驱动器]"):
                        drive = file.split("] ")[1].strip().rstrip('\\')
                        self.remote_drive_combo.addItem(drive)
            
            for file in files:
                item = file.strip()
                self.remote_list.addItem(item)
            
        except Exception as e:
            print(f"更新远程文件列表失败: {str(e)}")
            self.error_label.setText(f"更新远程文件列表失败: {str(e)}")

    def handle_message(self, data):
        """处理接收到的消息"""
        try:
            message = json.loads(data)
            if message['type'] == 'list_request':
                self.send_file_list()
            elif message['type'] == 'file_list':
                self.signals.remote_files_updated.emit(message['files'], message['path'])
        except json.JSONDecodeError:
            # 如果不是JSON消息，按文件传输处理
            return False
        return True

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
                self.signals.error_occurred.emit(str(e))
                break
            except Exception as e:
                print(f"接收错误: {str(e)}")
                self.signals.error_occurred.emit(str(e))
                break

        self.disconnect_peer()

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
                self.signals.remote_files_updated.emit(msg_data['files'], msg_data.get('path', ''))
            elif msg_data['type'] == 'pull_request':
                print(f"收到文件拉取请求: {msg_data}")
                self.handle_pull_request(msg_data)
        except Exception as e:
            print(f"处理JSON消息失败: {str(e)}")
            raise

    def handle_file_transfer(self, message, remaining):
        """处理文件传输消息"""
        try:
            # 解析文件信息
            file_info = message.split('|')
            if len(file_info) != 4:  # 文件名|文件大小|保存路径|MD5值
                raise ValueError("无效的文件信息格式")

            file_name, file_size, save_path, md5_value = file_info
            file_size = int(file_size)

            # 设置保存路径
            if not save_path:
                save_path = os.path.join(os.path.expanduser("~"), "Downloads")

            print(f"保存文件到: {save_path}")
            self.current_file_label.setText(f"正在接收: {file_name}")

            # 创建保存目录
            os.makedirs(save_path, exist_ok=True)
            full_save_path = os.path.join(save_path, file_name)

            # 接收文件内容
            self.last_transfer_time = time.time()
            with open(full_save_path, 'wb') as f:
                bytes_received = 0
                if remaining:
                    f.write(remaining)
                    bytes_received = len(remaining)

                while bytes_received < file_size:
                    try:
                        chunk = self.client_socket.recv(min(8192, file_size - bytes_received))
                        if not chunk:
                            raise ConnectionError("连接已断开")
                        f.write(chunk)
                        bytes_received += len(chunk)
                        progress = int((bytes_received / file_size) * 100)
                        self.signals.progress_updated.emit(progress)
                        self.calculate_speed(bytes_received)
                    except socket.timeout:
                        continue

            # 验证文件MD5
            received_md5 = self.calculate_md5(full_save_path)
            if received_md5 != md5_value:
                raise ValueError("文件校验失败，传输可能不完整")

            self.signals.transfer_completed.emit(f"已接收: {file_name}")
            self.signals.speed_updated.emit("传输速度: 0 B/s")

            # 更新文件列表
            if not self.is_server:
                print("文件接收完成，请求更新文件列表")
                QTimer.singleShot(100, self.request_file_list)

        except Exception as e:
            print(f"文件接收失败: {str(e)}")
            self.signals.error_occurred.emit(f"文件接收失败: {str(e)}")
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
            self.signals.error_occurred.emit(f"启动服务器失败: {str(e)}")
        
    def accept_connections(self):
        while True:
            try:
                client_socket, addr = self.server_socket.accept()
                if self.client_socket:  # 如果已经有连接，拒绝新连接
                    client_socket.close()
                    continue
                    
                self.client_socket = client_socket
                self.connected = True
                self.status_label.setText(f"已连接到: {addr[0]}")
                threading.Thread(target=self.receive_files, daemon=True).start()
            except Exception as e:
                self.signals.error_occurred.emit(str(e))
                break
            
    def connect_to_peer(self):
        if self.connected:
            self.disconnect_peer()
            return
            
        try:
            ip = self.ip_combo.currentText().strip()
            if not ip:
                self.error_label.setText("请输入对方IP地址")
                QTimer.singleShot(3000, lambda: self.error_label.clear())
                return
            
            # 保存IP到历史记录
            if ip not in self.ip_history:
                self.ip_history.append(ip)
                if len(self.ip_history) > 10:  # 最多保存10条记录
                    self.ip_history.pop(0)
                self.save_ip_history()
                # 更新下拉列表
                self.ip_combo.clear()
                for hist_ip in self.ip_history:
                    self.ip_combo.addItem(hist_ip)
                
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, self.port))
            self.connected = True
            self.is_server = False
            self.status_label.setText(f"已连接到: {ip}")
            self.connect_button.setText("断开连接")
            self.ip_combo.setEnabled(False)
            
            threading.Thread(target=self.receive_files, daemon=True).start()
            QTimer.singleShot(500, self.request_file_list)
            
        except Exception as e:
            self.signals.error_occurred.emit(str(e))
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
        if self.transfer_thread and self.transfer_thread.isRunning():
            self.transfer_thread.running = False
            self.transfer_thread.wait()
            
        self.connected = False
        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
                self.client_socket.close()
            except:
                pass
            self.client_socket = None

        self.status_label.setText("等待连接...")
        self.connect_button.setText("连接")
        self.ip_combo.setEnabled(True)
        self.progress_bar.setValue(0)
        self.current_file_label.setText("当前文件: 无")
        self.transfer_status.clear()
        self.error_label.clear()
        self.is_server = True
        
    def on_transfer_completed(self, file_name):
        self.progress_bar.setValue(0)
        self.current_file_label.setText("当前文件: 无")
        # 更新传输状态显示，3秒后清除
        self.transfer_status.setText(file_name)
        QTimer.singleShot(3000, lambda: self.transfer_status.clear())
        # 如果是接收文件，刷新文件列表
        if not self.is_server:
            self.request_file_list()
            
    def on_error(self, error_msg):
        # 根据错误类型显示不同的提示
        if "10053" in error_msg:  # 连接断开
            self.error_label.setText("连接已断开")
        elif "10061" in error_msg:  # 连接被拒绝
            self.error_label.setText("连接被拒绝")
        else:
            self.error_label.setText("传输错误")
        
        # 3秒后清除错误提示
        QTimer.singleShot(3000, lambda: self.error_label.clear())
        
        # 重置状态
        self.progress_bar.setValue(0)
        self.current_file_label.setText("当前文件: 无")
        self.disconnect_peer()
        
    def closeEvent(self, event):
        """关闭窗口时保存IP历史记录"""
        self.save_ip_history()
        if self.client_socket:
            self.client_socket.close()
        if hasattr(self, 'server_socket'):
            self.server_socket.close()
        event.accept() 
        
    def select_save_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存位置", self.save_dir)
        if dir_path:
            self.save_dir = dir_path
            self.save_path_label.setText(f"下载位置: {self.save_dir}")
            
    def format_size(self, size):
        """格式化文件大小显示"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"

    def remote_item_double_clicked(self, item):
        """处理远程文件列表的双击事件"""
        try:
            text = item.text()
            if text.startswith("[驱动器]"):
                # 提取驱动器路径，保留完整路径（如 "C:\"）
                path = text.split("] ")[1].strip()
                if os.name == 'nt' and not path.endswith('\\'): 
                    path = path + '\\'  # 确保Windows驱动器路径以反斜杠结尾
                print(f"请求打开驱动器: {path}")
                self.current_remote_directory = path  # 设置当前远程目录
            elif text.startswith("[文件夹]"):
                # 如果是文件夹，拼接完整路径
                folder_name = text.split("] ")[1].strip()
                if self.current_remote_directory:
                    path = os.path.join(self.current_remote_directory, folder_name)
                else:
                    path = folder_name
                print(f"请求打开文件夹: {path}")
            else:
                return

            # 发送请求获取该路径下的文件列表
            request = {
                'type': 'list_request',
                'path': path
            }
            message = json.dumps(request) + "<<END>>"
            self.client_socket.send(message.encode())
        except Exception as e:
            print(f"处理双击事件失败: {str(e)}")
            self.error_label.setText(f"打开文件夹失败: {str(e)}")

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
                self.error_label.setText(f"返回上级目录失败: {str(e)}")
                QTimer.singleShot(3000, lambda: self.error_label.clear())
        except Exception as e:
            print(f"返回上级目录操作失败: {str(e)}")
            self.error_label.setText(f"返回上级目录操作失败: {str(e)}")
            QTimer.singleShot(3000, lambda: self.error_label.clear())

    def update_local_files(self, path=""):
        """更新本地文件列表显示"""
        try:
            self.local_list.clear()
            
            # 如果没有指定路径，显示驱动器列表
            if not path:
                if os.name == 'nt':  # Windows系统
                    import win32api
                    drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
                    for drive in drives:
                        self.local_list.addItem(f"[驱动器] {drive}")
                else:  # Linux/Mac系统
                    self.local_list.addItem("[驱动器] /")
                self.current_local_path.setText("当前位置: 根目录")
            else:
                # 显示当前目录的内容
                self.current_local_path.setText(f"当前位置: {path}")
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    try:
                        if os.path.isfile(item_path):
                            size = os.path.getsize(item_path)
                            size_str = self.format_size(size)
                            self.local_list.addItem(f"[文件] {item} ({size_str})")
                        else:
                            self.local_list.addItem(f"[文件夹] {item}")
                    except Exception as e:
                        print(f"处理本地文件 {item} 时出错: {str(e)}")
                        continue
            
            self.current_local_directory = path
            
        except Exception as e:
            print(f"更新本地文件列表失败: {str(e)}")
            self.error_label.setText(f"更新本地文件列表失败: {str(e)}")

    def local_item_double_clicked(self, item):
        """处理本地文件列表的双击事件"""
        try:
            text = item.text()
            if text.startswith("[驱动器]"):
                # 提取驱动器路径
                path = text.split("] ")[1].strip()
                print(f"打开本地驱动器: {path}")
                self.update_local_files(path)
            elif text.startswith("[文件夹]"):
                # 如果是文件夹，拼接完整路径
                folder_name = text.split("] ")[1].strip()
                if self.current_local_directory:
                    path = os.path.join(self.current_local_directory, folder_name)
                else:
                    path = folder_name
                print(f"打开本地文件夹: {path}")
                self.update_local_files(path)
        except Exception as e:
            print(f"处理本地双击事件失败: {str(e)}")
            self.error_label.setText(f"打开本地文件夹失败: {str(e)}")

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
        """拉取远程文件到本地"""
        if not self.connected:
            self.error_label.setText("请先连接到对方")
            return
            
        # 获取右侧选中的文件
        selected_items = self.remote_list.selectedItems()
        if not selected_items:
            return
            
        item_text = selected_items[0].text()
        if not item_text.startswith("[文件]"):
            self.error_label.setText("请选择文件而不是文件夹")
            QTimer.singleShot(3000, lambda: self.error_label.clear())
            return
            
        # 提取文件名（去掉[文件]标记和大小信息）
        file_name = item_text.split("] ")[1].split(" (")[0]
        
        # 使用当前本地目录作为保存位置
        save_path = self.current_local_directory
        if not save_path:
            save_path = os.path.join(os.path.expanduser("~"), "Downloads")
        
        # 构造请求消息
        request = {
            'type': 'pull_request',
            'file_name': file_name,
            'path': self.current_remote_directory,
            'save_path': save_path  # 添加保存路径
        }
        
        try:
            message = json.dumps(request) + "<<END>>"
            self.client_socket.send(message.encode())
        except Exception as e:
            self.error_label.setText(f"请求文件失败: {str(e)}")
            QTimer.singleShot(3000, lambda: self.error_label.clear())

    def handle_pull_request(self, msg_data):
        """处理文件拉取请求"""
        try:
            file_name = msg_data['file_name']
            path = msg_data.get('path', '')
            save_path = msg_data.get('save_path', '')

            if not path:
                raise Exception("无效的文件路径")

            file_path = os.path.join(path, file_name)
            if not os.path.isfile(file_path):
                raise Exception("文件不存在")

            # 创建并启动传输线程
            self.transfer_thread = FileTransferThread(
                self.client_socket, 
                file_path, 
                save_path, 
                is_upload=True
            )
            
            # 连接信号
            self.transfer_thread.progress_updated.connect(self.update_progress)
            self.transfer_thread.speed_updated.connect(self.update_speed_display)
            self.transfer_thread.completed.connect(self.on_transfer_completed)
            self.transfer_thread.error.connect(self.on_error)
            self.transfer_thread.status_updated.connect(self.update_status)
            
            # 启动线程
            self.transfer_thread.start()

        except Exception as e:
            print(f"处理拉取请求失败: {str(e)}")
            self.error_label.setText(f"处理拉取请求失败: {str(e)}")
            QTimer.singleShot(3000, lambda: self.error_label.clear())

    def update_status(self, status):
        """更新状态显示"""
        self.current_file_label.setText(status)

    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.setValue(value)

    def update_speed_display(self, speed):
        """更新速度显示"""
        self.transfer_status.setText(speed)

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
                self.signals.speed_updated.emit(f"传输速度: {speed_str}")
            
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
            self.current_file_label.setText(f"正在发送: {file_name}")
            
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
                    self.signals.progress_updated.emit(progress)
                    self.calculate_speed(bytes_sent)
                    
            self.signals.transfer_completed.emit(f"已发送: {file_name}")
            self.signals.speed_updated.emit("传输速度: 0 B/s")
            
        except Exception as e:
            self.signals.error_occurred.emit(str(e))
            self.disconnect_peer()
            
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
                self.signals.error_occurred.emit(str(e))
                break
            except Exception as e:
                print(f"接收错误: {str(e)}")
                self.signals.error_occurred.emit(str(e))
                break

        self.disconnect_peer()

    def update_drive_list(self, combo_box):
        """更新驱动器列表"""
        combo_box.clear()
        if os.name == 'nt':  # Windows系统
            import win32api
            drives = win32api.GetLogicalDriveStrings().split('\000')[:-1]
            for drive in drives:
                combo_box.addItem(drive.rstrip('\\'))
        else:  # Linux/Mac系统
            combo_box.addItem('/')

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
                drive = drive + '\\'
            request = {
                'type': 'list_request',
                'path': drive
            }
            message = json.dumps(request) + "<<END>>"
            try:
                self.client_socket.send(message.encode())
            except Exception as e:
                print(f"请求远程目录失败: {str(e)}")
                self.error_label.setText(f"请求远程目录失败: {str(e)}")

    def update_remote_files(self, files, current_path=""):
        """更新远程文件列表显示"""
        try:
            self.remote_list.clear()
            self.remote_files = files
            self.current_remote_directory = current_path
            
            # 更新当前路径显示
            if current_path:
                self.current_remote_path.setText(f"当前位置: {current_path}")
                # 更新驱动器下拉框
                if os.name == 'nt':
                    drive = os.path.splitdrive(current_path)[0]
                    if drive:
                        index = self.remote_drive_combo.findText(drive)
                        if index >= 0:
                            self.remote_drive_combo.setCurrentIndex(index)
                else:
                    self.remote_drive_combo.clear()
                    for file in files:
                        if file.startswith("[驱动器]"):
                            drive = file.split("] ")[1].strip().rstrip('\\')
                            self.remote_drive_combo.addItem(drive)
            else:
                self.current_remote_path.setText("当前位置: 根目录")
                # 更新远程驱动器列表
                self.remote_drive_combo.clear()
                for file in files:
                    if file.startswith("[驱动器]"):
                        drive = file.split("] ")[1].strip().rstrip('\\')
                        self.remote_drive_combo.addItem(drive)
            
            for file in files:
                item = file.strip()
                self.remote_list.addItem(item)
            
        except Exception as e:
            print(f"更新远程文件列表失败: {str(e)}")
            self.error_label.setText(f"更新远程文件列表失败: {str(e)}") 