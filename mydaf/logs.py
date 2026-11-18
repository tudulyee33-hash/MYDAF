"""PC 로그. 외부로 전송하지 않는다.

- logs/app.log            : 진행 상황 (사람이 읽는 로그)
- logs/reasoning.jsonl    : 추론·추리 기록 (글마다 무엇을 어떤 근거로 추론했는지)
- posts/<날짜>_<id>/       : 글별 수집자료·검증표·원고·추론 전체 보관
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from .config import app_dir

LOG_DIR = app_dir() / "logs"
POST_DIR = app_dir() / "posts"
LOG_DIR.mkdir(exist_ok=True)
POST_DIR.mkdir(exist_ok=True)

log = logging.getLogger("mydaf")
if not log.handlers:
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)


def _append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def record_reasoning(post_id: str, topic: str, inferences: list[dict]) -> None:
    """추론·추리 내용을 반드시 남긴다 (비어 있어도 '추론 없음'으로 기록)."""
    _append_jsonl(LOG_DIR / "reasoning.jsonl", {
        "time": datetime.now().isoformat(timespec="seconds"),
        "post_id": post_id,
        "topic": topic,
        "inference_count": len(inferences),
        "inferences": inferences or [{"note": "이 글에는 추론·추리 문장이 없음"}],
    })


def post_folder(topic: str) -> tuple[str, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^\w가-힣]+", "_", topic)[:40].strip("_") or "post"
    post_id = f"{stamp}_{slug}"
    folder = POST_DIR / post_id
    folder.mkdir(parents=True, exist_ok=True)
    return post_id, folder


def save_json(folder: Path, name: str, data) -> None:
    (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def history_path() -> Path:
    return app_dir() / "history.jsonl"


def add_history(record: dict) -> None:
    _append_jsonl(history_path(), record)


def read_history() -> list[dict]:
    p = history_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
