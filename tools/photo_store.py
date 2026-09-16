#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
照片外置存储（七牛云 Kodo）—— 商家照片的落地与压缩。

为什么照片不能留在仓库里
    GitHub Pages 官方建议站点总量 ≤ 1GB、月流量 ≤ 100GB。
    1000 家 × 5 张 × 400KB ≈ 2GB，直接超。而且仓库会被图片撑爆，
    以后换一张图都得重新构建整站。

为什么数据里存「对象 key」而不是完整 URL
    七牛新账号送的测试域名只有 30 天有效期，正式上线必须绑自己的域名。
    如果把 https://xxxx.clouddn.com/shops/a/1.webp 直接写进商家数据，
    换域名那天就要改全部商家。所以：
        shops.json 里存  shops/zhuli-renjia/01-a3f9.webp
        域名放 data/site.json 的 photo_cdn
    换域名 = 改一行配置，商家数据一个字节都不用动。

两段式隔离区（temp/ → shops/）为什么这里只做一段
    设计文档里规划了 temp/ 隔离区，是为了防止「还没审核的照片先上了 CDN」。
    但走飞书原生表单这条路，照片本来就先落在飞书 Base 的附件字段里，
    只有审核人能看见——飞书本身就是那个隔离区。
    所以照片在「审核通过」之前根本不会进对象存储，少一段、少一处要定期清理的垃圾。
    将来如果换成自建表单直传，再把 temp/ 那一段补上（本模块已预留 key 前缀参数）。

用法
    python tools/photo_store.py --check          # 看配置是否可用
    python tools/photo_store.py --test 图.jpg    # 试传一张，验证密钥和域名
    python tools/selftest_photos.py              # 自检：EXIF 是否真被剥离、方向是否正确

配置（二选一，前者优先）
    1. 项目根目录 qiniu.config.json（已写进 .gitignore，不会进仓库）
       {
         "access_key": "...",
         "secret_key": "...",
         "bucket": "农家乐",
         "cdn_domain": "img.xn--fjq23fx8l.cn"
       }
    2. 环境变量 QINIU_AK / QINIU_SK / QINIU_BUCKET / QINIU_CDN

没配置任何密钥时，本模块整体「不存在」：enabled() 返回 False，
调用方自动回落到本地 static/uploads/，同步链路照样能跑通。
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "qiniu.config.json"

# 站点图片统一规格：长边 1600、webp、质量 82。
# 手机原图动辄 3–5MB，直接铺进页面首屏就废了。
MAX_EDGE = 1600
WEBP_QUALITY = 82


class QiniuNotConfigured(Exception):
    """没配密钥。调用方应当捕获它并回落到本地存储，而不是报错退出。"""


# ------------------------------------------------------------------ 配置
def config():
    """读取七牛配置，没配就返回 None。"""
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except (json.JSONDecodeError, OSError):
            cfg = {}
    # 环境变量可以覆盖文件里的值（CI 场景）
    for env_key, cfg_key in (("QINIU_AK", "access_key"), ("QINIU_SK", "secret_key"),
                             ("QINIU_BUCKET", "bucket"), ("QINIU_CDN", "cdn_domain")):
        if os.environ.get(env_key):
            cfg[cfg_key] = os.environ[env_key]
    need = ("access_key", "secret_key", "bucket", "cdn_domain")
    if not cfg.get("access_key") or not cfg.get("secret_key") or not cfg.get("bucket"):
        return None
    cfg["cdn_domain"] = (cfg.get("cdn_domain") or "").strip().rstrip("/")
    if cfg["cdn_domain"]:
        cfg["cdn_domain"] = cfg["cdn_domain"].replace("https://", "").replace("http://", "")
    return cfg


def enabled():
    """密钥配齐了没。没配就整条链路走本地。"""
    cfg = config()
    if not cfg:
        return False
    try:
        import qiniu  # noqa: F401
    except ImportError:
        return False
    return True


def public_url(key):
    """对象 key → 对外可访问的 CDN 地址。

    注意：一定要走「绑定的 CDN 域名」。七牛免费额度给的是 CDN 回源流量，
    直连源站域名按 0.26 元/GB 计费且没有免费额度——这是七牛最容易被忽略的坑。
    """
    cfg = config()
    if not cfg or not cfg.get("cdn_domain"):
        return ""
    return f"https://{cfg['cdn_domain']}/{key.lstrip('/')}"


