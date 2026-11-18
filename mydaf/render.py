"""원고 → 에디터 입력 블록 / 미리보기 HTML.
출처는 본문 맨 아래에 작은 글씨로, 기본 우측 정렬 (설정에서 좌측 가능)."""
from __future__ import annotations

import html
from pathlib import Path


def citation_line(n: int, s) -> str:
    if s.kind == "kiss":
        author = s.meta.get("citation_author", "")
        journal = s.meta.get("citation_journal_title", "")
        parts = [p for p in (author, f"「{s.title}」", journal, s.published[:4]) if p]
        return f"[{n}] " + ", ".join(parts) + " (KISS 한국학술정보)"
    parts = [p for p in (s.publisher, f"「{s.title}」", s.published) if p]
    return f"[{n}] " + ", ".join(parts) + f" {s.url}"


def to_blocks(post: dict, cited: list, align: str = "right", font_size: int = 11,
              images: list | None = None, heading_size: int = 34, body_size: int = 30,
              heading_style: str = "quote") -> list[dict]:
    """에디터 입력 순서. images[i] 는 i번째 소제목 아래에 들어간다 (None 이면 생략)."""
    images = images or []
    blocks: list[dict] = []
    if post.get("intro"):
        blocks.append({"type": "para", "text": post["intro"], "size": body_size})
    for i, sec in enumerate(post["sections"]):
        blocks.append({"type": "heading", "text": sec["heading"], "size": heading_size, "style": heading_style})
        pic = images[i] if i < len(images) else None
        if pic:
            blocks.append({"type": "image", "path": pic.path})
        for p in sec["paragraphs"]:
            blocks.append({"type": "para", "text": p["text"], "size": body_size})
    if post.get("conclusion"):
        blocks.append({"type": "para", "text": post["conclusion"], "size": body_size})
    lines = [citation_line(i, s) for i, s in enumerate(cited, 1)]
    lines += [f"[사진] {pic.credit}" for pic in images if pic]
    if lines:
        blocks.append({"type": "citations", "lines": ["출처"] + lines, "align": align, "size": font_size})
    return blocks


def preview_html(title: str, blocks: list[dict], tags: list[str]) -> str:
    out = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>",
           "<body style='max-width:720px;margin:40px auto;font-family:sans-serif;line-height:1.8'>",
           f"<h1>{html.escape(title)}</h1>"]
    for b in blocks:
        if b["type"] == "heading":
            out.append(f"<h2 style='border-left:4px solid #2563EB;padding-left:12px'>{html.escape(b['text'])}</h2>")
        elif b["type"] == "image":
            out.append(f"<p><img src='images/{html.escape(Path(b['path']).name)}' style='max-width:100%'></p>")
        elif b["type"] == "para":
            out.append(f"<p>{html.escape(b['text'])}</p>")
        else:
            lines = "<br>".join(html.escape(x) for x in b["lines"])
            out.append(f"<p style='text-align:{b['align']};font-size:{b['size']}px;color:#888'>{lines}</p>")
    out.append("<p style='color:#999'>" + " ".join("#" + html.escape(t) for t in tags) + "</p></body>")
    return "\n".join(out)
