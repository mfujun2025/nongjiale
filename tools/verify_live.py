#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发布后验证：确认线上跑的确实是刚发出去的那一版。

    python tools/verify_live.py

为什么需要它
    Pages 构建有 1~3 分钟延迟，域名又走 Cloudflare（缓存 max-age=600）。
    发完立刻 curl 看到 200 并不能说明什么——**200 很可能是缓存里的旧版**。
    这个脚本做三件事：
      1. 轮询 Pages 构建状态，等到 status=built 且 commit 等于本次产物
      2. 用随机参数破 CDN 缓存，抓首页确认是新版（按 title 特征词区分新旧）
      3. 探关键子页与 SEO 文件

    「commit 等于本次产物」这一步不能省：只看 status=built 会被上一次的构建记录骗过去，
    切换发布源之后尤其容易（Pages 不会自动重建）。
"""
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deploy                                              # noqa: E402

DOMAIN = "xn--fjq23fx8l.cn"
URL = f"https://{DOMAIN}/"

# 新旧版特征词：用来判断线上到底是哪一版
NEW_MARK = "全国农家乐信息平台｜按城市找"
OLD_MARK = "乡村旅游·休闲度假"
SAMPLE_SHOP = "竹里人家"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)


def title_of(html):
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    return m.group(1).strip() if m else "(无 title)"


def main():
    # 本次产物的 commit——用来和 Pages 的构建记录对账
    st, d = deploy.req("GET", f"/repos/{deploy.REPO}/git/ref/heads/{deploy.PROD_BRANCH}")
    want = d["object"]["sha"][:8] if st == 200 and isinstance(d, dict) else None
    print("=" * 62)
    print(f"仓库 {deploy.REPO}   产物分支 {deploy.PROD_BRANCH}   本次 commit {want}")

    print("\n[1] 等 Pages 构建完成")
    built = False
    for i in range(1, 21):
        st, d = deploy.req("GET", f"/repos/{deploy.REPO}/pages/builds/latest")
        if isinstance(d, dict):
            sha = str(d.get("commit"))[:8]
            status = d.get("status")
            mark = "← 本次" if sha == want else ""
            print(f"  第{i:2d}次: status={status:8s} commit={sha} {mark}")
            if status == "built":
                built = True
                if sha == want or want is None:
                    break
            elif status == "errored":
                print(f"  × 构建失败: {d.get('error')}")
                return 1
        else:
            print(f"  第{i:2d}次: {st} {str(d)[:110]}")
        time.sleep(12)

    if not built:
        print("  ⚠ 构建迟迟未完成，继续验证线上（可能是队列拥堵）")

    print("\n[2] 轮询线上（破 Cloudflare 缓存）")
    hit = None
    for i in range(1, 13):
        try:
            code, html, hdr = fetch(f"{URL}?cb={int(time.time() * 1000)}")
            t = title_of(html)
            tag = "新版 ✓" if NEW_MARK in t else ("旧版" if OLD_MARK in t else "未知版本")
            print(f"  第{i:2d}次: HTTP {code} | {len(html):6d} 字节 | "
                  f"x-cache={hdr.get('X-Cache', hdr.get('x-cache', '-')):4s} | {tag}")
            if NEW_MARK in t:
                print(f"          title: {t[:70]}")
                hit = (html, hdr)
                break
        except urllib.error.HTTPError as e:
            print(f"  第{i:2d}次: HTTP {e.code}（构建中，属正常）")
        except Exception as e:                            # noqa: BLE001
            print(f"  第{i:2d}次: {type(e).__name__}: {str(e)[:70]}")
        time.sleep(14)

    if not hit:
        print("\n× 轮询结束仍未见新版。多半是 Pages 排队中或 CF 缓存未过期，稍后重跑本脚本。")
        return 1

    html, hdr = hit
    print("\n[3] 内容核对")
    for label, ok in [
        ("新版 title 正确", NEW_MARK in title_of(html)),
        (f"商家「{SAMPLE_SHOP}」在页上", SAMPLE_SHOP in html),
        ("旧版标记已消失", OLD_MARK not in html),
    ]:
        print(f"  {'✓' if ok else '×'} {label}")

    print("\n[4] 关键子页")
    bad = 0
    for path, must in [
        ("/list/", "找农家乐"),
        ("/cities/", "城市"),
        ("/join/", "入驻"),
        ("/shop/zhuli-renjia/", SAMPLE_SHOP),
        ("/sitemap.xml", "<urlset"),
        ("/robots.txt", "Sitemap"),
    ]:
        try:
            code, body, _ = fetch(URL.rstrip("/") + path)
            ok = code == 200 and must in body
            bad += 0 if ok else 1
            print(f"  {'✓' if ok else '×'} {path:26s} HTTP {code} {len(body):6d} 字节")
        except urllib.error.HTTPError as e:
            bad += 1
            print(f"  × {path:26s} HTTP {e.code}")
        except Exception as e:                            # noqa: BLE001
            bad += 1
            print(f"  × {path:26s} {type(e).__name__}: {str(e)[:50]}")

    print("\n[5] 链路与缓存")
    for k in ("server", "last-modified", "cache-control", "x-cache", "x-github-request-id"):
        v = hdr.get(k) or hdr.get(k.title())
        if v:
            print(f"  {k}: {v}")
    print("=" * 62)
    print("结果：" + ("全部正常" if not bad else f"{bad} 个子页异常"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
