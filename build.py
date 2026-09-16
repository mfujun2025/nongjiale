# -*- coding: utf-8 -*-
"""
农家乐.cn 静态站生成器

    python build.py

读 data/ 下的 JSON，套 templates/ 生成 public/。
不清空 public/（本机 Python 删除操作会被路由到回收站），覆盖式写入。
"""
import json
import os
import re
import shutil
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
TPL = BASE / "templates"
STATIC = BASE / "static"
PUB = BASE / "public"

TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


# ============================================================ 工具
def esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def read_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write(rel, text):
    p = PUB / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return p


def render(s, mapping):
    """单次正则替换，避免模板值里再含 token 造成级联替换。"""
    return TOKEN_RE.sub(lambda m: str(mapping.get(m.group(1), m.group(0))), s)


def tpl(name):
    with open(TPL / name, "r", encoding="utf-8") as f:
        return f.read()


def fmt(n):
    return f"{n:,}"


# ============================================================ 图形
def art_svg(n, cls=""):
    """田园山川场景，代替照片。8 套配色在 CSS 里定义。"""
    n = ((int(n) - 1) % 8) + 1
    c = (" " + cls) if cls else ""
    return (
        f'<svg class="art art-{n}{c}" viewBox="0 0 400 300" '
        f'preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
        '<rect class="a-sky" width="400" height="300"/>'
        '<circle class="a-sun" cx="312" cy="66" r="30"/>'
        '<path class="a-far" d="M0 152 L64 104 L124 150 L186 92 L252 150 L314 112 L400 156 L400 300 L0 300 Z"/>'
        '<path class="a-near" d="M0 206 C58 188 118 226 178 206 C238 188 298 226 400 200 L400 300 L0 300 Z"/>'
        '<path class="a-field" d="M0 250 C78 240 158 264 238 254 C308 246 358 262 400 254 L400 300 L0 300 Z"/>'
        "</svg>"
    )


ICONS = {
    "bowl": '<path d="M3.5 11h17a8.5 8.5 0 0 1-17 0Z"/><path d="M12 11V7.5"/>'
            '<path d="M9.2 4.8c0 1.4 1.4 1.4 1.4 2.7"/><path d="M13.4 4.8c0 1.4 1.4 1.4 1.4 2.7"/>',
    "basket": '<path d="M4 9.5h16l-1.8 10.5H5.8L4 9.5Z"/><path d="M9.2 9.5 8 5.5"/>'
              '<path d="M14.8 9.5 16 5.5"/>',
    "house": '<path d="M3.5 10.5 12 3.6l8.5 6.9"/><path d="M5.8 9.4v11.1h12.4V9.4"/>'
             '<path d="M10 20.5v-5.6h4v5.6"/>',
    "fish": '<path d="M3.2 12c2.6-3.6 6.1-5.5 9.6-5.5 3.1 0 6.2 1.9 8.7 5.5'
            '-2.5 3.6-5.6 5.5-8.7 5.5-3.5 0-7-1.9-9.6-5.5Z"/>'
            '<path d="m3.2 12-2-4v8l2-4Z"/><circle cx="16.6" cy="10.6" r="1"/>',
    "kid": '<circle cx="8.2" cy="7" r="2.6"/><circle cx="16" cy="8.4" r="2.1"/>'
           '<path d="M3.6 20.4v-3.6a4.6 4.6 0 0 1 9.2 0v3.6"/>'
           '<path d="M13.6 20.4v-3a3.6 3.6 0 0 1 6.8-1.4"/>',
    "fire": '<path d="M12 21.5c3.9 0 6.6-2.6 6.6-6.2 0-3.9-3.4-5.7-4.8-10.1'
            '-1.9 2.9-3.7 3.8-3.7 6.6 0 1.1.4 1.9.4 1.9s-1.3-.6-2.2-.1'
            'c-.8.4-1 1.3-1 2.4 0 3.1 1.9 5.5 4.7 5.5Z"/>',
    "tag": '<path d="M20.6 12.6 12 21.2 3.4 12.6a2 2 0 0 1-.6-1.4V5a2 2 0 0 1 2-2h6.2'
           'a2 2 0 0 1 1.4.6l8.2 8.2a2 2 0 0 1 0 2.8Z"/><circle cx="7.6" cy="7.6" r="1.4"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
             '<path d="M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18Z"/>',
    "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6'
             'A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7'
             'a2 2 0 0 1-.5 2.1L8.1 9.7a16 16 0 0 0 6 6l1.2-1.2a2 2 0 0 1 2.1-.5'
             'c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.9 2.2Z"/>',
    "star": '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.9L12 17.8 5.8 21l1.2-6.9-5-4.9 6.9-1z"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
    "service": '<path d="M4 13a8 8 0 0 1 16 0"/><path d="M4 13v3a2 2 0 0 0 2 2h1v-5H6a2 2 0 0 0-2 2Z"/>'
               '<path d="M20 13v3a2 2 0 0 1-2 2h-1v-5h1a2 2 0 0 1 2 2Z"/>',
}


def icon(name, size=18):
    body = ICONS.get(name, ICONS["star"])
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{body}</svg>')


def star_icon(size=16):
    return (f'<svg class="score-star" width="{size}" height="{size}" viewBox="0 0 24 24" '
            f'fill="currentColor" aria-hidden="true">{ICONS["star"]}</svg>')


# ============================================================ 配置
SITE = read_json(DATA / "site.json")
SHOPS = read_json(DATA / "shops.json")

# 全国地级行政区基准表（337 个，覆盖面远超实际商家数）。由
# tools/build_regions.py 生成。它管「存在性」：这个城市名合不合法、slug 是什么。
REGIONS = read_json(DATA / "regions.json")["regions"]
REGION_BY_SLUG = {r["slug"]: r for r in REGIONS}
REGION_RANK = {r["slug"]: i for i, r in enumerate(REGIONS)}

# 策展城市：手写了简介和标签的那些（data/cities.json）。它管「内容」。
# 没被策展的城市一样可以有页面，只是简介走模板。
CURATED = {c["slug"]: c for c in read_json(DATA / "cities.json")}


def city_meta(slug):
    """一个城市页需要的元数据。

    优先用策展内容（手写简介 + 标签），没有就用基准表兜底。
    为什么必须兜底：商家在入驻表单里能从 337 个地级行政区里挑，
    挑了哪个城市就得有哪个城市的页面 —— 否则同步收进来了、这里却渲染不出来。
    """
    if slug in CURATED:
        c = dict(CURATED[slug])
        c["curated"] = True
        return c

    r = REGION_BY_SLUG.get(slug)
    if r:
        return {
            "slug": slug,
            "name": r["short"],
            "province": r["province"],
            # 模板简介：内容来自实际数据（有几家、价格谁给的），不编故事。
            # 等这个城市攒够商家，再把它挪进 cities.json 写正经简介。
            "desc": f"{r['province']}{r['short']}的农家乐与乡村民宿，"
                    f"价格与联系电话都由商家自己提供。",
            "tags": [],
            "curated": False,
        }

    # 连基准表里都没有 —— 说明数据对不上。不静默丢掉，用 slug 兜底渲染，
    # 让页面照常出，同时把问题喊出来。
    print(f"  [警告] 城市「{slug}」不在 regions.json 里，用 slug 兜底渲染")
    return {"slug": slug, "name": slug, "province": "", "desc": "农家乐与乡村民宿。",
            "tags": [], "curated": False}


# 只给「有商家」的城市建页面。
# 337 个地级行政区里绝大多数是空的，全建页等于给搜索引擎递一堆空页，
# 反而拉低整站质量评估。有商家才有内容，有内容才值得有页面。
_city_hits = {}
for _s in SHOPS:
    _city_hits[_s["city"]] = _city_hits.get(_s["city"], 0) + 1
CITIES = sorted(
    (city_meta(sl) for sl in _city_hits),
    key=lambda c: (-_city_hits[c["slug"]], REGION_RANK.get(c["slug"], 9999)),
)
CITY_MAP = {c["slug"]: c for c in CITIES}
SHOP_BY_SLUG = {s["slug"]: s for s in SHOPS}

