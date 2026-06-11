#!/usr/bin/env python3
"""
Third pass: rewrite remaining absolute CDN URLs in HTML files to local relative paths.
Covers og:image meta, JSON data blocks, and any other src= that still points live.
"""
import re
import os
import urllib.parse
from pathlib import Path

OUTPUT_DIR = Path(r"C:\Users\sunpreet kaur\Desktop\cocokart-archive\site")


def url_to_local(url: str) -> Path | None:
    """Given a CDN URL, return the expected local path (if it exists)."""
    url = url.split("?")[0].split("#")[0]
    if url.startswith("//"):
        url = "https:" + url
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc
    path = parsed.path.lstrip("/")
    local = OUTPUT_DIR / "_cdn" / domain / path
    if local.exists():
        return local
    return None


def relative(from_file: Path, to_file: Path) -> str:
    try:
        rel = os.path.relpath(str(to_file), str(from_file.parent))
        return rel.replace("\\", "/")
    except ValueError:
        return to_file.as_posix()


def rewrite_file(html_path: Path) -> int:
    """Rewrite a single HTML file. Returns number of replacements made."""
    text = html_path.read_text(encoding="utf-8", errors="replace")
    original = text
    count = 0

    # Match all CDN URLs (with or without protocol, with or without escaping)
    pattern = re.compile(
        r'(https?:)?'               # optional protocol
        r'(?:\\+/\\+/|//)'         # // or \\/\\/
        r'((?:www\.)?cocokart\.shop|cdn\.shopify\.com)'
        r'(/cdn/shop/[^\s"\'<>\\,]+)'   # path
        r'(?:\?[^\s"\'<>\\,]*)?'   # optional query
    )

    def replacer(m: re.Match) -> str:
        nonlocal count
        full = m.group(0)
        domain = m.group(2)
        path = m.group(3)
        # Normalise slashes (unescape \/)
        path = path.replace("\\/", "/")
        # Strip query
        path = path.split("?")[0]
        url = f"https://{domain}{path}"
        local = url_to_local(url)
        if local is None:
            return full  # file not downloaded, leave as-is
        rel = relative(html_path, local)
        count += 1
        return rel

    text = pattern.sub(replacer, text)

    if text != original:
        html_path.write_text(text, encoding="utf-8")

    return count


def main():
    html_files = list(OUTPUT_DIR.rglob("*.html"))
    print(f"Rewriting {len(html_files)} HTML files...")
    total = 0
    changed = 0
    for f in html_files:
        n = rewrite_file(f)
        if n > 0:
            changed += 1
            total += n
    print(f"Done: {total} URL rewrites across {changed} files.")


if __name__ == "__main__":
    main()
