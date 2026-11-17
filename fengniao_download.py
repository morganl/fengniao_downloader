#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蜂鸟网论坛(bbs.fengniao.com)图片批量下载器
=============================================

根据帖子 URL 自动抓取全部原图，并自动分类、按帖子标题命名到本地。

用法:
    py -3 fengniao_download.py <帖子URL> [帖子URL ...] [选项]

示例:
    py -3 fengniao_download.py https://bbs.fengniao.com/forum/12127185.html
    py -3 fengniao_download.py 12127185 https://bbs.fengniao.com/forum/12127199.html --out D:/photos
    py -3 fengniao_download.py 12127185 --pages 3

参数:
    帖子URL            一个或多个，也可以是纯数字的帖子 id (tid)
    --out DIR          输出根目录（默认: 脚本所在目录）
    --pages N          手动指定该帖子的总页数（默认自动检测，检测不到按 1 页处理）

输出结构:
    <out>/<图片分类>/<帖子标题>_<tid>/01.jpg, 02.jpg, ...

说明:
    - 下载的是网页里“下载”按钮对应的原图(downloadPic)，非缩略图。
    - 同一张图出现在多个楼层/入口时会自动去重。
    - 已下载的文件会跳过，可重复运行。
"""

import argparse
import html as html_mod
import json
import re
import sys
import time
from pathlib import Path
from urllib import request, error

UA = "Mozilla/5.0"
BASE = "https://bbs.fengniao.com"
CHARSET = "utf-8"


def _setup_encoding():
    """Windows 下强制 stdout/stderr 用 UTF-8，避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def log(msg):
    print(msg, flush=True)


