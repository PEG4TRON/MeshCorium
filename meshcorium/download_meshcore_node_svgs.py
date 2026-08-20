#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


BASE_URL = "https://flasher.meshcore.dev"
CONFIG_URL = f"{BASE_URL}/config.json"
DEST_DIR = Path(__file__).resolve().parent / "icons" / "nodes"
SVG_SRC_RE = re.compile(r"""src=['"](?P<src>/img/[^'"]+\.svg)['"]""", re.IGNORECASE)


def to_slug(text: str) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9.]+", "-", str(text).lower()))


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MeshcoriumNodeSvgDownloader/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MeshcoriumNodeSvgDownloader/1.0",
            "Accept": "image/svg+xml,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def extract_svg_paths(config: dict) -> list[str]:
    paths: set[str] = set()
    for device in config.get("device", []):
        tooltip = str(device.get("tooltip") or "")
        for match in SVG_SRC_RE.finditer(tooltip):
            paths.add(match.group("src"))
    return sorted(paths)


def download_svgs(force: bool = False) -> tuple[int, int, int]:
    config = fetch_json(CONFIG_URL)
    svg_paths = extract_svg_paths(config)
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    skipped = 0
    failed = 0

    for rel_path in svg_paths:
        filename = os.path.basename(rel_path)
        dest = DEST_DIR / filename
        if dest.exists() and not force:
            skipped += 1
            print(f"skip  {filename}")
            continue
        try:
            payload = fetch_bytes(f"{BASE_URL}{rel_path}")
            if b"<svg" not in payload.lower():
                raise ValueError("response does not look like SVG")
            dest.write_bytes(payload)
            downloaded += 1
            print(f"write {filename}")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            failed += 1
            print(f"fail  {filename}: {exc}", file=sys.stderr)

    return downloaded, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Download MeshCore flasher node SVG previews into icons/nodes/")
    parser.add_argument("--force", action="store_true", help="re-download SVG files even if they already exist")
    args = parser.parse_args()

    downloaded, skipped, failed = download_svgs(force=args.force)
    print(
        f"done downloaded={downloaded} skipped={skipped} failed={failed} dir={DEST_DIR}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
