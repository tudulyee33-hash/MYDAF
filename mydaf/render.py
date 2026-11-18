"""원고 → 에디터 입력 블록 / 미리보기 HTML.
출처는 본문 맨 아래에 작은 글씨로, 기본 우측 정렬 (설정에서 좌측 가능)."""
from __future__ import annotations

import html


def citation_line(n: int, s) -> str:
    if s.kind == "kiss":
        author = s.meta.get("citation_author", "")
        journal = s.meta.get("citation_journal_title", "")
        parts = [p for p in (author, f"「{s.title}」", journal, s.published[:4]) if p]
        return f"[{n}] " + ", ".join(parts) + " (KISS 한국학술정보)"
    parts = [p for p in (s.publisher, f"「{s.title}」", s.published) if p]
    return f"[{n}] " + ", ".join(parts) + f" {s.url}"


def to_blocks(post: dict, cited: list, align: str = "right", font_size: int = 11) -> list[dict]:
    blocks: list[dict] = []
    if post.get("intro"):
        blocks.append({"type": "para", "text": post["intro"]})
    for sec in post["sections"]:
        blocks.append({"type": "heading", "text": sec["heading"]})
        for p in sec["paragraphs"]:
            blocks.append({"type": "para", "text": p["text"]})
    if post.get("conclusion"):
        blocks.append({"type": "para", "text": post["conclusion"]})
    if cited:
        lines = ["출처"] + [citation_line(i, s) for i, s in enumerate(cited, 1)]
        blocks.append({"type": "citations", "lines": lines, "align": align, "size": font_size})
    return blocks


def preview_html(title: str, blocks: list[dict], tags: list[str]) -> str:
    out = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>",
           "<body style='max-width:720px;margin:40px auto;font-family:sans-serif;line-height:1.8'>",
           f"<h1>{html.escape(title)}</h1>"]
    for b in blocks:
        if b["type"] == "heading":
            out.append(f"<h2>{html.escape(b['text'])}</h2>")
        elif b["type"] == "para":
            out.append(f"<p>{html.escape(b['text'])}</p>")
        else:
            lines = "<br>".join(html.escape(x) for x in b["lines"])
            out.append(f"<p style='text-align:{b['align']};font-size:{b['size']}px;color:#888'>{lines}</p>")
    out.append("<p style='color:#999'>" + " ".join("#" + html.escape(t) for t in tags) + "</p></body>")
    return "\n".join(out)
