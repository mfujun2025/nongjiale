#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 data/regions.json —— 全国地级行政区基准表。

数据来源
    province-city-china（国家统计局统计用区划代码）
    https://cdn.jsdelivr.net/npm/province-city-china/dist/
    原始数据缓存在 data/_source/，用 --fetch 可重新拉取

收录口径：337 个
    地级市 293 + 自治州 30 + 地区 7 + 盟 3 = 333 个地级行政区
    另加北京 / 天津 / 上海 / 重庆 4 个直辖市
      （行政区划上属省级，但商家填表时就是当「城市」填的，得能选）
    港澳台不收录：农家乐是大陆业态
    「省直辖县级行政区划」占位条目不收录：那是县级市的归集壳子，不是独立行政区

这份文件解决三件事
    1. 飞书「所在城市」字段的选项 —— 入驻可选项，全量，任何地方的商家都能填
    2. 中文城市名 → 稳定 URL slug 的映射（tools/sync_from_feishu.py 用）
    3. cities.json 里没有策展内容的城市，用这里的标准名兜底（build.py 用）

为什么不直接把 337 个塞进 cities.json
    cities.json 是「策展」文件 —— 只放有商家、有手写描述和标签的城市，用来生成
    城市落地页。全量塞进去会让 331 个城市页变成空页，搜索引擎收录一堆薄内容
    页面，反而拉低整站质量评估。
    分工：regions.json 管「存在性」，cities.json 管「内容」。

用法
    python tools/build_regions.py            # 用 data/_source/ 缓存生成
    python tools/build_regions.py --fetch    # 重新下载最新数据再生成
    python tools/build_regions.py --check    # 只校验现有 regions.json 是否自洽
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA = BASE_DIR / "data"
SRC = DATA / "_source"
OUT = DATA / "regions.json"

CDN = "https://cdn.jsdelivr.net/npm/province-city-china/dist"

# 大陆 31 个省级行政区（港澳台不收录）
MAINLAND = {"11", "12", "13", "14", "15", "21", "22", "23",
            "31", "32", "33", "34", "35", "36", "37",
            "41", "42", "43", "44", "45", "46",
            "50", "51", "52", "53", "54",
            "61", "62", "63", "64", "65"}

DIRECT = ["11", "12", "31", "50"]          # 直辖市

# 民族名白名单。剥简称时必须靠白名单，不能用正则「X族」——
# 因为主体名和民族名都是汉字，贪婪匹配会把「延边朝鲜族」整个吃掉。
ETHNIC = [
    "乌孜别克族", "柯尔克孜族", "鄂伦春族", "鄂温克族", "达斡尔族", "塔塔尔族",
    "俄罗斯族", "撒拉族", "仡佬族", "毛南族", "仫佬族", "锡伯族", "阿昌族",
    "普米族", "塔吉克族", "德昂族", "保安族", "裕固族", "独龙族", "赫哲族",
    "门巴族", "珞巴族", "基诺族", "布依族", "朝鲜族", "土家族", "哈尼族",
    "哈萨克族", "傈僳族", "拉祜族", "东乡族", "纳西族", "景颇族", "布朗族",
    "高山族", "蒙古族", "维吾尔族", "回族", "藏族", "苗族", "彝族", "壮族",
    "满族", "侗族", "瑶族", "白族", "傣族", "黎族", "佤族", "畲族", "水族",
    "土族", "羌族", "怒族", "京族",
    # 自治州名里不带「族」的写法
    "柯尔克孜", "哈萨克", "维吾尔", "蒙古",
]
ETHNIC.sort(key=len, reverse=True)

ADMIN_SUFFIX = re.compile(r"(省|市|地区|盟|自治区|自治州|特别行政区)$")

