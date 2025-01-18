import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
import os
from file_transfer import FileTransferWindow

def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序图标
    icon_path = os.path.join(os.path.dirname(__file__), 'assets', '1024x1024.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    window = FileTransferWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main() 