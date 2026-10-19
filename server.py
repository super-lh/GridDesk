# -*- coding: utf-8 -*-
"""方块桌面 · 本地服务

职责：
- 启动时扫描应用（开始菜单 + 桌面 + UWP），后台生成 256px 图标与封面图
- 提供 index.html 与 JSON API（应用列表、启动、设置、排序、重扫…）
- 首次启动自动打开一个无浏览器界面的应用窗口（Chrome / Edge --app 模式）
- 窗口关闭后自动退出，避免后台常驻

用法：
    pythonw server.py --open      # 正常启动（静默，由启动脚本调用）
    python server.py --no-window  # 只起服务，调试用
    python server.py --scan-only  # 只扫描并打印结果
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

from core import apps_scan, icons, store, wallpaper  # noqa: E402
from core.store import (  # noqa: E402
    BASE_DIR as ROOT_DIR, BUNDLE_DIR, CACHE_DIR, COVER_DIR, DATA_DIR, ICON_DIR, LOG_FILE, Store,
)

APP_NAME = "方块桌面"
APP_CODE = "GridDesk"
VERSION = "0.1.0"
DEFAULT_PORT = 8765
WEB_DIR = BUNDLE_DIR / "web"
ASSETS_DIR = BUNDLE_DIR / "assets"
BROWSER_PROFILE = DATA_DIR / "browser-profile"

app = Flask(__name__, static_folder=None)
try:
    app.json.ensure_ascii = False
except Exception:
    pass

store_ = Store()
_lock = threading.RLock()

STATE = {
    "apps": [],
    "scan": {"running": False, "phase": "init", "done": 0, "total": 0, "updated": 0, "error": ""},
    "wallpaper": {"version": 0, "ok": False},
    "session": {"lastHeartbeat": 0.0, "windowOpened": False, "startedAt": time.time()},
    "log": [],
}


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #
def log(msg):
    line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
    with _lock:
        STATE["log"].append(line)
        if len(STATE["log"]) > 400:
            del STATE["log"][:-400]
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        if LOG_FILE.stat().st_size > 512 * 1024:
            LOG_FILE.unlink()
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 扫描与素材生成
# --------------------------------------------------------------------------- #
def _stamp(raw):
    try:
        src = raw.get("source") or ""
        if src.startswith("shell:"):
            return "uwp|" + src
        st = os.stat(src)
        return "%s|%d|%d" % (src, int(st.st_mtime), st.st_size)
    except Exception:
        return "unknown|" + str(raw.get("id"))


def _accent_seed(raw):
    return int(str(raw["id"])[:6], 16)


def _icon_candidates(raw):
    """按可靠性排序的图标来源：UWP 包内 logo → 真实 exe → 快捷方式图标位置 → 快捷方式本身。"""
    cands = []
    if raw.get("kind") == "uwp":
        cands.append(("uwp", raw))
    path = raw.get("path") or ""
    if path:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".ico", ".png", ".jpg", ".jpeg") and os.path.exists(path):
            cands.append(("image", path))
        elif os.path.exists(path):
            cands.append(("shell", path))
    icon_loc = (raw.get("iconLocation") or "").split(",")[0].strip().strip('"')
    if icon_loc:
        icon_loc = os.path.expandvars(icon_loc)
        if os.path.exists(icon_loc):
            ext = os.path.splitext(icon_loc)[1].lower()
            if ext in (".ico", ".png", ".jpg", ".jpeg"):
                cands.append(("image", icon_loc))
            else:
                cands.append(("shell", icon_loc))
    if raw.get("iconSource"):
        cands.append(("shell", raw["iconSource"]))
    return cands


def _best_icon(raw):
    """依次尝试各种来源，跳过 Windows 的通用白纸图标。"""
    for kind, value in _icon_candidates(raw):
        try:
            if kind == "uwp":
                img = icons.uwp_logo_icon(value.get("installDir") or "",
                                          value.get("aumid") or value.get("launch", {}).get("target") or "")
                if img is None:
                    img = icons.get_icon(value.get("iconSource") or "")
            elif kind == "image":
                img = icons.load_image_icon(value)
            else:
                img = icons.get_icon(value)
        except Exception:
            img = None
        if icons.is_generic_icon(img):
            continue
        return img
    return None


def build_assets(raw, force=False):
    """生成某个应用的图标 png + 封面 jpg，返回 (accent, 是否用了回退图标)。"""
    app_id = raw["id"]
    icon_path = ICON_DIR / (app_id + ".png")
    cover_path = COVER_DIR / (app_id + ".jpg")
    icon_img = _best_icon(raw)
    fallback = False
    if icon_img is not None:
        icon_img = icons.trim_icon(icon_img)
        accent = icons.compute_accent(icon_img, app_id)
        src_img = icon_img
    else:
        accent = icons.compute_accent(None, app_id)
        src_img = icons.make_letter_icon(raw["name"], accent)
        fallback = True
        log("图标缺失，使用字母图标：%s" % raw.get("name"))
    try:
        icon_img_resized = src_img.resize((256, 256), icons.Image.LANCZOS)
        icon_img_resized.save(icon_path, "PNG", optimize=True)
    except Exception as e:
        log("保存图标失败 %s: %s" % (raw["name"], e))
    try:
        cover = icons.make_cover(src_img, accent, seed=_accent_seed(raw), size=640)
        cover.save(cover_path, "JPEG", quality=86, optimize=True)
    except Exception as e:
        log("生成封面失败 %s: %s" % (raw["name"], e))
    return accent, fallback


def run_scan(force=False):
    with _lock:
        if STATE["scan"]["running"]:
            return False
        running_state = dict(STATE["scan"])
        running_state.update({"running": True, "phase": "listing", "done": 0,
                              "total": len(STATE["apps"]), "error": ""})
        STATE["scan"] = running_state
    try:
        log("开始扫描应用（force=%s）" % force)
        t0 = time.time()
        raw_apps = apps_scan.scan_all(log=log)
        # 首次运行时给几个常见应用一个"默认固定"，让拼贴模式一上手就有大卡片
        if not store_.apps and raw_apps:
            for name in ("Google Chrome", "微信", "Visual Studio Code", "哔哩哔哩"):
                for raw in raw_apps:
                    if raw["name"] == name:
                        store_.update_app(raw["id"], {"pinned": True})
                        break
        old_map = {}
        for item in store_.load_apps_cache():
            old_map[item.get("id")] = item
        with _lock:
            STATE["apps"] = raw_apps
            STATE["scan"].update({"total": len(raw_apps), "phase": "icons"})
        # 逐个准备素材（可以在界面上看到图标陆续出现）
        for idx, raw in enumerate(raw_apps):
            old = old_map.get(raw["id"]) or {}
            stamp = _stamp(raw)
            icon_path = ICON_DIR / (raw["id"] + ".png")
            cover_path = COVER_DIR / (raw["id"] + ".jpg")
            reusable = (not force and old.get("iconStamp") == stamp
                        and not old.get("fallback")
                        and icon_path.exists() and cover_path.exists() and old.get("accent"))
            if reusable:
                raw["accent"] = old["accent"]
                raw["fallback"] = False
            else:
                try:
                    accent, fallback = build_assets(raw, force=force)
                    raw["accent"] = accent
                    raw["fallback"] = fallback
                except Exception as e:
                    log("生成素材异常 %s: %s" % (raw.get("name"), e))
                    raw["accent"] = "#5b8cff"
                    raw["fallback"] = True
            raw["iconStamp"] = stamp
            raw["iconReady"] = icon_path.exists()
            raw["coverReady"] = cover_path.exists()
            with _lock:
                STATE["scan"]["done"] = idx + 1
        with _lock:
            STATE["scan"].update({"running": False, "phase": "ready",
                                  "updated": int(time.time())})
        store_.save_apps_cache(STATE["apps"])
        log("扫描完成：%d 个应用，用时 %.1fs" % (len(raw_apps), time.time() - t0))
    except Exception as e:
        log("扫描失败：%s" % e)
        log(traceback.format_exc())
        with _lock:
            STATE["scan"].update({"running": False, "phase": "error", "error": str(e)})
    return True


def prepare_wallpaper():
    try:
        path, version = wallpaper.ensure_wallpaper()
        with _lock:
            STATE["wallpaper"] = {"version": version, "ok": bool(path)}
        if path:
            log("壁纸背景已生成 v%d" % version)
    except Exception as e:
        log("壁纸处理失败：%s" % e)


# --------------------------------------------------------------------------- #
# 数据组装
# --------------------------------------------------------------------------- #
def _count_launch(app_id):
    meta = store_.meta(app_id)
    meta["launchCount"] = int(meta.get("launchCount") or 0) + 1
    meta["lastLaunch"] = int(time.time())
    store_.save()


def running_app_ids(raw_apps):
    """用进程名粗略判断哪些应用正在运行（尽力而为，失败就当全部未运行）。"""
    try:
        import psutil
    except Exception:
        return set()
    names = set()
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name:
                names.add(name)
    except Exception:
        return set()
    out = set()
    for raw in raw_apps:
        path = raw.get("path") or ""
        if not path:
            continue
        base = os.path.basename(path).lower()
        if base and base in names:
            out.add(raw["id"])
    return out


def public_app(raw, running=None):
    meta = store_.meta(raw["id"])
    accent = meta.get("accent") or raw.get("accent") or "#5b8cff"
    name = meta.get("name") or raw.get("name") or ""
    category = meta.get("category") or raw.get("category") or "其他"
    return {
        "id": raw["id"],
        "name": name,
        "rawName": raw.get("name") or "",
        "category": category,
        "kind": raw.get("kind") or "lnk",
        "accent": accent,
        "icon": ("/assets/icons/%s.png" % raw["id"]) if raw.get("iconReady") else None,
        "cover": ("/assets/covers/%s.jpg" % raw["id"]) if raw.get("coverReady") else None,
        "pinned": bool(meta.get("pinned")),
        "hidden": bool(meta.get("hidden")),
        "launchCount": int(meta.get("launchCount") or 0),
        "lastLaunch": int(meta.get("lastLaunch") or 0),
        "path": raw.get("path") or "",
        "source": raw.get("source") or "",
        "repaired": bool(raw.get("repaired")),
        "fallbackIcon": bool(raw.get("fallback")),
        "custom": bool(meta.get("name") or meta.get("category")),
        "running": bool(running and raw["id"] in running),
    }


def ordered_apps(running=None):
    with _lock:
        raws = list(STATE["apps"])
    apps = [public_app(r, running) for r in raws]
    base_index = {r["id"]: i for i, r in enumerate(raws)}
    order_list = list(store_.order)
    order_pos = {app_id: i for i, app_id in enumerate(order_list)}
    for a in apps:
        a["_base"] = base_index.get(a["id"], 10 ** 6)
        a["_order"] = order_pos.get(a["id"], 10 ** 6)
    apps.sort(key=lambda a: (a["_order"], a["_base"]))
    for a in apps:
        a.pop("_base", None)
        a.pop("_order", None)
    return apps


def categories_of(apps):
    counts = {}
    for a in apps:
        if a["hidden"]:
            continue
        counts[a["category"]] = counts.get(a["category"], 0) + 1
    out = [{"name": "全部", "count": sum(counts.values())}]
    for name in apps_scan.CATEGORY_ORDER:
        if counts.get(name):
            out.append({"name": name, "count": counts[name]})
    for name, count in counts.items():
        if name not in apps_scan.CATEGORY_ORDER:
            out.append({"name": name, "count": count})
    return out


def bootstrap_payload():
    running = running_app_ids(STATE["apps"])
    apps = ordered_apps(running)
    with _lock:
        scan = dict(STATE["scan"])
        wpaper = dict(STATE["wallpaper"])
    visible = [a for a in apps if not a["hidden"]]
    stats = {
        "total": len(visible),
        "pinned": len([a for a in visible if a["pinned"]]),
        "launched": len([a for a in visible if a["lastLaunch"] > 0]),
        "hidden": len(apps) - len(visible),
    }
    wallpaper_url = None
    if wpaper.get("ok"):
        wallpaper_url = "/assets/wallpaper.jpg?v=%d" % wpaper.get("version", 0)
    return {
        "ok": True,
        "app": APP_NAME,
        "code": APP_CODE,
        "version": VERSION,
        "now": int(time.time()),
        "settings": store_.settings,
        "scan": scan,
        "apps": apps,
        "categories": categories_of(visible),
        "stats": stats,
        "wallpaper": wallpaper_url,
        "dataDir": str(DATA_DIR),
        "user": os.environ.get("USERNAME") or "本地用户",
    }


# --------------------------------------------------------------------------- #
# 启动应用
# --------------------------------------------------------------------------- #
def find_raw(app_id):
    with _lock:
        for raw in STATE["apps"]:
            if raw["id"] == app_id:
                return raw
    return None


def launch_app(raw):
    launch = raw.get("launch") or {}
    kind = launch.get("type")
    target = launch.get("target") or ""
    if not target:
        raise RuntimeError("没有可启动的目标")
    if kind == "uwp":
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + target],
                         close_fds=True, creationflags=0x08000000)
    elif kind == "exe":
        import shlex
        args = []
        try:
            args = shlex.split(raw.get("args") or "", posix=True)
        except Exception:
            args = []
        workdir = raw.get("workdir") or ""
        if not os.path.isdir(workdir):
            workdir = os.path.dirname(target)
        subprocess.Popen([target] + args, cwd=workdir or None, close_fds=True,
                         creationflags=0x08000000)
    else:
        if not os.path.exists(target):
            raise RuntimeError("快捷方式不存在：%s" % target)
        os.startfile(target)  # noqa: S606


# --------------------------------------------------------------------------- #
# 浏览器应用窗口
# --------------------------------------------------------------------------- #
BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser():
    for path in BROWSER_CANDIDATES:
        if path and os.path.exists(path):
            return path
    return None


def screen_size():
    try:
        user32 = __import__("ctypes").windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


def open_window(port):
    url = "http://127.0.0.1:%d/" % port
    browser = find_browser()
    fullscreen = bool(store_.settings.get("fullscreen"))
    window_mode = store_.settings.get("windowMode") or "maximized"
    if not browser:
        log("没有找到 Chrome/Edge，改用默认浏览器打开")
        webbrowser.open(url)
        with _lock:
            STATE["session"]["windowOpened"] = True
            STATE["session"]["lastHeartbeat"] = time.time()
        return
    sw, sh = screen_size()
    width, height = min(1560, sw - 80), min(980, sh - 80)
    x, y = max(0, (sw - width) // 2), max(0, (sh - height) // 2 - 10)
    args = [
        "--app=" + url,
        "--user-data-dir=" + str(BROWSER_PROFILE),
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,TranslateUI,GlobalMediaControls",
        "--disable-session-crashed-bubble",
        "--noerrdialogs",
        "--hide-crash-restore-bubble",
        "--disable-background-mode",
    ]
    if window_mode == "windowed":
        args += ["--window-size=%d,%d" % (width, height), "--window-position=%d,%d" % (x, y)]
    else:
        args.append("--start-maximized")
    if fullscreen:
        args.append("--start-fullscreen")
    try:
        proc = subprocess.Popen([browser] + args, close_fds=True, creationflags=0x08000000)
        log("已打开应用窗口：%s（%s）" % (browser, window_mode))
        with _lock:
            STATE["session"]["windowOpened"] = True
            STATE["session"]["browserProc"] = proc
            STATE["session"]["procStartedAt"] = time.time()
            STATE["session"]["lastHeartbeat"] = time.time()
    except Exception as e:
        log("打开窗口失败：%s，改用默认浏览器" % e)
        webbrowser.open(url)


def is_our_server(port):
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=1) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("code") == APP_CODE
    except Exception:
        return False


def port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(preferred):
    if is_our_server(preferred):
        return preferred, True
    if port_free(preferred):
        return preferred, False
    for p in range(preferred + 1, preferred + 20):
        if port_free(p):
            return p, False
    return preferred, False


# --------------------------------------------------------------------------- #
# 开机自启
# --------------------------------------------------------------------------- #
def startup_shortcut_path():
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData/Roaming")
    folder = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (APP_NAME + ".lnk")


def pythonw_path():
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    if cand.exists():
        return cand
    return exe


def set_autostart(enabled):
    link = startup_shortcut_path()
    if not enabled:
        if link.exists():
            link.unlink()
        store_.set_settings({"autostart": False})
        return {"enabled": False}
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(link))
    shortcut.TargetPath = str(pythonw_path())
    shortcut.Arguments = '"%s" --open' % (ROOT_DIR / "server.py")
    shortcut.WorkingDirectory = str(ROOT_DIR)
    icon = ROOT_DIR / "assets" / "app.ico"
    if icon.exists():
        shortcut.IconLocation = str(icon)
    shortcut.Description = APP_NAME
    shortcut.Save()
    store_.set_settings({"autostart": True})
    return {"enabled": True, "path": str(link)}


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
@app.after_request
def add_headers(resp):
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.route("/api/ping")
def api_ping():
    if request.args.get("hb"):
        with _lock:
            STATE["session"]["lastHeartbeat"] = time.time()
    with _lock:
        scan = dict(STATE["scan"])
        session = dict(STATE["session"])
    return jsonify({
        "ok": True, "code": APP_CODE, "app": APP_NAME, "version": VERSION,
        "scan": scan, "windowOpened": session["windowOpened"],
    })


@app.route("/api/bye", methods=["POST", "GET"])
def api_bye():
    mark_bye()
    return jsonify({"ok": True})


@app.route("/api/bootstrap")
def api_bootstrap():
    return jsonify(bootstrap_payload())


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    force = bool((request.get_json(silent=True) or {}).get("force"))
    started = run_scan(force=force) if not STATE["scan"]["running"] else False
    if not STATE["scan"]["running"] and not started:
        # 可能刚好结束，重开一个线程
        threading.Thread(target=run_scan, kwargs={"force": force}, daemon=True).start()
        started = True
    return jsonify({"ok": True, "started": started})


@app.route("/api/launch", methods=["POST"])
def api_launch():
    data = request.get_json(silent=True) or {}
    app_id = data.get("id")
    raw = find_raw(app_id)
    if not raw:
        return jsonify({"ok": False, "error": "应用不存在"}), 404
    try:
        launch_app(raw)
    except Exception as e:
        log("启动失败 %s: %s" % (raw.get("name"), e))
        return jsonify({"ok": False, "error": str(e)}), 500
    _count_launch(raw["id"])
    meta = store_.meta(raw["id"])
    return jsonify({"ok": True, "name": (meta.get("name") or raw.get("name")),
                    "launchCount": int(meta.get("launchCount") or 0)})


@app.route("/api/app/<app_id>", methods=["PATCH", "POST"])
def api_update_app(app_id):
    raw = find_raw(app_id)
    if not raw:
        return jsonify({"ok": False, "error": "应用不存在"}), 404
    data = request.get_json(silent=True) or {}
    patch = {}
    for key in ("pinned", "hidden", "name", "category", "accent"):
        if key in data:
            patch[key] = data[key]
    store_.update_app(app_id, patch)
    return jsonify({"ok": True, "app": public_app(raw)})


@app.route("/api/order", methods=["POST"])
def api_order():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not isinstance(ids, list):
        return jsonify({"ok": False, "error": "ids 必须是数组"}), 400
    store_.set_order(ids)
    return jsonify({"ok": True, "count": len(ids)})


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.get_json(silent=True) or {}
    patch = data.get("settings") if isinstance(data.get("settings"), dict) else data
    settings = store_.set_settings(patch)
    return jsonify({"ok": True, "settings": settings})


@app.route("/api/autostart", methods=["POST"])
def api_autostart():
    enabled = bool((request.get_json(silent=True) or {}).get("enabled"))
    try:
        return jsonify({"ok": True, **set_autostart(enabled)})
    except Exception as e:
        log("设置开机自启失败：%s" % e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/open-location", methods=["POST"])
def api_open_location():
    app_id = (request.get_json(silent=True) or {}).get("id")
    raw = find_raw(app_id)
    if not raw:
        return jsonify({"ok": False, "error": "应用不存在"}), 404
    loc = raw.get("source") or raw.get("path")
    if not loc or loc.startswith("shell:"):
        loc = raw.get("path") or ""
    try:
        if loc and os.path.exists(loc):
            subprocess.Popen(["explorer.exe", "/select,", loc])
            return jsonify({"ok": True})
        subprocess.Popen(["explorer.exe", str(DATA_DIR)])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/open-data", methods=["POST"])
def api_open_data():
    try:
        os.startfile(str(DATA_DIR))  # noqa: S606
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/quit", methods=["POST"])
def api_quit():
    log("用户请求退出")
    stop_browser()
    threading.Timer(0.35, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


@app.route("/api/logs")
def api_logs():
    with _lock:
        return jsonify({"ok": True, "lines": list(STATE["log"][-200:])})


@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(str(CACHE_DIR), filename, max_age=300)


@app.route("/brand.png")
def brand_logo():
    return send_from_directory(str(ASSETS_DIR), "logo.png", max_age=3600)


@app.route("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html", max_age=0)


@app.route("/<path:filename>")
def web_files(filename):
    target = (WEB_DIR / filename).resolve()
    try:
        target.relative_to(WEB_DIR.resolve())
    except Exception:
        return jsonify({"ok": False, "error": "not found"}), 404
    if target.is_file():
        return send_from_directory(str(WEB_DIR), filename, max_age=0)
    return jsonify({"ok": False, "error": "not found"}), 404


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def count_app_windows():
    """数一数当前桌面上还有没有本应用的主窗口（用于判断窗口是否已关闭）。"""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = [0]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            # Chrome 的后台辅助窗口也可能带相同标题，用尺寸过滤掉
            if "GridDesk" in title or "方块桌面" in title:
                rect = RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                if (rect.right - rect.left) >= 400 and (rect.bottom - rect.top) >= 300:
                    found[0] += 1
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(EnumProc(_cb), 0)
    except Exception:
        return 1  # 检测失败时按"窗口还在"处理，避免误退出
    return found[0]


def watchdog():
    """窗口关闭后自动退出，避免 pythonw 常驻。

    三重保障：
    1. 前端 pagehide 时 sendBeacon('/api/bye')，2 秒后退出（最快）；
    2. 这里每 4 秒数一次本应用窗口，连续 3 次找不到就退出（最可靠）；
    3. 窗口最小化不会误判（最小化窗口仍然可见且有正常尺寸）。
    """
    misses = 0
    seen = False
    while True:
        time.sleep(2)
        session = STATE["session"]
        if not session.get("windowOpened"):
            continue
        if count_app_windows() > 0:
            seen = True
            misses = 0
            continue
        if not seen:
            # 窗口可能还在冷启动（首次打开 Chrome 时比较常见），先等它出现
            started = session.get("procStartedAt") or time.time()
            if (time.time() - started) < 45:
                continue
        misses += 1
        if misses >= 3:
            log("应用窗口已关闭，服务退出")
            stop_browser()
            os._exit(0)


def stop_browser():
    """退出前尽力结束应用窗口对应的浏览器进程（独立 profile，不会影响用户日常 Chrome）。"""
    proc = STATE["session"].get("browserProc")
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        pass


def mark_bye():
    """页面卸载（关闭窗口/刷新）时调用：稍等片刻，如果新页面没有发心跳就退出。"""
    with _lock:
        STATE["session"]["byeAt"] = time.time()

    def _check():
        time.sleep(2.2)
        session = STATE["session"]
        last = session.get("lastHeartbeat") or 0
        if last < (session.get("byeAt") or 0) - 0.5:
            log("窗口已关闭，服务退出")
            stop_browser()
            os._exit(0)

    threading.Thread(target=_check, daemon=True).start()


def load_cache():
    cached = store_.load_apps_cache()
    if not cached:
        return False
    for item in cached:
        item["iconReady"] = (ICON_DIR / (item["id"] + ".png")).exists()
        item["coverReady"] = (COVER_DIR / (item["id"] + ".jpg")).exists()
        item.setdefault("accent", "#5b8cff")
    with _lock:
        STATE["apps"] = cached
        STATE["scan"].update({"phase": "ready", "total": len(cached), "done": len(cached),
                              "updated": int(time.time())})
    return True


def scan_only():
    apps = apps_scan.scan_all(log=log)
    out = [{"name": a["name"], "category": a["category"], "kind": a["kind"],
            "path": a.get("path"), "source": a.get("source")} for a in apps]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def write_port_file(port):
    """把当前端口写到 data/port.txt，便携版启动脚本靠它找到服务。"""
    try:
        (DATA_DIR / "port.txt").write_text(str(port), encoding="utf-8")
        return True
    except Exception:
        return False


def main():
    # pythonw 下没有控制台，stdout/stderr 为 None，先兜底避免日志或 Flask 启动横幅报错
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open", action="store_true", help="启动后打开应用窗口")
    parser.add_argument("--no-window", action="store_true", help="只起服务，不开窗口")
    parser.add_argument("--external-window", action="store_true",
                        help="窗口由外部启动脚本打开，本进程只监控窗口关闭后退出")
    parser.add_argument("--scan-only", action="store_true", help="只扫描应用并打印结果")
    parser.add_argument("--force", action="store_true", help="强制重新生成图标与封面")
    args = parser.parse_args()

    if args.scan_only:
        scan_only()
        return

    port, already = pick_port(args.port)
    write_port_file(port)
    if already:
        log("服务已在运行，直接打开窗口")
        if args.open and not args.no_window:
            open_window(port)
        return

    log("%s v%s 启动，端口 %d" % (APP_NAME, VERSION, port))
    has_cache = load_cache()
    threading.Thread(target=prepare_wallpaper, daemon=True).start()
    # 有缓存先展示缓存，再后台刷新；没有缓存则直接扫描
    threading.Thread(target=run_scan, kwargs={"force": args.force}, daemon=True).start()
    if args.open and not args.no_window:
        threading.Thread(target=open_when_ready, args=(port,), daemon=True).start()
        threading.Thread(target=watchdog, daemon=True).start()
    elif args.external_window:
        with _lock:
            STATE["session"]["windowOpened"] = True
            STATE["session"]["lastHeartbeat"] = time.time()
            STATE["session"]["procStartedAt"] = time.time()
        threading.Thread(target=watchdog, daemon=True).start()
        log("外部启动窗口模式，窗口关闭后自动退出")
    else:
        log("未开启窗口模式，访问 http://127.0.0.1:%d/" % port)

    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False, debug=False)


def open_when_ready(port):
    for _ in range(60):
        if is_our_server(port):
            open_window(port)
            return
        time.sleep(0.25)
    log("服务启动超时，未能打开窗口")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        log("致命错误：\n" + traceback.format_exc())
        raise
