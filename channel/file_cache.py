"""
文件缓存管理器
用于缓存单独发送的文件消息（图片、视频、文档等），在用户提问时自动附加
"""
import logging

from common.expired_dict import ExpiredDict

logger = logging.getLogger(__name__)


class FileCache:
    """文件缓存管理器，按 session_id 缓存文件，TTL=5分钟"""

    def __init__(self, ttl=300):
        """
        Args:
            ttl: 缓存过期时间（秒），默认5分钟
        """
        self.cache = ExpiredDict(ttl)
        self.ttl = ttl

    def add(self, session_id: str, file_path: str, file_type: str = "image"):
        """
        添加文件到缓存

        Args:
            session_id: 会话ID
            file_path: 文件本地路径
            file_type: 文件类型（image, video, file 等）
        """
        # Every add rewrites the entry, so the TTL runs from the most recent
        # file: a burst of files is one batch and must not lose its head.
        files = self.cache.get(session_id) or []
        file_info = {'path': file_path, 'type': file_type}
        if file_info not in files:
            files.append(file_info)
            logger.info(f"[FileCache] Added {file_type} to cache for session {session_id}: {file_path}")
        self.cache[session_id] = files

    def get(self, session_id: str) -> list:
        """
        获取缓存的文件列表

        Args:
            session_id: 会话ID

        Returns:
            文件信息列表 [{'path': '...', 'type': 'image'}, ...]，如果没有或已过期返回空列表
        """
        return self.cache.get(session_id) or []

    def clear(self, session_id: str):
        """
        清除指定会话的缓存

        Args:
            session_id: 会话ID
        """
        if self.cache.pop(session_id, None) is not None:
            logger.info(f"[FileCache] Cleared cache for session {session_id}")


# 全局单例
_file_cache = FileCache()


def get_file_cache() -> FileCache:
    """获取全局文件缓存实例"""
    return _file_cache
