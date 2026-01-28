#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
使用示例：如何使用 auto-backup-wsl 包
"""

from auto_backup import BackupManager
from pathlib import Path

def example_backup():
    """示例：执行一次备份"""
    # 创建备份管理器
    manager = BackupManager()
    
    # 设置源目录和目标目录
    source_dir = str(Path.home())
    target_dir = Path.home() / ".dev/pypi_Backup/wsl"
    
    # 执行WSL备份
    print("开始备份WSL文件...")
    backup_dir = manager.backup_wsl_files(source_dir, str(target_dir))
    
    if backup_dir:
        print(f"备份完成，备份目录: {backup_dir}")
        
        # 压缩备份
        print("开始压缩...")
        zip_file_path = str(target_dir) + "_" + "example"
        backup_files = manager.zip_backup_folder(backup_dir, zip_file_path)
        
        if backup_files:
            print(f"压缩完成，文件: {backup_files}")
            
            # 上传备份（可选）
            print("开始上传...")
            if manager.upload_backup(backup_files):
                print("上传成功！")
            else:
                print("上传失败")
    else:
        print("备份失败")

if __name__ == "__main__":
    example_backup()

