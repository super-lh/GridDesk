# -*- coding: utf-8 -*-
"""打包成 Windows 便携版，输出三种形态：

1. exe 便携版（免安装 Python，但 exe 未签名，可能触发 SmartScreen / 杀软误报）
2. 脚本版（不含 exe，用本机已装的 Python 运行）
3. 完整版（自带 Python 官方 embeddable 运行时，无 exe、无签名提示，推荐分发）

用法：
    python build_portable.py                # 三种都打
    python build_portable.py --script-only  # 只打脚本版（跳过 PyInstaller）
    python build_portable.py --runtime-only # 只打完整版

产物：
    dist/方块桌面/                          # exe 免安装目录
    dist/方块桌面-便携版-<版本>.zip
    dist/方块桌面-脚本版-<版本>.zip
    dist/方块桌面-完整版/                    # 自带 Python 运行时目录
    dist/方块桌面-完整版-<版本>.zip
"""
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "方块桌面"
VERSION = "0.1.1"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
TARGET = DIST / APP_NAME
ZIP_PATH = DIST / ("%s-便携版-%s.zip" % (APP_NAME, VERSION))

SCRIPT_NAME = APP_NAME + "-脚本版"
SCRIPT_TARGET = DIST / SCRIPT_NAME
SCRIPT_ZIP = DIST / ("%s-%s.zip" % (SCRIPT_NAME, VERSION))

RUNTIME_NAME = APP_NAME + "-完整版"
RUNTIME_TARGET = DIST / RUNTIME_NAME
RUNTIME_ZIP = DIST / ("%s-%s.zip" % (RUNTIME_NAME, VERSION))
RUNTIME_CACHE = Path(tempfile.gettempdir()) / "griddesk-runtime" / "py"
EMBED_URLS = [
    "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
    "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip",
    "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip",
]

ICON = ROOT / "assets" / "app.ico"

AV_NOTE = r'''
--------------------------------
关于「Windows 显示文件有危害」
--------------------------------
exe 版里的 方块桌面.exe 是用 PyInstaller 打包的**未签名**程序：
- Windows SmartScreen 对「没有数字签名 + 没有下载信誉」的新程序默认拦截；
- 部分杀毒软件对 PyInstaller 打包的 exe 有通用启发式规则，常见误报（如 Wacatac / Bearfoos 之类）；
- 这个程序只在本机启动一个 127.0.0.1 的本地服务、再打开浏览器窗口，没有任何联网上传。

如果你不想处理这些提示，改用 **方块桌面-完整版**（自带 Python 官方运行时，不含 exe，
不会被 SmartScreen 拦）或 **方块桌面-脚本版**（本机已装 Python 时用）。

如果坚持用 exe 版，可以：
1. 右键 zip →「属性」→ 勾选「解除锁定」→ 确定，再解压；
2. 运行 exe 弹出 SmartScreen 时点「更多信息」→「仍要运行」；
3. 若被 Defender 隔离，在「Windows 安全中心 → 保护历史记录」里选择「允许在设备上保留」，
   或把程序文件夹加入排除项；
4. 最稳妥：自己在本机重新执行一次 python build_portable.py（本地新编译的文件不带「来自网络」标记）。
'''

