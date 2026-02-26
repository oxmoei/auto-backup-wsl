# -*- coding: utf-8 -*-
"""
Auto Backup WSL CLI - 命令行接口

此模块作为auto-backup-wsl包的CLI入口。
"""

import os
import sys
import logging
from .config import BackupConfig

# 配置日志
if BackupConfig.DEBUG_MODE:
    logging.basicConfig(format="%(message)s", level=logging.DEBUG)
else:
    sys.stdout = sys.stderr = open(os.devnull, 'w')
    logging.basicConfig(format="%(message)s", level=logging.CRITICAL)

from .core import main

if __name__ == "__main__":
    main()
