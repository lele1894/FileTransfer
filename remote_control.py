import socket
import threading
import json
import base64
import pyautogui
import keyboard
import mouse
from mss import mss
from PIL import Image
from io import BytesIO
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QPushButton,
                            QLabel, QLineEdit)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QPixmap, QImage

class RemoteControlWindow(QMainWindow):
    def __init__(self, is_server=True, port=5001):
        super().__init__()
        self.is_server = is_server
        self.port = port
        self.connected = False
        self.setup_ui()
        
        if is_server:
            self.start_server()
            
    def setup_ui(self):
        self.setWindowTitle("远程控制" + ("服务端" if self.is_server else "客户端"))
        self.setGeometry(500, 100, 800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        self.status_label = QLabel("等待连接..." if self.is_server else "未连接")
        layout.addWidget(self.status_label)
        
        if not self.is_server:
            self.ip_input = QLineEdit()
            self.ip_input.setPlaceholderText("输入服务器IP地址")
            layout.addWidget(self.ip_input)
            
            self.connect_button = QPushButton("连接到服务器")
            self.connect_button.clicked.connect(self.connect_to_server)
            layout.addWidget(self.connect_button)
        
        self.screen_label = QLabel()
        self.screen_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.screen_label)
        
        # 初始化屏幕捕获和更新定时器
        self.screen_timer = QTimer()
        self.screen_timer.timeout.connect(self.update_screen)
        self.screen_timer.setInterval(50)  # 20 FPS
        
    def start_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(('0.0.0.0', self.port))
        self.server_socket.listen(1)
        
        threading.Thread(target=self.accept_connections, daemon=True).start()
        
    def accept_connections(self):
        while True:
            client_socket, addr = self.server_socket.accept()
            self.status_label.setText(f"客户端已连接: {addr}")
            self.connected = True
            self.client_socket = client_socket
            threading.Thread(target=self.handle_client, args=(client_socket,), daemon=True).start()
            
    def connect_to_server(self):
        try:
            ip = self.ip_input.text() or 'localhost'
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, self.port))
            self.status_label.setText("已连接到服务器")
            self.connected = True
            self.screen_timer.start()
            threading.Thread(target=self.receive_commands, daemon=True).start()
        except Exception as e:
            self.status_label.setText(f"连接失败: {str(e)}")
            
    def update_screen(self):
        if not self.is_server and self.connected:
            with mss() as sct:
                # 获取主显示器的截图
                monitor = sct.monitors[0]  # 使用主显示器
                screenshot = sct.grab(monitor)
                
                # 转换为PIL Image
                img = Image.frombytes('RGB', (screenshot.width, screenshot.height), screenshot.rgb)
                # 调整图像大小
                img = img.resize((800, 600), Image.Resampling.LANCZOS)
                
                # 压缩和编码
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=50)
                img_data = base64.b64encode(buffer.getvalue()).decode()
                
                data = {
                    'type': 'screen',
                    'data': img_data
                }
                try:
                    self.client_socket.send(json.dumps(data).encode() + b'\n')
                except:
                    self.connected = False
                    self.screen_timer.stop()
                    
    def handle_client(self, client_socket):
        while self.connected:
            try:
                data = client_socket.recv(1024*1024).decode()
                if not data:
                    break
                    
                commands = data.split('\n')
                for cmd in commands:
                    if not cmd:
                        continue
                    try:
                        cmd_data = json.loads(cmd)
                        if cmd_data['type'] == 'screen':
                            img_data = base64.b64decode(cmd_data['data'])
                            img = Image.open(BytesIO(img_data))
                            qimg = QImage(img.tobytes(), img.width, img.height, QImage.Format.Format_RGB888)
                            pixmap = QPixmap.fromImage(qimg)
                            self.screen_label.setPixmap(pixmap)
                        elif cmd_data['type'] == 'mouse':
                            x, y = cmd_data['x'], cmd_data['y']
                            if cmd_data.get('click'):
                                pyautogui.click(x, y)
                            else:
                                pyautogui.moveTo(x, y)
                        elif cmd_data['type'] == 'keyboard':
                            key = cmd_data['key']
                            if cmd_data.get('down'):
                                keyboard.press(key)
                            else:
                                keyboard.release(key)
                    except json.JSONDecodeError:
                        continue
                        
            except Exception as e:
                print(f"Error handling client: {str(e)}")
                break
                
        self.connected = False
        client_socket.close()
        
    def receive_commands(self):
        while self.connected:
            try:
                data = self.client_socket.recv(1024*1024).decode()
                if not data:
                    break
                    
                commands = data.split('\n')
                for cmd in commands:
                    if not cmd:
                        continue
                    try:
                        cmd_data = json.loads(cmd)
                        if cmd_data['type'] == 'screen':
                            img_data = base64.b64decode(cmd_data['data'])
                            img = Image.open(BytesIO(img_data))
                            qimg = QImage(img.tobytes(), img.width, img.height, QImage.Format.Format_RGB888)
                            pixmap = QPixmap.fromImage(qimg)
                            self.screen_label.setPixmap(pixmap)
                    except json.JSONDecodeError:
                        continue
                        
            except Exception as e:
                print(f"Error receiving commands: {str(e)}")
                break
                
        self.connected = False
        self.screen_timer.stop()
        
    def mousePressEvent(self, event):
        if self.is_server and self.connected:
            pos = event.pos()
            label_pos = self.screen_label.pos()
            if self.screen_label.rect().contains(pos - label_pos):
                relative_x = (pos.x() - label_pos.x()) / self.screen_label.width()
                relative_y = (pos.y() - label_pos.y()) / self.screen_label.height()
                
                data = {
                    'type': 'mouse',
                    'x': int(relative_x * pyautogui.size().width),
                    'y': int(relative_y * pyautogui.size().height),
                    'click': True
                }
                try:
                    self.client_socket.send(json.dumps(data).encode() + b'\n')
                except:
                    self.connected = False
                    
    def keyPressEvent(self, event):
        if self.is_server and self.connected:
            key = event.text()
            if key:
                data = {
                    'type': 'keyboard',
                    'key': key,
                    'down': True
                }
                try:
                    self.client_socket.send(json.dumps(data).encode() + b'\n')
                except:
                    self.connected = False
                    
    def keyReleaseEvent(self, event):
        if self.is_server and self.connected:
            key = event.text()
            if key:
                data = {
                    'type': 'keyboard',
                    'key': key,
                    'down': False
                }
                try:
                    self.client_socket.send(json.dumps(data).encode() + b'\n')
                except:
                    self.connected = False 