# ---- 资讯栏目：一篇一个 JSON，文件名即 slug。
# 正文用 HTML 片段数组存（["<h2>..</h2>", "<p>..</p>"]），
# 这样零依赖、排版可控，不用在构建器里塞一个 markdown 解析器。
NEWS_DIR = DATA / "news"
NEWS_CATS = {
    "recommend": "农家乐推荐",
    "experience": "特色体验",
    "business": "经营动态",
    "trend": "行业趋势",
    "policy": "政策解读",
}


def _load_news():
    if not NEWS_DIR.is_dir():
        return []
    out = []
    for p in sorted(NEWS_DIR.glob("*.json")):
        try:
            a = read_json(p)
        except Exception as e:                                    # noqa: BLE001
            print(f"  [警告] 资讯 {p.name} 解析失败，已跳过：{e}")
            continue
        a.setdefault("slug", p.stem)
        if not a.get("title"):
            print(f"  [警告] 资讯 {p.name} 缺 title，已跳过")
            continue
        out.append(a)
    # 新的在前。同比日期时按 slug 倒序——保证构建可复现，不依赖文件系统顺序
    out.sort(key=lambda a: (a.get("date") or "", a["slug"]), reverse=True)
    return out


NEWS = _load_news()
NEWS_BY_SLUG = {a["slug"]: a for a in NEWS}
NEWS_DATES = sorted({a.get("date") for a in NEWS if a.get("date")}, reverse=True)

# config.local.json > 环境变量 > site.json（webhook 绝不硬编码在前端源码里）
LOCAL_CFG = {}
_cfg_path = BASE / "config.local.json"
if _cfg_path.is_file():
    try:
        LOCAL_CFG = read_json(_cfg_path) or {}
    except Exception as e:
        print(f"  [警告] config.local.json 读取失败，已忽略：{e}")


def cfg(key, env_name, default=""):
    v = LOCAL_CFG.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        v = os.environ.get(env_name) or SITE.get(key) or default
    return str(v or "").strip()


FEISHU_WEBHOOK = cfg("feishu_webhook", "NJ_FEISHU_WEBHOOK")
FEISHU_KEYWORD = cfg("feishu_keyword", "NJ_FEISHU_KEYWORD", "询单") or "询单"

BASE_URL = SITE["base_url"].rstrip("/")
PHONE = SITE["phone"]
PHONE_RAW = re.sub(r"[^\d+]", "", PHONE)

# 商家照片的图床域名（七牛绑定的 CDN 域名）。留空 = 照片全在本地。
# 数据里存的是对象 key（shops/<slug>/01-xxxx.webp），域名放这儿，
# 换 CDN 域名只改这一行，不用动 shops.json 里任何一条商家数据。
PHOTO_CDN = (SITE.get("photo_cdn") or "").strip().rstrip("/")
if PHOTO_CDN and not PHOTO_CDN.startswith("http"):
    PHOTO_CDN = "https://" + PHOTO_CDN

# 可选：拼在每张图床图后面的图片处理参数（七牛「图片样式」分隔符，如 ?imageView2/2/w/800）
# 留空 = 不加参数。等图床跑起来再按需打开，一行配置的事，不用改代码。
PHOTO_SUFFIX = (SITE.get("photo_cdn_suffix") or "").strip()

YEAR = datetime.now().year

TOTAL = len(SHOPS)
CITY_COUNT = len(CITIES)
REVIEW_TOTAL = sum(s.get("reviewCount") or 0 for s in SHOPS)
# 平均分只统计有评价的商家——把没有评价的新商家当成 0 分会把全站均分拉低
_RATED = [s for s in SHOPS if (s.get("reviewCount") or 0)]
AVG_SCORE = (round(sum(s.get("score") or 0 for s in _RATED) / len(_RATED), 1)
             if _RATED else 0.0)
FEATURED = [s for s in SHOPS if s.get("featured")]

# 全站出现过的标签，按出现次数排序
_tag_count = {}
for _s in SHOPS:
    for _t in (_s.get("tags") or []):
        _tag_count[_t] = _tag_count.get(_t, 0) + 1
ALL_TAGS = [t for t, _ in sorted(_tag_count.items(), key=lambda kv: (-kv[1], kv[0]))]

CFG_SCRIPT = (
    "<script>window.__NJ_CFG__="
    + json.dumps({"webhook": FEISHU_WEBHOOK, "keyword": FEISHU_KEYWORD, "site": SITE["name"]},
                 ensure_ascii=False, separators=(",", ":"))
    + ";</script>"
)


# ============================================================ 公共片段
def nav_html(active=""):
    links = []
    for it in SITE["nav"]:
        cls = ' class="is-active"' if it["url"] == active else ""
        links.append(f'<a href="{it["url"]}"{cls}>{esc(it["label"])}</a>')
    links.append('<span class="nav-cta"><a class="btn btn-primary btn-sm" href="/join/">免费入驻</a></span>')

    return f'''<header class="nav">
  <div class="wrap nav-inner">
    <a class="brand" href="/" aria-label="{esc(SITE['name'])} 首页">
      <span class="brand-mark">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 3 5.5 9.5a9 9 0 1 0 13 0L12 3Z" fill="#fff" opacity=".92"/>
          <path d="M12 7.5 9 10.5a4.2 4.2 0 1 0 6 0L12 7.5Z" fill="#3D8A5A"/>
        </svg>
      </span>
      <span>
        <span class="brand-text">{esc(SITE['name'])}</span>
        <span class="brand-sub">NONGJIALE</span>
      </span>
    </a>
    <input type="checkbox" id="navToggle" class="nav-toggle">
    <label class="nav-burger" for="navToggle" aria-label="打开或关闭导航菜单">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" aria-hidden="true">
        <path d="M4 7h16M4 12h16M4 17h16"/>
      </svg>
    </label>
    <nav class="nav-links" aria-label="主导航">
      {''.join(links)}
    </nav>
  </div>
</header>'''


def footer_html():
    city_links = "".join(
        f'<li><a href="/city/{c["slug"]}/">{esc(c["name"])}农家乐</a></li>' for c in CITIES
    )
    nav_links = "".join(
        f'<li><a href="{it["url"]}">{esc(it["label"])}</a></li>'
        for it in SITE["nav"] if it["url"] != "/"
    )
    beian = ""
    if SITE.get("icp"):
        beian += f'<a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener nofollow">{esc(SITE["icp"])}</a>'
    if SITE.get("police"):
        beian += f'<span>{esc(SITE["police"])}</span>'

    return f'''<footer class="footer">
  <div class="wrap">
    <div class="footer-top">
      <div>
        <a class="brand" href="/">
          <span class="brand-mark">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 3 5.5 9.5a9 9 0 1 0 13 0L12 3Z" fill="#fff" opacity=".92"/>
              <path d="M12 7.5 9 10.5a4.2 4.2 0 1 0 6 0L12 7.5Z" fill="#3D8A5A"/>
            </svg>
          </span>
          <span>
            <span class="brand-text">{esc(SITE['name'])}</span>
            <span class="brand-sub">NONGJIALE</span>
          </span>
        </a>
        <p class="footer-about">
          {esc(SITE['slogan'])}。收录各地农家乐与乡村民宿，按城市和玩法找，价格评价都摆在明面上，
          看中直接打电话给老板。
        </p>
        <p class="footer-about" style="margin-top:16px">
          商家入驻与合作：<a href="tel:{PHONE_RAW}" style="color:#fff;font-weight:600">{esc(PHONE)}</a>
        </p>
      </div>
      <div class="footer-cols">
        <div>
          <h4>按城市找</h4>
          <ul>{city_links}</ul>
        </div>
        <div>
          <h4>关于本站</h4>
          <ul>{nav_links}</ul>
        </div>
        <div>
          <h4>联系方式</h4>
          <ul>
            <li>客服电话：{esc(PHONE)}</li>
            <li>{esc(SITE.get('phone_note', ''))}</li>
            <li><a href="/join/">商家免费入驻 →</a></li>
          </ul>
        </div>
      </div>
    </div>
    <div class="footer-bottom">
      <div>© {YEAR} {esc(SITE['name'])} {beian}</div>
      <div><a href="/sitemap/">网站地图</a></div>
    </div>
  </div>
</footer>'''


