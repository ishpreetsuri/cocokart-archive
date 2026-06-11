#!/usr/bin/env python3
"""
CocoKart Site Mirror
Crawls cocokart.shop and saves a static offline copy for GitHub Pages.
"""

import os
import re
import sys
import time
import random
import urllib.parse
from collections import deque
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────────
BASE_URL = "https://cocokart.shop"
ALLOWED_DOMAINS = {"cocokart.shop", "cdn.shopify.com"}
OUTPUT_DIR = Path(r"C:\Users\sunpreet kaur\Desktop\cocokart-archive\site")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (CocoKart preservation archive)"

SKIP_EXTENSIONS = {".pdf", ".zip", ".gz", ".tar", ".mp4", ".mov", ".avi"}
SKIP_PATH_PREFIXES = [
    "/admin", "/cart", "/checkout", "/account", "/orders",
    "/tools/", "/?variant=",
]

SEED_URLS = [
    "/",
    "/collections",
    "/collections/all",
    "/pages/about",
    "/pages/about-us",
    "/pages/contact",
    "/pages/contact-us",
    "/pages/faq",
    "/pages/shipping",
    "/policies/privacy-policy",
    "/policies/refund-policy",
    "/policies/shipping-policy",
    "/policies/terms-of-service",
    "/blogs/news",
]

# ── State ────────────────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

visited_pages: set[str] = set()
downloaded_assets: set[str] = set()
failed: list[str] = []


# ── Path helpers ─────────────────────────────────────────────────────────────

def url_to_local_path(url: str) -> Path:
    """Turn a full URL into an absolute local file path."""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.split(":")[0]
    path = parsed.path or "/"

    # Strip query string from path
    if "?" in path:
        path = path.split("?")[0]

    # Ensure directories get an index.html
    if path == "" or path.endswith("/"):
        path = path.rstrip("/") + "/index.html"

    # Add .html if there's no file extension
    _, ext = os.path.splitext(path)
    if not ext:
        path = path + ".html"

    path = path.lstrip("/")

    if domain == "cocokart.shop":
        return OUTPUT_DIR / path
    else:
        return OUTPUT_DIR / "_cdn" / domain / path


def relative(from_file: Path, to_file: Path) -> str:
    """Return a POSIX relative path from one file to another."""
    try:
        rel = os.path.relpath(str(to_file), str(from_file.parent))
        return rel.replace("\\", "/")
    except ValueError:
        return to_file.as_posix()


# ── Asset downloader ─────────────────────────────────────────────────────────

