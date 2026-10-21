# -*- coding: utf-8 -*-
"""诊断：多线程/多次扫描时，WScript.Shell 解析 .lnk 是否会失败（target 变空）。"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import apps_scan  # noqa: E402


def collect(tag):
    logs = []
    t0 = time.time()
    apps = apps_scan.scan_all(log=logs.append)
    with_path = sum(1 for a in apps if a.get("path"))
    repaired = [l for l in logs if "自动修复路径" in l]
    print("[%s] apps=%d with_target=%d time=%.1fs | %s" % (
        tag, len(apps), with_path, time.time() - t0, repaired[-1] if repaired else "?"))
    return apps


def scan_in_thread(tag):
    app = apps_scan.scan_all if False else None
    logs = []
    apps = apps_scan.scan_all(log=logs.append)
    with_path = sum(1 for a in apps if a.get("path"))
    repaired = [l for l in logs if "自动修复路径" in l]
    print("[thread:%s] apps=%d with_target=%d | %s" % (
        tag, len(apps), with_path, repaired[-1] if repaired else "?"))


def scan_in_thread_cominit(tag):
    try:
        import pythoncom
        pythoncom.CoInitialize()
        inited = True
    except Exception as e:  # noqa: BLE001
        print("CoInitialize failed:", e)
        inited = False
    logs = []
    apps = apps_scan.scan_all(log=logs.append)
    with_path = sum(1 for a in apps if a.get("path"))
    repaired = [l for l in logs if "自动修复路径" in l]
    print("[thread+com:%s] apps=%d with_target=%d | %s" % (
        tag, len(apps), with_path, repaired[-1] if repaired else "?"))
    if inited:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def main():
    print("== 主线程第一次扫描 ==")
    collect("main-1")
    print("\n== 主线程第二次扫描 ==")
    collect("main-2")

    print("\n== 无 CoInitialize 的子线程 ==")
    for i in range(2):
        t = threading.Thread(target=scan_in_thread, args=(i,))
        t.start()
        t.join()

    print("\n== 有 CoInitialize 的子线程 ==")
    for i in range(2):
        t = threading.Thread(target=scan_in_thread_cominit, args=(i,))
        t.start()
        t.join()


if __name__ == "__main__":
    main()