def page(content, title, desc, canonical, active="", robots="index,follow",
         og_type="website", body_attr="", scripts="", json_ld=""):
    map_ = {
        "TITLE": esc(title),
        "DESC": esc(desc),
        "KEYWORDS": esc(SITE["keywords"]),
        "CANONICAL": canonical,
        "ROBOTS": robots,
        "OG_TYPE": og_type,
        "NAV": nav_html(active),
        "FOOTER": footer_html(),
        "CONTENT": content,
        "BODY_ATTR": body_attr,
        "JSON_LD": f'<script type="application/ld+json">{json_ld}</script>' if json_ld else "",
        "SCRIPTS": CFG_SCRIPT + '<script src="/js/site.js" defer></script>' + scripts,
    }
    out = render(tpl("layout.html"), map_)

    left = TOKEN_RE.findall(out)
    if left:
        raise RuntimeError(f"[{canonical}] 模板存在未替换的占位符：{sorted(set(left))}")
    return out


def json_ld(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def breadcrumb(items):
    return json_ld({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": BASE_URL + u}
            for i, (n, u) in enumerate(items)
        ],
    })


# ============================================================ 卡片
def city_card(c):
    n = sum(1 for s in SHOPS if s["city"] == c["slug"])
    return f'''<a class="city-card" href="/city/{c['slug']}/">
  <div class="city-art">
    {art_svg(CITIES.index(c) + 1)}
    <span class="city-veil"></span>
    <span class="city-name">{esc(c['name'])}<span class="city-count">{n} 家</span></span>
  </div>
  <div class="city-foot">
    <p>{esc(c['desc'])}</p>
  </div>
</a>'''


# ---------------------------------------------------------------- 商家卡片零件
# 新入驻商家没有评分、评价数、距离、房型——这些字段一律按"缺失"渲染，
# 而不是塞 0。显示「0.0 分（0 条评价）」会让新店看起来可疑，
# 显示「新入驻」反而是中性且有吸引力的。老数据不受影响。

def _meta_line(s, c):
    """城市 · 区县 [+ 距市中心距离]。没有距离数据就整段省略，不留空位。"""
    bits = [f"<span>{esc(c['name'])} · {esc(s.get('district') or '')}</span>"]
    d = s.get("distance") or 0
    if d:
        bits.append('<span class="dot"></span>')
        bits.append(f"<span>距市中心 {d}km</span>")
    return "".join(bits)


def _score_block(s, unit="条评价"):
    n = s.get("reviewCount") or 0
    if n:
        return (f'<span class="score">{star_icon(15)}'
                f'<span class="score-num">{s["score"]}</span>'
                f'<span class="score-from">{n} {unit}</span></span>')
    return f'<span class="score score--new">{icon("shield", 14)}新入驻</span>'


def _price_block(s, unit="/ 人"):
    p = s.get("price") or 0
    if not p:
        return '<span class="price"><span class="price-ask">价格面议</span></span>'
    return (f'<span class="price"><span class="price-sym">¥</span>'
            f'<span class="price-num">{p}</span>'
            f'<span class="price-unit">{unit}</span></span>')


def _photo_src(p):
    """照片地址。两种形态都能渲染，图床换不换域名都不用改商家数据。

        /uploads/<slug>/01.webp        → 本地，原样用
        https://...                    → 已是完整地址，原样用
        shops/<slug>/01-a3f9.webp      → 图床对象 key，前面拼 CDN 域名
    """
    p = str(p or "")
    if not p:
        return ""
    if p.startswith(("/", "http://", "https://")):
        return p + PHOTO_SUFFIX
    return f"{PHOTO_CDN}/{p.lstrip('/')}{PHOTO_SUFFIX}"


def _check_photo_config(shop_list):
    """构建前的自检：数据里是图床 key、但 site.json 没配图床域名 → 全站裂图。

    这种情况必须吵出来。悄悄输出 /shops/xxx.webp 会变成 404，
    而 404 的图片在浏览器里只是一片空白，很难一眼看出是配置漏了。
    """
    if PHOTO_CDN:
        return 0
    orphan = sum(1 for s in shop_list
                 for p in (s.get("photos") or [])
                 if not str(p).startswith(("/", "http://", "https://")))
    if orphan:
        print(f"\n  ⚠⚠ 有 {orphan} 张照片是图床对象 key，但 data/site.json 里"
              f"没填 photo_cdn！\n"
              f"      这些图会 404。两条路任选：\n"
              f"      · 接图床：把七牛绑定的 CDN 域名填进 site.json 的 photo_cdn\n"
              f"      · 不接图床：用同步脚本的 --no-upload 重新同步一次，照片会落回本地\n")
    return orphan


def _art_or_photo(s, cls=""):
    """有实拍照片用照片，没有就回落到 SVG 插画。新老数据可以混排。"""
    photos = s.get("photos") or []
    if photos:
        return (f'<img class="photo {cls}" src="{esc(_photo_src(photos[0]))}" '
                f'alt="{esc(s["name"])}" loading="lazy" decoding="async">')
    return art_svg(s.get("art") or 1, cls)


def shop_card(s):
    c = CITY_MAP[s["city"]]
    badge = ('<span class="badge-featured">'
             + icon("star", 13) + '精选</span>') if s.get("featured") else ""
    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in (s.get("tags") or [])[:3])
    return f'''<article class="shop-card">
  <a class="shop-art" href="/shop/{s['slug']}/" aria-label="{esc(s['name'])}">
    {_art_or_photo(s)}
    {badge}
  </a>
  <div class="shop-body">
    <div class="shop-meta">{_meta_line(s, c)}</div>
    <h3 class="shop-name"><a href="/shop/{s['slug']}/">{esc(s['name'])}</a></h3>
    <div class="shop-tags">{tags}</div>
    <div class="shop-foot">
      {_price_block(s, "/ 人")}
      {_score_block(s, "条")}
    </div>
  </div>
</article>'''


def shop_row(s):
    """列表页用的横向卡。排序/筛选靠 data-* 属性，前端 list.js 读。
    缺失字段统一给 0，让 list.js 的排序不会因为 undefined 出错。"""
    c = CITY_MAP[s["city"]]
    tag_list = s.get("tags") or []
    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in tag_list)
    badge = ('<span class="badge-featured">'
             + icon("star", 13) + '精选</span>') if s.get("featured") else ""
    searchable = (f"{s['name']} {c['name']} {s.get('district') or ''} "
                  f"{' '.join(tag_list)} {s.get('intro') or ''}")
    return f'''<article class="shop-row"
    data-slug="{s['slug']}" data-name="{esc(s['name'])}" data-city="{s['city']}"
    data-price="{s.get('price') or 0}" data-distance="{s.get('distance') or 0}"
    data-score="{s.get('score') or 0}" data-new="{0 if (s.get('reviewCount') or 0) else 1}"
    data-tags="{esc(','.join(tag_list))}" data-text="{esc(searchable.lower())}">
  <a class="shop-art" href="/shop/{s['slug']}/" aria-label="{esc(s['name'])}">
    {_art_or_photo(s)}
    {badge}
  </a>
  <div class="shop-row-body">
    <div class="shop-meta">{_meta_line(s, c)}</div>
    <h3 class="shop-name"><a href="/shop/{s['slug']}/">{esc(s['name'])}</a></h3>
    <p style="font-size:14px;color:var(--text-2);line-height:1.75">{esc(s.get('intro') or '')}</p>
    <div class="shop-tags">{tags}</div>
    <div class="shop-foot">
      {_price_block(s, "/ 人（含餐）")}
      {_score_block(s, "条评价")}
    </div>
  </div>
</article>'''


def city_chips(active=""):
    out = []
    for c in CITIES:
        cls = "chip is-on" if c["slug"] == active else "chip"
        out.append(f'<a class="{cls}" data-chip="city" data-value="{c["slug"]}" '
                   f'href="/list/?city={c["slug"]}">{esc(c["name"])}</a>')
    return "".join(out)


def tag_chips(active=""):
    out = []
    for t in ALL_TAGS:
        cls = "chip is-on" if t == active else "chip"
        out.append(f'<a class="{cls}" data-chip="tag" data-value="{esc(t)}" '
                   f'href="/list/?tag={urllib.parse.quote(t)}">{esc(t)}</a>')
    return "".join(out)


def filter_tags():
    return "".join(
        f'<button class="filter-opt" type="button" data-value="{esc(t)}">{esc(t)}</button>'
        for t in ALL_TAGS
    )


