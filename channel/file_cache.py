"""
文件缓存管理器
用于缓存单独发送的文件消息（图片、视频、文档等），在用户提问时自动附加
"""
import time
import logging

logger = logging.getLogger(__name__)


class FileCache:
    """文件缓存管理器，按 session_id 缓存文件，TTL=5分钟"""
    
    def __init__(self, ttl=300):
        """
        Args:
            ttl: 缓存过期时间（秒），默认5分钟
        """
        self.cache = {}
        self.ttl = ttl
    
    def add(self, session_id: str, file_path: str, file_type: str = "image"):
        """
        添加文件到缓存
        
        Args:
            session_id: 会话ID
            file_path: 文件本地路径
            file_type: 文件类型（image, video, file 等）
        """
        now = time.time()
        # Reclaim whatever aged out before touching this batch. An entry is
        # only revisited when its own session comes back, so an expiry enforced
        # only inside ``get()`` never runs for a session that uploads a file and
        # then goes quiet -- its batch stays in the process-wide cache for good.
        self.cleanup_expired(now)

        entry = self.cache.get(session_id)
        if entry is None:
            entry = {
                'files': [],
                'timestamp': now
            }
            self.cache[session_id] = entry
        else:
            # The window runs from the *most recent* file, not the first one:
            # a user sending several files in a row is building one batch, and
            # the earlier files must not expire while the batch is still going.
            # Refreshing only on creation made the TTL count from the first
            # file, so a burst spanning more than the TTL lost its tail —
            # including files that arrived seconds before the question.
            entry['timestamp'] = now

        # 添加文件（去重）
        file_info = {'path': file_path, 'type': file_type}
        if file_info not in entry['files']:
            entry['files'].append(file_info)
            logger.info(f"[FileCache] Added {file_type} to cache for session {session_id}: {file_path}")
    
    def get(self, session_id: str) -> list:
        """
        获取缓存的文件列表
        
        Args:
            session_id: 会话ID
        
        Returns:
            文件信息列表 [{'path': '...', 'type': 'image'}, ...]，如果没有或已过期返回空列表
        """
        # A batch may have aged out while waiting for the question; drop it
        # here rather than hand stale attachments to the next turn.
        self.cleanup_expired()

        item = self.cache.get(session_id)
        if item is None:
            return []

        return item['files']
    
    def clear(self, session_id: str):
        """
        清除指定会话的缓存
        
        Args:
            session_id: 会话ID
        """
        if session_id in self.cache:
            logger.info(f"[FileCache] Cleared cache for session {session_id}")
            del self.cache[session_id]
    
    def cleanup_expired(self, now: float = None):
        """清理所有过期的缓存，包括那些再没人来问的批次。"""
        current_time = time.time() if now is None else now
        expired_sessions = []
        
        for session_id, item in self.cache.items():
            if current_time - item['timestamp'] > self.ttl:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self.cache[session_id]
            logger.debug(f"[FileCache] Cleaned up expired cache for session {session_id}")
        
        if expired_sessions:
            logger.info(f"[FileCache] Cleaned up {len(expired_sessions)} expired cache(s)")


# 全局单例
_file_cache = FileCache()


def get_file_cache() -> FileCache:
    """获取全局文件缓存实例"""
    return _file_cache
