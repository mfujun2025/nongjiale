#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成「商家入驻」二维码 → static/img/join-qr.svg

为什么单独一个脚本：
  二维码是一次性生成的静态资产，固化进仓库即可，
  所以 build.py 不需要依赖 qrcode 库，只做文件复制。

依赖（仅本脚本需要）：
  python -m pip install qrcode

重新生成时机：
  site.json 里的 join_form_url 变了（比如换了表单），就要重跑一次。

用法：
  python tools/make_join_qr.py
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SITE = BASE / "data" / "site.json"
OUT = BASE / "static" / "img" / "join-qr.svg"

# 深绿：兼顾品牌感与扫描对比度（不要用浅色或渐变，会扫不出来）
QR_COLOR = "#14301F"


def main() -> int:
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        print("× 缺少依赖，请先执行：python -m pip install qrcode")
        return 1

    site = json.loads(SITE.read_text(encoding="utf-8"))
    # 二维码落在站内的入驻页，不直接落在飞书表单上：
    # 表单里「所在城市」是 337 个纵向平铺的选项，扫码直进要滚几百行；
    # 落在入驻页可以先把城市选好，跳过去时那一项会被自动填好并隐藏。
    base = (site.get("base_url") or "").rstrip("/")
    url = (base + "/join/") if base else (site.get("join_form_url") or "").strip()
    if not url:
        print("× data/site.json 里没有 base_url / join_form_url，无法生成二维码")
        return 1

    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    raw = img.to_string().decode("utf-8")

    # 把默认黑色替换成品牌深绿
    svg = re.sub(r'fill="#000000"', f'fill="{QR_COLOR}"', raw)
    svg = re.sub(r'fill="black"', f'fill="{QR_COLOR}"', svg)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")

    print(f"√ 已生成 {OUT.relative_to(BASE)}")
    print(f"  指向：{url}")
    print(f"  大小：{len(svg)} 字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
