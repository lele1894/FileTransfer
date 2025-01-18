import socket
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QPushButton,
                            QLabel, QRadioButton, QButtonGroup)
from PyQt5.QtCore import Qt

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

class StartupWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.selected_mode = 'file_transfer'
        self.is_controller = True  # 默认为发送方
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle("局域网文件快传")
        self.setGeometry(300, 300, 400, 250)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 标题
        title_label = QLabel("局域网文件快传")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #333; margin: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # IP地址显示
        self.ip_label = QLabel(f"本机IP地址: {get_local_ip()}")
        self.ip_label.setStyleSheet("font-size: 14px; font-weight: bold; color: blue;")
        self.ip_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.ip_label)
        
        # 添加说明标签
        self.tip_label = QLabel("请记住此IP地址，接收方需要输入此IP来连接")  # 默认显示发送方提示
        self.tip_label.setStyleSheet("color: red; margin: 10px;")
        self.tip_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.tip_label)
        
        layout.addWidget(QLabel(""))  # 空行
        
        # 模式选择
        mode_group = QButtonGroup(self)
        self.sender_radio = QRadioButton("作为发送方 (等待接收方连接)")
        self.receiver_radio = QRadioButton("作为接收方 (连接到发送方)")
        mode_group.addButton(self.sender_radio)
        mode_group.addButton(self.receiver_radio)
        
        # 设置单选按钮样式
        radio_style = """
            QRadioButton {
                font-size: 13px;
                padding: 5px;
            }
            QRadioButton::indicator {
                width: 15px;
                height: 15px;
            }
        """
        self.sender_radio.setStyleSheet(radio_style)
        self.receiver_radio.setStyleSheet(radio_style)
        
        # 默认选中发送方
        self.sender_radio.setChecked(True)
        
        layout.addWidget(self.sender_radio)
        layout.addWidget(self.receiver_radio)
        
        layout.addWidget(QLabel(""))  # 空行
        
        # 开始按钮
        self.start_btn = QPushButton("开始传输")
        self.start_btn.setEnabled(True)  # 默认启用开始按钮
        
        # 设置按钮样式
        button_style = """
            QPushButton {
                padding: 10px;
                font-size: 14px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                min-width: 150px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """
        self.start_btn.setStyleSheet(button_style)
        layout.addWidget(self.start_btn, alignment=Qt.AlignCenter)
        
        # 连接信号
        self.sender_radio.toggled.connect(self.on_sender_selected)
        self.receiver_radio.toggled.connect(self.on_receiver_selected)
        self.start_btn.clicked.connect(self.on_start_clicked)
        
    def on_sender_selected(self, checked):
        if checked:
            self.is_controller = True
            self.tip_label.setText("请记住此IP地址，接收方需要输入此IP来连接")
            
    def on_receiver_selected(self, checked):
        if checked:
            self.is_controller = False
            self.tip_label.setText("请输入发送方的IP地址进行连接")
        
    def on_start_clicked(self):
        self.close() 