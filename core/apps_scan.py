# -*- coding: utf-8 -*-
"""方块桌面 · 应用扫描

扫描来源：
- 开始菜单（当前用户 + 所有用户）里的 .lnk 快捷方式
- 桌面快捷方式
- UWP / Microsoft Store 应用（shell:AppsFolder）

扫描结果统一成同一个结构：
{
  "id": "a1b2c3d4e5f6",           # 稳定短哈希
  "name": "Google Chrome",        # 展示名
  "category": "浏览",             # 自动分类
  "kind": "lnk" | "uwp",
  "iconSource": "C:\\...\\Chrome.lnk" 或 "shell:AppsFolder\\xxx!App",
  "launch": {"type": "lnk", "target": "..."} | {"type": "uwp", "target": "AUMID"},
  "path": "C:\\...\\chrome.exe",   # 真实可执行文件（可能为空）
  "source": "C:\\...\\Chrome.lnk",
  "args": "",
  "workdir": ""
}
"""
import hashlib
import os
import re
import subprocess
from pathlib import Path

# 分类展示顺序
CATEGORY_ORDER = ["浏览", "AI", "社交", "影音", "办公", "开发", "设计", "游戏", "工具", "系统", "其他"]

# 关键词 -> 分类，按顺序匹配，越靠前优先级越高。
# 注意：只用「名称 + 目标路径」匹配，UWP 只用名称匹配，避免 AUMID 里的随机串误判。
CATEGORY_RULES = [
    ("开发", r"visual studio|vs ?code|vscode|code\.exe|pycharm|intellij|idea|webstorm|goland|clion|rider|"
             r"android studio|eclipse|sublime|notepad\+\+|neovim|^vim$|emacs|git ?hub|sourcetree|tortoisegit|"
             r"anaconda|conda|python|jupyter|spyder|node ?js|npm|postman|insomnia|apifox|docker|"
             r"navicat|dbeaver|datagrip|mysql|sql server|ssms|redis|mobaxterm|xshell|putty|winscp|filezilla|"
             r"windows terminal|powershell|命令提示符|xampp|wamp|unity|unreal|android|adb|keil|arduino|"
             r"stm32|cursor|windsurf|^trae$|git ?bash|visual studio installer|windows kits|copilot|"
             r"x-anylabeling|labeling|标注"),
    ("AI", r"chatgpt|openai|deepseek|kimi|豆包|doubao|claude|gemini|通义|千问|文心|智谱|chatbox|"
            r"cherry studio|lm studio|ollama|comfyui|stable diffusion|midjourney|codex|"
            r"creator ?zone|语音助手|唤醒"),
    ("影音", r"kugou|酷狗|cloudmusic|网易云|qq音乐|qqmusic|spotify|potplayer|vlc|kmplayer|mpc-hc|foobar|"
             r"剪映|capcut|premiere|after effects|obs|audition|爱奇艺|iqiyi|哔哩|bilibili|抖音|douyin|快手|"
             r"音乐|music|播放器|player|影音|视频|videolan|迅雷影音|qqlive|腾讯视频|优酷|youku|芒果|"
             r"酷我|kuwo|咪咕|喜马拉雅|ximalaya|podcast|录音|audacity|格式工厂|handbrake|"
             r"media player|录音机|相机|camera|照片|photos|媒体"),
    ("社交", r"微信|wechat|weixin|企业微信|wecom|wework|\bqq\b|qqnt|tim|钉钉|dingtalk|telegram|discord|"
             r"whatsapp|飞书|feishu|lark|skype|zoom|腾讯会议|voov|teams|微博|weibo|知乎|zhihu|"
             r"小红书|xiaohongshu|陌陌|soul|line|signal|messenger|聊天|chat"),
    ("浏览", r"chrome|edge|firefox|浏览器|browser|opera|vivaldi|360安全浏览器|360极速浏览器|qq浏览器|"
             r"搜狗浏览器|uc浏览器|safari|brave|tor browser|世界之窗|2345浏览器|夸克|quark|"
             r"chrome 应用|chrome apps"),
    ("设计", r"photoshop|illustrator|indesign|lightroom|figma|sketch|blender|cinema 4d|c4d|maya|"
             r"3ds max|coreldraw|canva|美图|美颜|xnview|honeyview|acdsee|cad|solidworks|autocad|revit|"
             r"渲染|krita|gimp|inkscape|procreate|clip studio|白板|whiteboard|画图|paint"),
    ("办公", r"word|excel|powerpoint|onenote|outlook|access|wps|office|libreoffice|openoffice|notion|"
             r"印象笔记|evernote|有道|youdao|石墨|腾讯文档|夸克网盘|坚果云|oneDrive|dropbox|"
             r"google drive|邮箱|mail|foxmail|thunderbird|pdf|xmind|mindmaster|幕布|语雀|yuque|"
             r"typora|obsidian|logseq|markdown|zotero|acrobat|福昕|foxit|扫描|打印机|printer|"
             r"日历|calendar|todo|to do|滴答清单|todoist|百度网盘|阿里云盘|网盘|"
             r"journal|笔记|notes|sticky"),
    ("游戏", r"steam|epic games|epicgames|wegame|battle\.net|battlenet|ubisoft|origin|ea app|gog|"
             r"游戏|game|minecraft|英雄联盟|league of legends|原神|genshin|崩坏|绝区零|穿越火线|"
             r"网易游戏|腾讯游戏|4399|游戏中心|xbox|playnite|legion zone|联想拯救者"),
    ("系统", r"设置|^settings$|控制面板|control panel|任务管理器|task manager|计算器|calculator|记事本|notepad|"
             r"资源管理器|explorer|磁盘|disk|设备管理器|系统信息|\bsystem\b|"
             r"声音|sound|音频|audio|蓝牙|bluetooth|"
             r"电源|power|显示设置|display settings|网络设置|network settings|"
             r"安全中心|security center|防火墙|firewall|"
             r"应用商店|microsoft store|截图|snip|时钟|clock|放大镜|讲述人"),
    ("工具", r"7-zip|7z|winrar|bandizip|压缩|解压|加速器|vpn|代理|proxy|clash|v2ray|shadowsocks|"
             r"迅雷|thunder|下载|download|idm|everything|listary|powertoys|utools|quicker|"
             r"输入法|ime|搜狗|百度|snipaste|录屏|bandicam|sharex|teamviewer|向日葵|todesk|anydesk|"
             r"清理|clean|优化|optimize|备份|backup|"
             r"英特尔|intel|nvidia|显卡|驱动|driver|联想|lenovo|电脑管家|管家|"
             r"华硕|asus|戴尔|dell|惠普|外设|键盘|鼠标|"
             r"网盘|同步|sync|discord|telegram|爱思助手|刷机|doc2x|workbuddy|deskbox|folia|"
             r"autodesk|犀牛|rhino|sketchup|keyshot|zbrush|substance|"
             r"x-rite|color assistant|rgb|外设|鼠标|键盘|thermal|fan|nitro|legion zone|联想"),
]