# 多音字 / 错读修正表。key 是简称（省级的也放这里）。
# 这里每一条都是 pypinyin 通用读音会读错、且**直接影响 URL** 的：
# URL 是收录和分享的入口，读错字既难看也影响搜索匹配。
PINYIN_FIX = {
    # —— pypinyin 实际读错的（跑 heteronym 排查出来的）
    "漯河": "luohe",         # 漯 读 luò；pypinyin 默认给 tà（古水名读音），差得最远
    "朝阳": "chaoyang",      # 地名读 cháo；pypinyin 默认 zhāo
    "昌都": "changdu",       # 都 读 dū；pypinyin 默认 dōu
    "克孜勒苏": "kezilesu",   # 勒 读 lè；pypinyin 给 lèi
    "锡林郭勒": "xilinguole", # 同上
    "阿勒泰": "aletai",       # 同上
    # —— 容易读错、预防性固定的
    "六安": "luan",          # 六 读 lù，不是 liù
    "蚌埠": "bengbu",        # 蚌 读 bèng，不是 bàng
    "亳州": "bozhou",        # 亳 bó，不是 háo
    "乐山": "leshan",        # 乐 读 lè
    "丽水": "lishui",        # 丽 读 lí
    "台州": "taizhou",       # 台 读 tāi
    "儋州": "danzhou",       # 儋 dān
    "长治": "changzhi",      # 长 读 cháng
    "长春": "changchun",
    "长沙": "changsha",
    "重庆": "chongqing",     # 重 读 chóng
    # —— 省名：拼音撞车时的消歧后缀，用官方英文拼法区分山西/陕西
    "陕西": "shaanxi",
    "山西": "shanxi",
}


def short_name(name):
    """杭州市 → 杭州；大理白族自治州 → 大理；内蒙古自治区 → 内蒙古；
    克孜勒苏柯尔克孜自治州 → 克孜勒苏；锡林郭勒盟 → 锡林郭勒。"""
    n = name
    while True:
        before = n
        n = ADMIN_SUFFIX.sub("", n)
        for e in ETHNIC:                       # 降序排列，长的先试
            if n.endswith(e) and len(n) > len(e):
                n = n[: -len(e)]
                break
        if n == before:                        # 不再变化就停
            break
    return n


def py(text, sep=""):
    """汉字转拼音。缺 pypinyin 时用 adcode 兜底，不中断。"""
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return None
    return sep.join(lazy_pinyin(text))


def slug_for(short, adcode):
    s = PINYIN_FIX.get(short) or py(short)
    if not s:
        return None
    s = re.sub(r"[^a-z0-9]+", "", s.lower())
    return s or None


def fetch():
    SRC.mkdir(parents=True, exist_ok=True)
    for fn, remote in (("source-province.json", "province.json"),
                       ("source-city.json", "city.json")):
        url = f"{CDN}/{remote}"
        print(f"  下载 {url}")
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        (SRC / fn).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    → data/_source/{fn}（{len(data)} 条）")


def build():
    prov = json.loads((SRC / "source-province.json").read_text(encoding="utf-8"))
    city = json.loads((SRC / "source-city.json").read_text(encoding="utf-8"))

    # province.json 里 code 是六位（110000），city.json 里引用的是两位（11）
    prov_name = {p["province"]: p["name"] for p in prov}
    prov_short = {p["province"]: short_name(p["name"]) for p in prov}

    rows = []

    # ---- 333 个地级行政区
    for c in city:
        code = c["province"]
        if code not in MAINLAND:
            continue
        if "直辖县级" in c["name"]:            # 归集壳子，跳过
            continue
        rows.append({
            "adcode": c["code"],
            "name": c["name"],
            "short": short_name(c["name"]),
            "province": prov_name.get(code, ""),
            "province_code": code,
        })

    # ---- 4 个直辖市（补成「城市」，让商家能选）
    for code in DIRECT:
        rows.append({
            "adcode": code + "0000",
            "name": prov_name[code],
            "short": short_name(prov_name[code]),
            "province": prov_name[code],
            "province_code": code,
        })

    # ---- 生成 slug：按 adcode 升序，同拼音的首个用裸 slug，其余加省后缀
    rows.sort(key=lambda r: r["adcode"])
    seen, out = {}, []
    for r in rows:
        base = slug_for(r["short"], r["adcode"])
        if not base:
            base = "city-" + r["adcode"]
            print(f"  ⚠ {r['name']}：拼音生成失败，slug 退回 {base}")
        if base in seen:
            ps = prov_short[r["province_code"]]
            suffix = PINYIN_FIX.get(ps) or py(ps) or r["adcode"]
            slug = f"{base}-{suffix}"
            print(f"  · 拼音撞车：{r['name']} 与 {seen[base]} 同为 {base} → {slug}")
        else:
            slug = base
            seen[base] = r["name"]
        r["slug"] = slug
        out.append(r)

    return out