LAUNCH_VBS = r'''Option Explicit
' 启动「方块桌面」便携版：先启动本地服务，再用 Chrome / Edge 打开应用窗口。
Dim fso, shell, appDir, exePath, portFile, port, i, url, browser, profile
Dim candidates, f
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
exePath = appDir & "\方块桌面.exe"
If Not fso.FileExists(exePath) Then
  MsgBox "没有找到 方块桌面.exe，请把整个文件夹完整解压后再运行。", 48, "方块桌面"
  WScript.Quit
End If
portFile = appDir & "\data\port.txt"
If fso.FileExists(portFile) Then On Error Resume Next : fso.DeleteFile portFile, True : On Error GoTo 0
shell.Run """" & exePath & """ --no-window --external-window", 0, False
port = ""
For i = 1 To 60
  WScript.Sleep 500
  If fso.FileExists(portFile) Then
    Set f = fso.OpenTextFile(portFile, 1)
    If Not f.AtEndOfStream Then port = Trim(f.ReadAll())
    f.Close
    If IsNumeric(port) Then Exit For
  End If
Next
If port = "" Then
  MsgBox "本地服务启动超时。请查看 data\server.log，或关闭后重试。", 48, "方块桌面"
  WScript.Quit
End If
WScript.Sleep 1000
url = "http://127.0.0.1:" & port & "/"
candidates = Array( _
  shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Google\Chrome\Application\chrome.exe", _
  shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Google\Chrome\Application\chrome.exe", _
  shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Google\Chrome\Application\chrome.exe", _
  shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Microsoft\Edge\Application\msedge.exe", _
  shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Microsoft\Edge\Application\msedge.exe")
browser = ""
For Each f In candidates
  If fso.FileExists(f) Then
    browser = f
    Exit For
  End If
Next
profile = appDir & "\data\browser-profile"
If browser = "" Then
  shell.Run url, 1, False
Else
  shell.Run """" & browser & """ --app=" & url & " --user-data-dir=""" & profile & """ --no-first-run --no-default-browser-check --disable-features=Translate,TranslateUI,GlobalMediaControls --disable-session-crashed-bubble --noerrdialogs --hide-crash-restore-bubble --disable-background-mode --start-maximized", 1, False
End If
'''

SHORTCUT_VBS = r'''Option Explicit
' 在桌面创建「方块桌面」快捷方式
Dim fso, shell, appDir, target, desktop, lnk
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
target = appDir & "\启动方块桌面.vbs"
If Not fso.FileExists(target) Then
  MsgBox "没有找到 启动方块桌面.vbs，请把这个脚本放在程序目录里再运行。", 48, "方块桌面"
  WScript.Quit
End If
desktop = shell.SpecialFolders("Desktop")
Set lnk = shell.CreateShortcut(desktop & "\方块桌面.lnk")
lnk.TargetPath = target
lnk.WorkingDirectory = appDir
If fso.FileExists(appDir & "\方块桌面.exe") Then
  lnk.IconLocation = appDir & "\方块桌面.exe,0"
Else
  lnk.IconLocation = appDir & "\assets\app.ico,0"
End If
lnk.Description = "方块桌面 · 把应用收进一面墙"
lnk.Save
MsgBox "已在桌面创建「方块桌面」快捷方式。", 64, "方块桌面"
'''

STOP_BAT = r'''@echo off
chcp 65001 >nul
echo 正在停止方块桌面…
taskkill /IM "方块桌面.exe" /F >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" 2>nul
echo 完成。如果应用窗口还开着，直接关闭窗口即可。
timeout /t 2 /nobreak >nul
'''

README_TXT = """方块桌面 · 便携版（exe 版）
==============================

【怎么用】
1. 把整个「方块桌面」文件夹解压到一个**可写**的目录（桌面、D 盘都行，别放 Program Files）。
2. 双击「启动方块桌面.vbs」启动。
   首次启动如果缺缓存会自动扫描本机应用，约 10-30 秒；之后启动直接读缓存，秒开。
3. 想放到桌面：双击「创建桌面快捷方式.vbs」。
4. 退出：点右下角电源按钮，或直接关闭窗口（本地服务会自动退出）。

【需要什么】
- Windows 10 / 11
- Chrome 或 Edge（用来承载无边框应用窗口；两个都没有时会退回默认浏览器打开）
- 不需要安装 Python

【目录说明】
- 方块桌面.exe       本地服务（不用手动双击，启动脚本会调用它）
- 启动方块桌面.vbs   启动入口（推荐双击这个）
- data\\              设置、图标 / 封面缓存、日志
- 如果程序目录没有写入权限，数据会自动改存到 %LOCALAPPDATA%\\GridDesk\\data
""" + AV_NOTE + """
【常见问题】
- 双击没反应 / 提示超时：看 data\\server.log；确认 Chrome 或 Edge 已安装。
- 图标是白纸 / 字母：设置 →「重建图标与封面」再试一次。
- 换电脑使用：整个文件夹拷走即可（data 里的缓存也会一起带走）。

【怎么重新打包】
在项目根目录执行：python build_portable.py
"""