# 名字本身就是"系统自带应用"，即使命中系统工具规则也保留
KEEP_NAMES = {
    "设置", "settings", "记事本", "notepad", "计算器", "calculator", "画图", "paint",
    "文件资源管理器", "file explorer", "任务管理器", "task manager", "windows terminal",
    "终端", "terminal", "控制面板", "control panel",
}

# 明显不是"应用"的条目（帮助/卸载/更新/系统管理工具…）
JUNK_NAME = re.compile(
    r"(?i)(卸载|uninstall|unins|readme|自述|帮助|help|manual|手册|官网|website|"
    r"documentation|文档|更新|update|updater|升级|repair|修复|license|许可|"
    r"release note|changelog|发行说明|反馈|feedback|remove|购买|入门|教程|tutorial|"
    r"sample|示例|about|版本说明|install|安装|setup|维护|诊断|diagnos|debug|crash|"
    r"报告|删除|命令行|command prompt|windows powershell|powershell|"
    r"control panel|控制面板|component services|组件服务|event viewer|事件查看器|"
    r"performance monitor|性能监视器|resource monitor|资源监视器|任务计划|task scheduler|"
    r"computer management|计算机管理|注册表|registry|远程桌面|remote desktop|"
    r"system information|系统信息|^services$|服务$|disk cleanup|磁盘清理|"
    r"character map|字符映射|屏幕键盘|on-screen keyboard|放大镜|magnify|讲述人|narrator|"
    r"live captions|实时字幕|步骤记录器|steps recorder|系统配置|system configuration|"
    r"^run$|^运行$|odbc|iscsi|appverif|application verifier|performance analyzer|"
    r"performance recorder|gpuview|app cert|应用验证|用户指南|单击以执行|click to do|"
    r"windows 备份|windows backup|碎片|disk defragment|windows software development kit|"
    r"steam support|family|game bar|游戏栏|journal|资讯|news|便笺|sticky notes|"
    r"nahimic|voiceaccess|语音访问|配置工具|语言首选项|send to|发送至|sql server|"
    r"导入和导出|windows 工具|windows tools|windows 功能|windows features|系统还原|"
    r"recovery|恢复|defender|防火墙|firewall|mmc|\.msc|msconfig|regedit|charmap|"
    r"dfrgui|cleanmgr|eventvwr|compmgmt|perfmon|taskschd|mstsc|msinfo32|iscsicpl|"
    r"psr\.exe|osk\.exe|narrator\.exe|magnify\.exe|appcertui|gpuview|wpa\.exe|wpri|"
    r"appverif|odbcad32|dtswizard|setlang|onenotem|此电脑|this pc|recycle|回收站|"
    r"^desktop$|应用商店|microsoft store|联想应用商店|lenovoappstore|"
    r"超级互联|联想超级文件|legion zone|拯救者|creator ?zone|autodesk dwf|"
    r"x-rite|color assistant|microsoft 资讯|资讯|"
    r"journal|便笺|family|game bar|xbox|"
    r"语音助手|唤醒|narrator|放大镜|讲述人|屏幕键盘|实时字幕|重置|reset|"
    r"nahimic|voiceaccess|windows 备份|单击以执行)"
)