def stats_html():
    items = [
        (fmt(TOTAL), "", "收录农家乐"),
        (str(CITY_COUNT), " 城", "覆盖城市"),
        (fmt(REVIEW_TOTAL), " +", "真实评价"),
        (str(AVG_SCORE), " 分", "平均评分"),
    ]
    return "".join(
        f'<div class="stat"><div class="stat-num">{n}<small>{u}</small></div>'
        f'<div class="stat-label">{l}</div></div>'
        for n, u, l in items
    )


def review_cards():
    """从各商家里挑评分最高的三家，各取一条 5 分评价。"""
    picks = []
    for s in sorted(SHOPS, key=lambda x: (-(x.get("score") or 0),
                                          -(x.get("reviewCount") or 0))):
        r = next((x for x in (s.get("reviews") or []) if x["score"] == 5), None)
        if r:
            picks.append((s, r))
        if len(picks) == 3:
            break

    out = []
    for s, r in picks:
        c = CITY_MAP[s["city"]]
        out.append(f'''<article class="review-card">
  <div class="review-head">
    <span class="avatar" aria-hidden="true">{esc(r['user'][0])}</span>
    <span class="review-who">
      <strong>{esc(r['user'])}</strong>
      <span>来自{esc(r['from'])} · {esc(r['date'])}</span>
    </span>
    <span class="score" style="margin-left:auto">{star_icon(14)}<span class="score-num">{r['score']}.0</span></span>
  </div>
  <p class="review-text">{esc(r['text'])}</p>
  <a class="review-shop" href="/shop/{s['slug']}/">—— {esc(c['name'])} · {esc(s['name'])}</a>
</article>''')
    return "".join(out)


def exp_cards():
    icons = ["bowl", "basket", "house", "fish", "kid", "fire"]
    return "".join(f'''<a class="exp-card" href="/list/?tag={urllib.parse.quote(e['name'][-2:])}">
  <span class="exp-icon">{art_svg(e['art'])}</span>
  <h3>{esc(e['name'])}</h3>
  <p>{esc(e['desc'])}</p>
</a>''' for e in SITE["experiences"])


# ============================================================ 资讯
def news_body(a):
    """正文：数组按顺序拼；也容忍直接给字符串（单段）。"""
    b = a.get("body")
    if isinstance(b, list):
        return "\n".join(str(x) for x in b)
    return str(b or "")


def news_plain(a):
    """剥掉标签的纯文本，用来数中文字数。"""
    return re.sub(r"<[^>]+>", "", news_body(a))


def news_chars(a):
    return len(re.findall(r"[\u4e00-\u9fff]", news_plain(a)))


def news_read_min(a):
    """按中文 400 字/分钟估。少于 1 分钟一律显示 1——「0 分钟」很蠢。"""
    return max(1, round(news_chars(a) / 400))


def news_date(a, style="full"):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", a.get("date") or "")
    if not m:
        return a.get("date") or ""
    y, mo, da = m.groups()
    if style == "md":
        return f"{mo}-{da}"
    if style == "short":
        return f"{int(mo)} 月 {int(da)} 日"
    return f"{y} 年 {int(mo)} 月 {int(da)} 日"


def news_cat(a):
    return NEWS_CATS.get(a.get("category") or "", a.get("category_name") or "资讯")


def news_card(a):
    return f'''<a class="news-card" href="/news/{a['slug']}/">
  <span class="news-cat">{esc(news_cat(a))}</span>
  <h3>{esc(a['title'])}</h3>
  <p>{esc(a.get('summary') or '')}</p>
  <span class="news-meta">{esc(news_date(a))} · 约 {news_read_min(a)} 分钟读完</span>
</a>'''


def news_cat_chips(active=""):
    """只列出真正有文章的栏目——点进去发现是空列表最伤体验。"""
    used = {a.get("category") for a in NEWS if a.get("category") in NEWS_CATS}
    chips = [f'<a class="chip{" is-on" if not active else ""}" href="/news/">全部</a>']
    for key, name in NEWS_CATS.items():
        if key in used:
            on = " is-on" if key == active else ""
            chips.append(f'<a class="chip{on}" href="/news/cat/{key}/">{esc(name)}</a>')
    return "".join(chips)


def news_sources(a):
    src = a.get("sources") or []
    if not src:
        return ""
    lis = "".join(
        f'<li><a href="{esc(s.get("url", ""))}" target="_blank" rel="noopener nofollow">'
        f'{esc(s.get("name", ""))}</a></li>' for s in src if s.get("url")
    )
    return f'''<div class="art-src">
  <h2>信息来源</h2>
  <ul>{lis}</ul>
  <p class="art-src-note">以上为本文引用的公开资料。政策与数据以官方原文为准，本站不代为解读未明确的内容。</p>
</div>'''


def news_related(a, limit=3):
    """延伸阅读：同栏目优先，不足用最新的补。"""
    same = [x for x in NEWS if x["slug"] != a["slug"] and x.get("category") == a.get("category")]
    others = [x for x in NEWS if x["slug"] != a["slug"] and x not in same]
    picked = (same + others)[:limit]
    if not picked:
        return ""
    return f'''<div class="art-rel">
  <h2>延伸阅读</h2>
  <div class="grid-news">{''.join(news_card(x) for x in picked)}</div>
</div>'''


# ============================================================ 页面：首页
def build_home():
    city_options = "".join(
        f'<option value="{c["slug"]}">{esc(c["name"])}</option>' for c in CITIES
    )
    hero_hots = "".join(
        f'<a href="/list/?q={urllib.parse.quote(h)}">{esc(h)}</a>' for h in SITE["hots"]
    )

    stat_rows = [
        (fmt(TOTAL), "收录农家乐"),
        (fmt(REVIEW_TOTAL) + " +", "真实评价"),
        (str(CITY_COUNT), "覆盖城市"),
        (str(AVG_SCORE) + " 分", "平均评分"),
    ]
    hero_stat = "".join(
        f'<div class="hero-stat-row"><span class="hero-stat-num">{n}</span>'
        f'<span class="hero-stat-label">{l}</span></div>'
        for n, l in stat_rows
    ) + ('<p class="hero-stat-note">数据来自平台收录与核验。'
         '评分与评价均来自实际到店游客，差评不删。</p>')

    cta_points = "".join(
        f'<span class="cta-point">{icon("star", 15)}{esc(a["title"])}</span>'
        for a in SITE["advantages"][:4]
    )

    content = render(tpl("home.html"), {
        "HERO_TITLE": esc(SITE["hero_title"]),
        "HERO_SUB": esc(SITE["hero_sub"]),
        "CITY_OPTIONS": city_options,
        "HERO_HOTS": hero_hots,
        "HERO_STAT_ROWS": hero_stat,
        "CITY_CARDS": "".join(city_card(c) for c in CITIES),
        "EXP_CARDS": exp_cards(),
        "SHOP_CARDS": "".join(shop_card(s) for s in FEATURED[:6]),
        "STATS": stats_html(),
        "REVIEW_CARDS": review_cards(),
        "NEWS_CARDS": ('<div class="grid-news">' + "".join(news_card(a) for a in NEWS[:3]) + "</div>")
                       if NEWS else '<p class="empty-note">资讯栏目正在筹备，敬请期待。</p>',
        "CTA_POINTS": cta_points,
        "TOTAL": TOTAL,
    })

    ld = json_ld({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": BASE_URL + "/#website",
                "url": BASE_URL + "/",
                "name": SITE["name"],
                "description": SITE["describe"],
                "inLanguage": "zh-CN",
                "publisher": {"@id": BASE_URL + "/#org"},
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": {"@type": "EntryPoint",
                               "urlTemplate": BASE_URL + "/list/?q={search_term_string}"},
                    "query-input": "required name=search_term_string",
                },
            },
            {
                "@type": "Organization",
                "@id": BASE_URL + "/#org",
                "name": SITE["name"],
                "url": BASE_URL + "/",
                "telephone": PHONE,
                "areaServed": "CN",
            },
        ],
    })

    return page(content, f"{SITE['name']} - 全国农家乐信息平台｜按城市找农家乐、看价格与评价",
                SITE["describe"], BASE_URL + "/", active="/", json_ld=ld)