# 回归断言：这些 slug 一旦变了，已发布的 URL 就断了（外链、收录、分享全废）。
# 每次重新生成都要过一遍，防止换拼音库版本 / 改剥名规则时静默改动。
EXPECTED_SLUGS = {
    "漯河": "luohe",        "朝阳": "chaoyang",   "昌都": "changdu",
    "克孜勒苏": "kezilesu",  "锡林郭勒": "xilinguole", "阿勒泰": "aletai",
    "六安": "luan",         "蚌埠": "bengbu",     "亳州": "bozhou",
    "丽水": "lishui",       "台州": "taizhou-zhejiang", "泰州": "taizhou",
    "苏州": "suzhou",       "宿州": "suzhou-anhui",
    "榆林": "yulin-shaanxi", "玉林": "yulin",
    "福州": "fuzhou",       "抚州": "fuzhou-jiangxi",
    "宜春": "yichun-jiangxi", "伊春": "yichun",
    "重庆": "chongqing",    "北京": "beijing",    "杭州": "hangzhou",
    "成都": "chengdu",      "西安": "xian",       "广州": "guangzhou",
    "大理": "dali",         "西双版纳": "xishuangbanna",
    "延边": "yanbian",      "海南": "hainan",     "黔东南": "qiandongnan",
}


FEISHU_FIELD = "所在城市"
FEISHU_FIELD_ID = "fldOVdMt7p"
FEISHU_FORM_ID = "vewsVyQjM0"
FEISHU_TAIL = "其他城市"        # 兜底项：省直辖县级市等（济源、仙桃、石河子…）
FEISHU_OUT = BASE_DIR / "build" / "feishu-city-field.json"


def emit_feishu():
    """导出飞书「所在城市」字段定义（全量 PUT 用）。

    选项按 adcode 顺序排列 —— 也就是行政区划的自然顺序（华北→东北→华东→
    中南→西南→西北），商家从上往下滑能按地理直觉找到自己那一带。
    不指定颜色，让飞书自己循环分配；337 个手写颜色只会更花。

    「其他城市」保留在最后：省直辖县级市（济源、仙桃、潜江、天门、
    石河子等）不在地级行政区里，没这个兜底商家就填不了。
    """
    rows = json.loads(OUT.read_text(encoding="utf-8"))["regions"]
    opts = [{"name": r["short"]} for r in rows]
    if FEISHU_TAIL not in [o["name"] for o in opts]:
        opts.append({"name": FEISHU_TAIL})

    payload = {
        "name": FEISHU_FIELD,
        "type": "select",
        "multiple": False,
        "options": opts,
    }
    FEISHU_OUT.parent.mkdir(parents=True, exist_ok=True)
    FEISHU_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(f"\n✔ 飞书字段定义已导出：{FEISHU_OUT.relative_to(BASE_DIR)}")
    print(f"  选项 {len(opts)} 个（含兜底「{FEISHU_TAIL}」），按行政区划顺序")
    print(f"  文件 {FEISHU_OUT.stat().st_size / 1024:.1f} KB")
    print()
    print("  写入命令（改生产表单，执行前确认）：")
    print(f'    lark-cli base +field-update --base-token <token> '
          f'--table-id <table_id> --field-id "{FEISHU_FIELD}" '
          f'--json "$(cat {FEISHU_OUT.relative_to(BASE_DIR)})" --as user --yes')
    print(f"  并把表单题目 {FEISHU_FIELD_ID} 的 option_display_mode 改成 0（下拉）：")
    print(f"    337 项在「纵向排列」下会铺满整屏，必须切下拉")