# 指向这些目标的快捷方式也不是"应用"
JUNK_TARGET = re.compile(
    r"(?i)(unins|uninst|uninstall|unwise|setup\.exe|installer|update\.exe|updater|"
    r"helper\.exe|repair\.exe|crashpad|crashreport|vcredist|dotnetfx|directx|"
    r"\\windows\\system32\\|\\windows\\syswow64\\|\\windows\\regedit\.exe|"
    r"\\windows\\system32\\windowsmediaplayer|appcertui|gpuview|wpa\.exe|wpri|"
    r"\\windows kits\\|\\windows performance toolkit\\|\\app certification kit\\|"
    r"\\common files\\lenovoappstorenotify\\|\\lenovo\\ready for assistant\\)"
)

# UWP 里常见的系统组件/无意义入口
UWP_JUNK = re.compile(
    r"(?i)(应用安装程序|app installer|windows 功能|windows feature|windows 工具|windows tools|"
    r"默认应用|default apps|可选功能|optional feature|入门|get started|提示|tips|"
    r"反馈|feedback|快速助手|quick assist|手机连接|phone link|你的手机|"
    r"游戏服务|gaming services|xbox game bar|游戏栏|"
    r"anaconda|command prompt|powershell|应用程序验证|application verifier|"
    r"组件服务|component services|odbc|visual studio installer|"
    r"windows 安全|windows security|secur|defender|"
    r"照片|photos|相机|camera|录音机|sound recorder|媒体播放器|media player|"
    r"地图|maps|天气|weather|邮件|mail|日历|calendar|people|联系人|"
    r"计算器|calculator|记事本|notepad|画图|paint|截图工具|snipping|"
    r"设置|settings|控制面板|control panel|任务管理器|task manager|"
    r"文件资源管理器|file explorer|存储|storage|磁盘|disk|优化|optimize|"
    r"剪贴板|clipboard|移动设备|mobile|"
    r"sound|声音|语音|voice|辅助功能|accessibility|"
    r"仪表板|dashboard|预览|preview|insider|dev home|"
    r"microsoft store|应用商店|商店|"
    r"快速|quick|新闻|news|体育|sports|财经|finance|"
    r"get help|获取帮助|远程桌面|remote desktop|终端|terminal|"
    r"power automate|power apps|系统|system|混合现实|mixed reality|看房|"
    r"秒表|定时器|时钟|clock|用户指南|运行|单击以执行|click to do|"
    r"备份|backup|sticky notes|便笺|family|journal|资讯|白板|whiteboard|"
    r"clipchamp|nahimic|语音访问|voiceaccess|任务计划|task scheduler|"
    r"事件查看器|event viewer|性能监视器|performance monitor|资源监视器|"
    r"resource monitor|计算机管理|computer management|记事本|notepad)"
)

