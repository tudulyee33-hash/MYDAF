"""주제 자동 발굴. 키워드 목록(개수·길이 제한 없음) + 구글 트렌드(한국)에서 후보를 만들고,
최근에 쓴 주제는 건너뛴다."""
from __future__ import annotations

import random
from datetime import datetime, timedelta


from .config import split_terms
from .logs import log, read_history
from .sources import HTTP, TIMEOUT, _feedparse, clean


def google_trends_kr(limit: int = 20) -> list[str]:
    try:
        r = HTTP.get("https://trends.google.com/trending/rss?geo=KR", timeout=TIMEOUT)
        r.raise_for_status()
        return [clean(e.get("title", "")) for e in _feedparse(r.text).entries[:limit] if e.get("title")]
    except Exception as e:
        log.warning("구글 트렌드 실패: %s", e)
        return []


def recent_topics(days: int) -> set[str]:
    since = datetime.now() - timedelta(days=days)
    out = set()
    for h in read_history():
        try:
            t = datetime.fromisoformat(h["time"])
            if t >= since and h.get("status") in ("published", "draft"):
                out.add(h["topic"].strip().lower())
                out.update(t.lower() for t in split_terms(h["topic"]))
            elif h.get("status") == "skipped" and t >= datetime.now() - timedelta(days=1):
                out.update(t.lower() for t in split_terms(h["topic"]))
                out.add(h["topic"].strip().lower())   # 자료 부족으로 건너뛴 주제는 하루 쉬었다 재시도
        except (KeyError, ValueError):
            continue
    return out


def next_topics(cfg) -> list[str]:
    """이번 회차에 시도할 주제 후보(우선순위 순). 키워드가 먼저, 트렌드는 키워드와 겹치거나 키워드가 없을 때."""
    used = recent_topics(cfg.topic_cooldown_days)
    keywords = [k.strip() for k in cfg.keywords if k.strip()]
    random.shuffle(keywords)
    candidates = []
    for k in keywords:
        terms = split_terms(k)
        if len(terms) > 1:      # 주제 묶음: 첫 검색어(중심 주제) + 최근에 안 쓴 검색어 2개
            head, rest = terms[0], terms[1:]
            fresh = [t for t in rest if t.lower() not in used] or rest
            random.shuffle(fresh)
            candidates.append(", ".join([head] + fresh[:2]))
        elif k.lower() not in used:
            candidates.append(k)

    if cfg.use_google_trends:
        trends = google_trends_kr()
        if keywords:
            # 키워드와 관련된 트렌드를 앞쪽에 (예: 키워드 '전기차' + 트렌드 '전기차 보조금')
            terms = [t for k in keywords for t in split_terms(k)]
            related = [t for t in trends if any(k.lower() in t.lower() or t.lower() in k.lower() for k in terms)]
            candidates = related + candidates
        else:
            candidates += trends
    seen, ordered = set(), []
    for c in candidates:
        if c.lower() not in seen and c.lower() not in used:
            seen.add(c.lower())
            ordered.append(c)
    return ordered
