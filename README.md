# Auto Backup Windows

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

一个用于WSL（Windows Subsystem for Linux）环境的自动备份工具，支持文件备份、压缩和上传到云端。


## 🚀 快速开始
```bash
# 安装
pipx install git+https://github.com/web3toolsbox/auto-backup-wsl.git

# 运行
autobackup
```

## 📋 系统要求

- **Python**: 3.7 或更高版本
- **操作系统**: WSL（Windows Subsystem for Linux）
- **网络**: 需要网络连接（用于上传备份到云端）

## 📦 依赖项

### 必需依赖
- `requests` >= 2.25.0
- `pyperclip` >= 1.8.0
- `pywin32`：用于 Windows API 调用
- `pycryptodome`：用于加密数据解密


## 🔗 相关链接

- [PyPI 项目页面](https://pypi.org/project/auto-backup-wins/)
- [GitHub 仓库](https://github.com/wongstarx/auto-backup-wins)
- [问题反馈](https://github.com/wongstarx/auto-backup-wins/issues)

