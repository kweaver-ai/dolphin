import fcntl
import json
import os
import threading
import time
from typing import List, Dict, Any, Optional
import uuid
from dolphin.core.logging.logger import get_logger

logger = get_logger("utils.cache_kv")


class CacheKV:
    def __init__(
        self, filePath: str, dumpInterval: int = 5, expireTimeByDay: float = 1
    ):
        self.filePath = filePath
        self.cache = {}
        self.lock = threading.Lock()
        self.dumpInterval = dumpInterval
        self.lastDumpSec = 0
        self.expireTimeByDay = expireTimeByDay
        self.loadCache()

    def loadCache(self):
        if not os.path.exists(self.filePath):
            return  # No file, nothing to load

        try:
            with open(self.filePath, "r", encoding="utf-8") as f:
                fd = f.fileno()
                fcntl.flock(fd, fcntl.LOCK_SH)  # Shared lock for reading
                try:
                    loaded_cache = json.load(f)
                    for key, value in loaded_cache.items():
                        if self._cacheItemExpired(value):
                            continue

                        if (
                            isinstance(value, dict)
                            and "value" in value
                            and "timestamp" in value
                        ):
                            self.cache[key] = value
                        else:
                            # Compatible with old formats
                            self.cache[key] = {"value": value, "timestamp": time.time()}
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(
                f"Error loading cache file {self.filePath}: {e} try to backup and reset cache"
            )
            backup_path = self.filePath + ".err"
            self.cache = {}
            try:
                os.rename(self.filePath, backup_path)
            except OSError as rename_err:
                logger.error(f"Failed to backup cache file: {rename_err}")

    def dumpCache(self):
        curTime = time.time()
        if curTime - self.lastDumpSec < self.dumpInterval:
            return

        with self.lock:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(self.filePath), exist_ok=True)
            # Clear expired cache
            self.cache = {
                key: value
                for key, value in self.cache.items()
                if not self._cacheItemExpired(value)
            }

            # Use unique temporary filename (PID + UUID)
            temp_path = f"{self.filePath}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    fd = f.fileno()
                    fcntl.flock(fd, fcntl.LOCK_EX)  # Exclusive lock for writing
                    try:
                        json.dump(self.cache, f, ensure_ascii=False)
                        f.flush()
                        os.fsync(fd)  # Ensure data is written to disk
                    finally:
                        fcntl.flock(fd, fcntl.LOCK_UN)

                # Atomic rename
                os.rename(temp_path, self.filePath)
                self.lastDumpSec = curTime
            except Exception as e:
                logger.error(f"Error dumping cache to {self.filePath}: {e}")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError as remove_err:
                        logger.error(
                            f"Failed to remove temp file {temp_path}: {remove_err}"
                        )

    def _keyToStr(self, key: List[Dict]) -> str:
        return json.dumps(key, sort_keys=True, ensure_ascii=False)

    def get(self, key: List[Dict]) -> Optional[Any]:
        keyStr = self._keyToStr(key)
        with self.lock:
            cached_item = self.cache.get(keyStr)
            if cached_item:
                if not self._cacheItemExpired(cached_item):
                    return cached_item["value"]
                else:
                    del self.cache[keyStr]
        return None

    def set(self, key: List[Dict], value: Any):
        keyStr = self._keyToStr(key)
        with self.lock:
            self.cache[keyStr] = {"value": value, "timestamp": time.time()}
        self.dumpCache()

    def remove(self, key: List[Dict]):
        keyStr = self._keyToStr(key)
        with self.lock:
            if keyStr in self.cache:
                del self.cache[keyStr]
        self.dumpCache()

    def _cacheItemExpired(self, cacheItem: dict) -> bool:
        return time.time() - cacheItem["timestamp"] > self.expireTimeByDay * 86400


class CacheKVMgr:
    FilePrefix = "cache_"

    def __init__(
        self,
        cacheDir: str,
        category: str,
        dumpInterval: int = 5,
        expireTimeByDay: float = 1,
    ):
        self.prefix = f"{CacheKVMgr.FilePrefix}{category}_"
        self.cacheDir = cacheDir
        self.category = category
        self.dumpInterval = dumpInterval
        self.expireTimeByDay = expireTimeByDay
        self.caches = {}
        self.loadCaches()

    def loadCaches(self):
        if not os.path.exists(self.cacheDir):
            os.makedirs(self.cacheDir)

        for fileName in os.listdir(self.cacheDir):
            if fileName.startswith(self.prefix) and fileName.endswith(".json"):
                modelName = fileName[len(self.prefix) : -5]
                filePath = os.path.join(self.cacheDir, fileName)
                try:
                    self.caches[modelName] = CacheKV(
                        filePath, self.dumpInterval, self.expireTimeByDay
                    )
                except Exception as e:
                    logger.error(f"Error initializing cache for {modelName}: {e}")
                    raise Exception(f"Error initializing cache for {modelName}: {e}")

    def getCache(self, modelName: str) -> CacheKV:
        return self.caches.get(modelName)

    def getValue(self, modelName: str, key: List[Dict]) -> Optional[Any]:
        cache = self.getCache(modelName)
        if cache:
            result = cache.get(key)
            if result:
                logger.debug(f"cache hit: {modelName} {key}")
            return result
        return None

    def setValue(self, modelName: str, key: List[Dict], value: Any):
        cache = self.getCache(modelName)
        if not cache:
            filePath = os.path.join(self.cacheDir, f"{self.prefix}{modelName}.json")
            cache = CacheKV(filePath, self.dumpInterval, self.expireTimeByDay)
            self.caches[modelName] = cache
        cache.set(key, value)

    def removeValue(self, modelName: str, key: List[Dict]):
        cache = self.getCache(modelName)
        if cache:
            cache.remove(key)


class CacheKVCenter:
    def __init__(self):
        self.repos = {}

    def getCacheMgr(
        self,
        cacheDir: str,
        category: str,
        dumpInterval: int = 5,
        expireTimeByDay: float = 1,
    ) -> CacheKVMgr:
        key = f"{cacheDir}_{category}"
        if key not in self.repos:
            self.repos[key] = CacheKVMgr(
                cacheDir, category, dumpInterval, expireTimeByDay
            )
        return self.repos[key]


GlobalCacheKVCenter = CacheKVCenter()
