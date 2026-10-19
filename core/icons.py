# -*- coding: utf-8 -*-
"""方块桌面 · 图标 / 主色 / 封面图

- 用 Windows Shell 的 IShellItemImageFactory 抓 256×256 图标（支持 .lnk、.exe、
  UWP 的 shell:AppsFolder 条目），比 Icon.ExtractAssociatedIcon 的 32px 清楚得多。
- 从图标里算一个"品牌主色"，再用它生成一张专辑封面质感的方形封面图，
  磁贴直接铺这张封面，视觉上就接近参考图里的音乐封面墙。
"""
import colorsys
import ctypes
import ctypes.wintypes as wt
import hashlib
import math
import os
import threading
from ctypes import POINTER, byref, sizeof

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
gdi32 = ctypes.WinDLL("gdi32")
user32 = ctypes.WinDLL("user32")


# --------------------------------------------------------------------------- #
# 基础结构体
# --------------------------------------------------------------------------- #
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


IID_IShellItemImageFactory = GUID(
    0xBCC18B79, 0xBA16, 0x442F,
    (ctypes.c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B),
)


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long), ("bmPlanes", ctypes.c_ushort),
        ("bmBitsPixel", ctypes.c_ushort), ("bmBits", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_ulong), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_ulong), ("biSizeImage", ctypes.c_ulong),
        ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_ulong), ("biClrImportant", ctypes.c_ulong),
    ]


def _init_api():
    try:
        shell32.SHCreateItemFromParsingName.argtypes = [
            wt.LPCWSTR, ctypes.c_void_p, POINTER(GUID), POINTER(ctypes.c_void_p)]
        shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
        shell32.SHGetFileInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.c_void_p,
                                           ctypes.c_uint, ctypes.c_uint]
        shell32.SHGetFileInfoW.restype = ctypes.c_void_p
        gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        gdi32.GetObjectW.restype = ctypes.c_int
        gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        gdi32.GetDIBits.restype = ctypes.c_int
        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.GetDC.restype = ctypes.c_void_p
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.DeleteObject.restype = ctypes.c_int
    except Exception:
        pass


_init_api()

_tls = threading.local()


def _ensure_com():
    """每个线程调用一次 CoInitializeEx（STA），Shell 接口需要。"""
    if getattr(_tls, "com_ready", False):
        return
    try:
        ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    except Exception:
        pass
    _tls.com_ready = True


# --------------------------------------------------------------------------- #
# 图标提取
# --------------------------------------------------------------------------- #
def _hbitmap_to_image(hbm):
    bmp = BITMAP()
    if not gdi32.GetObjectW(hbm, sizeof(bmp), byref(bmp)):
        return None
    w, h = int(bmp.bmWidth), int(bmp.bmHeight)
    if w <= 0 or h <= 0:
        return None
    bi = BITMAPINFOHEADER()
    bi.biSize = sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = user32.GetDC(None)
    got = gdi32.GetDIBits(hdc, hbm, 0, h, buf, byref(bi), 0)
    user32.ReleaseDC(None, hdc)
    if got == 0:
        return None
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4).astype(np.uint16)  # BGRA
    alpha = arr[:, :, 3:4]
    rgb = arr[:, :, :3]
    # HBITMAP 里的颜色是预乘 alpha 的，转回直通 alpha
    safe = np.maximum(alpha, 1)
    rgb = np.clip(rgb.astype(np.float32) * 255.0 / safe, 0, 255).astype(np.uint8)
    out = np.dstack([rgb[:, :, 2], rgb[:, :, 1], rgb[:, :, 0], arr[:, :, 3].astype(np.uint8)])
    return Image.fromarray(out, "RGBA")


def get_icon(source, size=256):
    """从任意 shell 路径取图标，返回 RGBA 图像；失败返回 None。"""
    if not source:
        return None
    _ensure_com()
    p = ctypes.c_void_p()
    try:
        hr = shell32.SHCreateItemFromParsingName(
            ctypes.c_wchar_p(source), None, byref(IID_IShellItemImageFactory), byref(p))
    except Exception:
        return None
    if hr != 0 or not p:
        return None
    try:
        vtable = ctypes.cast(p, POINTER(POINTER(ctypes.c_void_p))).contents
        GetImage = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_uint,
                                      POINTER(ctypes.c_void_p))(vtable[3])
        hbm = ctypes.c_void_p()
        SIIGBF_ICONONLY = 0x4
        SIIGBF_BIGGERSIZEOK = 0x1
        hr2 = GetImage(p, SIZE(size, size), SIIGBF_ICONONLY | SIIGBF_BIGGERSIZEOK, byref(hbm))
        if hr2 != 0 or not hbm:
            return None
        try:
            img = _hbitmap_to_image(hbm)
        finally:
            gdi32.DeleteObject(hbm)
        return img
    except Exception:
        return None
    finally:
        try:
            Rel = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
            Rel(p)
        except Exception:
            pass


