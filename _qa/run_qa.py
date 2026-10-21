# -*- coding: utf-8 -*-
"""方块桌面 · 黑盒 QA 脚本（CDP + HTTP）。"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

import websocket

BASE = "http://127.0.0.1:8901"
CDP = "http://127.0.0.1:9337"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT = {"checks": [], "console": [], "network_errors": [], "screenshots": []}


def add(name, status, detail="", **extra):
    item = {"name": name, "status": status, "detail": detail}
    item.update(extra)
    REPORT["checks"].append(item)
    print("[%s] %s %s" % (status.upper(), name, ("- " + str(detail))[:200]), flush=True)


def http(path, method="GET", body=None, timeout=20):
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return {"status": resp.status, "headers": dict(resp.headers), "body": raw}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "headers": dict(e.headers), "body": e.read()}
    except Exception as e:
        return {"status": 0, "error": repr(e)}


def http_json(path, method="GET", body=None, timeout=20):
    r = http(path, method=method, body=body, timeout=timeout)
    try:
        r["json"] = json.loads(r["body"].decode("utf-8"))
    except Exception:
        r["json"] = None
    return r


class Browser:
    def __init__(self):
        targets = json.load(urllib.request.urlopen(CDP + "/json", timeout=10))
        pages = [t for t in targets if t.get("type") == "page"]
        if not pages:
            raise SystemExit("no CDP page")
        self.page = pages[0]
        self.ws = websocket.create_connection(self.page["webSocketDebuggerUrl"], timeout=40)
        self.mid = 0
        self.console = []
        self.network_errors = []
        self._pending = {}
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Log.enable")
        self.send("Network.enable")

    def send(self, method, params=None, timeout=40):
        self.mid += 1
        mid = self.mid
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        start = time.time()
        while True:
            msg = json.loads(self.ws.recv())
            self._capture(msg)
            if msg.get("id") == mid:
                return msg
            if time.time() - start > timeout:
                raise TimeoutError(method)

    def _capture(self, msg):
        method = msg.get("method")
        if method == "Runtime.consoleAPICalled":
            typ = msg["params"].get("type")
            if typ in ("error", "warning", "assert"):
                args = []
                for a in msg["params"].get("args", []):
                    v = a.get("value", a.get("description", a.get("type")))
                    args.append(str(v)[:300])
                self.console.append({"type": typ, "text": " ".join(args)})
        elif method == "Runtime.exceptionThrown":
            d = msg["params"].get("exceptionDetails", {})
            self.console.append({"type": "exception", "text": str(d.get("text")) + " " +
                                 str((d.get("exception") or {}).get("description", ""))[:400]})
        elif method == "Log.entryAdded":
            entry = msg["params"]["entry"]
            if entry.get("level") in ("error",):
                self.console.append({"type": "log-error", "text": entry.get("text", "")[:400]})
        elif method == "Network.loadingFailed":
            p = msg["params"]
            if not p.get("canceled"):
                self.network_errors.append({"url": p.get("url", ""), "error": p.get("errorText", "")})
        elif method == "Network.responseReceived":
            p = msg["params"]
            status = p["response"].get("status", 0)
            url = p["response"].get("url", "")
            if status >= 400 and "127.0.0.1" in url:
                self.network_errors.append({"url": url, "status": status})

    def drain(self, seconds=0.5):
        self.ws.settimeout(seconds)
        try:
            while True:
                msg = json.loads(self.ws.recv())
                self._capture(msg)
        except Exception:
            pass
        finally:
            self.ws.settimeout(40)

    def evaluate(self, expression, timeout=40):
        res = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                             "awaitPromise": True, "timeout": timeout * 1000})
        result = res.get("result", {})
        if "exceptionDetails" in result:
            raise RuntimeError(str(result["exceptionDetails"])[:500])
        return result.get("result", {}).get("value")

    def navigate(self, url):
        self.send("Page.navigate", {"url": url})
        time.sleep(0.6)
        for _ in range(80):
            try:
                ready = self.evaluate("document.readyState")
                tiles = self.evaluate("document.querySelectorAll('.tile').length")
            except Exception:
                ready, tiles = "", 0
            if ready == "complete" and (tiles or 0) > 0:
                return True
            time.sleep(0.25)
        return False

    def emulate(self, width, height):
        self.send("Emulation.setDeviceMetricsOverride", {
            "width": int(width), "height": int(height), "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.6)

    def screenshot(self, name):
        res = self.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        path = os.path.join(OUT_DIR, name)
        with open(path, "wb") as f:
            f.write(base64.b64decode(res["result"]["data"]))
        REPORT["screenshots"].append(name)
        return path


def wait_tiles(browser, min_count=1, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        try:
            n = browser.evaluate("document.querySelectorAll('.tile').length")
            if n >= min_count:
                return n
        except Exception:
            pass
        time.sleep(0.3)
    return 0


# ---------------------------------------------------------------- 基础检查
def check_server_http():
    r = http_json("/api/ping")
    ok = r["status"] == 200 and r["json"] and r["json"].get("code") == "GridDesk"
    add("服务可访问 /api/ping", "pass" if ok else "fail", "status=%s" % r["status"])

    b = http_json("/api/bootstrap", timeout=40)
    boot = b["json"] or {}
    if b["status"] == 200 and boot.get("apps"):
        apps = boot["apps"]
        add("bootstrap 数据", "pass",
            "apps=%d categories=%d pinned=%d" % (len(apps), len(boot.get("categories") or []),
                                                 len([a for a in apps if a.get("pinned")])))
        # 数据结构完整性
        required = {"id", "name", "category", "kind", "accent", "pinned", "hidden",
                    "launchCount", "lastLaunch", "running"}
        missing = [a.get("id") for a in apps if not required.issubset(a.keys())]
        add("应用字段完整性", "pass" if not missing else "fail",
            "缺字段的应用 %d 个" % len(missing))
        bad_cover = [a["name"] for a in apps if not a.get("cover")]
        bad_icon = [a["name"] for a in apps if not a.get("icon")]
        add("图标/封面字段", "pass" if not (bad_cover or bad_icon) else "fail",
            "缺封面=%d 缺图标=%d" % (len(bad_cover), len(bad_icon)))
        fallback = [a["name"] for a in apps if a.get("fallbackIcon")]
        add("图标兜底检测", "pass" if not fallback else "warn",
            "使用字母兜底的应用: %s" % (", ".join(fallback[:5]) or "无"))
        # 检查资源可访问
        bad = []
        for a in apps:
            for key in ("icon", "cover"):
                url = a.get(key)
                if not url:
                    continue
                rr = http(url, timeout=15)
                if rr["status"] != 200 or len(rr["body"]) < 500:
                    bad.append((a["name"], key, rr["status"], len(rr["body"])))
        add("全部图标/封面可访问", "pass" if not bad else "fail",
            "异常 %d 个 %s" % (len(bad), bad[:3]))
        # 统计一致性
        visible = [a for a in apps if not a.get("hidden")]
        stats = boot.get("stats") or {}
        add("统计数字一致", "pass" if stats.get("total") == len(visible) else "fail",
            "stats.total=%s visible=%d" % (stats.get("total"), len(visible)))
        return boot
    add("bootstrap 数据", "fail", "status=%s" % b["status"])
    return {}


def check_http_assets():
    for path, kws in (("/", ("app.js", "app.css")), ("/app.css", ()), ("/app.js", ()),
                      ("/brand.png", ())):
        r = http(path)
        ok = r["status"] == 200 and len(r["body"]) > 100
        if path == "/":
            ok = ok and all(k.encode() in r["body"] for k in kws)
        add("静态资源 %s" % path, "pass" if ok else "fail",
            "status=%s size=%d" % (r["status"], len(r["body"])))
    for path in ("/assets/icons/not-exist.png", "/assets/nope.jpg", "/api/not-exist"):
        r = http(path)
        add("未知路径返回 404 (%s)" % path, "pass" if r["status"] == 404 else "warn",
            "status=%s" % r["status"])


def check_api_errors():
    r = http_json("/api/app/not-exist-id", method="PATCH", body={"name": "x"})
    add("PATCH 不存在的应用返回 404", "pass" if r["status"] in (400, 404) else "warn",
        "status=%s" % r["status"])
    r = http_json("/api/launch", method="POST", body={"id": "not-exist-id"})
    add("启动不存在的应用有兜底", "pass" if r["status"] in (400, 404) else "warn",
        "status=%s body=%s" % (r["status"], (r["body"] or b"")[:80]))
    r = http_json("/api/settings", method="POST", body={"settings": {"layout": "bad-value"}})
    add("非法设置值有处理", "pass" if r["status"] in (200, 400) else "warn",
        "status=%s" % r["status"])


# ---------------------------------------------------------------- UI 检查
BASE_JS = r"""
window.__qa = {
  tiles: () => Array.from(document.querySelectorAll('.tile')),
  rect: (el) => { const r = el.getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height, right:r.right, bottom:r.bottom}; },
  overlaps: (a, b, tol) => !(a.right <= b.x + tol || b.right <= a.x + tol || a.bottom <= b.y + tol || b.bottom <= a.y + tol),
  state: () => ({
    w: innerWidth, h: innerHeight,
    tiles: document.querySelectorAll('.tile').length,
    spans: Array.from(document.querySelectorAll('.tile')).map(t => (t.style.gridColumn || '') + '|' + (t.style.gridRow || '')),
    c: getComputedStyle(document.getElementById('grid')).getPropertyValue('--c').trim(),
    tile: getComputedStyle(document.getElementById('grid')).getPropertyValue('--tile').trim(),
    gap: getComputedStyle(document.getElementById('grid')).getPropertyValue('--gap').trim(),
    layoutSeg: (document.querySelector('#layoutSeg button.is-active') || {}).dataset,
  }),
};
'ok'
"""


def check_ui_basic(browser):
    browser.navigate(BASE + "/")
    browser.evaluate(BASE_JS)
    st = browser.evaluate("window.__qa.state()")
    add("页面加载与磁贴渲染", "pass" if st["tiles"] >= 10 else "fail",
        "tiles=%d c=%s tile=%s" % (st["tiles"], st["c"], st["tile"]))

    # 磁贴几何：方形、无重叠、在容器内
    geo = browser.evaluate(r"""(() => {
      const tiles = window.__qa.tiles();
      const rects = tiles.map(t => window.__qa.rect(t));
      const wrap = document.getElementById('gridWrap').getBoundingClientRect();
      const badSquare = rects.filter(r => Math.abs(r.w - r.h) > 1.5).length;
      let overlaps = 0;
      for (let i = 0; i < rects.length; i++) {
        for (let j = i + 1; j < rects.length; j++) {
          if (window.__qa.overlaps(rects[i], rects[j], 0.8)) overlaps++;
        }
      }
      const outside = rects.filter(r => r.x < -1 || r.right > innerWidth + 1).length;
      return {count: rects.length, badSquare, overlaps, outside,
              minW: Math.min(...rects.map(r => r.w)), maxW: Math.max(...rects.map(r => r.w)),
              wrapW: wrap.width};
    })()""")
    add("磁贴为正方形", "pass" if geo["badSquare"] == 0 else "fail",
        "%d/%d 个非正方形" % (geo["badSquare"], geo["count"]))
    add("磁贴无重叠", "pass" if geo["overlaps"] == 0 else "fail", "重叠对=%d" % geo["overlaps"])
    add("磁贴不超出视口", "pass" if geo["outside"] == 0 else "fail", "越界=%d" % geo["outside"])

    # 竖栏、卡片位置
    layout = browser.evaluate(r"""(() => {
      const nav = document.querySelector('.nav-center').getBoundingClientRect();
      const card = document.getElementById('cornerCard').getBoundingClientRect();
      const wall = document.getElementById('gridWrap').getBoundingClientRect();
      const rec = document.getElementById('recentCard').getBoundingClientRect();
      const right = document.querySelector('.bottom-right').getBoundingClientRect();
      return {
        navW: nav.width, navCenterDiff: Math.abs((nav.x + nav.width/2) - innerWidth/2),
        navH: nav.height, navTop: nav.top, navBottom: nav.bottom,
        cardX: card.x, cardRight: card.right, cardBottom: card.bottom, wallRight: wall.right, wallTop: wall.top,
        cardVisible: getComputedStyle(document.getElementById('cornerCard')).display !== 'none',
        recRight: rec.right, recBottom: rec.bottom, rightLeft: right.x, rightRight: right.right, rightBottom: right.bottom,
        innerW: innerWidth, innerH: innerHeight,
      };
    })()""")
    add("中间竖栏水平居中", "pass" if layout["navCenterDiff"] < 2 else "fail",
        "偏离中心 %.1fpx（宽 %.0f）" % (layout["navCenterDiff"], layout["navW"]))
    add("中间竖栏贴满高度", "pass" if abs(layout["navTop"] - 10) < 3 and abs(layout["innerH"] - layout["navBottom"] - 10) < 3 else "warn",
        "top=%.1f bottom=%.1f innerH=%d" % (layout["navTop"], layout["navBottom"], layout["innerH"]))
    add("右上角卡片位置", "pass" if layout["cardVisible"] and abs(layout["cardRight"] - layout["wallRight"]) < 3 else "warn",
        "visible=%s right=%.1f wallRight=%.1f" % (layout["cardVisible"], layout["cardRight"], layout["wallRight"]))
    add("底部卡片不溢出", "pass" if layout["recRight"] <= layout["innerW"] and layout["rightRight"] <= layout["innerW"] + 1 else "fail",
        "recentRight=%.1f rightGroupRight=%.1f" % (layout["recRight"], layout["rightRight"]))
    add("底部两组卡片不重叠", "pass" if layout["recRight"] <= layout["rightLeft"] + 1 else "fail",
        "recent.right=%.1f bottomRight.left=%.1f" % (layout["recRight"], layout["rightLeft"]))
    return st, layout


def check_layouts(browser):
    # 方格
    browser.evaluate("document.querySelector('#layoutSeg button[data-layout=square]').click()")
    time.sleep(0.9)
    sq = browser.evaluate(r"""(() => {
      const s = window.__qa.state();
      const spans = window.__qa.tiles().map(t => t.style.gridColumn + ' ' + t.style.gridRow);
      return {tile: s.tile, c: s.c, big: spans.filter(x => x.includes('span 2')).length,
              squareBad: window.__qa.tiles().filter(t => { const r = t.getBoundingClientRect(); return Math.abs(r.width - r.height) > 1.5; }).length};
    })()""")
    add("方格布局：无 2×2 磁贴", "pass" if sq["big"] == 0 else "fail", "2×2 数量=%d" % sq["big"])
    add("方格布局：磁贴仍为正方形", "pass" if sq["squareBad"] == 0 else "fail", "非正方形=%d" % sq["squareBad"])

    # 拼贴
    browser.evaluate("document.querySelector('#layoutSeg button[data-layout=collage]').click()")
    time.sleep(0.9)
    co = browser.evaluate(r"""(() => {
      const spans = window.__qa.tiles().map(t => t.style.gridColumn + ' ' + t.style.gridRow);
      const s = window.__qa.state();
      const bigRects = window.__qa.tiles().filter(t => t.style.gridColumn.includes('span 2')).map(t => window.__qa.rect(t));
      return {big: bigRects.length, tile: s.tile,
              bigSquare: bigRects.filter(r => Math.abs(r.w - r.h) > 2).length,
              bigOverlap: (() => { let n = 0; const all = window.__qa.tiles().map(t => window.__qa.rect(t));
                for (let i=0;i<all.length;i++) for (let j=i+1;j<all.length;j++) if (window.__qa.overlaps(all[i],all[j],0.8)) n++; return n; })()};
    })()""")
    add("拼贴布局：固定应用 2×2", "pass" if co["big"] >= 2 else "warn", "2×2 数量=%d" % co["big"])
    add("拼贴布局：大磁贴仍为正方形", "pass" if co["bigSquare"] == 0 else "fail", "非正方形=%d" % co["bigSquare"])
    add("拼贴布局：无重叠", "pass" if co["bigOverlap"] == 0 else "fail", "重叠对=%d" % co["bigOverlap"])

    # 紧凑
    browser.evaluate("document.querySelector('#layoutSeg button[data-layout=compact]').click()")
    time.sleep(0.9)
    cp = browser.evaluate(r"""(() => {
      const s = window.__qa.state();
      const subVisible = Array.from(document.querySelectorAll('.tile-sub')).filter(e => getComputedStyle(e).display !== 'none').length;
      return {tile: s.tile, c: s.c, subVisible};
    })()""")
    add("紧凑布局：隐藏副标题", "pass" if cp["subVisible"] == 0 else "warn", "可见副标题=%d" % cp["subVisible"])
    browser.evaluate("document.querySelector('#layoutSeg button[data-layout=collage]').click()")
    time.sleep(0.8)
    return sq, co, cp


def check_views(browser, orig_boot):
    counts = {}
    for view, expect in (("pinned", 4), ("recent", 0), ("categories", 52), ("all", 52)):
        browser.evaluate("document.querySelector('.rail-item[data-view=%s]').click()" % view)
        time.sleep(0.8)
        n = wait_tiles(browser, 0)
        empty = browser.evaluate("!document.getElementById('empty').hidden")
        counts[view] = {"tiles": n, "empty": empty}
    pinned_count = len([a for a in (orig_boot.get("apps") or []) if a.get("pinned")])
    add("常用视图渲染", "pass" if counts["pinned"]["tiles"] >= pinned_count else "warn",
        "tiles=%d（固定 %d 个；常用视图=固定+使用过的）" % (counts["pinned"]["tiles"], pinned_count))
    # 「最近」视图：没有使用记录时应该显示空状态；有记录时应该出现磁贴
    boot_has_launch = any((a.get("lastLaunch") or 0) > 0 for a in (orig_boot.get("apps") or []))
    if boot_has_launch:
        add("最近视图显示使用记录", "pass" if counts["recent"]["tiles"] >= 1 else "fail",
            "tiles=%d（有使用记录时应 >0）" % counts["recent"]["tiles"])
    else:
        add("最近视图空状态", "pass" if counts["recent"]["empty"] else "warn",
            "tiles=%d empty=%s" % (counts["recent"]["tiles"], counts["recent"]["empty"]))
    add("分类视图渲染", "pass" if counts["categories"]["tiles"] >= 40 else "warn",
        "tiles=%d" % counts["categories"]["tiles"])
    add("全部视图渲染", "pass" if counts["all"]["tiles"] == 52 else "warn",
        "tiles=%d" % counts["all"]["tiles"])

    # 分类视图 chips
    browser.evaluate("document.querySelector('.rail-item[data-view=categories]').click()")
    time.sleep(0.8)
    chips = browser.evaluate(r"""(() => {
      const box = document.getElementById('chips');
      return {hidden: box.hidden, count: box.querySelectorAll('.chip').length,
              infoHidden: document.getElementById('viewInfo').hidden};
    })()""")
    add("分类筛选条出现", "pass" if (not chips["hidden"] and chips["count"] >= 10) else "fail",
        "hidden=%s chips=%d" % (chips["hidden"], chips["count"]))
    add("分类视图隐藏视图信息卡", "pass" if chips.get("infoHidden") else "warn", "infoHidden=%s" % chips.get("infoHidden"))

    # 点击第一个分类
    if chips["count"]:
        browser.evaluate("document.querySelector('#chips .chip:nth-child(2)').click()")
        time.sleep(0.9)
        cat = browser.evaluate(r"""(() => ({
          tiles: document.querySelectorAll('.tile').length,
          active: (document.querySelector('#chips .chip.is-active') || {}).textContent || '',
          title: document.getElementById('viewTitle').textContent,
        }))()""")
        add("分类筛选生效", "pass" if cat["tiles"] >= 1 else "fail",
            "tiles=%d active=%s" % (cat["tiles"], cat["active"].strip()[:20]))
    browser.evaluate("document.querySelector('.rail-item[data-view=all]').click()")
    time.sleep(0.8)
    return counts


def check_search(browser):
    browser.evaluate("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: '/', bubbles: true}))")
    time.sleep(0.5)
    opened = browser.evaluate("!document.getElementById('searchModal').hidden")
    add("按 / 打开搜索", "pass" if opened else "fail", "hidden=%s" % (not opened))
    if opened:
        browser.evaluate("""(() => { const i = document.getElementById('searchInput'); i.value = '微';
            i.dispatchEvent(new Event('input', {bubbles: true})); })()""")
        time.sleep(0.7)
        res = browser.evaluate(r"""(() => ({
          count: document.querySelectorAll('.search-item').length,
          first: (document.querySelector('.search-item .si-name') || {}).textContent || '',
          active: document.querySelectorAll('.search-item.is-active').length,
        }))()""")
        add("搜索过滤结果", "pass" if res["count"] >= 1 else "fail",
            "结果=%d 首个=%s" % (res["count"], res["first"]))
        # 无结果
        browser.evaluate("""(() => { const i = document.getElementById('searchInput'); i.value = 'zzzz不存在';
            i.dispatchEvent(new Event('input', {bubbles: true})); })()""")
        time.sleep(0.6)
        empty = browser.evaluate("document.querySelectorAll('.search-empty').length")
        add("搜索无结果提示", "pass" if empty >= 1 else "warn", "empty=%d" % empty)
        browser.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        time.sleep(0.4)
        closed = browser.evaluate("document.getElementById('searchModal').hidden")
        add("Esc 关闭搜索", "pass" if closed else "fail", "hidden=%s" % closed)


def check_drawer(browser):
    browser.evaluate("document.getElementById('btnSettings').click()")
    time.sleep(0.8)
    st = browser.evaluate(r"""(() => {
      const d = document.getElementById('drawer');
      const rect = d.getBoundingClientRect();
      const switches = Array.from(document.querySelectorAll('.switch[data-key]')).map(s => s.dataset.key + '=' + s.getAttribute('aria-checked'));
      const active = Array.from(document.querySelectorAll('#setLayout button')).filter(b => b.classList.contains('is-active')).map(b => b.dataset.value);
      return {open: d.classList.contains('is-open'), x: rect.x, w: rect.width, innerW: innerWidth,
              switches, activeLayout: active, mask: !document.getElementById('drawerMask').hidden};
    })()""")
    add("设置抽屉打开", "pass" if st["open"] and st["mask"] else "fail", "open=%s mask=%s" % (st["open"], st["mask"]))
    add("设置抽屉在视口内", "pass" if st["x"] >= -1 and st["x"] + st["w"] <= st["innerW"] + 1 else "warn",
        "x=%.0f w=%.0f innerW=%d" % (st["x"], st["w"], st["innerW"]))
    add("设置项状态回显", "pass" if st["switches"] and st["activeLayout"] else "warn",
        "switches=%s layout=%s" % (",".join(st["switches"]), st["activeLayout"]))
    # 切换开关 → 磁贴分类角标消失
    browser.evaluate("document.querySelector('.switch[data-key=showChips]').click()")
    time.sleep(0.8)
    chips_after = browser.evaluate("document.querySelectorAll('.tile-chip').length")
    add("切换「显示分类标签」生效", "pass" if chips_after == 0 else "fail", "角标数=%d" % chips_after)
    browser.evaluate("document.querySelector('.switch[data-key=showChips]').click()")
    time.sleep(0.7)
    browser.evaluate("document.getElementById('drawerClose').click()")
    time.sleep(0.6)
    closed = browser.evaluate("!document.getElementById('drawer').classList.contains('is-open')")
    add("设置抽屉关闭", "pass" if closed else "fail", "closed=%s" % closed)


def check_sort_menu(browser):
    browser.evaluate("document.getElementById('btnSort').click()")
    time.sleep(0.6)
    menu = browser.evaluate(r"""(() => {
      const m = document.getElementById('ctxMenu');
      return {hidden: m.hidden, items: m.querySelectorAll('.menu-item').length,
              labels: Array.from(m.querySelectorAll('.menu-item span')).map(s => s.textContent)};
    })()""")
    add("排序菜单打开", "pass" if not menu["hidden"] and menu["items"] >= 4 else "fail",
        "items=%d labels=%s" % (menu["items"], ",".join(menu["labels"])[:60]))
    # 切到按名称排序
    browser.evaluate("""(() => { const items = Array.from(document.querySelectorAll('#ctxMenu .menu-item'));
        const target = items.find(i => i.textContent.includes('名称'));
        if (target) target.click(); })()""")
    time.sleep(1.2)
    names = browser.evaluate("Array.from(document.querySelectorAll('.tile-name')).slice(0,6).map(n => n.textContent)")
    add("按名称排序生效", "pass" if names else "warn", "前6个=%s" % names)
    # 还原自定义排序
    browser.evaluate("document.getElementById('btnSort').click()")
    time.sleep(0.5)
    browser.evaluate("""(() => { const items = Array.from(document.querySelectorAll('#ctxMenu .menu-item'));
        const target = items.find(i => i.textContent.includes('自定义'));
        if (target) target.click(); })()""")
    time.sleep(0.8)


def check_context_menu(browser):
    browser.evaluate(r"""(() => {
      const tile = document.querySelector('.tile');
      const r = tile.getBoundingClientRect();
      tile.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: r.x + 40, clientY: r.y + 40}));
    })()""")
    time.sleep(0.7)
    menu = browser.evaluate(r"""(() => {
      const m = document.getElementById('ctxMenu');
      return {hidden: m.hidden, count: m.querySelectorAll('.menu-item').length,
              labels: Array.from(m.querySelectorAll('.menu-item span')).map(s => s.textContent)};
    })()""")
    add("磁贴右键菜单", "pass" if not menu["hidden"] and menu["count"] >= 5 else "fail",
        "items=%d labels=%s" % (menu["count"], ",".join(menu["labels"])[:90]))
    # 分类子菜单（点击「修改分类」）
    browser.evaluate("document.body.click()")
    time.sleep(0.3)


def check_keyboard(browser):
    browser.evaluate("(() => { const t = document.querySelector('.tile'); t.focus(); })()")
    before = browser.evaluate("document.activeElement.querySelector('.tile-name').textContent")
    browser.send("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "ArrowRight",
                                            "code": "ArrowRight", "windowsVirtualKeyCode": 39})
    browser.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "ArrowRight",
                                            "code": "ArrowRight", "windowsVirtualKeyCode": 39})
    time.sleep(0.5)
    focus = browser.evaluate(r"""(() => {
      const el = document.activeElement;
      const cs = getComputedStyle(el);
      return {tag: el.tagName, cls: el.className,
              name: (el.querySelector('.tile-name') || {}).textContent || '',
              outline: cs.outlineStyle + ' ' + cs.outlineWidth,
              focusVisible: el.matches(':focus-visible')};
    })()""")
    ok = focus["tag"] == "ARTICLE" and focus["outline"].startswith("solid") and focus["focusVisible"]
    add("键盘方向键移动焦点", "pass" if ok else "warn",
        "%s -> %s, outline=%s focus-visible=%s" % (before, focus["name"], focus["outline"], focus["focusVisible"]))


def check_scroll(browser):
    b = browser.evaluate(r"""(() => {
      const wrap = document.getElementById('gridWrap');
      const before = {scrollTop: wrap.scrollTop, scrollHeight: wrap.scrollHeight, clientHeight: wrap.clientHeight};
      wrap.scrollTop = wrap.scrollHeight;
      return {before, after: wrap.scrollTop, canScroll: wrap.scrollHeight > wrap.clientHeight};
    })()""")
    time.sleep(0.5)
    fade = browser.evaluate("document.getElementById('gridFade').classList.contains('is-hidden')")
    add("磁贴墙可滚动", "pass" if b["canScroll"] and b["after"] > 0 else "warn",
        "scrollHeight=%d clientHeight=%d scrollTop=%d" % (b["before"]["scrollHeight"], b["before"]["clientHeight"], b["after"]))
    add("滚到底部时渐隐消失", "pass" if fade else "warn", "is-hidden=%s" % fade)
    browser.evaluate("document.getElementById('gridWrap').scrollTop = 0")
    time.sleep(0.4)


def check_clock(browser):
    clock = browser.evaluate("document.querySelector('#clock b').textContent")
    date = browser.evaluate("document.querySelector('#clock span').textContent")
    add("时钟显示正常", "pass" if ":" in clock and len(clock) == 5 else "warn",
        "时间=%s 日期=%s" % (clock, date))


def check_responsive(browser):
    sizes = [(1707, 996), (1560, 980), (1366, 728), (1200, 860), (1024, 768)]
    details = []
    for w, h in sizes:
        browser.emulate(w, h)
        time.sleep(1.0)
        data = browser.evaluate(r"""(() => {
          const st = window.__qa.state();
          const tiles = window.__qa.tiles().map(t => window.__qa.rect(t));
          const bad = tiles.filter(r => Math.abs(r.w - r.h) > 2).length;
          let overlaps = 0;
          for (let i = 0; i < tiles.length; i++) for (let j = i + 1; j < tiles.length; j++)
            if (window.__qa.overlaps(tiles[i], tiles[j], 0.8)) overlaps++;
          const nav = document.querySelector('.nav-center');
          const navScroll = nav.scrollHeight > nav.clientHeight + 2;
          const opened = document.getElementById('openedList');
          const openedScroll = opened.scrollHeight > opened.clientHeight + 2;
          const card = document.getElementById('cornerCard');
          const cardVisible = getComputedStyle(card).display !== 'none';
          const right = document.querySelector('.bottom-right').getBoundingClientRect();
          const recent = document.getElementById('recentCard').getBoundingClientRect();
          const c = Number(st.c);
          const maxCol = 2 * c + 1;
          const grid = document.getElementById('grid');
          const cs = getComputedStyle(grid);
          const template = cs.gridTemplateColumns.trim().split(/\s+/).map(v => parseFloat(v) || 0);
          const explicitCols = template.length;
          const tile = parseFloat(st.tile);
          const outOfGrid = Array.from(document.querySelectorAll('.tile')).filter(t => {
            const span = (t.style.gridColumn || '').split('/')[1] || '';
            const n = parseInt(span.replace('span', '').trim(), 10) || 1;
            const start = parseInt((t.style.gridColumn || '').split('/')[0], 10) || 1;
            return start + n - 1 > maxCol;
          }).length;
          const badWidth = Array.from(document.querySelectorAll('.tile')).filter(t => {
            const r = t.getBoundingClientRect();
            const span = parseInt(((t.style.gridColumn || '').split('/')[1] || '').replace('span', '').trim(), 10) || 1;
            const expect = span * tile + (span - 1) * parseFloat(st.gap);
            return Math.abs(r.width - expect) > 2.5;
          }).length;
          return {w: innerWidth, h: innerHeight, c: st.c, tile: st.tile, tiles: st.tiles,
                  badSquare: bad, overlaps, navScroll, openedScroll, cardVisible,
                  hScroll: document.documentElement.scrollWidth > innerWidth + 1,
                  bottomOverlap: recent.right > right.x + 1,
                  rightOverflow: right.right > innerWidth + 1,
                  explicitCols, outOfGrid, badWidth};
        })()""")
        details.append(data)
        issues = []
        if data["badSquare"]: issues.append("非正方形磁贴%d" % data["badSquare"])
        if data["overlaps"]: issues.append("重叠%d" % data["overlaps"])
        if data["hScroll"]: issues.append("出现横向滚动")
        if data["rightOverflow"]: issues.append("右下工具溢出")
        if data["bottomOverlap"]: issues.append("底部两组卡片重叠")
        if data["navScroll"] and not data["openedScroll"]: issues.append("竖栏内容被裁切")
        if data.get("outOfGrid"): issues.append("%d 个磁贴落在显式网格外" % data["outOfGrid"])
        if data.get("badWidth"): issues.append("%d 个磁贴宽度异常" % data["badWidth"])
        add("响应式 %dx%d" % (w, h), "pass" if not issues else "warn",
            "c=%s tile=%s 竖栏裁切=%s 卡片=%s %s" % (data["c"], data["tile"], data["navScroll"],
                                                    data["cardVisible"], "；".join(issues)))
    browser.emulate(1560, 980)
    time.sleep(0.8)
    return details


def check_perf(browser):
    metrics = browser.evaluate(r"""(() => {
      const nav = performance.getEntriesByType('navigation')[0] || {};
      const res = performance.getEntriesByType('resource');
      const js = res.find(r => r.name.endsWith('/app.js')) || {};
      const css = res.find(r => r.name.endsWith('/app.css')) || {};
      const boot = res.find(r => r.name.includes('/api/bootstrap')) || {};
      return {domContentLoaded: Math.round(nav.domContentLoadedEventEnd || 0),
              load: Math.round(nav.loadEventEnd || 0),
              jsKB: Math.round((js.transferSize || 0) / 1024),
              cssKB: Math.round((css.transferSize || 0) / 1024),
              bootstrapMs: Math.round(boot.duration || 0),
              resources: res.length};
    })()""")
    add("页面性能", "pass" if metrics["load"] < 4000 else "warn",
        "load=%dms bootstrap=%dms js=%dKB css=%dKB 请求数=%d" % (
            metrics["load"], metrics["bootstrapMs"], metrics["jsKB"], metrics["cssKB"], metrics["resources"]))
    return metrics


def check_console(browser):
    browser.drain(1.0)
    errors = [c for c in browser.console if c["type"] in ("error", "exception", "log-error")]
    warns = [c for c in browser.console if c["type"] == "warning"]
    add("浏览器控制台无报错", "pass" if not errors else "fail",
        "errors=%d %s" % (len(errors), errors[:2]))
    add("浏览器控制台无警告", "pass" if not warns else "warn",
        "warnings=%d %s" % (len(warns), warns[:2]))
    net = [e for e in browser.network_errors if e.get("error") != "net::ERR_ABORTED"]
    add("网络请求无失败", "pass" if not net else "fail", "失败=%d %s" % (len(net), net[:3]))
    REPORT["console"] = errors + warns
    REPORT["network_errors"] = browser.network_errors


# ---------------------------------------------------------------- 设置/数据写入
def check_scan_consistency(orig_boot):
    # Control Panel / File Explorer / 任务管理器是刻意保留的系统应用（KEEP_NAMES）
    junk_names = {"Administrative Tools", "LiveCaptions", "Tools for Desktop Apps",
                  "Tools for UWP Apps", "Windows Tools", "Windows 备份"}
    counts = []
    for i in range(2):
        http_json("/api/rescan", "POST", {"force": False})
        for _ in range(90):
            time.sleep(1)
            bb = http_json("/api/bootstrap", timeout=40)["json"] or {}
            scan = bb.get("scan") or {}
            if not scan.get("running") and scan.get("phase") in ("ready", "error"):
                apps = bb.get("apps") or []
                counts.append(len(apps))
                leak = [a["name"] for a in apps if a["name"] in junk_names]
                no_path = [a["name"] for a in apps if a["kind"] == "lnk" and not a.get("path")]
                add("重扫 #%d 数量一致" % (i + 1),
                    "pass" if len(apps) == len(orig_boot.get("apps") or []) else "warn",
                    "apps=%d（首扫 %d）" % (len(apps), len(orig_boot.get("apps") or [])))
                add("重扫 #%d 无系统垃圾项" % (i + 1), "pass" if not leak else "fail",
                    ("泄漏: " + ", ".join(leak[:8])) if leak else "无")
                add("重扫 #%d 目标路径完整" % (i + 1), "pass" if not no_path else "warn",
                    ("空目标 %d 个（Shell 命名空间快捷方式，可经 .lnk 启动）: %s"
                     % (len(no_path), ", ".join(no_path[:5]))) if no_path else "全部解析成功")
                break
    if len(counts) == 2:
        add("两次重扫结果一致", "pass" if counts[0] == counts[1] else "fail", "counts=%s" % counts)


def check_mutations(orig_boot):
    settings_before = orig_boot.get("settings") or {}
    # 列数设置
    r = http_json("/api/settings", "POST", {"settings": {"columns": 8}})
    b = http_json("/api/bootstrap", timeout=40)["json"] or {}
    add("设置：每行总列数=8", "pass" if (b.get("settings") or {}).get("columns") == 8 else "fail",
        "columns=%s" % (b.get("settings") or {}).get("columns"))
    http_json("/api/settings", "POST", {"settings": {"columns": settings_before.get("columns", 0)}})
    # 背景设置
    http_json("/api/settings", "POST", {"settings": {"background": "graphite"}})
    b = http_json("/api/bootstrap", timeout=40)["json"] or {}
    add("设置：纯深色背景", "pass" if (b.get("settings") or {}).get("background") == "graphite" else "fail",
        "background=%s" % (b.get("settings") or {}).get("background"))
    http_json("/api/settings", "POST", {"settings": {"background": settings_before.get("background", "wallpaper")}})

    # 固定 / 取消固定
    apps = (b.get("apps") or [])
    target = next((a for a in apps if not a.get("pinned")), None)
    if target:
        http_json("/api/app/%s" % target["id"], "PATCH", {"pinned": True})
        b2 = http_json("/api/bootstrap", timeout=40)["json"] or {}
        now = next((a for a in b2["apps"] if a["id"] == target["id"]), {})
        add("API：固定应用", "pass" if now.get("pinned") else "fail", target["name"])
        http_json("/api/app/%s" % target["id"], "PATCH", {"pinned": False})
        b3 = http_json("/api/bootstrap", timeout=40)["json"] or {}
        undo = next((a for a in b3["apps"] if a["id"] == target["id"]), {})
        add("API：取消固定", "pass" if not undo.get("pinned") else "fail", target["name"])
    # 重命名 + 恢复
    if target:
        old_name = target["name"]
        new_name = old_name + "·QA"
        http_json("/api/app/%s" % target["id"], "PATCH", {"name": new_name})
        b4 = http_json("/api/bootstrap", timeout=40)["json"] or {}
        got = next((a for a in b4["apps"] if a["id"] == target["id"]), {})
        add("API：重命名应用", "pass" if got.get("name") == new_name else "fail",
            "%s -> %s" % (old_name, got.get("name")))
        # 恢复（恢复原显示名需清空自定义名，用 rawName）
        raw = got.get("rawName") or old_name
        http_json("/api/app/%s" % target["id"], "PATCH", {"name": raw if raw != new_name else ""})
        b5 = http_json("/api/bootstrap", timeout=40)["json"] or {}
        got2 = next((a for a in b5["apps"] if a["id"] == target["id"]), {})
        add("API：恢复应用名", "pass" if got2.get("name") != new_name else "fail",
            "当前=%s" % got2.get("name"))
    # 排序接口
    order = [a["id"] for a in (http_json("/api/bootstrap", timeout=40)["json"] or {}).get("apps", [])]
    if len(order) >= 3:
        new_order = order[:]
        new_order[0], new_order[1] = new_order[1], new_order[0]
        r = http_json("/api/order", "POST", {"ids": new_order})
        b6 = http_json("/api/bootstrap", timeout=40)["json"] or {}
        got_order = [a["id"] for a in b6.get("apps", [])]
        add("API：拖拽排序保存", "pass" if got_order[:2] == new_order[:2] else "fail",
            "status=%s 前两位=%s" % (r["status"], got_order[:2]))
        http_json("/api/order", "POST", {"ids": order})

    # 重新扫描
    r = http_json("/api/rescan", "POST", {"force": False})
    scan_started = None
    for _ in range(60):
        time.sleep(1)
        bb = http_json("/api/bootstrap", timeout=40)["json"] or {}
        scan = bb.get("scan") or {}
        if scan.get("running"):
            scan_started = True
        elif scan.get("phase") in ("ready", "error"):
            add("API：重新扫描完成", "pass" if scan.get("phase") == "ready" else "fail",
                "apps=%d phase=%s error=%s" % (len(bb.get("apps") or []), scan.get("phase"), scan.get("error")))
            break
    else:
        add("API：重新扫描完成", "fail", "超时未完成")


# ---------------------------------------------------------------- 生命周期
def check_lifecycle():
    # 端口被占用时第二个实例应识别并退出（不重复拉服务）
    import subprocess
    pkg = os.environ.get("GRIDDESK_PKG", "")
    py = os.path.join(pkg, "runtime", "python.exe") if pkg else ""
    if not py or not os.path.exists(py):
        add("端口占用检测", "warn", "找不到测试用运行时 python")
        return
    proc = subprocess.Popen([py, "server.py", "--no-window", "--port", "8901"],
                            cwd=pkg, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        code = proc.wait(timeout=20)
        add("端口占用时第二个实例退出", "pass" if code == 0 else "warn",
            "exit=%s（应识别到服务已存在后退出）" % code)
    except subprocess.TimeoutExpired:
        proc.kill()
        add("端口占用时第二个实例退出", "fail", "第二个实例未退出，可能有双实例风险")


def main():
    print("=== QA 开始 ===", flush=True)
    boot = check_server_http()
    check_http_assets()
    check_api_errors()

    browser = Browser()
    try:
        check_ui_basic(browser)
        check_layouts(browser)
        check_views(browser, boot)
        check_search(browser)
        check_drawer(browser)
        check_sort_menu(browser)
        check_context_menu(browser)
        check_keyboard(browser)
        check_scroll(browser)
        check_clock(browser)
        check_responsive(browser)
        check_perf(browser)
        # 截图
        for name, action in (
            ("qa-01-全部.png", None),
            ("qa-02-分类.png", "document.querySelector('.rail-item[data-view=categories]').click()"),
            ("qa-03-搜索.png", "document.getElementById('btnSearch').click()"),
            ("qa-04-设置.png", "document.getElementById('btnSettings').click()"),
        ):
            if action:
                browser.evaluate(action)
                time.sleep(0.8)
            browser.screenshot(name)
            if "设置" in name:
                browser.evaluate("document.getElementById('drawerClose').click()")
            if "搜索" in name:
                browser.evaluate("document.getElementById('searchModal').hidden = true")
            if "分类" in name:
                browser.evaluate("document.querySelector('.rail-item[data-view=all]').click()")
            time.sleep(0.4)
        check_console(browser)
    finally:
        check_scan_consistency(boot)
        check_mutations(boot)
        check_lifecycle()
        try:
            browser.ws.close()
        except Exception:
            pass

    with open(os.path.join(OUT_DIR, "qa-report.json"), "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=1)

    total = len(REPORT["checks"])
    fails = [c for c in REPORT["checks"] if c["status"] == "fail"]
    warns = [c for c in REPORT["checks"] if c["status"] == "warn"]
    print("\n=== QA 汇总 ===")
    print("检查项 %d，失败 %d，警告 %d" % (total, len(fails), len(warns)))
    for c in fails:
        print("  FAIL:", c["name"], "-", c["detail"])
    for c in warns:
        print("  WARN:", c["name"], "-", c["detail"])


if __name__ == "__main__":
    main()
