import sys
import customtkinter as ctk
import os
from file_transfer import FileTransferWindow

def main():
    ctk.set_appearance_mode("System")  # 跟随系统主题
    ctk.set_default_color_theme("blue")  # 设置默认颜色主题
    
    window = FileTransferWindow(port=5000)
    window.geometry("1200x700")  # 设置初始窗口大小
    window.minsize(800, 600)     # 设置最小窗口大小
    window.mainloop()

if __name__ == '__main__':
    main() 