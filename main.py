import sys
from PyQt5.QtWidgets import QApplication
from file_transfer import FileTransferWindow

def main():
    app = QApplication(sys.argv)
    window = FileTransferWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main() 