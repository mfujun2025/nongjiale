# 农家乐.cn

全国农家乐信息平台。静态站，Python 零依赖构建器生成，托管在 GitHub Pages。

- 线上地址：<https://xn--fjq23fx8l.cn>（农家乐.cn）
- 分支约定：**`main` = 源码**，**`gh-pages` = 构建产物**（Pages 从 gh-pages 发布）

## 本地构建

```bash
python build.py      # 读 data/*.json + templates/*.html → 生成 public/
python check.py      # 全站自检：页面完整性、链接可达性、SEO 要素、数据一致性
```

构建器无第三方依赖（标准库即可跑）。两个可选依赖：`pypinyin`（商家 URL 的拼音 slug）、
`Pillow`（商家照片压缩），缺了会优雅降级，不影响构建。

## 发布

```bash
python deploy.py              # 只推产物 → gh-pages
python deploy.py --source     # 连源码一起推 → main
python deploy.py --dry-run    # 只报告将要发生什么
```

`deploy.py` 走 **GitHub Git Data API**（blobs → tree → commit → ref），不用 `git push`——
本机装了网络加速工具，git 的网络子进程会被 SIGTERM，push 送不出去。
一次发布只产生一个 commit，且会先按 blob sha 对账，没变的文件不重传。

> 产物分支用**覆盖式 tree**（不带 `base_tree`），所以 `public/CNAME` 和 `public/.nojekyll`
> 必须由 `build.py` 产出——否则发布会把 CNAME 抹掉，自定义域名当场解绑。
> `deploy.py` 里对这两个文件有硬校验，缺失直接拒绝发布。

## 数据

| 文件 | 作用 |
|---|---|
| `data/site.json` | 站点级配置：域名、电话、导航、首页文案、FAQ |
| `data/shops.json` | 商家数据，**站点的唯一数据源** |
| `data/cities.json` | 有内容简介的城市（只放想认真做的城市） |
| `data/regions.json` | 全国 337 个地级行政区基准表（存在性判定，不建空页） |
| `data/_source/` | 行政区划上游数据缓存，供 `tools/build_regions.py` 复现 |

城市页只给**有商家**的城市生成，避免产出空页拉低整站质量。

## 商家入驻

审核后台是飞书多维表格，商家提交走飞书公开表单（免注册、免登录）。

```
飞书表单提交 → Base 记录 → 运营改成「已通过」
  → tools/sync_from_feishu.py 同步进 data/shops.json
  → python build.py && python check.py
  → python deploy.py
```

```bash
python tools/sync_from_feishu.py --dry-run    # 先看会发布哪些
python tools/sync_from_feishu.py              # 正式同步并回写飞书状态
```

照片在同步时处理：剥离 EXIF/GPS（隐私）→ 压缩到长边 1600 的 webp（性能）→
上传七牛云对象存储（未配置密钥时回落本地 `static/uploads/`）。

## 工具

| 脚本 | 用途 |
|---|---|
| `tools/build_regions.py` | 由上游行政区划数据生成 `data/regions.json`，含 31 条地名读音回归断言 |
| `tools/sync_from_feishu.py` | 飞书审核通过 → 站点数据的同步引擎 |
| `tools/photo_store.py` | 照片处理与七牛上传（`--check` 看配置） |
| `tools/selftest_photos.py` | 照片管道自检：EXIF 清零、尺寸限制、webp 格式 |
| `tools/make_join_qr.py` | 由入驻表单地址生成站点用的二维码 |
| `tools/bootstrap_demo_data.py` | 生成演示商家数据 |
