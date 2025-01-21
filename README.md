# 文件快传

一个基于Python和CustomTkinter开发的局域网文件传输工具，支持Windows系统。

![版本](https://img.shields.io/badge/版本-1.0.0-blue.svg)
![许可证](https://img.shields.io/badge/许可证-MIT-green.svg)
![Python版本](https://img.shields.io/badge/Python-3.10+-yellow.svg)

## 功能特点

- 简洁的双窗格界面，方便文件浏览和传输
- 支持本地和远程文件夹浏览
- 实时显示传输速度和进度
- 文件MD5校验，确保传输完整性
- 支持文件推送和拉取操作
- 自动识别本机IP地址

## 系统要求

- Windows 7/8/10/11
- Python 3.10+
- 局域网环境

## 安装方法

### 方式一：直接下载
从[发布页面](https://github.com/yourusername/file-transfer/releases)下载最新版本的可执行文件。

### 方式二：从源码安装

1. 克隆仓库：
bash
git clone https://github.com/yourusername/file-transfer.git
cd file-transfer

2. 安装依赖：
bash
pip install -r requirements.txt

## 使用方法

1. 运行程序：
   - 如果使用可执行文件，直接双击运行
   - 如果使用源码：`python main.py`

2. 使用步骤：
   - 程序启动后会显示本机IP地址
   - 在对方电脑上输入本机IP地址并点击连接
   - 浏览并选择要传输的文件
   - 使用"推送"或"拉取"按钮传输文件

## 注意事项

- 确保两台电脑在同一局域网内
- 确保防火墙允许程序网络访问
- 大文件传输时请耐心等待
- 传输完成后会自动进行MD5校验

## 许可证

MIT License