def icon_coverage(img):
    """图标不透明像素占比，用来判断是不是抓到了空白图标。"""
    if img is None:
        return 0.0
    a = np.asarray(img.getchannel("A"))
    return float(np.count_nonzero(a > 24)) / float(a.size)


def trim_icon(img):
    """裁掉图标四周多余透明边，让它铺满画布。"""
    if img is None:
        return None
    bbox = img.getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    # 留一点呼吸空间，避免边缘被裁断
    pad = int(max(x1 - x0, y1 - y0) * 0.02)
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(img.width, x1 + pad), min(img.height, y1 + pad)
    crop = img.crop((x0, y0, x1, y1))
    side = max(crop.width, crop.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2), crop)
    return canvas


# --------------------------------------------------------------------------- #
# 通用"未知文件"图标识别
#   某些应用（尤其 UWP、或快捷方式找不到目标时）会让 Shell 返回一张
#   白纸图标。如果直接拿来当封面会很丑，这里用感知哈希把它识别出来。
# --------------------------------------------------------------------------- #
_generic_lock = threading.Lock()
_generic_hashes = None


def _dhash(img, n=16):
    im = img.convert("L").resize((n, n), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float32)
    return (arr > arr.mean()).astype(np.uint8).flatten()


def _hamming(a, b):
    return int(np.count_nonzero(a != b))


def generic_icon_hashes():
    global _generic_hashes
    with _generic_lock:
        if _generic_hashes is not None:
            return _generic_hashes
        refs = []
        try:
            from .store import CACHE_DIR
            probe_dir = CACHE_DIR / "_probe"
            probe_dir.mkdir(parents=True, exist_ok=True)
            samples = [("unknown" + ".zzz", b""), ("unknown" + ".exe", b"MZ" + b"\x00" * 64)]
            for filename, payload in samples:
                path = probe_dir / filename
                try:
                    path.write_bytes(payload)
                    img = get_icon(str(path))
                    if img is not None and icon_coverage(img) > 0.05:
                        refs.append(_dhash(img))
                except Exception:
                    pass
                finally:
                    try:
                        path.unlink()
                    except Exception:
                        pass
        except Exception:
            pass
        _generic_hashes = refs
        return refs


def is_generic_icon(img):
    """判断是不是 Windows 的"未知文件"白纸图标。"""
    if img is None:
        return True
    if icon_coverage(img) < 0.004:
        return True
    h = _dhash(img)
    for ref in generic_icon_hashes():
        if _hamming(h, ref) <= 10:
            return True
    return False


def load_image_icon(path):
    """直接读取 .ico / .png / .jpg 图标文件（.ico 会取最大尺寸）。"""
    try:
        im = Image.open(path)
        im.load()
        if im.format == "ICO":
            try:
                sizes = sorted(im.ico.sizes())
                if sizes:
                    im.size = sizes[-1]
                    im.load()
            except Exception:
                pass
        return im.convert("RGBA")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# UWP 应用图标：从 AppxManifest.xml 找高清 logo
# --------------------------------------------------------------------------- #
def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def uwp_logo_icon(install_dir, aumid):
    if not install_dir or not aumid:
        return None
    try:
        from pathlib import Path
        import xml.etree.ElementTree as ET
    except Exception:
        return None
    root_dir = Path(install_dir)
    manifest = root_dir / "AppxManifest.xml"
    if not manifest.exists():
        return None
    try:
        tree = ET.parse(str(manifest))
    except Exception:
        return None
    app_id = aumid.split("!")[1] if "!" in aumid else ""
    logos = []
    for el in tree.getroot().iter():
        if _local_name(el.tag) != "Application":
            continue
        el_id = ""
        for key, value in el.attrib.items():
            if _local_name(key) == "Id":
                el_id = value
        if app_id and el_id and el_id != app_id:
            continue
        for sub in el.iter():
            if _local_name(sub.tag) != "VisualElements":
                continue
            for key, value in sub.attrib.items():
                if _local_name(key) in ("Square44x44Logo", "Square150x150Logo", "Logo"):
                    logos.append(value)
    if not logos:
        for el in tree.getroot().iter():
            for key, value in el.attrib.items():
                if _local_name(key) in ("Square44x44Logo", "Square150x150Logo"):
                    logos.append(value)
    best = None
    for rel in logos:
        rel = rel.replace("/", "\\")
        rel_base = rel.rsplit(".", 1)[0]
        candidates = []
        try:
            direct = root_dir / rel
            if direct.exists():
                candidates.append(direct)
            for cand in root_dir.glob(rel_base + "*.png"):
                candidates.append(cand)
        except Exception:
            pass
        for cand in candidates:
            try:
                im = Image.open(str(cand))
                im.load()
                score = im.size[0] * im.size[1]
                if best is None or score > best[0]:
                    best = (score, im.convert("RGBA"))
            except Exception:
                continue
    return best[1] if best else None