SCRIPT_README = """方块桌面 · 脚本版
==============================

这个版本**不含 exe**，用本机已安装的 Python 运行，不会被 Windows 的
「未知发布者 / SmartScreen」拦截，适合自己电脑长期使用。

【怎么用】
1. 解压到任意目录（建议固定一个位置，方便以后启动）。
2. 双击「启动方块桌面.vbs」。
3. 想放桌面：双击「创建桌面快捷方式.vbs」。
4. 关闭应用窗口即退出本地服务。

【需要什么】
- Windows 10 / 11
- Python 3.9+，并已安装：flask、pillow、numpy、pywin32、psutil
  安装命令：pip install flask pillow numpy pywin32 psutil
- Chrome 或 Edge

启动脚本会自动寻找 pythonw.exe（优先 D:\\anaconda\\pythonw.exe，
也会找常见安装目录和 PATH）。如果提示找不到，请把 Python 加入 PATH 后重试。

【数据】
- 设置和缓存都在 data\\ 下；删掉 data 目录即可彻底重置（下次启动重新扫描）。

【和 exe 版的区别】
- 脚本版：依赖本机 Python，无 SmartScreen 拦截，适合自己用。
- exe 版：不需要 Python，适合拷给没有装 Python 的电脑，但未签名，可能弹安全提示。
"""

SCRIPT_VBS = r'''Option Explicit
' ============================================================
'  方块桌面 · GridDesk 启动器（脚本版）
'  以无窗口方式启动本地服务，并打开一个没有浏览器界面的应用窗口
' ============================================================
Dim fso, sh, baseDir, pyw, cmd, i, candidates
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FileExists(baseDir & "\server.py") Then
  MsgBox "没有找到 server.py，请确认整个文件夹是完整的。", 48, "方块桌面"
  WScript.Quit 1
End If

candidates = Array( _
  "D:\anaconda\pythonw.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python313\pythonw.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\pythonw.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python311\pythonw.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python310\pythonw.exe", _
  "C:\Python313\pythonw.exe", _
  "C:\Python312\pythonw.exe", _
  "C:\Python311\pythonw.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Launcher\pyw.exe", _
  "pythonw.exe")

pyw = ""
For i = 0 To UBound(candidates)
  If InStr(candidates(i), "\") = 0 Then
    pyw = candidates(i)
  ElseIf fso.FileExists(candidates(i)) Then
    pyw = candidates(i)
  End If
  If pyw <> "" Then Exit For
Next

If pyw = "" Then
  MsgBox "没有找到 pythonw.exe，请先安装 Python 3 并加入 PATH。", 48, "方块桌面"
  WScript.Quit 1
End If

sh.CurrentDirectory = baseDir
cmd = """" & pyw & """ """ & baseDir & "\server.py"" --open"
sh.Run cmd, 0, False
'''


RUNTIME_VBS = r'''Option Explicit
' ============================================================
'  方块桌面 · 完整版启动器（自带 Python 运行环境，无需安装 Python）
'  以无窗口方式启动本地服务，并打开一个没有浏览器界面的应用窗口
' ============================================================
Dim fso, sh, appDir, runtimePy, cmd, i, pyw, candidates
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FileExists(appDir & "\server.py") Then
  MsgBox "没有找到 server.py，请确认整个文件夹是完整的。", 48, "方块桌面"
  WScript.Quit 1
End If

runtimePy = appDir & "\runtime\pythonw.exe"
If Not fso.FileExists(runtimePy) Then
  MsgBox "内置运行环境不完整（缺少 runtime\pythonw.exe），请重新解压完整压缩包。", 48, "方块桌面"
  WScript.Quit 1
End If

sh.CurrentDirectory = appDir
cmd = """" & runtimePy & """ """ & appDir & "\server.py"" --open"
sh.Run cmd, 0, False
'''