# ============================================================ 页面：列表
def build_list():
    # 默认顺序：精选在前，其次评分、评价量 —— 与 list.js 的「综合排序」一致
    ordered = sorted(SHOPS, key=lambda s: (not s.get("featured"),
                                           -(s.get("score") or 0),
                                           -(s.get("reviewCount") or 0)))

    content = render(tpl("list.html"), {
        "LIST_SUB": f"收录全国 {TOTAL} 家农家乐，覆盖 {CITY_COUNT} 座城市。"
                    f"按人均价格、特色服务和距市中心的距离筛一遍，看中就打电话。",
        "CITY_CHIPS": city_chips(),
        "TAG_CHIPS": tag_chips(),
        "FILTER_TAGS": filter_tags(),
        "SHOP_ROWS": "".join(shop_row(s) for s in ordered),
        "TOTAL": TOTAL,
    })
    scripts = '<script src="/js/list.js" defer></script>'
    ld = json_ld({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "找农家乐",
        "description": f"全国 {TOTAL} 家农家乐列表，支持按城市、人均价格、特色服务筛选。",
        "url": BASE_URL + "/list/",
        "inLanguage": "zh-CN",
    })
    return page(content, f"找农家乐 - 全国 {TOTAL} 家农家乐列表｜按价格与玩法筛选",
                f"全国 {TOTAL} 家农家乐完整列表，覆盖 {CITY_COUNT} 座城市。"
                f"可按城市、人均价格、特色服务（采摘、垂钓、烧烤、民宿）和距市中心距离筛选，"
                f"支持按评分和价格排序。",
                BASE_URL + "/list/", active="/list/", scripts=scripts, json_ld=ld)


# ============================================================ 页面：城市索引
def build_cities():
    content = render(tpl("cities.html"), {
        "CITY_COUNT": CITY_COUNT,
        "TOTAL": TOTAL,
        "CITY_CARDS": "".join(city_card(c) for c in CITIES),
    })
    ld = json_ld({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "热门城市",
        "url": BASE_URL + "/cities/",
        "inLanguage": "zh-CN",
    })
    return page(content, f"热门城市 - 覆盖 {CITY_COUNT} 座城市的农家乐分布",
                f"农家乐.cn 目前覆盖 {CITY_COUNT} 座城市、{TOTAL} 家农家乐，"
                f"每座城市都有独立页面，可按玩法、人均价格和距离继续筛选。",
                BASE_URL + "/cities/", active="/cities/", json_ld=ld)


# ============================================================ 页面：城市落地页
def build_city(c):
    mine = [s for s in SHOPS if s["city"] == c["slug"]]
    mine.sort(key=lambda s: (-(s.get("score") or 0), -(s.get("reviewCount") or 0)))

    others = [x for x in CITIES if x["slug"] != c["slug"]][:3]
    city_tag_chips = "".join(
        f'<a href="/list/?city={c["slug"]}&tag={urllib.parse.quote(t)}" '
        f'style="padding:4px 12px;border-radius:999px;background:rgba(255,255,255,.10);'
        f'color:rgba(255,255,255,.9)">{esc(t)}</a>'
        for t in c["tags"]
    )

    # 价格区间与平均分只在有数据时才写。新入驻商家可能没填价格、也还没评价，
    # 硬算会把 0 算进去，写出「人均 0–300 元、平均 0 分」这种一眼就不对的文案。
    prices = [s["price"] for s in mine if (s.get("price") or 0)]
    scores = [s["score"] for s in mine if (s.get("reviewCount") or 0)]
    price_part = f"价格区间大致在人均 {min(prices)}–{max(prices)} 元，" if prices else ""
    score_part = (f"平均评分 {round(sum(scores) / len(scores), 1)} 分。"
                  if scores else "新商家还在陆续入驻，评价正在累积中。")
    # 首页那句「集中在……」只有策展城市才写得出（要用简介首句）。
    # 新城市没手写简介，硬套会拼成「主要集中在XX的农家乐与乡村民宿」这种病句。
    if c.get("curated"):
        lead = (f"<p>{esc(c['name'])}的农家乐主要集中在{c['desc'].split('。')[0]}。"
                f"目前平台在{esc(c['name'])}收录了 {len(mine)} 家，{price_part}{score_part}</p>")
    else:
        lead = (f"<p>{esc(c['name'])}的农家乐与乡村民宿。目前平台在{esc(c['name'])}"
                f"收录了 {len(mine)} 家，{price_part}{score_part}</p>")

    seo = lead + f'''<p>挑{esc(c['name'])}的农家乐，建议先看<strong>距市中心的公里数</strong>：标 50km 以内的大多是当天来回，
    适合临时起意的周末；80km 以上的更适合住一晚，第二天顺路再玩半天，不然路上时间占比太高。</p>
    <p>再看<strong>玩法是否对得上</strong>。带小孩优先找有采摘园、动物区或浅溪的；朋友聚会重点看有没有烧烤台和棋牌；
    想安静待两天的，直接筛民宿类，注意看房间数和评价里有没有提到隔音。
    每家详情页都列了房型、含餐情况和真实评价，价格也是商家自己给的，出行前打电话再确认一次最稳妥。</p>'''

    content = render(tpl("city.html"), {
        "CITY_NAME": esc(c["name"]),
        "CITY_PROVINCE": esc(c["province"]),
        "CITY_DESC": esc(c["desc"]),
        "CITY_TAG_CHIPS": city_tag_chips,
        "CITY_COUNT": len(mine),
        "SHOP_ROWS": "".join(shop_row(s) for s in mine),
        "CITY_SEO": seo,
        "OTHER_CITIES": "".join(city_card(x) for x in others),
        "TOTAL": TOTAL,
    })

    ld = json_ld({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage",
                "name": f"{c['name']}农家乐",
                "url": f"{BASE_URL}/city/{c['slug']}/",
                "inLanguage": "zh-CN",
                "about": {"@type": "Place", "name": c["name"],
                          "address": {"@type": "PostalAddress",
                                      "addressRegion": c["province"],
                                      "addressCountry": "CN"}},
            },
            json.loads(breadcrumb([("首页", "/"), ("热门城市", "/cities/"), (c["name"], f"/city/{c['slug']}/")])),
        ],
    })

    return page(content,
                f"{c['name']}农家乐 - {len(mine)} 家精选推荐｜价格、评价与电话",
                f"农家乐.cn 收录{c['name']}（{c['province']}）{len(mine)} 家农家乐，"
                f"含人均价格、房型、设施与真实评价。{c['desc']}",
                f"{BASE_URL}/city/{c['slug']}/", active="/cities/", json_ld=ld)


