#!/usr/bin/env python3
"""
Second pass: extract and download all product images missed in the first crawl.
Handles www.cocokart.shop/cdn/shop/ URLs and protocol-relative //... URLs.
"""
import re
import os
import time
import random
import urllib.parse
from pathlib import Path

import requests

OUTPUT_DIR = Path(r"C:\Users\sunpreet kaur\Desktop\cocokart-archive\site")
CDN_DIR = OUTPUT_DIR / "_cdn" / "www.cocokart.shop"
USER_AGENT = "Mozilla/5.0 (CocoKart preservation archive)"

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

# Patterns to find all image URLs in HTML files
PATTERNS = [
    # og:image meta tag content
    r'content="(https?://(?:www\.)?cocokart\.shop/cdn/shop/[^"?]+)',
    r'content="(https?://cdn\.shopify\.com/s/files/[^"?]+)',
    # src / srcset attributes (protocol-relative)
    r'src="(//(?:www\.)?cocokart\.shop/cdn/shop/[^"?]+)',
    r'src="(//cdn\.shopify\.com/s/files/[^"?]+)',
    # JSON data (escaped slashes)
    r'"src":"(\\/\\/(?:www\.)?cocokart\.shop\\/cdn\\/shop\\/[^"\\]+)',
    r'"src":"(\\/\\/cdn\.shopify\.com\\/s\\/files\\/[^"\\]+)',
    # unescaped in JSON
    r'"src":"(//(?:www\.)?cocokart\.shop/cdn/shop/[^"?]+)',
    r'"src":"(//cdn\.shopify\.com/s/files/[^"?]+)',
    # srcset
    r'srcset="([^"]*(?:cocokart\.shop|cdn\.shopify\.com)/cdn/shop/[^"?]+)',
]

def unescape_json_url(url):
    return url.replace("\\/", "/")

def normalise_url(url):
    url = unescape_json_url(url)
    if url.startswith("//"):
        url = "https:" + url
    # Strip width/version query params
    url = url.split("?")[0]
    return url

def url_to_local(url):
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc  # e.g. www.cocokart.shop or cdn.shopify.com
    path = parsed.path.lstrip("/")
    return OUTPUT_DIR / "_cdn" / domain / path

def download(url, local):
    if local.exists():
        return True
    try:
        time.sleep(random.uniform(0.3, 0.8))
        r = session.get(url, timeout=30, stream=True)
        r.raise_for_status()
        local.parent.mkdir(parents=True, exist_ok=True)
        with open(local, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        print(f"  [+{local.stat().st_size//1024}KB] {url}")
        return True
    except Exception as e:
        print(f"  [!] {url}: {e}")
        return False

def main():
    print("=== Image second pass ===")
    found_urls = set()

    html_files = list(OUTPUT_DIR.rglob("*.html"))
    print(f"Scanning {len(html_files)} HTML files...")

    for html_file in html_files:
        text = html_file.read_text(encoding="utf-8", errors="replace")
        for pattern in PATTERNS:
            for match in re.findall(pattern, text):
                # srcset may have multiple URLs
                for part in match.split(","):
                    part = part.strip().split()[0]  # take URL only (not descriptor)
                    url = normalise_url(part)
                    if url.startswith("https://") and any(
                        d in url for d in ("cocokart.shop", "cdn.shopify.com")
                    ):
                        found_urls.add(url)

    print(f"Found {len(found_urls)} unique image URLs")
    print()

    ok = 0
    fail = 0
    for url in sorted(found_urls):
        local = url_to_local(url)
        if download(url, local):
            ok += 1
        else:
            fail += 1

    print()
    print(f"=== Done: {ok} downloaded, {fail} failed ===")

    # Count total images now
    all_images = list(OUTPUT_DIR.rglob("*.webp")) + list(OUTPUT_DIR.rglob("*.jpg")) + list(OUTPUT_DIR.rglob("*.jpeg")) + list(OUTPUT_DIR.rglob("*.png"))
    total_size = sum(f.stat().st_size for f in all_images) // 1024 // 1024
    print(f"Total images on disk: {len(all_images)} ({total_size} MB)")

if __name__ == "__main__":
    main()