def check():
    """校验现有 regions.json 是否自洽，不改文件。"""
    if not OUT.exists():
        print("× data/regions.json 不存在，先跑一次生成")
        return 1
    raw = json.loads(OUT.read_text(encoding="utf-8"))
    rows = raw["regions"] if isinstance(raw, dict) else raw
    bad = 0
    slugs = {}
    for r in rows:
        for k in ("adcode", "name", "short", "province", "slug"):
            if not r.get(k):
                print(f"× {r.get('name', '?')} 缺字段 {k}")
                bad += 1
        if r["slug"] in slugs:
            print(f"× slug 重复：{r['slug']}（{r['name']} / {slugs[r['slug']]}）")
            bad += 1
        slugs[r["slug"]] = r["name"]
    print(f"  条目 {len(rows)} 条，slug {len(slugs)} 个唯一值，问题 {bad} 处")

    # slug 回归断言
    by_short = {r["short"]: r["slug"] for r in rows}
    for name, want in EXPECTED_SLUGS.items():
        got = by_short.get(name)
        if got is None:
            print(f"  ⚠ 断言落空：「{name}」不在基准表里")
            bad += 1
        elif got != want:
            print(f"× slug 变了：「{name}」应为 {want}，实际 {got} —— 已有链接会失效")
            bad += 1
    print(f"  回归断言 {len(EXPECTED_SLUGS)} 条")

    # 与 cities.json 的策展城市对齐检查
    cj = DATA / "cities.json"
    if cj.exists():
        for c in json.loads(cj.read_text(encoding="utf-8")):
            hit = [r for r in rows if r["slug"] == c["slug"]]
            if not hit:
                print(f"  ⚠ 策展城市「{c['name']}」({c['slug']}) 在基准表里找不到对应")
                bad += 1
            elif hit[0]["short"] != c["name"]:
                print(f"  · 名称差异：cities.json 写「{c['name']}」，基准表是"
                      f"「{hit[0]['name']}」（简称「{hit[0]['short']}」）")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="重新下载行政区划数据")
    ap.add_argument("--check", action="store_true", help="只校验，不生成")
    ap.add_argument("--feishu", action="store_true",
                    help="额外导出飞书「所在城市」字段定义")
    args = ap.parse_args()

    if args.check:
        sys.exit(check())

    if args.feishu and OUT.exists() and not args.fetch:
        emit_feishu()
        sys.exit(check())

    if args.fetch or not (SRC / "source-city.json").exists():
        fetch()

    rows = build()

    provs = sorted({r["province"] for r in rows})
    payload = {
        "_note": "全国地级行政区基准表。来源：国家统计局统计用区划代码 / "
                 "province-city-china。由 tools/build_regions.py 生成，不要手改。",
        "count": len(rows),
        "province_count": len(provs),
        "regions": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    print(f"\n✔ 写入 data/regions.json —— {len(rows)} 个城市，覆盖 {len(provs)} 个省级行政区")
    kinds = {}
    for r in rows:
        for k in ("市", "自治州", "地区", "盟"):
            if r["name"].endswith(k):
                kinds[k] = kinds.get(k, 0) + 1
                break
    print(f"  构成：" + " / ".join(f"{k} {v}" for k, v in kinds.items()))
    print(f"  文件大小：{OUT.stat().st_size / 1024:.1f} KB")
    emit_feishu()
    sys.exit(check())


if __name__ == "__main__":
    main()
