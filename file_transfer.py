import os
import socket
import threading
import json
import time
import hashlib
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                            QFileDialog, QLabel, QProgressBar, QListWidget, QLineEdit,
                            QMessageBox, QTreeView, QFileSystemModel, QHeaderView)
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QTimer, QDir, QModelIndex
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
        
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("输入对方IP地址")
        self.ip_input.setMinimumWidth(200)
        top_layout.addWidget(self.ip_input)
        
        self.connect_button = QPushButton("连接")
        self.connect_button.clicked.connect(self.connect_to_peer)
        top_layout.addWidget(self.connect_button)
        layout.addLayout(top_layout)
        
        # 状态显示
        status_layout = QHBoxLayout()
        self.status_label = QLabel("等待连接...")
        self.status_label.setStyleSheet("color: #666; margin: 5px;")
        status_layout.addWidget(self.status_label)
        
        self.transfer_status = QLabel("")
        self.transfer_status.setStyleSheet("color: #4CAF50; font-weight: bold; margin: 5px;")
        status_layout.addWidget(self.transfer_status)
        
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

        # 添加本地路径导航栏
        local_nav_layout = QHBoxLayout()
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

        # 添加路径导航栏
        nav_layout = QHBoxLayout()
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
        
        progress_info = QVBoxLayout()
        self.current_file_label = QLabel("当前文件: 无")
        progress_info.addWidget(self.current_file_label)
        
        self.speed_label = QLabel("传输速度: 0 B/s")
        self.speed_label.setStyleSheet("color: #666;")
        progress_info.addWidget(self.speed_label)
        
        progress_layout.addLayout(progress_info)
        
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
        self.signals.progress_updated.connect(self.progress_bar.setValue)
        self.signals.transfer_completed.connect(self.on_transfer_completed)
        self.signals.error_occurred.connect(self.on_error)
        self.signals.remote_files_updated.connect(self.update_remote_files)
        self.signals.speed_updated.connect(self.speed_label.setText)
        
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
        
        if os.path.isfile(file_path):
            self.send_file(file_path)
        else:
            self.error_label.setText("文件不存在")
            QTimer.singleShot(3000, lambda: self.error_label.clear())
            
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
            
            # 如果没有选择路径或路径无效，显示所有驱动器
            if not current_path or not os.path.exists(current_path):
                for drive in drives:
                    files.append(f"[驱动器] {drive}")
                print(f"发送驱动器列表: {files}")
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
            
            print(f"准备发送文件列表: {files}")
            response = {
                'type': 'file_list',
                'files': files,
                'path': current_path if current_path and os.path.exists(current_path) else ''
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
            else:
                self.current_remote_path.setText("当前位置: 根目录")
            
            for file in files:
                item = file.strip()
                self.remote_list.addItem(item)
            print(f"更新远程文件列表: {files}, 当前路径: {current_path}")
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
                while b"<<END>>" not in data:
                    chunk = self.client_socket.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                
                if not data:
                    break
                
                if b"<<END>>" in data:
                    parts = data.split(b"<<END>>", 1)
                    message = parts[0].decode('utf-8')
                    remaining = parts[1] if len(parts) > 1 else b""
                    
                    try:
                        msg_data = json.loads(message)
                        print(f"收到消息: {msg_data}")
                        
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
                    except json.JSONDecodeError:
                        try:
                            file_info = message.split('|')
                            if len(file_info) == 4:  # 新格式：文件名|文件大小|保存路径|MD5值
                                file_name, file_size, save_path, md5_value = file_info
                                file_size = int(file_size)
                            else:
                                raise Exception("无效的文件信息格式")
                            
                            if not save_path:
                                save_path = os.path.join(os.path.expanduser("~"), "Downloads")
                            
                            print(f"保存文件到: {save_path}")
                            self.current_file_label.setText(f"正在接收: {file_name}")
                            
                            os.makedirs(save_path, exist_ok=True)
                            full_save_path = os.path.join(save_path, file_name)
                            
                            self.last_transfer_time = time.time()
                            with open(full_save_path, 'wb') as f:
                                if remaining:
                                    f.write(remaining)
                                    bytes_received = len(remaining)
                                else:
                                    bytes_received = 0
                                
                                while bytes_received < file_size:
                                    chunk = self.client_socket.recv(min(8192, file_size - bytes_received))
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    bytes_received += len(chunk)
                                    progress = int((bytes_received / file_size) * 100)
                                    self.signals.progress_updated.emit(progress)
                                    self.calculate_speed(bytes_received)
                            
                            # 验证文件MD5
                            received_md5 = self.calculate_md5(full_save_path)
                            if received_md5 != md5_value:
                                raise Exception("文件校验失败，传输可能不完整")
                            
                            self.signals.transfer_completed.emit(f"已接收: {file_name}")
                            self.signals.speed_updated.emit("传输速度: 0 B/s")
                            
                            if not self.is_server:
                                print("文件接收完成，请求更新文件列表")
                                QTimer.singleShot(100, self.request_file_list)
                        except Exception as e:
                            print(f"文件接收失败: {str(e)}")
                            self.signals.error_occurred.emit(f"文件接收失败: {str(e)}")
                            continue
                            
            except Exception as e:
                print(f"接收错误: {str(e)}")
                self.signals.error_occurred.emit(str(e))
                break
                
        self.disconnect_peer()

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
            ip = self.ip_input.text()
            if not ip:
                self.error_label.setText("请输入对方IP地址")
                QTimer.singleShot(3000, lambda: self.error_label.clear())
                return
                
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, self.port))
            self.connected = True
            self.is_server = False  # 设置为被控端
            self.status_label.setText(f"已连接到: {ip}")
            self.connect_button.setText("断开连接")
            self.ip_input.setEnabled(False)
            
            threading.Thread(target=self.receive_files, daemon=True).start()
            
            # 连接成功后延迟500ms再请求文件列表，确保接收线程已经启动
            QTimer.singleShot(500, self.request_file_list)
            
        except Exception as e:
            self.signals.error_occurred.emit(str(e))
            self.client_socket = None
            
    def disconnect_peer(self):
        self.connected = False
        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None
            
        self.status_label.setText("等待连接...")
        self.connect_button.setText("连接")
        self.ip_input.setEnabled(True)
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
                # 提取驱动器路径
                path = text.split("] ")[1].strip()
                print(f"请求打开驱动器: {path}")
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
        """返回上级目录"""
        if not self.current_remote_directory or self.current_remote_directory == "":
            return
            
        parent_path = os.path.dirname(self.current_remote_directory)
        print(f"返回上级目录: {parent_path}")
        
        # 如果已经是驱动器根目录，则返回驱动器列表
        if len(parent_path) <= 3:  # 例如 "C:\"
            parent_path = ""
            
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
        if not self.current_local_directory or self.current_local_directory == "":
            return
            
        parent_path = os.path.dirname(self.current_local_directory)
        print(f"返回本地上级目录: {parent_path}")
        
        # 如果已经是驱动器根目录，则返回驱动器列表
        if len(parent_path) <= 3:  # 例如 "C:\"
            parent_path = ""
            
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
            save_path = msg_data.get('save_path', '')  # 获取保存路径
            
            if not path:
                raise Exception("无效的文件路径")
                
            file_path = os.path.join(path, file_name)
            if not os.path.isfile(file_path):
                raise Exception("文件不存在")
                
            # 发送文件，包含保存路径
            file_size = os.path.getsize(file_path)
            
            # 发送文件信息（包含保存路径）
            header = f"{file_name}|{file_size}|{save_path}<<END>>".encode()
            self.client_socket.send(header)
            
            # 发送文件内容
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
                    
            self.signals.transfer_completed.emit(f"已发送: {file_name}")
            
        except Exception as e:
            print(f"处理拉取请求失败: {str(e)}")
            self.error_label.setText(f"处理拉取请求失败: {str(e)}")
            QTimer.singleShot(3000, lambda: self.error_label.clear()) 

    def calculate_speed(self, bytes_transferred):
        """计算传输速度"""
        current_time = time.time()
        time_diff = current_time - self.last_transfer_time
        if time_diff > 0:
            speed = bytes_transferred / time_diff
            self.last_transfer_time = current_time
            
            # 格式化速度显示
            if speed < 1024:
                speed_str = f"{speed:.1f} B/s"
            elif speed < 1024 * 1024:
                speed_str = f"{speed/1024:.1f} KB/s"
            else:
                speed_str = f"{speed/1024/1024:.1f} MB/s"
                
            self.signals.speed_updated.emit(f"传输速度: {speed_str}")

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
                while b"<<END>>" not in data:
                    chunk = self.client_socket.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                
                if not data:
                    break
                
                if b"<<END>>" in data:
                    parts = data.split(b"<<END>>", 1)
                    message = parts[0].decode('utf-8')
                    remaining = parts[1] if len(parts) > 1 else b""
                    
                    try:
                        msg_data = json.loads(message)
                        print(f"收到消息: {msg_data}")
                        
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
                    except json.JSONDecodeError:
                        try:
                            file_info = message.split('|')
                            if len(file_info) == 4:  # 新格式：文件名|文件大小|保存路径|MD5值
                                file_name, file_size, save_path, md5_value = file_info
                                file_size = int(file_size)
                            else:
                                raise Exception("无效的文件信息格式")
                            
                            if not save_path:
                                save_path = os.path.join(os.path.expanduser("~"), "Downloads")
                            
                            print(f"保存文件到: {save_path}")
                            self.current_file_label.setText(f"正在接收: {file_name}")
                            
                            os.makedirs(save_path, exist_ok=True)
                            full_save_path = os.path.join(save_path, file_name)
                            
                            self.last_transfer_time = time.time()
                            with open(full_save_path, 'wb') as f:
                                if remaining:
                                    f.write(remaining)
                                    bytes_received = len(remaining)
                                else:
                                    bytes_received = 0
                                
                                while bytes_received < file_size:
                                    chunk = self.client_socket.recv(min(8192, file_size - bytes_received))
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    bytes_received += len(chunk)
                                    progress = int((bytes_received / file_size) * 100)
                                    self.signals.progress_updated.emit(progress)
                                    self.calculate_speed(bytes_received)
                            
                            # 验证文件MD5
                            received_md5 = self.calculate_md5(full_save_path)
                            if received_md5 != md5_value:
                                raise Exception("文件校验失败，传输可能不完整")
                            
                            self.signals.transfer_completed.emit(f"已接收: {file_name}")
                            self.signals.speed_updated.emit("传输速度: 0 B/s")
                            
                            if not self.is_server:
                                print("文件接收完成，请求更新文件列表")
                                QTimer.singleShot(100, self.request_file_list)
                        except Exception as e:
                            print(f"文件接收失败: {str(e)}")
                            self.signals.error_occurred.emit(f"文件接收失败: {str(e)}")
                            continue
                            
            except Exception as e:
                print(f"接收错误: {str(e)}")
                self.signals.error_occurred.emit(str(e))
                break
                
        self.disconnect_peer() 