# --------------------------------------------------------------------------- #
# 颜色工具
# --------------------------------------------------------------------------- #
def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def hex_to_rgb(value, default=(110, 150, 255)):
    try:
        s = (value or "").lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            return default
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(_clamp(v, 0, 255)) for v in rgb)


def mix(c1, c2, t):
    t = _clamp(t)
    return tuple(c1[i] * (1 - t) + c2[i] * t for i in range(3))


def shift_rgb(rgb, dh=0.0, ds=0.0, dv=0.0):
    h, s, v = colorsys.rgb_to_hsv(*[c / 255.0 for c in rgb])
    h = (h + dh) % 1.0
    s = _clamp(s + ds)
    v = _clamp(v + dv)
    return tuple(c * 255.0 for c in colorsys.hsv_to_rgb(h, s, v))


def _hsv(rgb):
    return colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)


def _normalize_accent(rgb):
    """把品牌色调成适合深色底的强调色：够饱和、亮度适中。"""
    h, s, v = _hsv(rgb)
    if s < 0.06:  # 灰白黑图标：给一个稳定的品牌色
        h = (h + 0.58) % 1.0
        s = 0.52
        v = 0.68
    else:
        s = _clamp(max(s, 0.42), 0.0, 0.92)
        v = _clamp(v, 0.54, 0.76)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def compute_accent(img, fallback_seed=""):
    """从图标里提取主色：按色相分桶加权，挑出最"显眼"的颜色。"""
    if img is None or img.size[0] < 8:
        rgb = (95, 140, 255)
    else:
        small = img.convert("RGBA").resize((48, 48), Image.LANCZOS)
        arr = np.asarray(small).astype(np.float32) / 255.0
        pixels = arr.reshape(-1, 4)
        buckets = {}
        for r, g, b, a in pixels:
            if a < 0.55:
                continue
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            if v < 0.18 or v > 0.97 or s < 0.12:
                continue
            weight = (s ** 1.4) * (1.0 - abs(v - 0.6) * 1.3)
            if weight <= 0:
                continue
            key = int(h * 24) % 24
            slot = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0])
            slot[0] += weight
            slot[1] += r * weight
            slot[2] += g * weight
            slot[3] += b * weight
        if buckets:
            best = max(buckets.values(), key=lambda s: s[0])
            total = best[0]
            rgb = (best[1] / total * 255.0, best[2] / total * 255.0, best[3] / total * 255.0)
        else:
            rgb = (95, 140, 255)
    accent = _normalize_accent(rgb)
    if fallback_seed and accent == (0, 0, 0):
        h = (int(hashlib.sha1(fallback_seed.encode("utf-8")).hexdigest()[:6], 16) % 360) / 360.0
        accent = tuple(c * 255 for c in colorsys.hsv_to_rgb(h, 0.55, 0.7))
    return rgb_to_hex(accent)


# --------------------------------------------------------------------------- #
# 回退图标（首字母/首字磁贴）
# --------------------------------------------------------------------------- #
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
]
_font_cache = {}


