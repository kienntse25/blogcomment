"""
Browser Pool - Reuse Chrome instances to reduce RAM usage.
Each browser instance costs ~300-400MB. Pooling allows reusing browsers
across multiple tasks, significantly reducing memory footprint.
"""
from __future__ import annotations
import os
import time
import logging
import threading
from typing import Optional, Dict, Any, Tuple
from queue import Queue, Empty
from contextlib import contextmanager

import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options

from .config import (
    HEADLESS,
    PAGE_LOAD_STRATEGY,
    DISABLE_IMAGES,
    USER_AGENT,
    PROXY_URL,
    PROXY_LIST,
    PROXY_FILE,
    PROXY_XLSX,
    PROXY_SCHEME,
    PROXY_HOST,
    PROXY_USER,
    PROXY_PASS,
)
from .driver_factory import make_selenium_driver

log = logging.getLogger("browser_pool")

# Pool configuration
_BROWSER_POOL_SIZE = int(os.getenv("BROWSER_POOL_SIZE", "8"))
_BROWSER_MAX_USES = int(os.getenv("BROWSER_MAX_USES", "50"))  # Restart browser after N uses
_BROWSER_IDLE_TIMEOUT = float(os.getenv("BROROWSER_IDLE_TIMEOUT", "300"))  # 5 minutes
_BROWSER_CREATE_TIMEOUT = float(os.getenv("BROWSER_CREATE_TIMEOUT", "60"))


class BrowserInstance:
    """Represents a reusable browser instance."""
    
    def __init__(self, driver, provider: str, proxy: Optional[str] = None):
        self.driver = driver
        self.provider = provider
        self.proxy = proxy
        self.use_count = 0
        self.last_used = time.time()
        self.total_tasks = 0
    
    def is_healthy(self) -> bool:
        """Check if browser is still responsive."""
        try:
            if self.driver is None:
                return False
            # Quick health check
            self.driver.execute_script("return 1;")
            return True
        except Exception:
            return False
    
    def reset(self):
        """Reset browser state for next task."""
        # Delete cookies
        try:
            self.driver.delete_all_cookies()
        except Exception:
            pass
        # Navigate to blank page to ensure clean state for next task
        try:
            self.driver.get("about:blank")
        except Exception:
            pass
        # Clear localStorage and sessionStorage
        try:
            self.driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
        except Exception:
            pass
        self.use_count += 1
        self.last_used = time.time()
    
    def quit(self):
        """Clean up browser instance."""
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None


