#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
照片管道自检

    python tools/selftest_photos.py

守的是两件不能出错的事：

1. **隐私** —— 手机照片默认带 GPS 经纬度。不剥离 = 把商家的店面精确位置
   公开在每一张图上。这是法律意义上的个人信息，不是"优化项"。
2. **性能** —— 手机原图 3–5MB，不压就直接铺进页面，首屏基本废了。

这两件事错了都不会报错、不会崩，只会"看起来一切正常"。所以必须有测试盯着。

注意：剥离 EXIF 之前必须先应用旋转（exif_transpose）。只剥不转，
全站竖拍的照片会集体躺倒——这是最容易漏掉的一步。
"""
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import photo_store                                       # noqa: E402

# 临时文件落在 build/ 下，不落源码目录。
# 原因：本机有安全删除机制，rmtree 可能被拦而静默失败；
# 万一清理不掉，放进 build/（已被 .gitignore 与发布脚本排除）不会污染仓库。
TMP = Path(__file__).resolve().parent.parent / "build" / "_selftest"
FAIL, WARN = [], []


def check(label, got, want):
    if got == want:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}\n         期望 {want!r} / 实际 {got!r}")
        FAIL.append(label)


def note(msg):
    print(f"  [WARN] {msg}")
    WARN.append(msg)


def build_phone_shot():
    """造一张竖拍手机照：横置像素 + Orientation=6 + GPS + 机型。"""
    TMP.mkdir(exist_ok=True)
    src = TMP / "phone_shot.jpg"
    img = Image.new("RGB", (4000, 3000))
    for x in range(0, 4000, 400):
        for y in range(0, 3000, 400):
            img.putpixel((x, y), (200, 60, 40))
    exif = Image.Exif()
    exif[0x0112] = 6                     # Orientation：顺时针 90°
    exif[0x010F] = "Xiaomi"              # Make
    exif[0x0110] = "MI 14"               # Model
    try:
        exif[0x8825] = {1: "N", 2: (31.0, 13.0, 0.0),
                        3: "E", 4: (121.0, 28.0, 0.0)}   # GPSInfo
    except Exception as exc:             # noqa: BLE001
        note(f"GPS 标签写入失败，本轮只验证其余元数据（{exc}）")
    img.save(src, "JPEG", exif=exif, quality=95)
    return src


def main():
    print("=" * 58)
    print("  照片管道自检")
    print("=" * 58)

    src = build_phone_shot()
    raw = Image.open(src)
    print(f"\n[0] 输入：{raw.size}，EXIF {len(raw.getexif())} 个标签"
          f"，GPS {'有' if raw.getexif().get_ifd(0x8825) else '无'}")

    out = photo_store.compress_to_webp(src)
    res = Image.open(out)

    print("\n[A] 压缩规格")
    check("输出为 webp", out.suffix, ".webp")
    check("长边不超过 1600（首屏性能）", max(res.size) <= 1600, True)

    print("\n[B] 方向校正（漏了这步，全站竖拍照会躺倒）")
    check("4000x3000 + Orientation=6 → 旋转后缩放到 1200x1600",
          res.size, (1200, 1600))
    check("结果仍是竖构图", res.size[1] > res.size[0], True)

    print("\n[C] 隐私：元数据必须清空")
    meta = res.getexif()
    check("EXIF 标签数归零", len(meta), 0)
    check("GPS 定位信息已清除", bool(meta.get_ifd(0x8825)), False)
    check("机型信息已清除（Make/Model）",
          (meta.get(0x010F), meta.get(0x0110)), (None, None))
    check("Orientation 标记已清除", meta.get(0x0112), None)

    print("\n[D] 边界情况")
    small = TMP / "small.png"
    Image.new("RGB", (320, 200), (10, 120, 80)).save(small)
    check("小图不放大", Image.open(photo_store.compress_to_webp(small)).size,
          (320, 200))

    print("\n[E] 文件名不可猜测（防遍历未审核/已下线的图）")
    names = {photo_store.safe_name(None, i) for i in range(50)}
    check("50 次生成互不重复", len(names), 50)
    check("带数字序号前缀（保住图库首图顺序）",
          all(n.split("-")[0].isdigit() for n in names), True)
    check("后缀统一 .webp", {n.rsplit(".", 1)[-1] for n in names}, {"webp"})

    print("\n[F] 原图清理是收尾，不能反过来影响发布结果")
    if src.exists():
        note("原图未能删除（本机文件删除被安全删除机制接管）——"
             "压缩结果不受影响，代码只警告不回落")
    else:
        check("原图已清理，不留双份", src.exists(), False)

    print("\n[G] 七牛配置")
    if photo_store.enabled():
        cfg = photo_store.config()
        check("配了 CDN 域名", bool(cfg.get("cdn_domain")), True)
        print(f"         bucket={cfg['bucket']}  域名={cfg.get('cdn_domain')}")
    else:
        note("七牛未配置 → 照片会落到本地 static/uploads/（同步链路照常可用）")

    shutil.rmtree(TMP, ignore_errors=True)

    print("\n" + "=" * 58)
    if FAIL:
        print(f"  结果：{len(FAIL)} 项失败")
        for f in FAIL:
            print(f"    ✗ {f}")
        return 1
    print(f"  结果：全部通过（{len(WARN)} 项提示）")
    for w in WARN:
        print(f"    · {w}")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())