# ============================================================ 页面：商家详情
def build_shop(s):
    """商家详情页。

    新入驻商家没有评分、评价、房型、距离、价格——这里逐项降级：
    缺数据的区块整块不出现，而不是留一个「暂无/0」的空壳。
    详情页的电话一律打给商家自己（回落到平台号）。
    """
    c = CITY_MAP[s["city"]]
    photos = s.get("photos") or []
    reviews = s.get("reviews") or []
    rooms = s.get("rooms") or []
    tags_list = s.get("tags") or []
    fac_list = s.get("facilities") or []
    price = s.get("price") or 0
    score = s.get("score") or 0
    rcount = s.get("reviewCount") or 0
    distance = s.get("distance") or 0
    district = s.get("district") or ""
    shop_phone = s.get("phone") or PHONE
    shop_phone_raw = re.sub(r"[^0-9+]", "", shop_phone) or PHONE_RAW

    # ---- 图库：有实拍照片铺照片（不足三张就重复补位），没有回落 SVG 插画
    if photos:
        shots = (photos * 3)[:3]
        gallery = (f'<div class="g-main"><img class="photo" src="{esc(_photo_src(shots[0]))}" '
                   f'alt="{esc(s["name"])}" loading="lazy" decoding="async"></div>'
                   + "".join(f'<div class="g-sub"><img class="photo" '
                             f'src="{esc(_photo_src(p))}" '
                             f'alt="{esc(s["name"])}" loading="lazy" decoding="async"></div>'
                             for p in shots[1:]))
    else:
        art = s.get("art") or 1
        gallery = (f'<div class="g-main">{art_svg(art)}</div>'
                   f'<div class="g-sub">{art_svg(art % 8 + 1)}</div>'
                   f'<div class="g-sub">{art_svg(art % 8 + 2)}</div>')

    # ---- 头部副信息：没有评价就挂「新入驻」而不是「0 分」
    head = []
    if rcount:
        head.append(f'<span class="score">{star_icon(16)}'
                    f'<span class="score-num">{score}</span>'
                    f'<span class="score-from">{fmt(rcount)} 条评价</span></span>')
    else:
        head.append(f'<span class="score score--new">{icon("shield", 14)}新入驻</span>')
    head.append('<span class="dot"></span>')
    loc = esc(c["name"]) + (f" · {esc(district)}" if district else "")
    if distance:
        loc += f" · 距市中心约 {distance} 公里"
    head.append(f"<span>{loc}</span>")
    if tags_list:
        head.append('<span class="dot"></span>')
        head.append("".join(f'<span class="tag tag--brand">{esc(t)}</span>' for t in tags_list))
    head_meta = "".join(head)

    # ---- 基础信息：缺哪行就不出现哪行
    city_line = esc(c["name"]) + (f" · {esc(district)}" if district else "")
    rating_text = f"{score} 分 / {fmt(rcount)} 条评价" if rcount else "新入驻，暂无评价"
    info_rows = [f'<div class="info-item"><dt>所在城市</dt><dd>{city_line}</dd></div>']
    if distance:
        info_rows.append(f'<div class="info-item"><dt>距市中心</dt><dd>约 {distance} 公里</dd></div>')
    if price:
        info_rows.append(f'<div class="info-item"><dt>人均消费</dt><dd>¥{price} 起（含餐）</dd></div>')
    info_rows.append(f'<div class="info-item"><dt>评分</dt><dd>{rating_text}</dd></div>')
    info_rows.append(f'<div class="info-item"><dt>联系电话</dt><dd>{esc(shop_phone)}</dd></div>')
    if tags_list:
        tags_line = " · ".join(tags_list)
        info_rows.append(f'<div class="info-item"><dt>特色</dt><dd>{esc(tags_line)}</dd></div>')
    info = "".join(info_rows)

    fac = "".join(f'<span class="tag tag--brand">{esc(f)}</span>' for f in fac_list)

    # ---- 房型：只做餐饮的农家乐本来就没这一块，整块省略
    if rooms:
        room_rows = "".join(
            f'<tr><td class="room-name">{esc(r.get("name") or "")}</td>'
            f'<td>{esc(r.get("bed") or "")}</td>'
            f'<td>{esc(r.get("area") or "")}</td>'
            f'<td class="room-note">{esc(r.get("note") or "")}</td>'
            f'<td style="text-align:right;font-weight:600;color:var(--brand-deep)">'
            f'¥{r.get("price") or 0}</td></tr>' for r in rooms)
        rooms_section = f'''<section class="panel" id="rooms">
        <h2>房型与价格</h2>
        <div class="table-scroll">
          <table class="room-table">
            <thead>
              <tr>
                <th>房型</th>
                <th>床位</th>
                <th>面积</th>
                <th>含餐</th>
                <th style="text-align:right">每晚</th>
              </tr>
            </thead>
            <tbody>
              {room_rows}
            </tbody>
          </table>
        </div>
        <p style="font-size:13px;color:var(--text-3);margin-top:14px">
          房价为平日参考价，节假日与周末可能上浮，建议电话确认。
        </p>
      </section>'''
        room_min = min((r.get("price") or 0) for r in rooms) or 0
        book_note = (f'<div class="book-note">房价 ¥{room_min} 起 · 平日参考价</div>'
                     if room_min else '<div class="book-note">房价以电话确认为准</div>')
        book_rooms_btn = '<a class="btn btn-ghost btn-block" href="#rooms">查看房型与价格</a>'
    else:
        rooms_section = ""
        room_min = 0
        book_note = '<div class="book-note">是否提供住宿与具体价格，建议电话确认</div>'
        book_rooms_btn = ""

    # ---- 评价：新商家给一段正向文案，而不是一片空白
    if rcount and reviews:
        base = score
        dims = [("环境", round(min(5, base + 0.1), 1)),
                ("服务", round(min(5, base + 0.05), 1)),
                ("餐饮", round(max(4.0, base - 0.05), 1)),
                ("性价比", round(max(4.0, base - 0.1), 1))]
        bars = "".join(
            f'<div class="rate-bar"><span>{n}</span>'
            f'<span class="rate-track"><span class="rate-fill" '
            f'style="width:{v / 5 * 100:.0f}%"></span></span>'
            f'<span class="rate-val">{v}</span></div>' for n, v in dims)
        review_list = "".join(f'''<article class="review-card" style="box-shadow:none">
  <div class="review-head">
    <span class="avatar" aria-hidden="true">{esc(r['user'][0])}</span>
    <span class="review-who"><strong>{esc(r['user'])}</strong>
      <span>来自{esc(r['from'])} · {esc(r['date'])}</span></span>
    <span class="score" style="margin-left:auto">{star_icon(14)}<span class="score-num">{r['score']}.0</span></span>
  </div>
  <p class="review-text">{esc(r['text'])}</p>
</article>''' for r in reviews)
        reviews_section = f'''<section class="panel">
        <h2>用户评价</h2>
        <div class="rate-bars" style="margin-bottom:24px">
          {bars}
        </div>
        <div class="stack-list">
          {review_list}
        </div>
      </section>'''
    else:
        reviews_section = '''<section class="panel">
        <h2>用户评价</h2>
        <p style="color:var(--text-2);line-height:1.85">
          这家是刚上线的新商家，评价还在累积中。去过的话，欢迎把你的真实体验告诉我们——
          核实之后我们会补充到这里，对后来的客人帮很大。
        </p>
      </section>'''

    nearby_pool = [x for x in SHOPS if x["city"] == s["city"] and x["slug"] != s["slug"]][:3]
    nearby = ""
    if nearby_pool:
        nearby = f'''<section class="panel">
  <h2>{esc(c['name'])}的其他农家乐</h2>
  <div class="grid-shops">{''.join(shop_card(x) for x in nearby_pool)}</div>
</section>'''

    # ---- 预订卡与吸底栏：没填价格就显示「电话询价」，不要出现 ¥0
    if price:
        book_price = (f'<div class="book-price"><span class="price">'
                      f'<span class="price-sym">¥</span>'
                      f'<span class="price-num">{price}</span></span>'
                      f'<span class="price-unit">/ 人起（含餐）</span></div>')
        bar_price = (f'<div class="bar-price"><span class="price">'
                     f'<span class="price-sym">¥</span>'
                     f'<span class="price-num">{price}</span></span>'
                     f'<small>人均 · 含餐</small></div>')
    else:
        book_price = ('<div class="book-price"><span class="price">'
                      '<span class="price-ask">电话询价</span></span>'
                      '<span class="price-unit">含餐情况请电话确认</span></div>')
        bar_price = ('<div class="bar-price"><span class="price">'
                     '<span class="price-ask">电话询价</span></span></div>')

    # ---- 位置说明
    loc_note = f"{esc(c['name'])}{esc(district)}"
    if distance:
        loc_note += f" · 距市中心约 {distance} 公里"
    loc_note += f"。导航搜索「{esc(s['name'])}」即可直达。"

    content = render(tpl("shop.html"), {
        "CITY_SLUG": c["slug"],
        "CITY_NAME": esc(c["name"]),
        "CITY_ART": s.get("art") or 1,
        "SHOP_NAME": esc(s["name"]),
        "DISTRICT": esc(district),
        "HEAD_META": head_meta,
        "BOOK_PRICE": book_price,
        "BAR_PRICE": bar_price,
        "BOOK_NOTE": book_note,
        "BOOK_ROOMS_BTN": book_rooms_btn,
        "ROOMS_SECTION": rooms_section,
        "REVIEWS_SECTION": reviews_section,
        "LOCATION_NOTE": loc_note,
        "PHONE": esc(shop_phone),
        "PHONE_RAW": shop_phone_raw,
        "GALLERY": gallery,
        "INTRO": esc(s.get("intro") or ""),
        "INFO_GRID": info,
        "FACILITIES": fac,
        "NEARBY": nearby,
    })

    # ---- 结构化数据：没有评价时不能带 aggregateRating，否则 Google 判为无效标记
    biz = {
        "@type": ["LocalBusiness", "Restaurant"],
        "@id": f"{BASE_URL}/shop/{s['slug']}/#biz",
        "name": s["name"],
        "description": s.get("intro") or "",
        "url": f"{BASE_URL}/shop/{s['slug']}/",
        "telephone": shop_phone,
        "address": {"@type": "PostalAddress",
                    "addressLocality": c["name"],
                    "addressRegion": c["province"],
                    "addressCountry": "CN"},
    }
    if price:
        biz["priceRange"] = f"¥{price}/人"
    if rcount:
        biz["aggregateRating"] = {"@type": "AggregateRating",
                                  "ratingValue": score,
                                  "reviewCount": rcount,
                                  "bestRating": 5}
    if fac_list:
        biz["amenityFeature"] = [{"@type": "LocationFeatureSpecification",
                                  "name": f, "value": True} for f in fac_list]

    ld = json_ld({
        "@context": "https://schema.org",
        "@graph": [
            biz,
            json.loads(breadcrumb([("首页", "/"), ("热门城市", "/cities/"),
                                   (c["name"], f"/city/{c['slug']}/"),
                                   (s["name"], f"/shop/{s['slug']}/")])),
        ],
    })

    # ---- 标题与描述：缺评分/价格时不硬凑，避免出现「人均 ¥None、None 分」
    title = f"{s['name']} - {c['name']}{district}{'农家乐' if not district else ''}"
    extras = []
    if price:
        extras.append(f"人均 ¥{price}")
    if rcount:
        extras.append(f"{score} 分")
    if extras:
        title += "｜" + "、".join(extras)

    desc_bits = [s.get("intro") or "", f"位于{c['name']}{district}。"]
    if distance:
        desc_bits.append(f"距市中心约 {distance} 公里。")
    if price:
        desc_bits.append(f"人均 ¥{price} 起。")
    if rcount:
        desc_bits.append(f"评分 {score} 分（{fmt(rcount)} 条评价）。")
    else:
        desc_bits.append("新入驻商家，评价正在累积。")
    if tags_list:
        desc_bits.append(f"特色：{'、'.join(tags_list)}。")
    desc_bits.append(f"预订与咨询电话 {shop_phone}。")

    return page(content, title, "".join(desc_bits),
                f"{BASE_URL}/shop/{s['slug']}/", active="/list/",
                og_type="article", body_attr=' class="has-mobile-bar"', json_ld=ld)