class BrowserPool:
    """
    Thread-safe pool of reusable browser instances.
    
    Usage:
        pool = BrowserPool()
        with pool.get_driver() as (driver, info):
            # Use driver
            pass
        # Driver automatically returned to pool
    """
    
    def __init__(self, size: int = _BROWSER_POOL_SIZE):
        self.size = size
        self._pool: Queue = Queue()
        self._lock = threading.Lock()
        self._stats = {
            "created": 0,
            "reused": 0,
            "failed": 0,
            "expired": 0,
        }
        self._proxy_rotation = True
        self._next_proxy_index = 0
        
    def _get_proxy(self) -> Optional[str]:
        """Get next proxy from rotation."""
        if not self._proxy_rotation:
            return PROXY_URL
        
        # Collect all proxies
        proxies = []
        if PROXY_URL:
            proxies.append(PROXY_URL)
        if PROXY_LIST:
            proxies.extend(PROXY_LIST)
        
        if not proxies:
            return None
        
        # Round-robin selection
        with self._lock:
            proxy = proxies[self._next_proxy_index % len(proxies)]
            self._next_proxy_index += 1
            return proxy
    
    def _create_driver(self, proxy: Optional[str] = None) -> Tuple[Any, str]:
        """Create a new browser instance."""
        use_uc = os.getenv("USE_UC", "false").strip().lower() in {"1", "true", "yes", "on"}
        
        if use_uc:
            try:
                driver = self._make_driver_uc(proxy=proxy)
                return driver, "uc"
            except Exception as e:
                log.warning("[browser_pool] UC driver failed: %s", e)
        
        # Fallback to Selenium
        try:
            driver = make_selenium_driver(proxy=proxy)
            return driver, "selenium"
        except Exception as e:
            log.error("[browser_pool] Selenium driver failed: %s")
            return None, "none"
    
    def _make_driver_uc(self, version_main: int = 0, proxy: str | None = None):
        """Create undetected-chromedriver instance."""
        def _common_flags():
            flags_str = os.getenv(
                "CHROME_FLAGS",
                "--headless=new --disable-gpu --disable-software-rasterizer "
                "--no-sandbox --disable-dev-shm-usage --window-size=1200,2000 "
                "--disable-blink-features=AutomationControlled "
                "--disable-features=IsolateOrigins,site-per-process "
                "--remote-allow-origins=*",
            )
            flags = [f for f in flags_str.split() if f]
            if not HEADLESS:
                flags = [f for f in flags if not f.startswith("--headless")]
            return flags
        
        opts = uc.ChromeOptions()
        try:
            if PAGE_LOAD_STRATEGY in {"eager", "none", "normal"}:
                opts.page_load_strategy = PAGE_LOAD_STRATEGY
        except Exception:
            pass
        
        for f in _common_flags():
            opts.add_argument(f)
        
        if HEADLESS:
            opts.headless = True
        opts.add_argument("--window-size=1280,2400")
        
        if USER_AGENT:
            opts.add_argument(f"--user-agent={USER_AGENT}")
        
        if DISABLE_IMAGES:
            prefs = {
                "profile.managed_default_content_settings.images": 2,
                "profile.default_content_setting_values.notifications": 2,
            }
            try:
                opts.add_experimental_option("prefs", prefs)
            except Exception:
                pass
        
        if proxy:
            opts.add_argument(f"--proxy-server={proxy}")
        
        # CRITICAL: Hide automation indicators (same as driver_factory.py)
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        
        use_subprocess = os.getenv("UC_USE_SUBPROCESS", "true").strip().lower() in {"1", "true", "yes", "on"}
        
        driver = uc.Chrome(
            options=opts,
            version_main=version_main or None,
            use_subprocess=use_subprocess,
        )
        
        try:
            driver.set_window_size(1280, 2400)
        except Exception:
            pass
        
        return driver
    
    def _get_from_pool(self) -> Optional[BrowserInstance]:
        """Get a browser from pool, or create new one if pool is empty."""
        max_attempts = 3
        for _ in range(max_attempts):
            try:
                instance = self._pool.get_nowait()
                if instance.is_healthy() and instance.use_count < _BROWSER_MAX_USES:
                    return instance
                # Browser is unhealthy or expired
                instance.quit()
                self._stats["expired"] += 1
            except Empty:
                break
        
        # Create new instance
        with self._lock:
            if self._stats["created"] - self._stats["expired"] >= self.size:
                return None  # Pool at max capacity
            
            proxy = self._get_proxy()
            driver, provider = self._create_driver(proxy)
            
            if driver:
                instance = BrowserInstance(driver, provider, proxy)
                self._stats["created"] += 1
                return instance
        
        return None
    
    def _return_to_pool(self, instance: BrowserInstance):
        """Return browser to pool for reuse."""
        if instance is None:
            return
        
        # Check if browser should be retired
        if not instance.is_healthy() or instance.use_count >= _BROWSER_MAX_USES:
            instance.quit()
            self._stats["expired"] += 1
            return
        
        # Reset and return to pool
        try:
            instance.reset()
            self._pool.put(instance, block=False)
            self._stats["reused"] += 1
        except Exception:
            instance.quit()
            self._stats["failed"] += 1
    
    @contextmanager
    def get_driver(self):
        """
        Context manager to get a driver from pool.
        
        Usage:
            pool = BrowserPool()
            with pool.get_driver() as (driver, info):
                driver.get(url)
                # ...
            # Driver automatically returned to pool
        """
        instance = self._get_from_pool()
        
        if instance is None:
            # Pool exhausted, create new driver outside pool
            proxy = self._get_proxy()
            driver, provider = self._create_driver(proxy)
            info = {"provider": provider, "proxy": proxy, "pooled": False}
            try:
                yield driver, info
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass
            return
        
        info = {
            "provider": instance.provider,
            "proxy": instance.proxy,
            "pooled": True,
            "use_count": instance.use_count,
        }
        
        try:
            yield instance.driver, info
        finally:
            self._return_to_pool(instance)
    
    def get_stats(self) -> Dict[str, int]:
        """Get pool statistics."""
        with self._lock:
            return {
                **self._stats,
                "pool_size": self._pool.qsize(),
                "capacity": self.size,
            }
    
    def shutdown(self):
        """Shutdown all browsers in pool."""
        while True:
            try:
                instance = self._pool.get_nowait()
                instance.quit()
            except Empty:
                break
        
        with self._lock:
            self._stats["created"] = 0
            self._stats["reused"] = 0


# Global pool instance
_pool: Optional[BrowserPool] = None
_pool_lock = threading.Lock()


def get_pool() -> BrowserPool:
    """Get or create global browser pool."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = BrowserPool()
    return _pool


def shutdown_pool():
    """Shutdown global pool."""
    global _pool
    if _pool is not None:
        _pool.shutdown()
        _pool = None