def download_asset(url: str) -> Path | None:
    """Download a binary/text asset and return its local path."""
    # Normalise
    url = url.split("?")[0].split("#")[0]
    if url in downloaded_assets:
        return url_to_local_path(url)
    downloaded_assets.add(url)

    local = url_to_local_path(url)
    if local.exists():
        return local

    try:
        time.sleep(random.uniform(0.2, 0.6))
        r = session.get(url, timeout=30, stream=True)
        r.raise_for_status()
        local.parent.mkdir(parents=True, exist_ok=True)
        with open(local, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        size = local.stat().st_size
        print(f"  [asset +{size//1024}KB] {url}")
        return local
    except Exception as e:
        msg = f"Asset FAIL: {url}  ({e})"
        print(f"  [!] {msg}")
        failed.append(msg)
        return None


def process_css(css_text: str, css_url: str, local_css_path: Path) -> str:
    """Find url() references in CSS, download them, rewrite to relative paths."""
    def replace_url(match):
        raw = match.group(1).strip("'\"")
        if raw.startswith("data:") or raw.startswith("#"):
            return match.group(0)
        abs_url = urllib.parse.urljoin(css_url, raw)
        if not any(d in abs_url for d in ALLOWED_DOMAINS):
            return match.group(0)
        local = download_asset(abs_url)
        if local is None:
            return match.group(0)
        rel = relative(local_css_path, local)
        return f"url({rel})"

    return re.sub(r"url\(([^)]+)\)", replace_url, css_text)


# ── HTML rewriter ────────────────────────────────────────────────────────────

def rewrite_html(html: str, page_url: str, local_page: Path) -> tuple[str, list[str]]:
    """
    Parse HTML, download all assets, rewrite links to relative paths.
    Returns (rewritten_html, list_of_new_page_urls).
    """
    soup = BeautifulSoup(html, "lxml")
    new_links: list[str] = []

    def abs_url(href: str) -> str:
        return urllib.parse.urljoin(page_url, href)

    def is_allowed_asset(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc in ALLOWED_DOMAINS

    # ── Images (src, data-src, srcset) ────────────────────────────────────
    for tag in soup.find_all(["img", "source"]):
        for attr in ("src", "data-src", "data-lazy-src"):
            val = tag.get(attr)
            if val and not val.startswith("data:"):
                a = abs_url(val)
                if is_allowed_asset(a):
                    loc = download_asset(a)
                    if loc:
                        tag[attr] = relative(local_page, loc)
        for attr in ("srcset", "data-srcset"):
            val = tag.get(attr)
            if not val:
                continue
            parts = []
            for piece in val.split(","):
                piece = piece.strip()
                if not piece:
                    continue
                tokens = piece.split()
                img_url = tokens[0]
                descriptor = " " + tokens[1] if len(tokens) > 1 else ""
                a = abs_url(img_url)
                if is_allowed_asset(a):
                    loc = download_asset(a)
                    if loc:
                        parts.append(relative(local_page, loc) + descriptor)
                        continue
                parts.append(piece)
            tag[attr] = ", ".join(parts)

    # ── CSS <link> ────────────────────────────────────────────────────────
    for tag in soup.find_all("link"):
        rel_attr = tag.get("rel", [])
        if isinstance(rel_attr, str):
            rel_attr = [rel_attr]
        if "stylesheet" in rel_attr and tag.get("href"):
            a = abs_url(tag["href"])
            if is_allowed_asset(a):
                loc = download_asset(a)
                # Also process CSS for url() references
                if loc and loc.exists() and loc.suffix == ".css":
                    css_text = loc.read_text(encoding="utf-8", errors="replace")
                    rewritten_css = process_css(css_text, a, loc)
                    loc.write_text(rewritten_css, encoding="utf-8")
                if loc:
                    tag["href"] = relative(local_page, loc)
        elif tag.get("href") and tag["href"].startswith("http"):
            a = abs_url(tag["href"])
            if is_allowed_asset(a):
                loc = download_asset(a)
                if loc:
                    tag["href"] = relative(local_page, loc)

    # ── JavaScript <script src> ───────────────────────────────────────────
    for tag in soup.find_all("script", src=True):
        a = abs_url(tag["src"])
        if is_allowed_asset(a):
            loc = download_asset(a)
            if loc:
                tag["src"] = relative(local_page, loc)

    # ── Internal anchor links → collect new pages + rewrite ──────────────
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        a = abs_url(href)
        parsed_a = urllib.parse.urlparse(a)
        if parsed_a.netloc == "cocokart.shop":
            # Clean URL for crawling
            clean = urllib.parse.urlunparse(parsed_a._replace(fragment="", query=""))
            ext = os.path.splitext(parsed_a.path)[1].lower()
            if (ext not in SKIP_EXTENSIONS and
                    not any(parsed_a.path.startswith(p) for p in SKIP_PATH_PREFIXES) and
                    clean not in visited_pages):
                new_links.append(clean)
            # Rewrite link
            loc = url_to_local_path(clean)
            tag["href"] = relative(local_page, loc)

    # ── Inline <style> blocks ─────────────────────────────────────────────
    for tag in soup.find_all("style"):
        if tag.string:
            tag.string.replace_with(
                process_css(tag.string, page_url, local_page)
            )

    # ── Inline style= attributes ──────────────────────────────────────────
    for tag in soup.find_all(style=True):
        tag["style"] = process_css(tag["style"], page_url, local_page)

    return str(soup), new_links


# ── Page crawler ─────────────────────────────────────────────────────────────

def crawl_page(url: str) -> list[str]:
    """Fetch one HTML page, save it, return new URLs to visit."""
    url = url.rstrip("/")
    if not url:
        url = BASE_URL

    if url in visited_pages:
        return []
    visited_pages.add(url)

    parsed = urllib.parse.urlparse(url)
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in SKIP_EXTENSIONS:
        return []
    if any(parsed.path.startswith(p) for p in SKIP_PATH_PREFIXES):
        return []

    local_path = url_to_local_path(url)

    try:
        time.sleep(random.uniform(0.8, 1.5))
        r = session.get(url, timeout=30, allow_redirects=True)
        r.raise_for_status()

        ct = r.headers.get("content-type", "")
        if "text/html" not in ct:
            download_asset(url)
            return []

        size_kb = len(r.content) // 1024
        print(f"[page {size_kb}KB] {url}")

        rewritten, new_links = rewrite_html(r.text, url, local_path)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(rewritten, encoding="utf-8")

        return new_links

    except requests.exceptions.HTTPError as e:
        msg = f"Page FAIL {e.response.status_code}: {url}"
        print(f"  [!] {msg}")
        failed.append(msg)
        return []
    except Exception as e:
        msg = f"Page FAIL: {url}  ({e})"
        print(f"  [!] {msg}")
        failed.append(msg)
        return []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  CocoKart Site Mirror")
    print(f"  Output -> {OUTPUT_DIR}")
    print("=" * 60)
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    queue: deque[str] = deque()
    for path in SEED_URLS:
        queue.append(BASE_URL + path)

    while queue:
        url = queue.popleft()
        new_links = crawl_page(url)
        for link in new_links:
            if link not in visited_pages:
                queue.append(link)

        if len(visited_pages) % 5 == 0:
            print(f"\n  -- {len(visited_pages)} pages | {len(downloaded_assets)} assets --\n")

    # ── Summary ──────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  DONE")
    print(f"  Pages saved : {len(visited_pages)}")
    print(f"  Assets saved: {len(downloaded_assets)}")

    # Count files and total size
    all_files = list(OUTPUT_DIR.rglob("*"))
    file_count = sum(1 for f in all_files if f.is_file())
    total_size = sum(f.stat().st_size for f in all_files if f.is_file())
    print(f"  Files on disk: {file_count} ({total_size // 1024 // 1024} MB)")

    index = OUTPUT_DIR / "index.html"
    if index.exists():
        print(f"  index.html: {index.stat().st_size // 1024} KB  [OK]")
    else:
        print("  index.html: MISSING  [!]")

    if failed:
        print(f"\n  Failed ({len(failed)}):")
        for f in failed:
            print(f"    {f}")
    else:
        print("\n  No failures [OK]")

    print("=" * 60)

    # Write failure log
    log_path = Path(r"C:\Users\sunpreet kaur\Desktop\cocokart-archive\mirror-failures.txt")
    log_path.write_text("\n".join(failed), encoding="utf-8")
    print(f"\n  Failure log -> {log_path}")


if __name__ == "__main__":
    main()