# UWP 里值得保留的（命中即保留，即便上面的规则没排除干净）
UWP_KEEP = re.compile(
    r"(?i)(微信|wechat|qq|钉钉|dingtalk|telegram|discord|whatsapp|spotify|哔哩|bilibili|"
    r"抖音|tiktok|netflix|爱奇艺|腾讯视频|优酷|网易云|zoom|teams|skype|todo|notion|"
    r"evernote|印象笔记|vs code|visual studio|github|photoshop|acrobat|foxit|kindle|"
    r"steam|epic|xbox|chatgpt|spyder|美图|intel graphics)"
)


def _norm_name(name):
    """用于去重的规范化名称。"""
    s = (name or "").strip().lower()
    s = re.sub(r"[-_ ]*(快捷方式|shortcut)\s*$", "", s)
    s = re.sub(r"\s*\((new|x86|x64|64 位|32 位|64-bit|32-bit)\)\s*$", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def _clean_name(name, fallback=""):
    s = (name or fallback or "").strip()
    s = re.sub(r"\s*[-–—]\s*快捷方式\s*$", "", s)
    s = re.sub(r"\s*快捷方式\s*$", "", s)
    s = re.sub(r"\s*\(new\)\s*$", "", s, flags=re.I)
    s = re.sub(r"\s*\(?x86\)?\s*$", "", s, flags=re.I)
    s = s.replace("®", "").replace("™", "").replace("©", "").strip()
    # "美图秀秀：AI修图与设计工具集" -> "美图秀秀"
    if "：" in s or ":" in s:
        head = re.split(r"[：:]", s)[0].strip()
        if 2 <= len(head) <= 16:
            s = head
    # "PyCharm 2025.3.6.1" / "Blender 5.0" -> 去掉尾随版本号
    trimmed = re.sub(r"\s+v?\d+(\.\d+)+.*$", "", s).strip()
    if len(trimmed) >= 2:
        s = trimmed
    return s.strip() or fallback


def _make_id(prefix, key):
    h = hashlib.sha1(("griddesk|" + prefix + "|" + key.lower()).encode("utf-8")).hexdigest()
    return h[:12]


_KEEP_NORM = {re.sub(r"\s+", "", k.lower()) for k in KEEP_NAMES}


def _classify(name, target=""):
    text = (name + " " + (target or "")).lower()
    if re.sub(r"\s+", "", (name or "").lower()) in _KEEP_NORM:
        return "系统"
    for cat, pattern in CATEGORY_RULES:
        try:
            if re.search(pattern, text, re.I):
                return cat
        except re.error:
            continue
    return "其他"


def _is_junk_name(name):
    norm = re.sub(r"\s+", "", (name or "").lower())
    if norm in _KEEP_NORM:
        return False
    return bool(JUNK_NAME.search(name or ""))


def _is_junk_target(target):
    return bool(JUNK_TARGET.search(target or ""))


def start_menu_dirs():
    dirs = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("ProgramData")
    if appdata:
        dirs.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if programdata:
        dirs.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    home = Path.home()
    desktop_dirs = [home / "Desktop", Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop"]
    for d in desktop_dirs:
        if d.exists():
            dirs.append(d)
    return [d for d in dirs if d.exists()]


def _iter_shortcuts():
    for base in start_menu_dirs():
        try:
            for p in base.rglob("*.lnk"):
                yield p
        except Exception:
            continue


class ShortcutResolver:
    """用 WScript.Shell 解析 .lnk。"""

    def __init__(self):
        self._shell = None

    def _get_shell(self):
        if self._shell is None:
            import win32com.client  # 延迟导入
            self._shell = win32com.client.Dispatch("WScript.Shell")
        return self._shell

    def resolve(self, lnk_path):
        try:
            sc = self._get_shell().CreateShortcut(str(lnk_path))
            return {
                "target": sc.TargetPath or "",
                "args": sc.Arguments or "",
                "workdir": sc.WorkingDirectory or "",
                "iconLocation": sc.IconLocation or "",
                "description": sc.Description or "",
            }
        except Exception:
            return {"target": "", "args": "", "workdir": "", "iconLocation": "", "description": ""}


def _dedupe(apps):
    seen_name = {}
    seen_target = {}
    out = []
    for app in apps:
        key = _norm_name(app["name"])
        if not key:
            continue
        target_key = (app.get("path") or "").lower()
        if key in seen_name:
            old = seen_name[key]
            if len(app.get("path") or "") > len(old.get("path") or ""):
                out[out.index(old)] = app
                seen_name[key] = app
            continue
        if target_key and target_key in seen_target:
            continue
        seen_name[key] = app
        if target_key:
            seen_target[target_key] = app
        out.append(app)
    return out


# 应用被人为搬家后，快捷方式可能还指着旧路径；在下面这些常见根目录里找回 exe
def _relocation_roots():
    roots = []
    env = os.environ
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        val = env.get(key)
        if val:
            roots.append(Path(val) / "Programs" if key == "LOCALAPPDATA" else Path(val))
    roots += [Path("D:/Apps"), Path("D:/Program Files"), Path("D:/Program Files (x86)"),
              Path("D:/"), Path("E:/Apps"), Path("E:/Program Files")]
    seen, out = set(), []
    for r in roots:
        try:
            key = str(r).lower()
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key)
        if r.exists():
            out.append(r)
    return out


# 这些文件名太通用，只按文件名找回容易张冠李戴
GENERIC_EXE_NAMES = {
    "launcher.exe", "start.exe", "app.exe", "main.exe", "run.exe", "update.exe",
    "helper.exe", "setup.exe", "application.exe", "program.exe", "client.exe",
    "game.exe", "platform.exe", "tool.exe", "tools.exe",
}


def _suffix_match_score(original, candidate):
    """从路径末尾开始数连续相同的分量个数。"""
    a = [p.lower() for p in Path(original).parts[1:]]
    b = [p.lower() for p in Path(candidate).parts[1:]]
    score = 0
    for x, y in zip(reversed(a), reversed(b)):
        if x == y:
            score += 1
        else:
            break
    return score


def find_relocated_exe(target):
    """快捷方式目标不存在时，按相对路径 / 文件名在常见目录里找回来。

    为避免误匹配（例如把 WeGame 指向别的 launcher.exe），要求候选路径
    与原始路径至少有 2 个连续同名分量，或文件名足够独特。
    """
    if not target:
        return None
    try:
        p = Path(os.path.expandvars(target))
    except Exception:
        return None
    if not p.name or p.is_dir():
        return None
    try:
        rel = p.relative_to(p.drive + os.sep) if p.drive else p
    except Exception:
        rel = Path(p.name)
    basename = p.name.lower()
    distinctive = basename not in GENERIC_EXE_NAMES and len(p.stem) >= 5
    for root in _relocation_roots():
        candidates = [root / rel, root / p.name]
        try:
            candidates += list(root.glob("*/" + p.name))[:6]
            candidates += list(root.glob("*/*/" + p.name))[:6]
        except Exception:
            pass
        for cand in candidates:
            try:
                if not cand.is_file():
                    continue
            except Exception:
                continue
            score = _suffix_match_score(p, cand)
            if score >= 2 or (score == 1 and distinctive):
                return str(cand)
    return None


def scan_shortcuts(resolver=None, log=None, include_all=False):
    """扫描开始菜单 + 桌面快捷方式。"""
    resolver = resolver or ShortcutResolver()
    apps = []
    broken = 0
    repaired = 0
    for lnk in _iter_shortcuts():
        raw_name = lnk.stem
        name = _clean_name(raw_name)
        if not name:
            continue
        if not include_all and _is_junk_name(name):
            continue
        info = resolver.resolve(lnk)
        target = info.get("target") or ""
        args = info.get("args") or ""
        if not include_all and _is_junk_target(target):
            continue
        if "shell:" in args.lower() and "explorer" in target.lower():
            continue
        if target.lower().endswith((".url", ".html", ".htm")):
            continue
        launch = {"type": "lnk", "target": str(lnk)}
        # 目标被移动过：尝试自动修复路径，修好后直接启动 exe（更可靠）
        if target and not os.path.exists(target):
            fixed = find_relocated_exe(target)
            if fixed:
                target = fixed
                repaired += 1
                launch = {"type": "exe", "target": fixed}
            else:
                broken += 1
                if log:
                    log("快捷方式已失效，跳过：%s -> %s" % (name, target))
                continue
        if not target:
            # 没有目标（部分系统项），保留快捷方式本身
            target = ""
        category = _classify(name, target)
        apps.append({
            "id": _make_id("lnk", str(lnk).lower()),
            "name": name,
            "category": category,
            "kind": "lnk",
            "iconSource": str(lnk),
            "iconLocation": info.get("iconLocation") or "",
            "launch": launch,
            "path": target,
            "args": args,
            "workdir": info.get("workdir") or "",
            "source": str(lnk),
            "repaired": launch["type"] == "exe",
        })
    apps = _dedupe(apps)
    if log:
        log("开始菜单/桌面：%d 个（自动修复路径 %d 个，失效跳过 %d 个）"
            % (len(apps), repaired, broken))
    return apps


def _run_powershell(script, timeout=60):
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=timeout, startupinfo=si,
        )
        return out.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def _package_dirs():
    """PackageFamilyName -> 安装目录（用于从 UWP 包内取高清图标）。"""
    script = (
        "$OutputEncoding=[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-AppxPackage | ForEach-Object { $_.PackageFamilyName + [char]9 + $_.InstallLocation }"
    )
    text = _run_powershell(script, timeout=40)
    out = {}
    for line in text.splitlines():
        if "\t" not in line:
            continue
        family, location = line.split("\t", 1)
        family, location = family.strip(), location.strip()
        if family and location:
            out[family] = location
    return out


