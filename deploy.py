#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""农家乐.cn 发布：产物 → gh-pages，源码 → main。

    python deploy.py                 # 只推产物到 gh-pages
    python deploy.py --source        # 连源码一起推 main
    python deploy.py --dry-run       # 只报告将要发生什么，不写任何东西

为什么不用 git push
    本机装了 Watt Toolkit，git 的网络子进程（git-remote-https）会被 SIGTERM 秒杀，
    任何 push / ls-remote 都送不出去。所以全部走 GitHub Git Data API：
    blobs → tree → commit → ref。效果等同，且一次提交多个文件只产生一个 commit。
    凭据从 ~/.git-credentials 读，只用不打印、不落盘。

分支约定（与老孟其他站点一致）
    main     源码：build.py / data / templates / static / tools
    gh-pages 产物：public/ 的内容，GitHub Pages 从这里发布

产物 must 自带 CNAME，否则覆盖式发布会把域名绑定的 CNAME 一起抹掉、站点掉线。
build.py 已经负责产出它，本脚本只做校验（见 ASSERT_REQUIRED）。
"""
import argparse
import base64
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = os.environ.get("GH_REPO", "mfujun2025/nongjiale")
PROD_BRANCH = os.environ.get("GH_PROD_BRANCH", "gh-pages")
SRC_BRANCH = os.environ.get("GH_SRC_BRANCH", "main")
API = "https://api.github.com"

BASE = Path(__file__).resolve().parent
PUB = BASE / "public"

# 产物里必须存在的文件。缺一个就拒绝发布——特别是 CNAME，
# 丢了它 GitHub 会解绑自定义域名，线上直接掉。
ASSERT_REQUIRED = {"CNAME", ".nojekyll", "index.html"}

# 源码分支要排除的东西
SRC_EXCLUDE_DIRS = {
    ".git", "public", "build", "__pycache__", ".workbuddy",
    ".vscode", ".idea", ".deploy", "node_modules",
    # 自检脚本的临时目录（已挪到 build/，这里防旧版本残留）
    "_selftest_tmp", "_selftest",
}
SRC_EXCLUDE_FILES = {
    "_feishu_check.html", "qiniu.config.json", "config.local.json",
}


# ---------------------------------------------------------------- HTTP
def _token():
    cred = Path(os.path.expanduser("~")) / ".git-credentials"
    if not cred.exists():
        return None
    for line in cred.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "github.com" not in line:
            continue
        parts = line.split(":", 2)
        if len(parts) == 3:
            return parts[2].split("@")[0]
    return None


TOKEN = _token()
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def req(method, path, payload=None, retries=4):
    """发一个 GitHub API 请求。返回 (status, dict|str)。

    409/422/428 在 Git Data API 里常是暂时性的（并发、竞态、偶发 missing_field），
    退避重试；502/503 是 GitHub 自己的抖动，同样重试。
    """
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    last = (0, "no attempt")
    for attempt in range(retries):
        r = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            # 必须显式：urllib 默认 form-urlencoded，会让 POST /git/trees 直接 404
            "Content-Type": "application/json",
            "User-Agent": "wb-nongjiale-deploy",
        })
        try:
            with urllib.request.urlopen(r, context=CTX, timeout=90) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return resp.status, json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            last = (e.code, body)
            if e.code in (409, 422, 428, 502, 503) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = (0, str(e))
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            return last
    return last


# ---------------------------------------------------------------- 文件收集
def git_blob_sha(raw):
    """Git 的 blob 对象 id = sha1("blob <len>\\0" + content)。

    本地算得出来，就能和远端 tree 里的 sha 对账：一样就不用重传。
    """
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(raw))
    h.update(raw)
    return h.hexdigest()


def collect_prod():
    """public/ 下全部文件，包括 .nojekyll / CNAME 这类隐藏文件。"""
    if not PUB.is_dir():
        return []
    out = []
    for p in sorted(PUB.rglob("*")):
        if p.is_file():
            out.append((p.relative_to(PUB).as_posix(), p))
    return out


def collect_source():
    """源码文件，排除产物目录与会话数据。"""
    out = []
    for p in sorted(BASE.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(BASE)
        if set(rel.parts[:-1]) & SRC_EXCLUDE_DIRS:
            continue
        if rel.name in SRC_EXCLUDE_FILES or rel.suffix == ".pyc":
            continue
        if rel.name.endswith(".dump.html"):
            continue
        out.append((rel.as_posix(), p))
    return out


# ---------------------------------------------------------------- 发布
def remote_index(branch):
    """远端分支上 {路径: blob sha}。分支不存在返回 None。"""
    st, ref = req("GET", f"/repos/{REPO}/git/ref/heads/{branch}")
    if st != 200:
        return None
    st, tree = req("GET", f"/repos/{REPO}/git/trees/{branch}?recursive=1")
    if st != 200 or not isinstance(tree, dict):
        return {}
    return {x["path"]: x["sha"] for x in tree.get("tree", []) if x["type"] == "blob"}


def push_branch(branch, files, message, src_sha=None, dry=False):
    """把 files 覆盖式推到 branch。返回 (结果字符串, commit sha)。

    覆盖式 = tree 不带 base_tree。这样分支上只留本次列出的文件，
    上一次发布残留的旧文件会自动消失——正是我们要的（比如 main 上 9/7 那版原型）。
    """
    remote = remote_index(branch)
    exists = remote is not None
    parent = None
    if exists:
        st, ref = req("GET", f"/repos/{REPO}/git/ref/heads/{branch}")
        parent = ref["object"]["sha"] if st == 200 else None
    remote = remote or {}

    print(f"\n[{branch}] {'已存在' if exists else '新建'}，目标 {len(files)} 个文件")

    # 先对账：本地算 sha，与远端一致的直接复用，不重传
    entries, upload, reuse, total_bytes = [], [], 0, 0
    for path, local in files:
        raw = local.read_bytes()
        total_bytes += len(raw)
        sha = git_blob_sha(raw)
        if remote.get(path) == sha:
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})
            reuse += 1
            continue
        upload.append((path, raw, sha))

    print(f"  blob: 复用 {reuse} 个，需上传 {len(upload)} 个（共 {total_bytes / 1024:.0f} KB）")

    if dry:
        return (f"dry-run 跳过写入（将上传 {len(upload)} 个 blob）", None)

    if not upload and exists and len(remote) == len(files) and src_sha is None:
        print("  无变化，跳过")
        return ("无变化", parent)

    for path, raw, sha in upload:
        st, blob = req("POST", f"/repos/{REPO}/git/blobs",
                       {"content": base64.b64encode(raw).decode("ascii"),
                        "encoding": "base64"})
        if st not in (200, 201):
            return (f"FAIL blob {path} → {st} {str(blob)[:200]}", None)
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"    ↑ {path}")

    st, tree = req("POST", f"/repos/{REPO}/git/trees", {"tree": entries})
    if st not in (200, 201):
        return (f"FAIL tree → {st} {str(tree)[:300]}", None)

    parents = [parent] if parent and src_sha is None else ([src_sha] if src_sha else [])
    st, commit = req("POST", f"/repos/{REPO}/git/commits",
                     {"message": message, "tree": tree["sha"], "parents": parents})
    if st not in (200, 201):
        return (f"FAIL commit → {st} {str(commit)[:200]}", None)
    sha = commit["sha"]

    if exists:
        st, out = req("PATCH", f"/repos/{REPO}/git/refs/heads/{branch}",
                      {"sha": sha, "force": False})
    else:
        st, out = req("POST", f"/repos/{REPO}/git/refs",
                      {"ref": f"refs/heads/{branch}", "sha": sha})
        # 已存在等同成功（并发或上一次跑了一半）
        if st == 422 and "already exists" in str(out):
            st, out = req("PATCH", f"/repos/{REPO}/git/refs/heads/{branch}",
                          {"sha": sha, "force": False})
    if st not in (200, 201):
        return (f"FAIL ref → {st} {str(out)[:200]}", None)

    return (f"OK commit={sha[:8]}（{len(entries)} 个文件）", sha)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="农家乐.cn 发布到 GitHub Pages")
    ap.add_argument("--source", action="store_true", help="同时把源码推到 main")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写")
    ap.add_argument("--message", default=None, help="自定义 commit message")
    args = ap.parse_args()

    if not TOKEN:
        print("× 找不到 GitHub 凭据（~/.git-credentials）")
        return 2

    prod = collect_prod()
    if not prod:
        print("× public/ 为空或不存在，先跑 python build.py")
        return 2

    names = {p for p, _ in prod}
    missing = ASSERT_REQUIRED - names
    if missing:
        print(f"× 产物缺少必需文件：{sorted(missing)}")
        print("  CNAME 丢了会导致自定义域名被解绑，拒绝发布。请重跑 python build.py")
        return 2

    cname = (PUB / "CNAME").read_text(encoding="utf-8").strip()
    print(f"仓库 {REPO}    产物 {len(prod)} 个文件    CNAME {cname}")
    if args.dry_run:
        print("（dry-run：只报告，不写任何东西）")

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = args.message or f"publish: {len(prod)} files @ {stamp}"
    result, _ = push_branch(PROD_BRANCH, prod, msg, dry=args.dry_run)
    print(f"  → {result}")
    if result.startswith("FAIL"):
        return 1

    if args.source:
        src = collect_source()
        print(f"\n源码 {len(src)} 个文件")
        smsg = args.message or f"source: sync @ {stamp}"
        sresult, _ = push_branch(SRC_BRANCH, src, smsg, src_sha=None, dry=args.dry_run)
        print(f"  → {sresult}")
        if sresult.startswith("FAIL"):
            return 1

    print("\n完成。Pages 构建有 1~3 分钟延迟；域名走 Cloudflare，缓存 max-age=600。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