def _load_font(size):
    if size in _font_cache:
        return _font_cache[size]
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _font_cache[size] = font
                return font
            except Exception:
                continue
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def make_letter_icon(name, accent_hex, size=256):
    accent = hex_to_rgb(accent_hex)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = int(size * 0.22)
    top = mix(accent, (255, 255, 255), 0.16)
    bottom = mix(accent, (0, 0, 0), 0.34)
    for y in range(size):
        t = y / max(1, size - 1)
        draw.line([(0, y), (size, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    img.putalpha(mask)
    text = (name or "A").strip()
    if not text:
        text = "A"
    text = text[0].upper() if re_ascii(text[0]) else text[0]
    font = _load_font(int(size * 0.46))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - size * 0.01), text,
              font=font, fill=(255, 255, 255, 242))
    return img


def re_ascii(ch):
    return ord(ch) < 128


# --------------------------------------------------------------------------- #
# 封面生成
# --------------------------------------------------------------------------- #
def _gradient_array(size, c1, c2, angle=118.0):
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / max(1, size - 1)
    a = math.radians(angle)
    t = xx * math.cos(a) + yy * math.sin(a)
    t = (t - t.min()) / max(1e-6, (t.max() - t.min()))
    t = t ** 1.15
    arr = (np.array(c1, np.float32)[None, None, :] * (1 - t[..., None])
           + np.array(c2, np.float32)[None, None, :] * t[..., None])
    return np.clip(arr, 0, 255).astype(np.uint8)


def _radial(size, cx, cy, radius, power=2.0):
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / max(1, size - 1)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(1e-6, radius)
    return np.clip(1.0 - d, 0.0, 1.0) ** power


def _rounded_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return np.asarray(mask).astype(np.float32) / 255.0


def make_cover(icon, accent_hex, seed=0, size=512):
    """生成一张 512×512、有专辑封面质感的方形封面。"""
    _ensure_com()
    accent = np.array(hex_to_rgb(accent_hex), np.float32)
    rng = np.random.default_rng(seed & 0xFFFFFFFF)
    dark1 = np.array(mix(accent, (7, 9, 14), 0.72), np.float32)
    dark2 = np.array(mix(shift_rgb(accent, dh=0.085, ds=-0.16, dv=-0.46), (4, 5, 9), 0.62), np.float32)
    arr = _gradient_array(size, dark1, dark2, angle=104 + (seed % 48)).astype(np.float32)

    # 左上角光晕
    glow = _radial(size, 0.26, 0.14, 0.86, 1.5)[..., None]
    gleam = mix(accent, (255, 255, 255), 0.18)
    arr += glow * np.array(gleam, np.float32)[None, None, :] * 0.22

    # 中部径向提亮
    core = _radial(size, 0.5, 0.46, 0.66, 2.1)[..., None]
    arr += core * accent[None, None, :] * 0.18
    arr = np.clip(arr, 0, 255)
    base = Image.fromarray(arr.astype(np.uint8), "RGB").convert("RGBA")

    # 环境层：把图标放大、模糊后铺底，形成"封面里的画面"
    if icon is not None:
        amb = icon.copy()
        amb_side = int(size * (1.10 + (seed % 5) * 0.015))
        amb = amb.resize((amb_side, amb_side), Image.LANCZOS)
        amb = amb.filter(ImageFilter.GaussianBlur(size * 0.078))
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ox = int((size - amb_side) / 2 + (seed % 7 - 3) * size * 0.008)
        oy = int((size - amb_side) / 2 - size * 0.02 + (seed % 5 - 2) * size * 0.008)
        layer.paste(amb, (ox, oy), amb)
        a = np.asarray(layer.getchannel("A")).astype(np.float32) * 0.40
        layer.putalpha(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)))
        base = Image.alpha_composite(base, layer)

        # 清晰图标 + 投影
        ico_side = int(size * 0.38)
        ico = icon.resize((ico_side, ico_side), Image.LANCZOS)
        shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        silhouette = Image.new("RGBA", ico.size, (2, 4, 8, 255))
        silhouette.putalpha(ico.getchannel("A").point(lambda v: int(v * 0.62)))
        sx = (size - ico_side) // 2
        sy = (size - ico_side) // 2 + int(size * 0.016)
        shadow.paste(silhouette, (sx, sy), silhouette)
        shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.028))
        base = Image.alpha_composite(base, shadow)
        base.paste(ico, (sx, sy - int(size * 0.006)), ico)

    # 顶部高光 + 暗角
    arr = np.asarray(base.convert("RGB")).astype(np.float32)
    sheen = _radial(size, 0.18, -0.08, 0.95, 1.2)[..., None] * 255.0 * 0.07
    arr = arr + sheen
    vign = 1.0 - 0.50 * (1.0 - _radial(size, 0.5, 0.46, 1.02, 1.25))[..., None]
    arr = arr * vign
    # 细颗粒，消除色彩断层
    noise = rng.normal(0.0, 3.0, (size, size, 1))
    arr = arr + noise
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def make_wallpaper(src_path, out_path, size=(1760, 1100)):
    """把壁纸处理成深色、模糊、可铺满窗口的背景图。"""
    try:
        src = Image.open(src_path).convert("RGB")
    except Exception:
        return None
    tw, th = size
    sw, sh = src.size
    scale = max(tw / sw, th / sh)
    src = src.resize((max(tw, int(sw * scale + 0.5)), max(th, int(sh * scale + 0.5))), Image.LANCZOS)
    left = (src.width - tw) // 2
    top = (src.height - th) // 2
    src = src.crop((left, top, left + tw, top + th))
    src = src.filter(ImageFilter.GaussianBlur(30))
    arr = np.asarray(src).astype(np.float32)
    arr = arr * 0.54
    # 轻微降低对比、加一点点冷色，和玻璃卡片更协调
    arr = (arr - 128) * 0.92 + 126
    arr[:, :, 2] = np.clip(arr[:, :, 2] * 1.06, 0, 255)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    out = Image.fromarray(arr, "RGB")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.save(out_path, "JPEG", quality=86, optimize=True)
    return out_path
