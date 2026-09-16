#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把飞书 Base「入驻申请」里状态 = 已通过 的商家，同步进 data/shops.json 并回写发布状态。

这是「审核通过 → 网站自动更新」这条链路的引擎。
审核员在飞书里只做一个动作：把状态改成「已通过」。剩下的由本脚本完成：

    飞书 Base（状态 = 已通过）
      → 白名单取字段 / 生成 URL slug
      → 下载照片 → 剥离 EXIF → 压成 webp → 传七牛（未配密钥则落本地）
      → 合并进 data/shops.json（站点的唯一数据源）
      → 回写状态「已发布」+ 上线地址

用法：
    python tools/sync_from_feishu.py --dry-run       # 只报告将要发生什么，不写任何东西
    python tools/sync_from_feishu.py                 # 正式同步，并回写飞书状态
    python tools/sync_from_feishu.py --no-writeback  # 只写入 shops.json，不回写飞书
    python tools/sync_from_feishu.py --no-upload     # 照片强制落本地，临时绕过图床
    python tools/sync_from_feishu.py --prune         # 换图后清理图床上的旧文件

同步完记得跑一次构建：
    python build.py && python check.py

依赖：
    pypinyin    生成拼音 URL（可选，缺了就用 record_id 兜底）
    Pillow      压缩照片 + 剥离 EXIF（可选，缺了就原样保存）
    qiniu       照片上传图床（可选，缺了就落本地 static/uploads/）
    lark-cli    读写飞书，需已登录（可用环境变量 LARK_CLI 指定路径）

照片走哪条路取决于 tools/photo_store.py 的配置：
    配了七牛密钥 → 上传到 shops/<slug>/，shops.json 存对象 key
    没配         → 存在 static/uploads/<slug>/，shops.json 存 /uploads/... 路径
站点构建时两种形态都能渲染，随时可以切换，不会有一半图挂掉。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import photo_store                                     # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
DATA = BASE_DIR / "data"
UPLOADS = BASE_DIR / "static" / "uploads"
STAGING = UPLOADS / ".staging"

# 从环境变量覆盖，方便以后接 CI
BASE_TOKEN = os.environ.get("FEISHU_BASE_TOKEN", "MxZlbHXgXaJkHxsb0kTcFCkJnae")
TABLE_ID = os.environ.get("FEISHU_TABLE_ID", "tblpndu1XRI64TsG")
SITE_BASE = os.environ.get("SITE_BASE_URL", "https://xn--fjq23fx8l.cn")

# 只有这些字段会被写进公开数据。白名单而不是黑名单——
# 以后 Base 里加字段忘了排除，白名单不会泄，黑名单会。
PUBLIC_FIELDS = {
    "农家乐名称": "name",
    "所在城市": "city_cn",
    "区县/乡镇": "district",
    "经营电话": "phone",
    "人均消费": "price",
    "一句话特色": "tagline",
    "详细介绍": "intro",
    "特色标签": "tags",
    "设施服务": "facilities",
    "房型与价格": "rooms_text",
}

# 明确不导出的（留在飞书，永不进构建产物）
PRIVATE_FIELDS = {"详细地址", "联系人姓名", "联系人手机", "微信/QQ"}


DRY_RUN = False          # --dry-run 时置真：不下载照片、不写文件、不动飞书


class Skip(Exception):
    """这条记录暂不满足发布条件，跳过并说明原因。"""


# ---------------------------------------------------------------- lark-cli 桥接
def _extract_json(text):
    """lark-cli 有时会在 JSON 前面打印一行提示，所以不能直接 loads。"""
    i = text.find("{")
    while i != -1:
        try:
            return json.loads(text[i:])
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
    return None


def _find_cli():
    exe = os.environ.get("LARK_CLI") or shutil.which("lark-cli")
    if exe:
        return exe
    for cand in (
        Path.home() / ".workbuddy" / "binaries" / "node" / "cli-connector-packages" / "lark-cli",
        Path.home() / ".workbuddy" / "binaries" / "node" / "cli-connector-packages" / "lark-cli.cmd",
    ):
        if cand.exists():
            return str(cand)
    raise SystemExit("× 找不到 lark-cli。请先登录飞书，或用环境变量 LARK_CLI 指定它的路径。")