# ============================================================ 页面：入驻
def build_join():
    steps = [
        ("01", "填表提交", "必填五项：名称、城市、经营电话、三张照片、确认授权。全程不用注册账号。"),
        ("02", "人工核验", "我们打一次电话确认，并交叉核对地址与网上公开信息，1 个工作日内完成。"),
        ("03", "补充资料", "房型、价格、特色标签可以这时补，也可以等上线之后再补。"),
        ("04", "自动上线", "审核通过后由系统自动发布，你马上就能在对应城市的列表里被客人搜到。"),
    ]
    steps_html = "".join(
        f'<div class="step"><div class="step-no">{n}</div>'
        f'<h3>{esc(t)}</h3><p>{esc(d)}</p></div>' for n, t, d in steps
    )
    # 权益的 icon 字段是业务名，映射到实际图标
    ADV_ICON = {"free": "tag", "expose": "globe", "phone": "phone",
                "star": "star", "shield": "shield", "service": "service"}
    adv_html = "".join(
        f'<div class="adv-card"><span class="adv-icon">'
        f'{icon(ADV_ICON.get(a["icon"], "star"), 20)}</span>'
        f'<div><h3>{esc(a["title"])}</h3><p>{esc(a["desc"])}</p></div></div>'
        for a in SITE["advantages"]
    )
    faq_html = "".join(
        f'<details><summary>{esc(f["q"])}</summary>'
        f'<div class="faq-body">{esc(f["a"])}</div></details>'
        for f in SITE["faq"]
    )

    content = render(tpl("join.html"), {
        "STEPS": steps_html,
        "ADV_CARDS": adv_html,
        "FAQ": faq_html,
        "JOIN_FORM_URL": esc(SITE.get("join_form_url", "")),
        "JOIN_FORM_NOTE": esc(SITE.get("join_form_note", "")),
        # 入驻可选项是全域的（337 个地级行政区），跟站点已收录的城市数不是一回事。
        # 商家最关心「我的城市能不能填」，所以在这儿明确给个数。
        "CITY_TOTAL": str(len(REGIONS)),
        "PHONE": esc(PHONE),
        "PHONE_RAW": PHONE_RAW,
        "PHONE_NOTE": esc(SITE.get("phone_note", "")),
    })

    ld = json_ld({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebPage", "name": "商家入驻", "url": BASE_URL + "/join/",
             "inLanguage": "zh-CN"},
            {"@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in SITE["faq"]]},
        ],
    })

    return page(content, "商家免费入驻 - 农家乐.cn｜免费收录、按城市推荐、电话直连客人",
                f"农家乐、乡村民宿、采摘园、垂钓园免费入驻农家乐.cn。不收入年费、不抽佣金，"
                f"提交四项信息即可上线，1 个工作日内完成核验。合作电话 {PHONE}。",
                BASE_URL + "/join/", active="/join/", json_ld=ld)


# ============================================================ 页面：关于
def build_about():
    content = render(tpl("about.html"), {
        "PHONE": esc(PHONE),
        "PHONE_RAW": PHONE_RAW,
        "PHONE_NOTE": esc(SITE.get("phone_note", "")),
    })
    return page(content, "关于我们 - 农家乐.cn｜只做信息，不碰交易",
                "农家乐.cn 是全国农家乐信息平台，只做信息收录与展示，不自建预订、不代收款、不抽佣金。"
                "了解我们的收录标准、评分规则与联系方式。",
                BASE_URL + "/about/", active="/about/")


# ============================================================ 页面：资讯
NEWS_DESC = ("农家乐行业资讯与实用指南：农家乐推荐、特色体验玩法、经营动态、行业趋势与政策解读。"
             "每周更新，写给想出门的人，也写给开农家乐的人。")


def build_news(items=None, cat_key="", cat_name=""):
    items = NEWS if items is None else items
    title = f"{cat_name} - 农家乐资讯" if cat_key else "农家乐资讯"
    h1 = cat_name if cat_key else "农家乐资讯"
    sub = (f"共 {len(items)} 篇" if items else "内容准备中")
    if cat_key:
        sub += " · 返回全部资讯请看下方导航"

    if items:
        cards = '<div class="grid-news">' + "".join(news_card(a) for a in items) + "</div>"
    else:
        cards = ('<p class="empty-note">这个栏目还在筹备，先去 '
                 '<a href="/news/">看看其他资讯</a>，或者直接 <a href="/list/">按城市找农家乐</a>。</p>')

    content = render(tpl("news.html"), {
        "H1": esc(h1),
        "SUB": esc(sub),
        "CATS": news_cat_chips(cat_key),
        "NEWS_CARDS": cards,
    })

    canonical = BASE_URL + (f"/news/cat/{cat_key}/" if cat_key else "/news/")
    return page(content, f"{title} - 农家乐.cn", NEWS_DESC, canonical,
                active="/news/", json_ld=breadcrumb(
                    [("首页", "/"), ("农家乐资讯", "/news/")] +
                    ([(cat_name, f"/news/cat/{cat_key}/")] if cat_key else [])))


def build_article(a):
    chars = news_chars(a)
    head_bits = [news_date(a), f"约 {news_read_min(a)} 分钟读完", f"{chars} 字"]

    cta = f'''<div class="art-cta">
  <div>
    <h2>想找一家能去的农家乐？</h2>
    <p>按城市和玩法筛，看人均价格、真实评价，看中直接打电话给老板。</p>
  </div>
  <a class="btn btn-primary btn-lg" href="/list/">按城市找农家乐 →</a>
</div>'''

    content = render(tpl("article.html"), {
        "CAT": esc(news_cat(a)),
        "CAT_URL": f"/news/cat/{a['category']}/" if a.get("category") in NEWS_CATS else "/news/",
        "TITLE": esc(a["title"]),
        "META": esc(" · ".join(head_bits)),
        "SUMMARY": esc(a.get("summary") or ""),
        "BODY": news_body(a),
        "SOURCES": news_sources(a),
        "RELATED": news_related(a),
        "CTA": cta,
    })

    ld = json_ld({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Article",
                "headline": a["title"],
                "description": a.get("summary") or "",
                "datePublished": a.get("date") or "",
                "dateModified": a.get("updated") or a.get("date") or "",
                "inLanguage": "zh-CN",
                "mainEntityOfPage": {"@type": "WebPage",
                                     "@id": f"{BASE_URL}/news/{a['slug']}/"},
                "author": {"@type": "Organization", "name": SITE["name"], "url": BASE_URL + "/"},
                "publisher": {"@type": "Organization", "name": SITE["name"], "url": BASE_URL + "/"},
                "articleSection": news_cat(a),
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "name": n, "item": BASE_URL + u}
                    for i, (n, u) in enumerate(
                        [("首页", "/"), ("农家乐资讯", "/news/"),
                         (a["title"], f"/news/{a['slug']}/")])
                ],
            },
        ],
    })

    desc = a.get("summary") or news_plain(a)[:110]
    return page(content, f"{a['title']} - 农家乐.cn资讯", desc,
                f"{BASE_URL}/news/{a['slug']}/", active="/news/",
                og_type="article", json_ld=ld)