def http_get(url, referer=None, timeout=30, retries=3):
    """GET 请求，返回 bytes；失败抛异常。"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = request.Request(url, headers={
                "User-Agent": UA,
                "Referer": referer or BASE + "/",
                "Accept": "*/*",
            })
            with request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise last_err


def get_text(url, referer=None):
    return http_get(url, referer=referer).decode(CHARSET, errors="replace")


def extract_tid(arg):
    """从 URL 或纯数字字符串里提取帖子 id (tid)。"""
    m = re.search(r"/(\d+)\.html", arg)
    if m:
        return m.group(1)
    if arg.strip().isdigit():
        return arg.strip()
    m = re.search(r"(\d{6,})", arg)
    if m:
        return m.group(1)
    raise ValueError(f"无法从参数里识别帖子 id: {arg}")


def normalize_thread_url(arg):
    tid = extract_tid(arg)
    return f"{BASE}/forum/{tid}.html", tid


def extract_title(html_text):
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.DOTALL)
    title = html_mod.unescape(m.group(1)).strip() if m else ""
    title = re.sub(r"\s*[-–—]\s*蜂鸟网\s*$", "", title).strip()
    return title or None


def extract_slide_links(html_text):
    """抓取页面里所有 slide 链接（去重、补全域名）。"""
    hrefs = re.findall(r'href="([^"]*/forum/pic/slide_[^"]+\.html)"', html_text)
    links = []
    seen = set()
    for h in hrefs:
        if h.startswith("http"):
            full = h
        else:
            full = BASE + h
        if full not in seen:
            seen.add(full)
            links.append(full)
    return links


def detect_total_pages(html_text, tid):
    """尽力检测总页数；检测不到返回 1。"""
    nums = set()
    nums |= {int(n) for n in re.findall(rf"/forum/{tid}_(\d+)\.html", html_text)}
    nums |= {int(n) for n in re.findall(rf"/forum/{tid}_1_(\d+)\.html", html_text)}
    if nums:
        return max(nums)
    return 1


def parse_piclist(slide_html):
    """
    解析 slide 页面里的 picList JSON，返回图片列表。
    每项含 picPos / pid / downloadPic / label。
    """
    m = re.search(r"picList\s*=\s*eval\('\('\+'(.*?)'\+'\)'\);", slide_html, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        # 兜底：逐条抠 downloadPic / pid / label
        data = []
        for pm in re.finditer(r'\{"picPos":(\d+),"pid":"(\d+)"(.*?)\}(?=,\{"picPos"|\])', slide_html, re.DOTALL):
            picpos, pid, rest = pm.groups()
            dl = re.search(r'"downloadPic":"(.*?)"', rest)
            lab = re.search(r'"title":"(.*?)"', rest)
            data.append({
                "picPos": int(picpos),
                "pid": pid,
                "downloadPic": (dl.group(1) if dl else "").replace("\\/", "/"),
                "label": [{"title": (lab.group(1) if lab else "")}],
            })
    return data


def pic_hash(download_pic_url):
    """用图片文件的 32 位十六进制哈希作为去重键。"""
    m = re.search(r"/([0-9a-f]{32})\.(?:jpg|jpeg|png)", download_pic_url, re.I)
    return m.group(1) if m else download_pic_url


def first_category(pics):
    for p in pics:
        for lbl in p.get("label", []):
            t = (lbl.get("title") or "").strip()
            if t and t not in ("暂无参数", ""):
                return t
    return None


def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name or "未命名"


def looks_like_image(data):
    """校验下载到的字节是否为有效图片。"""
    if not data or len(data) < 1000:
        return False
    if data[:2] == b"\xff\xd8":            # JPEG
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":   # PNG
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):  # GIF
        return True
    return False


def download_image(download_pic_url, slide_url):
    """下载一张原图；失败时重抓 slide 页换取新鲜 auth_key 再试一次。"""
    try:
        return http_get(download_pic_url, referer=slide_url, timeout=60)
    except Exception:
        # 重新抓 slide 页，用同一个文件哈希匹配到新鲜 downloadPic
        try:
            fresh_html = get_text(slide_url)
            key = pic_hash(download_pic_url)
            for p in parse_piclist(fresh_html):
                if pic_hash(p.get("downloadPic", "")) == key:
                    return http_get(p["downloadPic"], referer=slide_url, timeout=60)
        except Exception:
            pass
        return None


def process_thread(arg, out_root, force_pages=None):
    thread_url, tid = normalize_thread_url(arg)
    log(f"\n=== 帖子 {thread_url} ===")

    html_text = get_text(thread_url)
    title = extract_title(html_text) or f"帖子_{tid}"
    log(f"标题: {title}")

    total_pages = force_pages or detect_total_pages(html_text, tid)
    log(f"页数: {total_pages}")

    # 收集所有 slide 链接（跨页）
    slide_links = extract_slide_links(html_text)
    if total_pages > 1:
        for pg in range(2, total_pages + 1):
            try:
                phtml = get_text(f"{BASE}/forum/{tid}_{pg}.html")
                slide_links += extract_slide_links(phtml)
            except Exception as e:  # noqa: BLE001
                log(f"  第 {pg} 页抓取失败: {e}")
        # 去重保持顺序
        slide_links = list(dict.fromkeys(slide_links))

    if not slide_links:
        log("  未在页面里发现图片 slide 链接。")
        return 0

    # 逐 slide 解析并下载
    seen = set()
    category = None
    downloaded = 0
    failed = []
    save_dir = None
    index = 0

    for s_url in slide_links:
        try:
            s_html = get_text(s_url)
        except Exception as e:  # noqa: BLE001
            log(f"  slide 页抓取失败 {s_url}: {e}")
            continue
        pics = parse_piclist(s_html)
        if not pics:
            continue
        if category is None:
            category = first_category(pics)
        for pic in sorted(pics, key=lambda x: x.get("picPos", 0)):
            dl = pic.get("downloadPic", "")
            if not dl:
                continue
            key = pic_hash(dl)
            if key in seen:
                continue
            seen.add(key)
            index += 1

            # 确定保存目录（拿到分类后才建目录）
            if save_dir is None:
                cat = sanitize(category or "未分类")
                folder = sanitize(f"{title}_{tid}")
                save_dir = out_root / cat / folder
                save_dir.mkdir(parents=True, exist_ok=True)

            ext = ".jpg"
            m = re.search(r"\.(jpg|jpeg|png)", dl, re.I)
            if m:
                ext = "." + m.group(1).lower()
            fname = save_dir / f"{index:02d}{ext}"

            if fname.exists() and fname.stat().st_size > 0:
                log(f"  [{index:02d}] 已存在，跳过 {fname.name}")
                downloaded += 1
                continue

            data = download_image(dl, s_url)
            if looks_like_image(data):
                fname.write_bytes(data)
                downloaded += 1
                log(f"  [{index:02d}] 保存 {fname.name} ({len(data)//1024} KB)")
            else:
                failed.append((index, dl))
                log(f"  [{index:02d}] 下载失败 {dl}")

    log(f"完成: 共 {index} 张，成功 {downloaded}，失败 {len(failed)}，保存目录 {save_dir or '无'}")
    if failed:
        for i, u in failed:
            log(f"  失败 [{i:02d}] {u}")
    return downloaded


def main():
    _setup_encoding()
    ap = argparse.ArgumentParser(description="蜂鸟网论坛图片批量下载器")
    ap.add_argument("urls", nargs="+", help="帖子 URL 或帖子 id，可多个")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent), help="输出根目录")
    ap.add_argument("--pages", type=int, default=None, help="手动指定总页数")
    args = ap.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    total = 0
    for u in args.urls:
        try:
            total += process_thread(u, out_root, args.pages)
        except Exception as e:  # noqa: BLE001
            log(f"处理 {u} 出错: {e}")

    log(f"\n全部完成，共下载 {total} 张。输出目录: {out_root}")


if __name__ == "__main__":
    main()