RUNTIME_README = """方块桌面 · 完整版（自带 Python 运行环境）
==============================

这个版本**没有 exe**，而是把 Python 官方运行环境（python.org 发布、带数字签名）
一起打包了进来，所以：
- 不需要安装 Python；
- 不会出现「未知发布者 / SmartScreen 有危害」的提示（启动的是 Python 官方签名的 pythonw.exe）。

【怎么用】
1. 解压到任意可写目录（桌面、D 盘都行）。
   如果系统提示「此文件来自其他计算机」，可先右键 zip →「属性」→ 勾选「解除锁定」→ 再解压。
2. 双击「启动方块桌面.vbs」。
3. 想放桌面：双击「创建桌面快捷方式.vbs」。
4. 关闭应用窗口即退出本地服务。

【需要什么】
- Windows 10 / 11
- Chrome 或 Edge（用来承载无边框应用窗口）
- 不需要安装 Python

【目录说明】
- runtime\\            Python 3.12 运行环境（官方 embeddable 包 + 依赖库，含 LICENSE）
- server.py / core\\ / web\\   程序本体
- 启动方块桌面.vbs    启动入口
- data\\               设置、图标 / 封面缓存、日志
- 如果程序目录没有写入权限，数据会自动改存到 %LOCALAPPDATA%\\GridDesk\\data

【为什么能避免安全提示】
- 程序入口是 .vbs 脚本，真正运行的是 runtime\\pythonw.exe；
- 该文件由 Python Software Foundation 数字签名（可用右键 → 属性 → 数字签名 查看）；
- 包里不含任何自编译的 .exe，因此不会触发「未签名的应用程序」拦截。

【常见问题】
- 双击没反应 / 提示超时：看 data\\server.log；确认 Chrome 或 Edge 已安装。
- 提示缺少 msvcp140 / vcruntime：本包已内置 vcruntime140.dll；如仍报错，安装
  「Microsoft Visual C++ 2015-2022 Redistributable」即可。
- 想彻底重置：退出后删除 data 目录，下次启动会重新扫描生成。

【怎么重新打包】
在项目根目录执行：python build_portable.py
"""


def log(msg):
    print("[build] " + msg, flush=True)


def clean():
    for d in (BUILD, DIST):
        if d.exists():
            log("清理 " + str(d))
            shutil.rmtree(d, ignore_errors=True)


def build_exe():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", APP_NAME,
        "--icon", str(ICON),
        "--add-data", str(ROOT / "web") + ";web",
        "--add-data", str(ROOT / "assets") + ";assets",
        "--hidden-import", "win32com",
        "--hidden-import", "win32com.client",
        "--hidden-import", "pythoncom",
        "--hidden-import", "pywintypes",
        "--hidden-import", "psutil",
        "--paths", str(ROOT),
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        str(ROOT / "server.py"),
    ]
    log("开始 PyInstaller…")
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        raise SystemExit("PyInstaller 失败，退出码 %s" % proc.returncode)
    log("PyInstaller 完成，用时 %.1fs" % (time.time() - started))


def copy_data(dst_root):
    src = ROOT / "data"
    dst = dst_root / "data"
    cache_dst = dst / "cache"
    cache_dst.mkdir(parents=True, exist_ok=True)
    for name in ("apps.json", "state.json"):
        f = src / name
        if f.exists():
            shutil.copy2(f, dst / name)
    for sub in ("icons", "covers"):
        s = src / "cache" / sub
        if s.exists():
            shutil.copytree(s, cache_dst / sub, dirs_exist_ok=True)
    wp = src / "cache" / "wallpaper.jpg"
    if wp.exists():
        shutil.copy2(wp, cache_dst / "wallpaper.jpg")


def copy_docs(dst_root, extra=None):
    for name in ("README.md", "使用说明.md", "设计说明.md"):
        f = ROOT / name
        if f.exists():
            shutil.copy2(f, dst_root / name)
    if extra:
        for name, text in extra.items():
            (dst_root / name).write_text(text, encoding="utf-8")