def scan_uwp(log=None, include_all=False):
    """通过 Get-StartApps 枚举 UWP / Store 应用。"""
    script = (
        "$OutputEncoding=[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-StartApps | ForEach-Object { $_.Name + [char]9 + $_.AppID }"
    )
    text = _run_powershell(script)
    try:
        package_dirs = _package_dirs()
    except Exception:
        package_dirs = {}
    apps = []
    for line in text.splitlines():
        if "\t" not in line:
            continue
        name, aumid = line.split("\t", 1)
        name, aumid = name.strip(), aumid.strip()
        if not name or not aumid:
            continue
        if "\\" in aumid or aumid.lower().endswith(".exe"):
            continue
        if not re.search(r"[!_.]", aumid):
            continue
        if not include_all:
            if re.search(r"(?i)(^reset|重置|settings$)", name):
                continue
            if UWP_JUNK.search(name) and not UWP_KEEP.search(name):
                continue
            if _is_junk_name(name):
                continue
        category = _classify(name)  # UWP 只用名称分类
        name = _clean_name(name)
        family = aumid.split("!")[0]
        apps.append({
            "id": _make_id("uwp", aumid),
            "name": name,
            "category": category,
            "kind": "uwp",
            "iconSource": "shell:AppsFolder\\" + aumid,
            "installDir": package_dirs.get(family) or "",
            "aumid": aumid,
            "launch": {"type": "uwp", "target": aumid},
            "path": "",
            "args": "",
            "workdir": "",
            "source": "shell:AppsFolder\\" + aumid,
        })
    apps = _dedupe(apps)
    if log:
        log("UWP 应用：%d 个" % len(apps))
    return apps


def scan_all(log=None, include_all=False):
    """完整扫描：开始菜单优先，UWP 补充，最后按分类 + 名称排序。"""
    shortcuts = scan_shortcuts(log=log, include_all=include_all)
    try:
        uwp = scan_uwp(log=log, include_all=include_all)
    except Exception as e:
        if log:
            log("UWP 扫描失败：%s" % e)
        uwp = []
    existing = {_norm_name(a["name"]) for a in shortcuts}
    merged = list(shortcuts)
    for app in uwp:
        if _norm_name(app["name"]) in existing:
            continue
        merged.append(app)
    merged.sort(key=lambda a: (CATEGORY_ORDER.index(a["category"]) if a["category"] in CATEGORY_ORDER else 99,
                               a["name"].lower()))
    for i, app in enumerate(merged):
        app["order"] = i
    if log:
        log("合计：%d 个应用" % len(merged))
    return merged
