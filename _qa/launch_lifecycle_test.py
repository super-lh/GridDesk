# -*- coding: utf-8 -*-
"""功能测试：真实启动应用 / 退出 / 重启后数据持久化。"""
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8901"
PKG = os.environ.get("GRIDDESK_PKG", "")
REPORT = []


def add(name, status, detail=""):
    REPORT.append({"name": name, "status": status, "detail": detail})
    print("[%s] %s - %s" % (status.upper(), name, detail), flush=True)


def http(path, method="GET", body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return 0, repr(e).encode()


def boot():
    code, raw = http("/api/bootstrap", timeout=40)
    return json.loads(raw.decode("utf-8")) if code == 200 else {}


def find_app(name):
    for a in boot().get("apps", []):
        if a["name"] == name:
            return a
    return None


def proc_exists(name):
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + name],
                         capture_output=True, text=True)
    return name.lower() in (out.stdout or "").lower()


def kill_proc(name):
    subprocess.run(["taskkill", "/IM", name, "/F"], capture_output=True)


def test_launch_lnk_empty_path():
    app = find_app("Windows Media Player Legacy")
    if not app:
        add("启动：Shell 快捷方式（空路径）", "warn", "未找到测试应用")
        return None
    kill_proc("wmplayer.exe")
    time.sleep(0.5)
    code, raw = http("/api/launch", "POST", {"id": app["id"]})
    ok = code == 200
    time.sleep(3.5)
    running = proc_exists("wmplayer.exe")
    add("启动：Shell 快捷方式（空路径）", "pass" if ok and running else "fail",
        "api=%s 进程=%s" % (code, running))
    kill_proc("wmplayer.exe")
    time.sleep(1)
    after = find_app("Windows Media Player Legacy")
    add("启动后记录使用次数", "pass" if after and after.get("launchCount", 0) > 0 else "warn",
        "launchCount=%s lastLaunch=%s" % ((after or {}).get("launchCount"),
                                          (after or {}).get("lastLaunch")))
    return app


def test_launch_repaired_exe():
    app = find_app("Folia")
    if not app:
        add("启动：修复路径的 exe 直启", "warn", "未找到测试应用")
        return
    kill_proc("Folia.exe")
    time.sleep(0.5)
    code, raw = http("/api/launch", "POST", {"id": app["id"]})
    time.sleep(3.5)
    running = proc_exists("Folia.exe")
    add("启动：修复路径的 exe 直启", "pass" if code == 200 and running else "fail",
        "api=%s 进程=%s" % (code, running))
    kill_proc("Folia.exe")
    time.sleep(1)


def snapshot_state():
    b = boot()
    return {
        "settings": b.get("settings"),
        "order": [a["id"] for a in b.get("apps", [])][:5],
        "pinned": [a["id"] for a in b.get("apps", []) if a.get("pinned")],
        "total": len(b.get("apps", [])),
        "launchCounts": {a["id"]: a.get("launchCount") for a in b.get("apps", [])
                         if a.get("launchCount")},
    }


def quit_and_restart(before):
    code, raw = http("/api/quit", "POST", {})
    time.sleep(4)
    alive = False
    try:
        urllib.request.urlopen(BASE + "/api/ping", timeout=2)
        alive = True
    except Exception:
        alive = False
    add("退出接口关闭服务", "pass" if code == 200 and not alive else "fail",
        "api=%s 端口仍可访问=%s" % (code, alive))

    # 重启（同一目录）
    py = os.path.join(PKG, "runtime", "pythonw.exe")
    subprocess.Popen([py, os.path.join(PKG, "server.py"), "--no-window", "--port", "8901"],
                     cwd=PKG, close_fds=True, creationflags=0x08000000)
    for _ in range(30):
        time.sleep(1)
        try:
            if boot():
                break
        except Exception:
            pass
    after = snapshot_state()
    ok = (after.get("total") == before.get("total")
          and after.get("pinned") == before.get("pinned")
          and after.get("settings") == before.get("settings")
          and after.get("order") == before.get("order"))
    add("重启后数据持久化", "pass" if ok else "fail",
        "total=%s pinned=%s order一致=%s settings一致=%s" % (
            after.get("total"), after.get("pinned"),
            after.get("order") == before.get("order"),
            after.get("settings") == before.get("settings")))
    add("重启后启动记录保留", "pass" if after.get("launchCounts") else "warn",
        "有启动记录的应用=%d" % len(after.get("launchCounts") or {}))


def main():
    print("== 启动 API 功能测试 ==", flush=True)
    before = snapshot_state()
    test_launch_lnk_empty_path()
    test_launch_repaired_exe()
    after = snapshot_state()
    print("\n== 退出 & 重启 ==", flush=True)
    quit_and_restart(before)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch-report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=1)
    fails = [x for x in REPORT if x["status"] == "fail"]
    print("\n完成：%d 项，失败 %d" % (len(REPORT), len(fails)))


if __name__ == "__main__":
    main()