def copy_tree(src, dst):
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def write_exe_extras():
    (TARGET / "启动方块桌面.vbs").write_text(LAUNCH_VBS, encoding="utf-16")
    (TARGET / "创建桌面快捷方式.vbs").write_text(SHORTCUT_VBS, encoding="utf-16")
    (TARGET / "停止方块桌面.bat").write_text(STOP_BAT, encoding="utf-8")
    (TARGET / "打包说明.txt").write_text(README_TXT, encoding="utf-8")


def zip_dir(src_dir, zip_path, root_name):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                zf.write(path, Path(root_name) / path.relative_to(src_dir))


def build_exe_package():
    log("== exe 便携版 ==")
    build_exe()
    copy_data(TARGET)
    copy_docs(TARGET)
    write_exe_extras()
    log("已放入缓存、启动脚本与说明")
    log("压缩 exe 版 zip…")
    zip_dir(TARGET, ZIP_PATH, APP_NAME)
    log("exe 版 zip：%s（%.1f MB）" % (ZIP_PATH, ZIP_PATH.stat().st_size / 1024 / 1024))


def build_script_package():
    log("== 脚本版（不含 exe，不会被 SmartScreen 拦）==")
    SCRIPT_TARGET.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "server.py", SCRIPT_TARGET / "server.py")
    copy_tree(ROOT / "core", SCRIPT_TARGET / "core")
    copy_tree(ROOT / "web", SCRIPT_TARGET / "web")
    copy_tree(ROOT / "assets", SCRIPT_TARGET / "assets")
    copy_data(SCRIPT_TARGET)
    copy_docs(SCRIPT_TARGET, {"打包说明.txt": SCRIPT_README})
    (SCRIPT_TARGET / "启动方块桌面.vbs").write_text(SCRIPT_VBS, encoding="utf-16")
    debug_bat = ROOT / "启动方块桌面(调试).bat"
    if debug_bat.exists():
        shutil.copy2(debug_bat, SCRIPT_TARGET / debug_bat.name)
    (SCRIPT_TARGET / "创建桌面快捷方式.vbs").write_text(SHORTCUT_VBS, encoding="utf-16")
    (SCRIPT_TARGET / "停止方块桌面.bat").write_text(STOP_BAT, encoding="utf-8")
    log("压缩脚本版 zip…")
    zip_dir(SCRIPT_TARGET, SCRIPT_ZIP, SCRIPT_NAME)
    log("脚本版 zip：%s（%.1f MB）" % (SCRIPT_ZIP, SCRIPT_ZIP.stat().st_size / 1024 / 1024))


