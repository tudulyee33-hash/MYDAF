"""설정 저장/불러오기. 모든 설정은 이 PC의 사용자 폴더에만 저장된다."""
from __future__ import annotations

import json
import re
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


STALE_GEMINI_MODELS = {"gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-preview",
                       "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash"}


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


# 네이버 저품질·이용 제한 위험을 줄이기 위한 고정 안전장치 (설정 화면·원격으로도 넘을 수 없음)
HARD_DAILY_MAX = 3            # 하루 최대 글 수
MIN_INTERVAL_FLOOR = 180      # 글 사이 최소 간격(분) = 3시간


def split_terms(line: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,;，、]+", str(line)) if t.strip()]


def split_keywords(items) -> list[str]:
    """키워드 목록 정리. 한 줄 = 한 주제(묶음). 쉼표로 이어 적은 줄은 '주제 묶음'으로 남겨 두고
    (매번 그중 2~3개를 골라 한 편으로 엮는다), 빈 칸·중복만 정리한다."""
    if isinstance(items, str):
        items = [items]
    out, seen = [], set()
    for item in items or []:
        for line in str(item).splitlines():
            terms = split_terms(line)
            if not terms:
                continue
            k = ", ".join(terms)
            if k.lower() not in seen:
                seen.add(k.lower())
                out.append(k)
    return out


@dataclass
class Config:
    # 화면
    setup_done: bool = False             # 최초 설정 마법사를 마쳤는지
    auto_start: bool = False             # 프로그램을 켜면 자동 등록 바로 시작

    # AI
    ai_provider: str = "gemini"          # gemini(무료 키 가능) | claude
    gemini_api_key: str = ""             # aistudio.google.com 에서 무료 발급
    gemini_model: str = "gemini-3.5-flash"
    anthropic_api_key: str = ""
    model: str = "claude-opus-5-5"
    effort: str = "xhigh"           # 고품질: 깊게 생각하고 쓰기

    # 네이버 블로그
    naver_blog_id: str = "tudulyee33"
    publish_mode: str = "draft"          # draft(임시저장) | publish(발행)
    category: str = ""                   # 비워두면 기본 카테고리
    browser_channel: str = "msedge"      # msedge | chrome

    # 글쓰기
    writer_style: str = "정보 전달형 전문가"   # 정보 전달형 전문가 | 트렌드 관찰형 | 친근한 이웃형 | 분석 리포트형
    heading_style: str = "quote"         # quote(인용구 소제목) | bold(굵은 글씨)
    heading_font_size: int = 34
    body_font_size: int = 30
    use_images: bool = True
    images_per_post: int = 4
    pexels_api_key: str = ""             # 선택: pexels.com 무료 키. 없으면 위키미디어 공용(자유 라이선스)
    show_browser: bool = True            # 작성 중 블로그 화면 보이기

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
    min_verified_facts: int = 6          # 이보다 적으면 그 주제는 발행하지 않음

    # 출처 표기
    citation_align: str = "right"        # right | left
    citation_font_size: int = 11

    # 연속 실행
    daily_limit: int = 3                 # 최대 HARD_DAILY_MAX(3)
    interval_min_minutes: int = 200      # 최소 MIN_INTERVAL_FLOOR(180)
    interval_max_minutes: int = 300
    active_start_hour: int = 8           # 이 시간대 안에서만 글을 올림
    active_end_hour: int = 22
    min_post_chars: int = 1800           # 본문이 이보다 짧으면 올리지 않음

    # 원격 제어 (선택, 기본 꺼짐)
    remote_enabled: bool = False
    remote_url: str = ""                 # 예: https://내서버.com
    remote_token: str = ""
    remote_poll_seconds: int = 30

    def ai_key(self) -> str:
        return self.gemini_api_key if self.ai_provider == "gemini" else self.anthropic_api_key

    def __post_init__(self):
        self.clamp()

    def clamp(self) -> None:
        """안전장치: 한도·간격은 고정 기준을 넘지 못하게 맞춘다."""
        self.keywords = split_keywords(self.keywords)
        if self.gemini_model in STALE_GEMINI_MODELS or "2.5" in self.gemini_model:
            self.gemini_model = "gemini-3.5-flash"    # 새 키에서 404·한도 오류가 나던 예전 기본값 교체
        self.daily_limit = max(1, min(int(self.daily_limit), HARD_DAILY_MAX))
        self.interval_min_minutes = max(int(self.interval_min_minutes), MIN_INTERVAL_FLOOR)
        self.interval_max_minutes = max(int(self.interval_max_minutes), self.interval_min_minutes)
        self.active_start_hour = max(0, min(int(self.active_start_hour), 23))
        self.active_end_hour = max(self.active_start_hour + 1, min(int(self.active_end_hour), 24))

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
        self.clamp()
        return changed
