"""설정 저장/불러오기. 모든 설정은 이 PC의 사용자 폴더에만 저장된다."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_dir() -> Path:
    """설정·로그·브라우저 프로필이 저장되는 폴더 (%APPDATA%\\MYDAF)."""
    override = os.environ.get("MYDAF_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "MYDAF"
    else:
        base = Path.home() / ".mydaf"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Config:
    # AI
    ai_provider: str = "claude"          # 지금은 claude. ai.py 에 다른 공급자를 추가할 수 있다.
    anthropic_api_key: str = ""
    model: str = "claude-opus-5-5"
    effort: str = "high"

    # 네이버 블로그
    naver_blog_id: str = ""
    publish_mode: str = "draft"          # draft(임시저장) | publish(발행)
    category: str = ""                   # 비워두면 기본 카테고리
    browser_channel: str = "msedge"      # msedge | chrome

    # 주제/키워드 (개수·길이 제한 없음, 한 줄에 하나)
    keywords: list[str] = field(default_factory=list)
    use_google_trends: bool = True
    topic_cooldown_days: int = 14        # 같은 주제를 다시 쓰기까지 최소 일수

    # 자료 출처
    naver_client_id: str = ""            # developers.naver.com 검색 API (선택)
    naver_client_secret: str = ""
    google_api_key: str = ""             # Google Programmable Search (선택)
    google_cx: str = ""
    rss_feeds: list[str] = field(default_factory=list)
    society_sources: list[str] = field(default_factory=list)   # 학회 RSS 또는 공지 페이지 주소
    use_kiss: bool = True
    max_items_per_source: int = 6

    # 검증
    min_independent_sources: int = 2     # 사실 1개당 서로 다른 출처(도메인) 최소 수
    allow_single_source: bool = False    # True면 1곳 확인 사실도 "단일 출처"로 쓸 수 있음
    min_verified_facts: int = 4          # 이보다 적으면 그 주제는 발행하지 않음

    # 출처 표기
    citation_align: str = "right"        # right | left
    citation_font_size: int = 11

    # 연속 실행
    daily_limit: int = 5
    interval_min_minutes: int = 40
    interval_max_minutes: int = 90

    # 원격 제어 (선택, 기본 꺼짐)
    remote_enabled: bool = False
    remote_url: str = ""                 # 예: https://내서버.com
    remote_token: str = ""
    remote_poll_seconds: int = 30

    @classmethod
    def path(cls) -> Path:
        return app_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = cls.path()
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path())

    def update(self, values: dict) -> list[str]:
        """원격/화면에서 받은 값을 형식에 맞게 반영. 반영된 키 목록 반환."""
        changed = []
        types = {f.name: f.type for f in fields(self)}
        for key, value in values.items():
            if key not in types or key in ("remote_token",):
                continue
            cur = getattr(self, key)
            if isinstance(cur, bool):
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
            elif isinstance(cur, int):
                value = int(value)
            elif isinstance(cur, list):
                value = [s.strip() for s in (value if isinstance(value, list) else str(value).splitlines()) if str(s).strip()]
            else:
                value = str(value)
            setattr(self, key, value)
            changed.append(key)
        return changed
