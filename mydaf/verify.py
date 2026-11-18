"""사실 검증 (필수 단계).

AI가 뽑은 사실마다:
1. 인용문이 해당 원문에 실제로 있는지 글자 단위로 대조 (공백·따옴표 차이는 무시)
2. 실제로 확인된 근거의 '서로 다른 매체' 수를 센다
3. 기준(기본 2곳) 이상이면 verified, 1곳이면 single(설정 시에만 사용), 0곳이면 rejected

그리고 AI가 쓴 원고에서 사실 문단이 검증된 사실만 근거로 삼았는지 다시 확인한다.
"""
from __future__ import annotations

import re
import unicodedata

QUOTE_CHARS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "·": " ", "…": "..."})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(QUOTE_CHARS)
    return re.sub(r"[\s\"']+", "", text).lower()


def quote_in_text(quote: str, text: str) -> bool:
    q = normalize(quote)
    return len(q) >= 8 and q in normalize(text)


def verify_facts(extracted: dict, sources: list, min_outlets: int = 2, allow_single: bool = False) -> dict:
    by_id = {s.id: s for s in sources}
    verified, single, rejected = [], [], []
    for raw in extracted.get("facts", []):
        good, bad = [], []
        for ev in raw.get("evidence", []):
            s = by_id.get(ev.get("source_id", ""))
            if s and quote_in_text(ev.get("quote", ""), s.text):
                good.append({"source_id": s.id, "outlet": s.outlet, "quote": ev["quote"]})
            else:
                bad.append({**ev, "reason": "원문에서 인용문을 찾지 못함" if s else "없는 자료 ID"})
        outlets = sorted({g["outlet"] for g in good})
        fact = {"statement": raw.get("statement", "").strip(), "evidence": good, "rejected_evidence": bad,
                "outlets": outlets, "outlet_count": len(outlets)}
        if len(outlets) >= min_outlets:
            verified.append(fact)
        elif len(outlets) == 1:
            single.append(fact)
        else:
            rejected.append(fact)

    usable = verified + (single if allow_single else [])
    for i, f in enumerate(usable, 1):
        f["id"] = f"F{i}"
    return {"usable": usable, "verified": verified, "single": single, "rejected": rejected,
            "conflicts": extracted.get("conflicts", [])}


def check_draft(post: dict, usable_facts: list[dict]) -> dict:
    """원고 검사: 사실 문단이 없는 사실 ID를 대거나 근거가 비어 있으면 그 문단을 뺀다.
    추론 문단은 추론 근거가 비어 있으면 뺀다 (추론 기록 누락 방지)."""
    valid_ids = {f["id"] for f in usable_facts}
    removed, inferences = [], []
    for sec in post.get("sections", []):
        kept = []
        for p in sec.get("paragraphs", []):
            ids = [i for i in p.get("fact_ids", []) if i in valid_ids]
            if p.get("is_inference"):
                if not p.get("inference_reasoning", "").strip():
                    removed.append({"text": p["text"], "reason": "추론 근거가 기록되지 않음"})
                    continue
                inferences.append({"section": sec.get("heading", ""), "text": p["text"],
                                   "reasoning": p["inference_reasoning"], "based_on": ids})
            elif not ids:
                removed.append({"text": p["text"], "reason": "근거 사실 ID 없음"})
                continue
            p["fact_ids"] = ids
            kept.append(p)
        sec["paragraphs"] = kept
    post["sections"] = [s for s in post.get("sections", []) if s["paragraphs"]]
    return {"removed": removed, "inferences": inferences}


def cited_sources(post: dict, usable_facts: list[dict], sources: list) -> list:
    """글에 실제로 쓰인 사실의 근거 자료만 출처로 표기한다 (등장 순서대로)."""
    facts = {f["id"]: f for f in usable_facts}
    by_id = {s.id: s for s in sources}
    order: list[str] = []
    for sec in post.get("sections", []):
        for p in sec["paragraphs"]:
            for fid in p.get("fact_ids", []):
                for ev in facts.get(fid, {}).get("evidence", []):
                    if ev["source_id"] not in order:
                        order.append(ev["source_id"])
    return [by_id[i] for i in order if i in by_id]


def body_chars(post: dict) -> int:
    """본문 글자 수, 공백 포함 (네이버·일반 글자 수 세기와 같은 방식). 품질 기준 확인용."""
    parts = [post.get("intro", ""), post.get("conclusion", "")]
    parts += [p["text"] for s in post.get("sections", []) for p in s["paragraphs"]]
    return sum(len(" ".join(x.split())) for x in parts)