# ------------------------------------------------------------------ 压缩
def compress_to_webp(path):
    """把照片压成站点规格的 webp，并**彻底剥离 EXIF**。返回新文件路径。

    两个必须做的动作，少一个都出问题：

    1. exif_transpose —— 手机竖着拍的照片，像素其实是横的，
       靠 EXIF 里的 Orientation 标记告诉浏览器转 90°。
       如果只剥离 EXIF 不先应用旋转，全站竖拍照会集体躺倒。

    2. 剥离 EXIF —— 手机照片默认带 GPS 经纬度。
       不剥离 = 把商家的**店面精确位置**公开在每张图上。
       这是隐私问题，不是优化项。

    paste 到一张新图上是最省事又彻底的做法：新图不携带任何元数据。
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        print("    ⚠ 未安装 Pillow，照片将原样发布（体积大、EXIF 未剥离）")
        return path

    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)          # 先把方向烧进像素

        if img.mode in ("RGBA", "LA", "P"):
            # 带透明通道的转 RGB 会变黑底，垫一层白
            base = Image.new("RGB", img.size, (255, 255, 255))
            base.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
            img = base
        elif img.mode != "RGB":
            img = img.convert("RGB")

        clean = Image.new("RGB", img.size)          # 新图：不带任何 EXIF/GPS
        clean.paste(img)

        w, h = clean.size
        if max(w, h) > MAX_EDGE:
            scale = MAX_EDGE / max(w, h)
            clean = clean.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                                 Image.LANCZOS)

        dst = path.with_suffix(".webp")
        clean.save(dst, "WEBP", quality=WEBP_QUALITY, method=5)

        # 结果已经落地，删原图只是收尾。这一步在 Windows 上失败是常态
        # （文件被占用、杀软正在扫描、回收站不可用），所以它必须在 try 之外：
        # 早期版本把 unlink 放在同一个 try 里，一失败就整体"回落到用原图发布"，
        # 结果是 3–5MB 的原始手机照带着 GPS 坐标上了线。
        # 清理失败可以忍；这种静默降级不能忍。
        if dst != path:
            drop(path)
        return dst
    except Exception as exc:                        # noqa: BLE001
        print(f"    ⚠ 照片处理失败，改用原图（{exc}）")
        return path


def drop(path):
    """尽力删除文件。失败只警告，绝不抛异常——清理是收尾，不是结果。"""
    try:
        Path(path).unlink(missing_ok=True)
        return True
    except OSError as exc:
        print(f"    · 原图未能删除（不影响发布，可事后手动清理）："
              f"{Path(path).name}（{exc}）")
        return False


def safe_name(local_path, index=0):
    """生成不可猜测的文件名。

    为什么不用原文件名：手机拍的是 IMG_0421.jpg，顺序可推。
    如果有人遍历域名下的文件名，未审核或已下线的图会被翻出来。
    随机 hash + 序号前缀：既防遍历，又保住了图库首图的顺序。
    """
    h = hashlib.sha1(os.urandom(16)).hexdigest()[:10]
    return f"{index + 1:02d}-{h}.webp"


# ------------------------------------------------------------------ 上传
def upload(local_path, key):
    """上传到七牛。成功返回 True，失败抛异常由调用方决定怎么降级。"""
    cfg = config()
    if not cfg:
        raise QiniuNotConfigured("七牛未配置（缺 qiniu.config.json 或环境变量）")
    try:
        from qiniu import Auth, put_file
    except ImportError as exc:
        raise QiniuNotConfigured("未安装七牛 SDK，执行 pip install qiniu") from exc

    auth = Auth(cfg["access_key"], cfg["secret_key"])
    token = auth.upload_token(cfg["bucket"], key, 3600)
    ret, info = put_file(token, key, str(local_path), version="v2")
    if ret and ret.get("key"):
        return True
    raise RuntimeError(f"七牛拒绝上传（{getattr(info, 'status_code', '?')}）：{info}")


def delete(key):
    """删除对象。用于商家下线或换图后清理孤儿文件。"""
    cfg = config()
    if not cfg:
        return False
    try:
        from qiniu import Auth, BucketManager
    except ImportError:
        return False
    auth = Auth(cfg["access_key"], cfg["secret_key"])
    mgr = BucketManager(auth)
    ret, info = mgr.delete(cfg["bucket"], key)
    return getattr(info, "status_code", 0) == 200


# ------------------------------------------------------------------ CLI
def _check():
    cfg = config()
    if not cfg:
        print("× 七牛未配置。照片会继续存在本地 static/uploads/。")
        print(f"  配置方式：在 {CONFIG_PATH} 写入 access_key / secret_key / bucket / cdn_domain")
        return 1
    print(f"√ 读到配置：bucket={cfg['bucket']}，"
          f"CDN 域名={cfg.get('cdn_domain') or '（未填，图片将无法生成外链）'}")
    if not cfg.get("cdn_domain"):
        print("  ⚠ 没填 cdn_domain：能上传但拼不出可访问地址，请先把域名补上")
        return 1
    try:
        import qiniu  # noqa: F401
    except ImportError:
        print("× 未安装七牛 SDK：pip install qiniu")
        return 1
    print("√ 七牛 SDK 就绪，配置可用")
    return 0


def _test(path):
    src = Path(path)
    if not src.exists():
        print(f"× 找不到文件：{src}")
        return 1
    out = compress_to_webp(src)
    cfg = config()
    prefix = os.environ.get("QINIU_PREFIX", "_selftest")
    key = f"{prefix}/{safe_name(out)}"
    print(f"→ 压缩：{src.name} → {out.name}（{out.stat().st_size // 1024} KB）")
    try:
        upload(out, key)
    except Exception as exc:                        # noqa: BLE001
        print(f"× 上传失败：{exc}")
        return 1
    url = public_url(key)
    print(f"√ 上传成功\n  key = {key}\n  url = {url}")
    print("\n请复制上面这个 url 到浏览器打开确认能访问——"
          "能上传不等于能访问（CDN 域名没绑好、防盗链写错都会 403）。")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="商家照片的压缩与七牛上传")
    ap.add_argument("--check", action="store_true", help="检查七牛配置是否可用")
    ap.add_argument("--test", metavar="FILE", help="试传一张照片，验证密钥与域名")
    a = ap.parse_args()
    if a.test:
        sys.exit(_test(a.test))
    sys.exit(_check())
