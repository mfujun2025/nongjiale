# -*- coding: utf-8 -*-
"""
构建后自检

    python check.py

断言：内链可达、无残留占位符、sitemap 条数一致、必备文件齐全、页面结构完整。
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
PUB = BASE / "public"
DATA = BASE / "data"

FAIL = []
WARN = []


def ok(msg):
    print(f"  [OK]   {msg}")


def bad(msg):
    FAIL.append(msg)
    print(f"  [FAIL] {msg}")


def warn(msg):
    WARN.append(msg)
    print(f"  [WARN] {msg}")


# ---------------------------------------------------------------- 载入
SITE = json.loads((DATA / "site.json").read_text(encoding="utf-8"))
CITIES = json.loads((DATA / "cities.json").read_text(encoding="utf-8"))
SHOPS = json.loads((DATA / "shops.json").read_text(encoding="utf-8"))


def _load_news():
    d = DATA / "news"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            continue
        a.setdefault("slug", p.stem)
        a["_file"] = p.name
        out.append(a)
    out.sort(key=lambda a: (a.get("date") or "", a["slug"]), reverse=True)
    return out


NEWS = _load_news()

HTML_FILES = sorted(PUB.rglob("*.html"))
print("=" * 62)
print(f"  农家乐.cn 构建自检 · {len(HTML_FILES)} 个 HTML 文件")
print("=" * 62)

# ---------------------------------------------------------------- 1 必备文件
print("\n[1] 必备文件")
REQUIRED = ["index.html", "404.html", "CNAME", ".nojekyll", "robots.txt", "sitemap.xml",
            "list/index.html", "cities/index.html", "join/index.html",
            "about/index.html", "sitemap/index.html", "news/index.html",
            "css/style.css", "js/site.js", "js/list.js", "favicon.svg",
            "img/join-qr.svg"]
for rel in REQUIRED:
    p = PUB / rel
    if not p.is_file():
        bad(f"缺少 {rel}")
    elif rel not in ("CNAME", ".nojekyll") and p.stat().st_size == 0:
        bad(f"{rel} 是空文件")
if not FAIL:
    ok(f"{len(REQUIRED)} 个必备文件齐全")

cname = (PUB / "CNAME").read_text(encoding="utf-8").strip()
if cname != SITE["domain"]:
    bad(f"CNAME 内容错误：{cname}，应为 {SITE['domain']}")
else:
    ok(f"CNAME = {cname}")

# ---------------------------------------------------------------- 2 页面数量
print("\n[2] 页面数量")
for c in CITIES:
    if not (PUB / "city" / c["slug"] / "index.html").is_file():
        bad(f"缺少城市页 {c['slug']}")
for s in SHOPS:
    if not (PUB / "shop" / s["slug"] / "index.html").is_file():
        bad(f"缺少商家页 {s['slug']}")
expected = 6 + len(CITIES) + len(SHOPS)
actual = len([p for p in HTML_FILES if p.name == "index.html" or p.name == "404.html"])
if not any("缺少城市页" in f or "缺少商家页" in f for f in FAIL):
    ok(f"{len(CITIES)} 个城市页 + {len(SHOPS)} 个商家页 + 6 个功能页 = {expected} 页，全部生成")

# ---------------------------------------------------------------- 3 占位符残留
print("\n[3] 占位符残留")
leftover = {}
for p in HTML_FILES:
    txt = p.read_text(encoding="utf-8")
    found = set(re.findall(r"\{\{[A-Z0-9_]+\}\}", txt))
    if found:
        leftover[str(p.relative_to(PUB))] = sorted(found)
if leftover:
    for k, v in list(leftover.items())[:5]:
        bad(f"{k} 残留 {v}")
else:
    ok("所有页面均无未替换的 {{占位符}}")

# ---------------------------------------------------------------- 4 内链
print("\n[4] 站内链接可达性")
LINK_RE = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"')
SKIP_PREFIX = ("http://", "https://", "mailto:", "tel:", "#", "data:", "//", "javascript:")

broken = {}
checked = 0
for p in HTML_FILES:
    txt = p.read_text(encoding="utf-8")
    for raw in LINK_RE.findall(txt):
        if raw.startswith(SKIP_PREFIX) or not raw.strip():
            continue
        url = unquote(raw.split("#")[0].split("?")[0])
        if not url:
            continue
        if url.startswith("/"):
            target = PUB / url.lstrip("/")
        else:
            target = p.parent / url
        if url.endswith("/") or target.is_dir():
            target = target / "index.html"
        checked += 1
        if not target.is_file():
            broken.setdefault(str(p.relative_to(PUB)), []).append(raw)

if broken:
    for k, v in list(broken.items())[:8]:
        bad(f"{k} 断链：{sorted(set(v))[:4]}")
else:
    ok(f"检查 {checked} 个站内链接，全部可达")

# ---------------------------------------------------------------- 5 sitemap
print("\n[5] 站点地图一致性")
xml = (PUB / "sitemap.xml").read_text(encoding="utf-8")
locs = re.findall(r"<loc>([^<]+)</loc>", xml)
# 从产物反推，而不是硬编码数字——每加一类页面都要改断言的话，
# 这个检查早晚会被人改成「反正它就是过」，失去意义。
# 每个 index.html 对应一条 sitemap URL（404.html 不是 index.html，天然排除）。
expected_locs = len(list(PUB.rglob("index.html")))
if len(locs) != expected_locs:
    bad(f"sitemap.xml 有 {len(locs)} 条，产物里有 {expected_locs} 个页面 → 有页面没进地图")
else:
    ok(f"sitemap.xml {len(locs)} 条 URL，与产物页面数一致")

base = SITE["base_url"].rstrip("/")
if not all(u.startswith(base) for u in locs):
    bad("sitemap.xml 存在非本站域名 URL")
else:
    ok(f"全部 URL 使用规范域名 {base}")

dupes = [u for u in set(locs) if locs.count(u) > 1]
if dupes:
    bad(f"sitemap.xml 有重复 URL：{dupes[:3]}")
else:
    ok("sitemap.xml 无重复 URL")

# HTML 版地图的页数声明
map_html = (PUB / "sitemap" / "index.html").read_text(encoding="utf-8")
m = re.search(r"本站全部\s*([\d,]+)\s*个页面", map_html)
if not m:
    warn("HTML 版网站地图没找到页数声明")
else:
    declared = int(m.group(1).replace(",", ""))
    html_map_links = len(set(re.findall(r'<li><a href="(/[^"]*)"', map_html)))
    if declared != html_map_links:
        bad(f"HTML 地图声明 {declared} 页，实际列出 {html_map_links} 条")
    else:
        ok(f"HTML 版网站地图声明 {declared} 页，实际 {html_map_links} 条，一致")

# ---------------------------------------------------------------- 6 robots
print("\n[6] robots.txt")
rb = (PUB / "robots.txt").read_text(encoding="utf-8")
if "Disallow: /" in rb:
    bad("robots.txt 禁止了全站抓取")
elif "Sitemap:" not in rb:
    bad("robots.txt 缺少 Sitemap 声明")
else:
    ok("robots.txt 允许抓取且声明了 Sitemap")

# ---------------------------------------------------------------- 7 页面结构
print("\n[7] 关键页面结构")
checks = [
    ("index.html", ['class="hero-card"', 'class="search-bar"', 'class="grid-cities"',
                    'class="grid-shops"', 'class="stats"', 'class="grid-reviews"',
                    'class="cta-band"', 'class="footer"']),
    ("list/index.html", ['class="filter-panel"', 'id="shopList"', 'data-chip="city"',
                         'data-filter="price"', 'id="emptyBox"', 'js/list.js']),
    ("join/index.html", ['class="steps"', 'class="grid-adv"', 'class="apply-card"',
                         'class="faq"', '/img/join-qr.svg']),
    ("cities/index.html", ['class="grid-cities"', 'class="prose"']),
    ("about/index.html", ['class="prose"']),
]
for rel, needles in checks:
    txt = (PUB / rel).read_text(encoding="utf-8")
    miss = [n for n in needles if n not in txt]
    if miss:
        bad(f"{rel} 缺少：{miss}")
    else:
        ok(f"{rel} 结构完整（{len(needles)} 项）")

# 商家详情页抽查
sample = SHOPS[0]
sp = PUB / "shop" / sample["slug"] / "index.html"
spt = sp.read_text(encoding="utf-8")
need = ['class="gallery"', 'class="book-card"', 'class="room-table"', 'class="rate-bars"',
        'class="mobile-bar"', 'has-mobile-bar', f'tel:{re.sub(r"[^0-9+]", "", SITE["phone"])}',
        "LocalBusiness", "BreadcrumbList"]
miss = [n for n in need if n not in spt]
if miss:
    bad(f"商家详情页（{sample['slug']}）缺少：{miss}")
else:
    ok(f"商家详情页结构完整（{len(need)} 项，含结构化数据与移动端吸底栏）")

# 列表页的商家卡数量
lt = (PUB / "list" / "index.html").read_text(encoding="utf-8")
rows = len(re.findall(r'<article class="shop-row"', lt))
if rows != len(SHOPS):
    bad(f"列表页渲染了 {rows} 张商家卡，应为 {len(SHOPS)}")
else:
    ok(f"列表页服务端渲染 {rows} 张商家卡（爬虫可见，JS 只做筛选重排）")

# ---------------------------------------------------------------- 8 表单配置
print("\n[8] 入驻表单与接收端")

# 8.1 入驻表单是主链路：必须指向飞书表单，且页面上要能扫码打开。
#     这里断的是"链接为空/模板没注入"这类静默故障——页面上按钮点了没反应最难查。
join_html = (PUB / "join" / "index.html").read_text(encoding="utf-8")
form_url = SITE.get("join_form_url", "")
if not form_url:
    bad("data/site.json 未配置 join_form_url → 入驻页没有可用入口")
elif form_url not in join_html:
    bad("入驻页没有出现 join_form_url → 模板未注入表单地址")
elif 'src="/img/join-qr.svg"' not in join_html:
    bad("入驻页缺少扫码入口 /img/join-qr.svg")
else:
    ok(f"入驻表单指向飞书（{form_url[8:46]}…）且含扫码入口")

# 8.2 回拨表单的 webhook 是可选能力（只影响详情页的回拨小表单），未配置只算演示模式
cfg_js = (PUB / "index.html").read_text(encoding="utf-8")
wh = re.search(r'"webhook":"([^"]*)"', cfg_js)
if not wh:
    bad("首页没注入 __NJ_CFG__ 配置")
elif wh.group(1):
    ok("回拨表单接收端已配置")
else:
    warn("回拨表单未配置 webhook → 走演示模式（不影响入驻主链路）")

# ------------------------------------------------------- 9 发布产物洁净度
print("\n[9] 发布产物洁净度")
junk = [p for p in PUB.rglob("*")
        if p.is_file() and (p.name.startswith("_") or p.suffix in (".py", ".md", ".bak", ".tmp"))]
if junk:
    bad("public/ 含调试/源文件产物：" + "、".join(str(p.relative_to(PUB)) for p in junk[:5]))
else:
    ok("public/ 无调试产物与源文件残留")

# public/ 与 static/ 的 CSS 必须逐字节一致，防止改了源码忘了重建
src_css = (BASE / "static" / "css" / "style.css").read_text(encoding="utf-8")
pub_css = (PUB / "css" / "style.css").read_text(encoding="utf-8")
if src_css == pub_css:
    ok("静态资源与源目录一致（无未重建的改动）")
else:
    bad("public/css/style.css 与 static/css/style.css 不一致 → 请重新运行 build.py")

# ------------------------------------------------------- 10 照片与图床
print("\n[10] 照片存储与图床")
photo_cdn = (SITE.get("photo_cdn") or "").strip()
local_photos = sum(1 for s in SHOPS for p in (s.get("photos") or [])
                   if str(p).startswith("/"))
key_photos = sum(1 for s in SHOPS for p in (s.get("photos") or [])
                 if not str(p).startswith(("/", "http://", "https://")))
with_photo = sum(1 for s in SHOPS if (s.get("photos") or []))
art_only = len(SHOPS) - with_photo

if key_photos and not photo_cdn:
    bad(f"{key_photos} 张照片是图床对象 key，但 site.json 未填 photo_cdn → 这些图会 404。"
        f"接图床就补域名，不接就用 --no-upload 重新同步")
elif key_photos:
    ok(f"图床已接通（{photo_cdn}）：{key_photos} 张照片走 CDN，{local_photos} 张仍在本地")
else:
    ok(f"照片全部本地存储（{local_photos} 张，{art_only} 家暂无照片走 SVG 插画）")

# 图床图必须渲染成绝对地址——渲染成 /shops/xxx.webp 会 404
if key_photos and photo_cdn:
    sample_key = next(p for s in SHOPS for p in (s.get("photos") or [])
                      if not str(p).startswith(("/", "http")))
    sample_slug = next(s["slug"] for s in SHOPS if sample_key in (s.get("photos") or []))
    detail = (PUB / "shop" / sample_slug / "index.html").read_text(encoding="utf-8")
    expect = f"https://{photo_cdn.replace('https://', '').replace('http://', '')}/"
    if sample_key not in detail:
        bad(f"商家页（{sample_slug}）没渲染出图床文件 {sample_key}")
    elif expect not in detail:
        bad(f"商家页（{sample_slug}）的图床地址没带上 CDN 域名 {expect}")
    else:
        ok(f"图床图渲染为绝对地址（抽查 {sample_slug}）")

# 本地照片必须真的存在于 public/
missing_local = []
for s in SHOPS:
    for p in (s.get("photos") or []):
        if str(p).startswith("/") and not (PUB / str(p).lstrip("/")).is_file():
            missing_local.append(f"{s['slug']}: {p}")
if missing_local:
    bad(f"{len(missing_local)} 张本地照片在 public/ 里不存在：" + "、".join(missing_local[:3]))
elif local_photos:
    ok(f"{local_photos} 张本地照片均存在于 public/")

# 同步脚本的下载暂存区绝不能进产物
staged = [p for p in PUB.rglob("*") if p.is_file() and ".staging" in p.parts]
if staged:
    bad(f"public/ 混入了下载暂存区文件（{len(staged)} 个）→ 检查 build.py 的 copy_static 过滤")
else:
    ok("public/ 无同步暂存区残留")

# ------------------------------------------------------- 11 入驻城市基准表
print("\n[11] 入驻城市基准表")
_regions_file = DATA / "regions.json"
if not _regions_file.is_file():
    bad("data/regions.json 缺失 → 跑 tools/build_regions.py 生成。"
        "没有它，入驻表单里能选的城市在站点侧会发布不出来")
else:
    _reg = json.loads(_regions_file.read_text(encoding="utf-8"))
    _rows = _reg.get("regions") or []
    ok(f"基准表 {len(_rows)} 个地级行政区，覆盖 {_reg.get('province_count')} 个省级行政区")
    if len(_rows) != 337:
        warn(f"基准表不是 337 条（现 {len(_rows)}）→ 如果是有意调整口径就忽略，"
             f"否则跑 tools/build_regions.py --fetch 重新生成")
    _slugs = [r["slug"] for r in _rows]
    _dup = sorted({s for s in _slugs if _slugs.count(s) > 1})
    if _dup:
        bad(f"基准表 slug 重复：{'、'.join(_dup[:5])} → 重跑 tools/build_regions.py")
    else:
        ok(f"city slug {len(_slugs)} 个全部唯一（URL 不会互相覆盖）")

    # 每个商家的城市都得能对上，否则城市页只能靠兜底渲染 —— 说明数据对不上
    _known = set(_slugs) | {c["slug"] for c in CITIES}
    _orphan = sorted({s["city"] for s in SHOPS} - _known)
    if _orphan:
        warn(f"{len(_orphan)} 个商家城市不在基准表里：{'、'.join(_orphan[:5])}"
             f" → 城市页会用 slug 兜底渲染")
    else:
        ok("所有商家的城市都能在基准表里找到对应")

    # 飞书字段定义文件是否与基准表同步（写接口读不回全量选项，只能比对导出文件）
    _fld = DATA.parent / "build" / "feishu-city-field.json"
    if _fld.is_file():
        _names = [o["name"] for o in json.loads(_fld.read_text(encoding="utf-8"))["options"]]
        _want = [r["short"] for r in _rows] + ["其他城市"]
        if _names != _want:
            warn("飞书城市字段定义与基准表不一致 → 重跑 tools/build_regions.py --feishu")
        else:
            ok(f"飞书「所在城市」字段定义同源（{len(_names)} 个选项，含「其他城市」兜底）")

# ------------------------------------------------------- 12 资讯栏目
print("\n[12] 资讯栏目")

CATS = {"recommend": "农家乐推荐", "experience": "特色体验",
        "business": "经营动态", "trend": "行业趋势", "policy": "政策解读"}

if not NEWS:
    warn("还没有资讯文章（/news/ 会显示筹备中占位，导航入口不会断）")
else:
    ok(f"{len(NEWS)} 篇资讯，最新一篇：{NEWS[0].get('date')} {NEWS[0]['title'][:24]}…")

    # 必填字段：缺一个，列表页或 meta 就会缺内容，而且是静默的
    FIELD_NAMES = {"title": "标题", "date": "日期", "category": "分类",
                   "summary": "摘要", "body": "正文"}
    missing = []
    for a in NEWS:
        for k, cn in FIELD_NAMES.items():
            if not a.get(k):
                missing.append(f"{a['_file']} 缺{cn}")
        if a.get("category") and a["category"] not in CATS:
            missing.append(f"{a['_file']} 分类 {a['category']} 不在栏目表里（会退化成自由文本）")
    if missing:
        bad("资讯字段不完整：" + "；".join(missing[:4]))
    else:
        ok(f"每篇的 {len(FIELD_NAMES)} 个必填字段齐全，分类都在栏目表里")

    # slug：与文件名一致、全局唯一。不一致会导致 URL 与文件对不上，排查很费劲
    slug_bad = [a["_file"] for a in NEWS if a["slug"] != a["_file"][:-5]]
    if slug_bad:
        bad(f"slug 与文件名不一致：{slug_bad[:3]} → URL 会与文件对不上")
    dup_slug = {a["slug"] for a in NEWS if [x["slug"] for x in NEWS].count(a["slug"]) > 1}
    if dup_slug:
        bad(f"slug 重复：{sorted(dup_slug)[:3]} → 页面会互相覆盖")
    if not slug_bad and not dup_slug:
        ok(f"{len(NEWS)} 个 slug 与文件名一致且唯一")

    # 日期：格式合法 + 一天只能一篇（「每日一篇」的硬约束，同日两篇说明去重没做好）
    date_bad = [a["_file"] for a in NEWS
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", a.get("date") or "")]
    dup_date = {a["date"] for a in NEWS if [x["date"] for x in NEWS].count(a["date"]) > 1}
    if date_bad:
        bad(f"日期格式不是 YYYY-MM-DD：{date_bad[:3]}")
    elif dup_date:
        bad(f"同一天有多篇：{sorted(dup_date)} → 每日一篇，同日重复说明选题去重失效")
    else:
        ok("日期格式合法，无同日重复")

    # 字数：需求是 800~1200 字。明显偏离才 FAIL，边缘区间只提醒，
    # 免得某天写了 1230 字就把整条发布链卡住
    def _body_text(a):
        b = a.get("body")
        if isinstance(b, list):
            b = "\n".join(str(x) for x in b)
        return str(b or "")

    too_short, too_long, edge = [], [], []
    for a in NEWS:
        n = len(re.findall(r"[\u4e00-\u9fff]", re.sub(r"<[^>]+>", "", _body_text(a))))
        a["_chars"] = n
        if n < 700:
            too_short.append(f"{a['slug']}({n})")
        elif n > 1400:
            too_long.append(f"{a['slug']}({n})")
        elif not (800 <= n <= 1200):
            edge.append(f"{a['slug']}({n})")
    if too_short or too_long:
        bad(f"正文字数明显偏离 800~1200：偏短 {too_short[:2]} 偏长 {too_long[:2]}")
    elif edge:
        warn(f"字数在边缘（{edge[:3]}），需求是 800~1200 字")
    else:
        ok(f"正文字数都在 800~1200 区间")

    # 正文里的未替换占位符会原样显示给读者，必须扫
    tok = [a["slug"] for a in NEWS if "{{" in _body_text(a)]
    if tok:
        bad(f"正文含未替换的占位符：{tok[:3]}")
    else:
        ok("正文无未替换的占位符")

    # 每篇文章的产物页面必须在，且标题写进了 <title>
    miss_page = []
    for a in NEWS:
        p = PUB / "news" / a["slug"] / "index.html"
        if not p.is_file():
            miss_page.append(a["slug"])
        elif a["title"][:12] not in p.read_text(encoding="utf-8"):
            miss_page.append(f"{a['slug']}(标题未渲染)")
    if miss_page:
        bad(f"文章页缺失或标题未渲染：{miss_page[:3]}")
    else:
        ok(f"{len(NEWS)} 篇文章页都在，标题已渲染")

    # 栏目归档页：有文章的栏目必须能点进去
    for key in CATS:
        if any(a.get("category") == key for a in NEWS):
            if not (PUB / "news" / "cat" / key / "index.html").is_file():
                bad(f"栏目 {CATS[key]}（{key}）有文章，但归档页 /news/cat/{key}/ 不存在")

# 首页必须挂上资讯入口，否则新文章只能靠 sitemap 被找到
home = (PUB / "index.html").read_text(encoding="utf-8")
if 'href="/news/"' not in home:
    bad("首页没有资讯入口")
else:
    ok("首页已挂资讯区块与入口")

nav_labels = [i["label"] for i in SITE.get("nav", [])]
if not any(i["url"] == "/news/" for i in SITE.get("nav", [])):
    bad(f"导航里没有资讯入口（当前导航：{nav_labels}）")
else:
    ok("导航含资讯入口")

# ------------------------------------------------------- 13 全国城市目录
print("\n[13] 全国城市目录")
_regf = DATA / "regions.json"
_rows = (json.loads(_regf.read_text(encoding="utf-8")).get("regions") or []
         if _regf.is_file() else [])
_reg_page = PUB / "regions" / "index.html"

if not _reg_page.is_file():
    bad("public/regions/index.html 缺失 → 全国 337 个城市在站上一个入口都没有。"
        "build.py 的 main() 里要调 build_region_directory()")
else:
    _rh = _reg_page.read_text(encoding="utf-8")

    # 1) 基准城市一个都不能少 —— 这个页面存在的唯一理由就是回答「我的城市在不在」
    _miss = [r["short"] for r in _rows if f'>{r["short"]}<' not in _rh]
    if _miss:
        bad(f"城市目录漏了 {len(_miss)} 个城市（{'、'.join(_miss[:8])}…）"
            f"→ 查 build_region_directory 的省份分组与 chip 渲染")
    else:
        ok(f"{len(_rows)} 个地级行政区在目录页全部列出")

    # 2) 有商家的城市必须可点：列出来了却没链接，等于白丢入口
    _live = sorted({s["city"] for s in SHOPS})
    _dead = [sl for sl in _live if f'href="/city/{sl}/"' not in _rh]
    if _dead:
        bad(f"已开通城市在目录页点不进去：{'、'.join(_dead)}")
    else:
        ok(f"{len(_live)} 座已开通城市都能点进城市页")

    # 3) 未开通城市要落到入驻引导 —— 点了没反应比不可点更糟
    _soon = re.findall(r'class="region-chip is-soon" href="/join/\?city=', _rh)
    if not _soon:
        bad("未开通城市没有指向入驻引导 → 点上去会没反应")
    else:
        ok(f"{len(_soon)} 个未开通城市指向入驻引导（带城市名回显）")

    # 4) 两个口径必须同时出现，否则「已开通 6」和「可入驻 337」又会互相打脸
    if "已开通城市" not in _rh:
        bad("目录页没写「已开通城市」口径 → 访客会把 337 当成已覆盖的城市数")
    else:
        ok("目录页同时标明了地级行政区总数与已开通城市数")

# 全站入口：四处缺任一个，这个页面就等于孤岛
_home_h = (PUB / "index.html").read_text(encoding="utf-8")
_cities_h = (PUB / "cities" / "index.html").read_text(encoding="utf-8")
_sitemap_h = (PUB / "sitemap.xml").read_text(encoding="utf-8")
_no_entry = []
if not any(i["url"] == "/regions/" for i in SITE.get("nav", [])):
    _no_entry.append("导航")
if 'href="/regions/"' not in _home_h:
    _no_entry.append("首页")
if 'href="/regions/"' not in _cities_h:
    _no_entry.append("热门城市页")
if "/regions/" not in _sitemap_h:
    _no_entry.append("sitemap.xml")
if _no_entry:
    bad(f"城市目录缺入口：{'、'.join(_no_entry)}")
else:
    ok("城市目录在导航 / 首页 / 热门城市页 / sitemap 都有入口")

# ------------------------------------------------------- 14 入驻页城市选择器
print("\n[14] 入驻页城市选择器")
# 飞书表单里「所在城市」是 337 个纵向平铺的选项，填表人要滚几百行。
# /join/ 改成先在站内选「省 + 市」，跳转时拼 prefill_/hide_ 把那一项填好并隐藏。
# 这里守三件事：城市全、名字对得上、参数拼得出来 —— 破一个就又滚回长列表。
_REGS = json.loads((DATA / "regions.json").read_text(encoding="utf-8"))["regions"]
_join_h = (PUB / "join" / "index.html").read_text(encoding="utf-8")
_m = re.search(r'<script type="application/json" id="cpData">(.*?)</script>', _join_h, re.S)
if not _m:
    bad("入驻页没有城市选择器数据（cpData）")
else:
    try:
        _cp = json.loads(_m.group(1))
    except Exception as e:
        _cp = None
        bad(f"cpData 不是合法 JSON：{e}")
    if _cp:
        _want_c = {r["short"] for r in _REGS}
        _got_c = {c["short"] for p in _cp["provinces"] for c in p["cities"]}
        if _got_c != _want_c:
            bad("选择器城市与基准表不一致：缺 "
                f"{sorted(_want_c - _got_c)[:6]}，多 {sorted(_got_c - _want_c)[:6]}")
        else:
            ok(f"选择器覆盖全部 {len(_got_c)} 个城市")

        _want_p = {r["province"] for r in _REGS}
        _got_p = {p["name"] for p in _cp["provinces"]}
        if _got_p != _want_p:
            bad(f"选择器省份与基准表不一致：缺 {sorted(_want_p - _got_p)}，"
                f"多 {sorted(_got_p - _want_p)}")
        else:
            ok(f"选择器覆盖全部 {len(_got_p)} 个省级分组")

        # 「已开通」标记必须与商家数据同源，否则会出现「标了已开通、点进去没商家」
        _hits = {}
        for _s in SHOPS:
            _hits[_s["city"]] = _hits.get(_s["city"], 0) + 1
        _slug2short = {r["slug"]: r["short"] for r in _REGS}
        _want_open = {_slug2short[k]: v for k, v in _hits.items() if k in _slug2short}
        _got_open = {c["short"]: c["count"]
                     for p in _cp["provinces"] for c in p["cities"] if c["open"]}
        if _want_open != _got_open:
            bad(f"「已开通」标记与商家数据不符：页面 {_got_open}，应为 {_want_open}")
        else:
            ok(f"「已开通」标记与商家数据一致（{len(_want_open)} 座）")

if "prefill_" not in _join_h or "hide_" not in _join_h:
    bad("入驻页缺少 prefill_/hide_ 跳转参数构造")
else:
    ok("跳转参数含 prefill_ 与 hide_（缺一个那 337 行就会重新出现）")

# 题目名要与飞书表单里的一字不差，否则 prefill 不生效
if "var FIELD = '所在城市'" not in _join_h:
    bad("入驻页的预填字段名常量丢了（应为「所在城市」）")
else:
    ok("预填字段名锁定为「所在城市」")

if 'id="cpSubmit"' not in _join_h or 'id="cpProvince"' not in _join_h:
    bad("入驻页缺少选择器或提交按钮节点")
else:
    ok("选择器与提交按钮节点齐全")

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 62)
if FAIL:
    print(f"  结果：{len(FAIL)} 项失败，{len(WARN)} 项警告")
    for f in FAIL:
        print(f"    ✗ {f}")
    sys.exit(1)
print(f"  结果：全部通过（{len(WARN)} 项警告）")
for w in WARN:
    print(f"    · {w}")
print("=" * 62)
