# -*- coding: utf-8 -*-
"""方块桌面 · 壁纸处理

读取当前 Windows 壁纸 → 模糊压暗 → 作为窗口背景图缓存到 data/cache/wallpaper.jpg。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import time
from pathlib import Path

from . import icons
from .store import CACHE_DIR, WALLPAPER_FILE

user32 = ctypes.WinDLL("user32")
_META = CACHE_DIR / "wallpaper.meta.json"
SPI_GETDESKWALLPAPER = 0x0073


def get_wallpaper_path():
    """拿到当前壁纸文件路径（注册表优先，失败再用 SystemParametersInfo）。"""
    candidates = []
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop")
        try:
            val, _ = winreg.QueryValueEx(key, "WallPaper")
            if val:
                candidates.append(val)
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    try:
        buf = ctypes.create_unicode_buffer(520)
        if user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, len(buf), buf, 0):
            if buf.value:
                candidates.append(buf.value)
    except Exception:
        pass
    for path in candidates:
        try:
            p = Path(os.path.expandvars(path))
            if p.is_file():
                return str(p)
        except Exception:
            continue
    return None


def ensure_wallpaper(size=(1760, 1100)):
    """确保背景图是最新的，返回 (路径, 版本号)；没有壁纸时返回 (None, 0)。"""
    src = get_wallpaper_path()
    if not src:
        return None, 0
    try:
        st = os.stat(src)
        stamp = "%s|%d|%d|%dx%d" % (src, int(st.st_mtime), st.st_size, size[0], size[1])
    except Exception:
        return None, 0
    meta = {}
    try:
        with open(_META, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}
    version = int(time.time())
    if meta.get("stamp") == stamp and WALLPAPER_FILE.exists():
        return str(WALLPAPER_FILE), int(meta.get("version") or 0)
    out = icons.make_wallpaper(src, str(WALLPAPER_FILE), size=size)
    if not out:
        return None, 0
    try:
        with open(_META, "w", encoding="utf-8") as f:
            json.dump({"stamp": stamp, "version": version, "source": src}, f, ensure_ascii=False)
    except Exception:
        pass
    return str(WALLPAPER_FILE), version
