# -*- coding: utf-8 -*-
"""方块桌面 · 数据持久化

保存三类东西：
1. 用户设置（布局、排序、启动方式等）
2. 每个应用的个性化信息（固定、隐藏、自定义名称/分类、排序、启动次数）
3. 扫描结果缓存（apps.json），让二次启动可以秒开
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # PyInstaller 便携版：exe 所在目录放数据，_MEIPASS 里放 web / assets 资源
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = BASE_DIR


def _pick_data_dir(base):
    """优先用 exe 旁边的 data/（便携）；不可写时回落到用户目录。"""
    candidates = [base / "data"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "GridDesk" / "data")
    candidates.append(Path.home() / "GridDesk" / "data")
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return cand
        except Exception:
            continue
    return candidates[0]


DATA_DIR = _pick_data_dir(BASE_DIR) if FROZEN else BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
ICON_DIR = CACHE_DIR / "icons"
COVER_DIR = CACHE_DIR / "covers"
WALLPAPER_FILE = CACHE_DIR / "wallpaper.jpg"
STATE_FILE = DATA_DIR / "state.json"
APPS_CACHE = DATA_DIR / "apps.json"
LOG_FILE = DATA_DIR / "server.log"

DEFAULT_SETTINGS = {
    "layout": "collage",        # square 方格 | collage 拼贴 | compact 紧凑
    "columns": 0,              # 0 = 自动按窗口宽度计算
    "background": "wallpaper",  # wallpaper 壁纸模糊 | graphite 纯深色
    "showChips": True,         # 磁贴左上角分类标签
    "showSubtitle": True,      # 磁贴底部副标题（使用时间）
    "launchMode": "single",    # single 单击启动 | double 双击启动
    "sort": "custom",          # custom | name | recent | frequent
    "fullscreen": False,       # 启动时全屏
    "autostart": False,        # 开机自启
    "windowMode": "maximized",  # maximized 最大化窗口 | windowed 1560×980 窗口
}


def ensure_dirs():
    for d in (DATA_DIR, CACHE_DIR, ICON_DIR, COVER_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _atomic_write_json(path, payload):
    ensure_dirs()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Store:
    """线程安全的设置 / 应用元数据存储。"""

    def __init__(self):
        ensure_dirs()
        self._lock = threading.RLock()
        raw = _read_json(STATE_FILE, {})
        if not isinstance(raw, dict):
            raw = {}
        settings = dict(DEFAULT_SETTINGS)
        settings.update({k: v for k, v in (raw.get("settings") or {}).items() if k in DEFAULT_SETTINGS})
        self.settings = settings
        self.apps = raw.get("apps") if isinstance(raw.get("apps"), dict) else {}
        self.order = raw.get("order") if isinstance(raw.get("order"), list) else []
        self.updated = raw.get("updated", 0)
        self._dirty = False

    # ---------------- 应用元数据 ----------------
    def meta(self, app_id):
        """只读取，不写入（避免轮询请求把空记录写进 state.json）。"""
        with self._lock:
            m = self.apps.get(app_id)
            return m if isinstance(m, dict) else {}

    def update_app(self, app_id, patch):
        with self._lock:
            m = self.apps.get(app_id)
            if not isinstance(m, dict):
                m = {}
                self.apps[app_id] = m
            for k, v in patch.items():
                if k in ("pinned", "hidden", "name", "category", "order", "accent", "launchCount", "lastLaunch", "iconStamp"):
                    m[k] = v
            self.save()
            return m

    # ---------------- 设置 ----------------
    SETTING_CHOICES = {
        "layout": {"square", "collage", "compact"},
        "background": {"wallpaper", "graphite"},
        "sort": {"custom", "name", "recent", "pinned"},
        "launchMode": {"single", "double"},
        "windowMode": {"maximized", "windowed"},
    }

    @classmethod
    def _clean_setting(cls, key, value):
        """校验并规整一个设置值；非法值返回 None（保持原值）。"""
        if key not in DEFAULT_SETTINGS:
            return None
        choices = cls.SETTING_CHOICES.get(key)
        if choices is not None:
            v = str(value or "").strip()
            return v if v in choices else None
        if key == "columns":
            try:
                n = int(value)
            except (TypeError, ValueError):
                return None
            return n if 0 <= n <= 16 else None
        if key in ("showChips", "showSubtitle", "fullscreen", "autostart"):
            return bool(value)
        return value

    def set_settings(self, patch):
        with self._lock:
            for k, v in (patch or {}).items():
                clean = self._clean_setting(k, v)
                if clean is not None:
                    self.settings[k] = clean
            self.save()
            return self.settings

    # ---------------- 排序 ----------------
    def set_order(self, ids):
        with self._lock:
            self.order = [str(i) for i in (ids or []) if i]
            self.save()
            return self.order

    # ---------------- 读写 ----------------
    def save(self):
        with self._lock:
            payload = {
                "version": 1,
                "settings": self.settings,
                "apps": self.apps,
                "order": self.order,
                "updated": int(time.time()),
            }
            _atomic_write_json(STATE_FILE, payload)
            self._dirty = False

    # ---------------- 扫描缓存 ----------------
    def load_apps_cache(self):
        raw = _read_json(APPS_CACHE, {})
        if not isinstance(raw, dict):
            return []
        apps = raw.get("apps")
        return apps if isinstance(apps, list) else []

    def save_apps_cache(self, apps, extra=None):
        payload = {"version": 1, "savedAt": int(time.time()), "apps": apps}
        if extra:
            payload.update(extra)
        _atomic_write_json(APPS_CACHE, payload)

    def clear_cache(self):
        removed = 0
        for d in (ICON_DIR, COVER_DIR):
            for p in d.glob("*"):
                try:
                    p.unlink()
                    removed += 1
                except Exception:
                    pass
        return removed
