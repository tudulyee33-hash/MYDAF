"""이미지 자동 준비. 저작권 문제가 없는 이미지만 쓴다.

1순위 Pexels (무료 키가 있을 때, 상업적 이용 가능 라이선스)
2순위 위키미디어 공용 (자유 라이선스, 저작자·라이선스 표기 필수 → 출처란에 자동 기입)
뉴스 기사 사진은 저작권이 있어 쓰지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import requests

from .logs import log

UA = {"User-Agent": "MYDAF/1.1 (local blog writing tool)"}
TIMEOUT = 20
FREE_LICENSES = ("cc0", "public domain", "cc by", "cc-by", "pd")


@dataclass
class Picture:
    path: str
    credit: str          # 출처란에 들어갈 표기
    page_url: str


def _clean(html_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text or "")).strip()


def _download(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            return False
        dest.write_bytes(r.content)
        return dest.stat().st_size > 5000
    except requests.RequestException as e:
        log.info("이미지 다운로드 실패 %s: %s", url, e)
        return False


def pexels_search(query: str, key: str, n: int) -> list[dict]:
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key, **UA},
                     params={"query": query, "per_page": max(n, 3), "orientation": "landscape"}, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"url": p["src"]["large2x"], "credit": f"Photo: {p['photographer']} / Pexels", "page": p["url"]}
            for p in r.json().get("photos", [])]


def parse_commons(data: dict) -> list[dict]:
    out = []
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _clean(meta.get("LicenseShortName", {}).get("value", ""))
        if not lic or not any(k in lic.lower() for k in FREE_LICENSES):
            continue
        if info.get("width", 0) and info.get("width", 0) < 800:
            continue
        artist = _clean(meta.get("Artist", {}).get("value", "")) or "작자 미상"
        url = info.get("thumburl") or info.get("url")
        if url:
            out.append({"url": url, "credit": f"{artist[:60]}, {lic}, Wikimedia Commons",
                        "page": info.get("descriptionurl", "")})
    return out


def commons_search(query: str, n: int) -> list[dict]:
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=TIMEOUT, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": max(n * 3, 10),
        "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 1400})
    r.raise_for_status()
    return parse_commons(r.json())


def prepare(queries: list[str], folder: Path, cfg, progress=lambda m: None) -> list[Picture | None]:
    """소제목별 검색어 → 이미지 파일. 못 구한 칸은 None (그 소제목은 이미지 없이 진행)."""
    folder.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    result: list[Picture | None] = []
    for i, q in enumerate(queries[: cfg.images_per_post]):
        pic = None
        try:
            cands = pexels_search(q, cfg.pexels_api_key, 3) if cfg.pexels_api_key else []
            cands += commons_search(q, 3)
        except Exception as e:
            log.warning("이미지 검색 실패 %s: %s", q, e)
            cands = []
        for c in cands:
            if c["url"] in used:
                continue
            ext = ".png" if c["url"].lower().endswith(".png") else ".jpg"
            dest = folder / f"img{i + 1}{ext}"
            if _download(c["url"], dest):
                used.add(c["url"])
                pic = Picture(str(dest), c["credit"], c["page"])
                break
        progress(f"  · 이미지 {i + 1}: {'준비됨' if pic else '못 찾음 (건너뜀)'} ({q})")
        result.append(pic)
    return result