def prepare_runtime():
    """准备「官方 Python embeddable + 依赖库」的内置运行时（缓存在临时目录）。"""
    if (RUNTIME_CACHE / "pythonw.exe").exists() and (RUNTIME_CACHE / "site-packages").exists():
        log("复用已缓存的内置运行时：%s" % RUNTIME_CACHE)
        return RUNTIME_CACHE
    import urllib.request

    base = RUNTIME_CACHE.parent
    RUNTIME_CACHE.mkdir(parents=True, exist_ok=True)
    zip_path = base / "python-embed.zip"
    log("下载 Python embeddable 包（约 11 MB）…")
    last_error = None
    for url in EMBED_URLS:
        try:
            urllib.request.urlretrieve(url, zip_path)
            log("已下载：" + url)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log("下载失败，换一个源：%s" % exc)
    else:
        raise SystemExit("无法下载 Python embeddable：%s" % last_error)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(RUNTIME_CACHE)

    site_packages = RUNTIME_CACHE / "site-packages"
    site_packages.mkdir(exist_ok=True)
    log("安装依赖到内置运行时（flask / pillow / numpy / pywin32 / psutil）…")
    proc = subprocess.run([
        sys.executable, "-m", "pip", "install", "--quiet",
        "--disable-pip-version-check", "--no-warn-script-location",
        "--only-binary=:all:", "--target", str(site_packages),
        "flask", "pillow", "numpy", "pywin32", "psutil",
    ])
    if proc.returncode != 0:
        raise SystemExit("依赖安装失败")

    # pywin32 的 DLL 放到 win32 目录 / 运行时根目录，保证 win32com 可导入
    for dll in (site_packages / "pywin32_system32").glob("*.dll"):
        shutil.copy2(dll, site_packages / "win32")
        shutil.copy2(dll, RUNTIME_CACHE)

    pth = next(RUNTIME_CACHE.glob("python*._pth"))
    pth.write_text(
        "python312.zip\n.\nsite-packages\nsite-packages\\win32\n"
        "site-packages\\win32\\lib\nsite-packages\\Pythonwin\nimport site\n",
        encoding="ascii",
    )

    # 精简掉用不到的文件，减小体积
    for rel in ("PyWin32.chm", "win32\\include", "win32\\libs", "pythonwin",
                "adodbapi", "isapi", "win32comext"):
        target = site_packages / rel
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink()
    for pycache in RUNTIME_CACHE.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)

    log("自检内置运行时…")
    check = subprocess.run([
        str(RUNTIME_CACHE / "python.exe"), "-c",
        "import win32com.client, flask, PIL, numpy, psutil; print('runtime ok')",
    ], capture_output=True, text=True)
    if check.returncode != 0:
        raise SystemExit("内置运行时自检失败：\n" + (check.stdout or "") + (check.stderr or ""))
    log("内置运行时自检通过")
    return RUNTIME_CACHE


def build_runtime_package():
    log("== 完整版（自带 Python 运行时，无 exe，零签名提示）==")
    runtime = prepare_runtime()
    RUNTIME_TARGET.mkdir(parents=True, exist_ok=True)
    copy_tree(runtime, RUNTIME_TARGET / "runtime")
    shutil.copy2(ROOT / "server.py", RUNTIME_TARGET / "server.py")
    copy_tree(ROOT / "core", RUNTIME_TARGET / "core")
    copy_tree(ROOT / "web", RUNTIME_TARGET / "web")
    copy_tree(ROOT / "assets", RUNTIME_TARGET / "assets")
    copy_data(RUNTIME_TARGET)
    copy_docs(RUNTIME_TARGET, {"打包说明.txt": RUNTIME_README})
    (RUNTIME_TARGET / "启动方块桌面.vbs").write_text(RUNTIME_VBS, encoding="utf-16")
    debug_bat = ROOT / "启动方块桌面(调试).bat"
    if debug_bat.exists():
        shutil.copy2(debug_bat, RUNTIME_TARGET / debug_bat.name)
    (RUNTIME_TARGET / "创建桌面快捷方式.vbs").write_text(SHORTCUT_VBS, encoding="utf-16")
    (RUNTIME_TARGET / "停止方块桌面.bat").write_text(STOP_BAT, encoding="utf-8")
    log("压缩完整版 zip（含运行时，稍慢）…")
    zip_dir(RUNTIME_TARGET, RUNTIME_ZIP, RUNTIME_NAME)
    log("完整版 zip：%s（%.1f MB）" % (RUNTIME_ZIP, RUNTIME_ZIP.stat().st_size / 1024 / 1024))


def summary():
    for p, label in ((RUNTIME_ZIP, "完整版（零提示）"), (ZIP_PATH, "exe 便携版"),
                     (SCRIPT_ZIP, "脚本版")):
        if p.exists():
            log("%s：%s（%.1f MB）" % (label, p, p.stat().st_size / 1024 / 1024))


def main():
    if not ICON.exists():
        raise SystemExit("缺少图标文件：%s" % ICON)
    script_only = "--script-only" in sys.argv
    runtime_only = "--runtime-only" in sys.argv
    clean()
    if not script_only and not runtime_only:
        build_exe_package()
    if not runtime_only:
        build_script_package()
    build_runtime_package()
    summary()


if __name__ == "__main__":
    main()