def lark(*args):
    cli = _find_cli()
    proc = subprocess.run([cli, "base", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    payload = _extract_json(proc.stdout or "")
    if payload is None:
        raise SystemExit(f"× lark-cli 调用失败（exit={proc.returncode}）："
                         f"{(proc.stderr or proc.stdout or '')[:400]}")
    if not payload.get("ok", False):
        err = payload.get("error") or {}
        raise SystemExit(f"× 飞书接口报错：{err.get('message') or payload}")
    return payload


# ---------------------------------------------------------------- 数据转换
def one(value):
    """飞书的单选/多选返回数组，这里取第一个值。"""
    if isinstance(value, list):
        return value[0] if value else ""
    return "" if value is None else value


def make_slug(name, taken, fallback=""):
    """中文店名 → 拼音 URL。

    括号里的补充说明不参与 slug（「竹里人家（临安店）」→ zhuli-renjia），
    重名自动加序号。没装 pypinyin 时退化成 shop-xxxxxx 这种形式。
    """
    clean = re.sub(r"[（(【\[].*?[）)】\]]", "", name).strip() or name
    try:
        from pypinyin import lazy_pinyin
        raw = "-".join(lazy_pinyin(clean))
    except ImportError:
        print("    ⚠ 未安装 pypinyin，URL 会退化成 shop-xxxxxx；"
              "执行 pip install pypinyin 可修复")
        raw = fallback or clean
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:40]
    if not slug:
        slug = fallback or "shop"
    final, i = slug, 2
    while final in taken:
        final = f"{slug}-{i}"
        i += 1
    return final


def parse_rooms(text):
    """把「标准间 150元/晚；大床房 220元/晚」解析成结构化房型。

    解析不出来就返回空数组——详情页会自动省略房型区块，不会留一个空表格。
    只做餐饮的农家乐本来就没有房型，缺这一块是正常的。
    """
    if not text:
        return []
    out = []
    for frag in re.split(r"[；;、\n]+", str(text)):
        frag = frag.strip()
        if not frag:
            continue
        m = re.search(r"(\d+)\s*元", frag)
        if not m:
            continue
        name = frag[:m.start()].strip(" ·-—:：,，")
        name = name.replace("元", "").strip()
        if not name:
            continue
        out.append({"name": name, "bed": "", "area": "",
                    "price": int(m.group(1)), "note": ""})
    return out


def art_for(slug):
    """没有照片时用哪套 SVG 插画。按 slug 固定，保证同一家店每次构建配色一致。"""
    return (sum(ord(ch) for ch in slug) % 8) + 1


def compress_image(path):
    """保留旧名字，实际转交给 photo_store —— 压缩逻辑只维护一处。"""
    return photo_store.compress_to_webp(path)


# ---- 照片管道：飞书附件 → 剥离 EXIF → webp → 图床或本地
UPLOAD_ENABLED = True     # --no-upload 时置假：强制照片落本地
PRUNE = False             # --prune 时置真：清理图床上的孤儿文件


def _download_to_staging(record_id, slug):
    """把这条记录的附件先落到本地暂存区。

    为什么必须下载：飞书附件的 URL 是带签名的临时地址，会过期。
    直接把飞书 URL 写进 HTML，过几天全站图片集体失效——
    这是本方案最隐蔽、也最难排查的坑。
    """
    dest = STAGING / slug
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        lark("+record-download-attachment", "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
             "--record-id", record_id, "--output", str(dest), "--overwrite", "--as", "user")
    except SystemExit as exc:
        print(f"    ⚠ 照片下载失败，该商家将回落到插画（{exc}）")
        return None
    # 飞书偶尔会把附件塞进子目录，递归取一层
    files = sorted(p for p in dest.rglob("*") if p.is_file())
    if not files:
        return None
    return files


def publish_photos(record_id, slug, existing=None):
    """照片管道。返回 (写进 shops.json 的列表, 走的是哪条路)。

    站点构建对两种形态都支持，所以图床没配好也不会阻塞发布：
        走图床 → ["shops/<slug>/01-a3f9.webp", ...]   存对象 key，域名在 site.json
        落本地 → ["/uploads/<slug>/01-a3f9.webp", ...] 存站内路径
    """
    if DRY_RUN:
        return [], "none"

    files = _download_to_staging(record_id, slug)
    if not files:
        return [], "none"

    use_qiniu = UPLOAD_ENABLED and photo_store.enabled()
    # 逐张处理：压成 webp 后文件名会变（.jpg → .webp），所以列表要接下新路径
    processed = [compress_image(f) for f in files]

    if use_qiniu:
        keys = []
        for i, f in enumerate(processed):
            key = f"shops/{slug}/{photo_store.safe_name(f, i)}"
            try:
                photo_store.upload(f, key)
                keys.append(key)
            except Exception as exc:                        # noqa: BLE001
                print(f"    ⚠ 第 {i + 1} 张上传图床失败，本次整体回落本地（{exc}）")
                keys = []
                break
        if keys:
            shutil.rmtree(STAGING / slug, ignore_errors=True)
            _prune_old(slug, keys, existing)
            return keys, "qiniu"

    # ---- 回落本地：把暂存的照片挪到 static/uploads/<slug>/
    dest = UPLOADS / slug
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for f in processed:
        target = dest / f.name
        try:
            if f.resolve() != target.resolve():
                shutil.move(str(f), str(target))
        except OSError as exc:
            # 挪不过去就别把它写进数据——写进去就是一个 404 的空图位。
            # 少一张图页面还能看，多一个断图会让整页显得没人管。
            print(f"    ⚠ 照片落盘失败，跳过这张（{f.name}）：{exc}")
            continue
        out.append(f"/uploads/{slug}/{target.name}")
    shutil.rmtree(STAGING / slug, ignore_errors=True)
    return out, "local"


def _prune_old(slug, new_keys, existing):
    """换图之后，把图床上这条商家名下的旧文件删掉。

    只在 --prune 时执行：删图床对象是不可逆的，默认不动手。
    不做的话，换三次图就会留两批孤儿文件——不占多少钱，但会让人分不清哪张是现役的。
    """
    if not PRUNE or not existing:
        return
    old = [k for k in (existing.get("photos") or []) if not str(k).startswith(("/", "http"))]
    stale = [k for k in old if k not in new_keys and k.startswith(f"shops/{slug}/")]
    for k in stale:
        if photo_store.delete(k):
            print(f"    · 已清理图床旧文件 {k}")
        else:
            print(f"    ⚠ 图床旧文件清理失败（不影响发布）：{k}")


def to_shop(rec, taken, city_by_name, existing=None):
    """飞书记录 → (shops.json 条目, 照片走的是哪条路)。"""
    name = (rec.get("农家乐名称") or "").strip()
    if not name:
        raise Skip("没有商家名称")

    city_cn = one(rec.get("所在城市"))
    city_slug = city_by_name.get(city_cn)
    if not city_slug:
        if city_cn == "其他城市":
            raise Skip("城市选了「其他城市」—— 请把地级市补进「所在城市」"
                       "（省直辖县级市填在「区县/乡镇」里）")
        raise Skip(f"城市「{city_cn or '未填'}」不在 data/regions.json 里，"
                   f"跑 tools/build_regions.py --fetch 更新基准表后再发布")

    # 同一条记录重新审核时不换 slug，避免同一家店出现两个页面
    if existing and existing.get("slug"):
        slug = existing["slug"]
    else:
        slug = make_slug(name, taken,
                         fallback=f"shop-{rec['_record_id'][-6:].lower()}")

    price = rec.get("人均消费")
    price = int(price) if isinstance(price, (int, float)) and price else 0

    intro = (rec.get("详细介绍") or "").strip()
    if not intro:
        intro = (rec.get("一句话特色") or "").strip()

    photos, photo_where = publish_photos(rec["_record_id"], slug, existing)

    return {
        "slug": slug,
        "name": name,
        "city": city_slug,
        "district": (rec.get("区县/乡镇") or "").strip(),
        "price": price,
        "phone": (rec.get("经营电话") or "").strip(),
        "intro": intro,
        "tags": [t for t in (rec.get("特色标签") or []) if t],
        "facilities": [f for f in (rec.get("设施服务") or []) if f],
        "rooms": parse_rooms(rec.get("房型与价格")),
        "featured": False,
        "art": art_for(slug),
        # 走图床时这里存的是对象 key（shops/<slug>/01-xxxx.webp），
        # 域名在 data/site.json 的 photo_cdn —— 换 CDN 域名不用动商家数据
        "photos": photos,
        "feishu_record_id": rec["_record_id"],
        # 注意：不写 score / reviewCount / reviews ——
        # 新商家本来就没有评价，缺这几个键时页面会显示「新入驻」。
        # 写成 0 会让新店看起来可疑，也会把它错误地排到列表底部。
    }, photo_where


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="把飞书里已通过的入驻申请同步到站点数据")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件、不回写飞书")
    ap.add_argument("--no-writeback", action="store_true", help="写入 shops.json，但不回写飞书状态")
    ap.add_argument("--no-upload", action="store_true", help="照片强制落本地，临时绕过图床")
    ap.add_argument("--prune", action="store_true", help="换图后清理图床上的旧文件（不可逆）")
    args = ap.parse_args()

    global DRY_RUN, UPLOAD_ENABLED, PRUNE
    DRY_RUN = args.dry_run
    UPLOAD_ENABLED = not args.no_upload
    PRUNE = args.prune

    if not DRY_RUN:
        if UPLOAD_ENABLED and photo_store.enabled():
            cfg = photo_store.config()
            print(f"→ 照片走七牛图床（bucket={cfg['bucket']}，"
                  f"域名={cfg.get('cdn_domain') or '未填'}）")
        else:
            print("→ 照片存本地 static/uploads/"
                  "（七牛未配置，或指定了 --no-upload）")

    # 城市名 → slug。以 regions.json（337 个地级行政区）为主：入驻表单里
    # 能选的城市就在这份表里，两边同源，不会出现「表单能选、这里发布不了」。
    # cities.json 只做别名补充，防止基准表被换掉时断链。
    cities = json.loads((DATA / "cities.json").read_text(encoding="utf-8"))
    shops = json.loads((DATA / "shops.json").read_text(encoding="utf-8"))
    city_by_name = {}
    regions_file = DATA / "regions.json"
    if regions_file.is_file():
        for r in json.loads(regions_file.read_text(encoding="utf-8"))["regions"]:
            city_by_name[r["short"]] = r["slug"]
            city_by_name[r["name"]] = r["slug"]        # 全称也认（「杭州市」）
        print(f"→ 城市基准表 {len(city_by_name)} 个可识别的城市名")
    else:
        print("  ⚠ 找不到 data/regions.json，城市映射退回 cities.json")
        print("    （跑一次 tools/build_regions.py 可生成）")
    for c in cities:
        city_by_name.setdefault(c["name"], c["slug"])

    print("→ 读取飞书 Base 里「已通过」的入驻申请…")
    payload = lark("+record-list", "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
                   "--filter-json", json.dumps(
                       {"logic": "and", "conditions": [["状态", "intersects", ["已通过"]]]},
                       ensure_ascii=False),
                   "--format", "json", "--as", "user")
    d = payload.get("data") or {}
    fields = d.get("fields") or []
    rows = d.get("data") or []
    rids = d.get("record_id_list") or []
    approved = []
    for row, rid in zip(rows, rids):
        rec = dict(zip(fields, row))
        rec["_record_id"] = rid
        approved.append(rec)

    print(f"  找到 {len(approved)} 条待发布")
    if not approved:
        print("√ 没有待发布的商家，结束")
        return 0

    by_rid = {s.get("feishu_record_id"): s for s in shops if s.get("feishu_record_id")}
    taken = {s["slug"] for s in shops}
    ready, skipped = [], []

    for rec in approved:
        try:
            existing = by_rid.get(rec["_record_id"])
            shop, where = to_shop(rec, taken, city_by_name, existing)
            taken.add(shop["slug"])
            ready.append((rec, shop, existing is not None, where))
        except Skip as exc:
            skipped.append((rec.get("农家乐名称") or "(未命名)", str(exc)))

    _where_cn = {"qiniu": "图床", "local": "本地", "none": "无照片"}
    for rec, shop, is_update, where in ready:
        print(f"  ✔ {shop['name']} → /shop/{shop['slug']}/"
              f"（{shop['city']}{shop['district']}，"
              f"{'更新' if is_update else '新增'}，"
              f"{len(shop['photos'])} 张照片[{_where_cn.get(where, where)}]，"
              f"{len(shop['rooms'])} 个房型）")
    for name, why in skipped:
        print(f"  ✗ {name}：{why}")

    if not ready:
        print("\n没有可发布的记录（全部被跳过）")
        return 1

    # ---- 合并进 shops.json
    updates = []
    for rec, shop, is_update, _where in ready:
        if is_update:
            existing = by_rid[rec["_record_id"]]
            existing.update(shop)
            updates.append((rec["_record_id"], shop["slug"]))
        else:
            shops.append(shop)
            updates.append((rec["_record_id"], shop["slug"]))

    if args.dry_run:
        print(f"\n[dry-run] 将新增/更新 {len(updates)} 家，"
              f"跳过 {len(skipped)} 家。没有写入任何文件，也没有改飞书状态。")
        return 0

    (DATA / "shops.json").write_text(
        json.dumps(shops, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n√ 已写入 data/shops.json（现有 {len(shops)} 家）")

    if args.no_writeback:
        print("  已跳过回写飞书状态（--no-writeback）")
    else:
        upd = {rid: {"状态": ["已发布"],
                     "上线地址": f"{SITE_BASE}/shop/{slug}/"}
               for rid, slug in updates}
        lark("+record-batch-update", "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
             "--json", json.dumps({"update_records": upd}, ensure_ascii=False), "--as", "user")
        print(f"√ 已把 {len(upd)} 条记录的状态回写为「已发布」，并写入了上线地址")

    print("\n下一步：python build.py && python check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