# ============================================================ 页面：网站地图
def build_sitemap_page():
    def group(title, items):
        lis = "".join(
            f'<li><a href="{u}">{esc(n)}</a><span class="map-meta">{m}</span></li>'
            for n, u, m in items
        )
        return f'<div class="map-group"><h2>{esc(title)}</h2><ul class="map-list">{lis}</ul></div>'

    main = group("主要页面", [
        ("首页", "/", ""),
        ("找农家乐", "/list/", f"{TOTAL} 家"),
        ("热门城市", "/cities/", f"{CITY_COUNT} 座城市"),
        ("农家乐资讯", "/news/", f"{len(NEWS)} 篇"),
        ("商家入驻", "/join/", ""),
        ("关于我们", "/about/", ""),
        ("网站地图", "/sitemap/", ""),
    ])

    city_items = [(f"{c['name']}农家乐", f"/city/{c['slug']}/",
                   f"{sum(1 for s in SHOPS if s['city'] == c['slug'])} 家") for c in CITIES]
    cities_block = group("城市页面", city_items)

    def _shop_note(s):
        bits = [CITY_MAP[s["city"]]["name"]]
        if s.get("price"):
            bits.append(f"¥{s['price']}")
        elif not (s.get("reviewCount") or 0):
            bits.append("新入驻")
        return " · ".join(bits)

    shop_items = [(s["name"], f"/shop/{s['slug']}/", _shop_note(s)) for s in SHOPS]
    shops_block = group("农家乐详情（按城市分组）", shop_items)

    news_block = ""
    if NEWS:
        news_items = [(a["title"], f"/news/{a['slug']}/",
                       f"{news_cat(a)} · {news_date(a, 'short')}") for a in NEWS]
        news_block = group("资讯文章", news_items)

    total_pages = 7 + CITY_COUNT + TOTAL + (len(NEWS) if NEWS else 0)
    content = render(tpl("sitemap.html"), {
        "SITEMAP_CONTENT": main + news_block + cities_block + shops_block,
        "PAGE_TOTAL": total_pages,
    })
    return page(content, f"网站地图 - 农家乐.cn｜全部 {total_pages} 个页面",
                f"农家乐.cn 全部 {total_pages} 个页面的索引，含 {CITY_COUNT} 座城市页、"
                f"{TOTAL} 个农家乐详情页与 {len(NEWS)} 篇资讯文章。",
                BASE_URL + "/sitemap/")


# ============================================================ 页面：404
def build_404():
    content = render(tpl("404.html"), {"CITY_CHIPS": city_chips()})
    return page(content, "页面不存在 - 农家乐.cn",
                "这个页面找不到了。你可以回首页重新搜索，或者按城市浏览各地农家乐。",
                BASE_URL + "/404.html", robots="noindex,follow")


# ============================================================ 站点文件
def build_sitemap_xml():
    today = datetime.now().strftime("%Y-%m-%d")
    urls = [
        ("/", "1.0", "daily"),
        ("/list/", "0.9", "daily"),
        ("/cities/", "0.8", "weekly"),
        ("/join/", "0.7", "monthly"),
        ("/about/", "0.4", "monthly"),
        ("/sitemap/", "0.3", "monthly"),
    ]
    for c in CITIES:
        urls.append((f"/city/{c['slug']}/", "0.8", "weekly"))
    for s in SHOPS:
        urls.append((f"/shop/{s['slug']}/", "0.7", "monthly"))
    # 资讯：栏目页 daily（每天有新文章），文章页 weekly（进站的新链接要靠它被抓）
    urls.append(("/news/", "0.8", "daily"))
    for a in NEWS:
        urls.append((f"/news/{a['slug']}/", "0.7", "weekly"))
    for key in NEWS_CATS:
        if any(a.get("category") == key for a in NEWS):
            urls.append((f"/news/cat/{key}/", "0.5", "weekly"))

    body = "".join(
        f"  <url>\n    <loc>{BASE_URL}{u}</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>{cf}</changefreq>\n"
        f"    <priority>{pr}</priority>\n  </url>\n"
        for u, pr, cf in urls
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}</urlset>\n")


def build_robots():
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "Sitemap: " + BASE_URL + "/sitemap.xml\n"
    )


def copy_static():
    if not STATIC.is_dir():
        return 0
    n = 0
    for root, dirs, files in os.walk(STATIC):
        # 跳过 .staging 这类临时目录（同步脚本的下载暂存区，不该进产物）
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.startswith("."):
                continue
            src = Path(root) / fn
            rel = os.path.relpath(src, STATIC)
            dst = PUB / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    return n


# ============================================================ 主流程
def main():
    PUB.mkdir(parents=True, exist_ok=True)

    _check_photo_config(SHOPS)

    written = []

    def w(rel, text):
        written.append(write(rel, text))

    w("index.html", build_home())
    w("list/index.html", build_list())
    w("cities/index.html", build_cities())
    for c in CITIES:
        w(f"city/{c['slug']}/index.html", build_city(c))
    for s in SHOPS:
        w(f"shop/{s['slug']}/index.html", build_shop(s))
    w("join/index.html", build_join())
    w("about/index.html", build_about())

    # 资讯：栏目页无条件生成（导航挂着入口，缺了就是死链），文章页按内容出
    w("news/index.html", build_news())
    for a in NEWS:
        w(f"news/{a['slug']}/index.html", build_article(a))
    n_news_cat = 0
    for key, name in NEWS_CATS.items():
        sub = [a for a in NEWS if a.get("category") == key]
        if sub:
            w(f"news/cat/{key}/index.html", build_news(sub, key, name))
            n_news_cat += 1

    w("sitemap/index.html", build_sitemap_page())
    w("404.html", build_404())

    # 站点级文件
    w("sitemap.xml", build_sitemap_xml())
    w("robots.txt", build_robots())

    # CNAME 与 .nojekyll 必须由构建产出，否则会被覆盖式发布会抹掉
    w("CNAME", SITE["domain"])
    w(".nojekyll", "")

    # 数据副本：给未来的前端功能（收藏、离线比对）留的接口
    write("data/shops.json", json.dumps(SHOPS, ensure_ascii=False, separators=(",", ":")))
    write("data/site.json", json.dumps(
        {k: SITE[k] for k in ("name", "slogan", "base_url", "phone")},
        ensure_ascii=False, separators=(",", ":")))

    n_static = copy_static()
    n_html = sum(1 for p in written if p.suffix == ".html")

    print("=" * 58)
    print(f"  农家乐.cn 构建完成")
    print("=" * 58)
    print(f"  商家 {TOTAL} 家 · 城市 {CITY_COUNT} 座 · 评价 {fmt(REVIEW_TOTAL)} 条 · 均分 {AVG_SCORE}")
    print(f"  资讯 {len(NEWS)} 篇 · 栏目 {n_news_cat} 个")
    print(f"  生成 {n_html} 个 HTML 页面 + {len(written) - n_html} 个站点文件 + {n_static} 个静态资源")
    print(f"  收录标签 {len(ALL_TAGS)} 个：{'、'.join(ALL_TAGS[:10])}…")
    print(f"  接收端 {'已配置 → ' + FEISHU_WEBHOOK[:46] + '…' if FEISHU_WEBHOOK else '未配置（表单进演示模式）'}")
    print(f"  关键词 {FEISHU_KEYWORD}")
    print(f"  输出目录 {PUB}")
    print("=" * 58)


if __name__ == "__main__":
    main()
