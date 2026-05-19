"""MBC 손에 잡히는 경제 팟캐스트 RSS 수집.

피드에서 가장 최근 에피소드 1건을 가져와 title/description/pubDate/audio_url을 반환.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

import feedparser
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

RSS_URL = "https://minicast.imbc.com/PodCast/pod.aspx?code=1000671100000100000"


@dataclass
class Episode:
    title: str
    description: str
    description_html: str
    pub_date: str
    audio_url: Optional[str]
    guid: str
    source_feed: str
    fetched_at: str


def _strip_html(html: str) -> str:
    """HTML → 줄바꿈을 보존한 plain text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert_after("\n")
    text = soup.get_text()
    # 연속 공백·줄바꿈 정리
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _dedup_description(text: str) -> str:
    """MBC 손경제 RSS는 description 텍스트가 중간에 잘려 여러 번 반복되는 케이스가 있음.

    - 첫 줄 마커가 본문에 다시 등장하면 마지막 등장 이후부터 사용
    - 같은 prefix(앞 5자)를 가진 라인이 여러 개면 가장 긴 것만 남김
      (예: "3) 한은 삼전 총파업"과 "3) 한은 삼전 총파업 시 경제성장률..." → 후자만)
    """
    if not text:
        return text
    # 1단계: 첫 줄 마커의 마지막 등장 이후부터 사용
    first_line = text.split("\n", 1)[0].strip()
    if first_line and len(first_line) >= 3:
        last_occurrence = text.rfind(first_line)
        if last_occurrence > 0:
            text = text[last_occurrence:].strip()

    # 2단계: prefix 기반 dedup, 가장 긴 라인만 보존
    prefix_to_line: dict[str, str] = {}
    order: list[str] = []
    EMPTY = "\x00empty\x00"
    for raw in text.split("\n"):
        line = raw.rstrip()
        norm = line.strip()
        if not norm:
            if not order or order[-1] != EMPTY:
                order.append(EMPTY)
            continue
        prefix = norm[:5]
        if prefix not in prefix_to_line:
            prefix_to_line[prefix] = line
            order.append(prefix)
        elif len(line) > len(prefix_to_line[prefix]):
            prefix_to_line[prefix] = line
    out = [("" if p == EMPTY else prefix_to_line[p]) for p in order]
    return "\n".join(out).strip()


def _audio_url(entry) -> Optional[str]:
    """RSS enclosure에서 오디오 URL 추출."""
    for enc in entry.get("enclosures", []) or []:
        url = enc.get("href") or enc.get("url")
        if url and (url.endswith(".mp3") or "audio" in enc.get("type", "")):
            return url
    # links에 type=audio가 있을 수도 있음
    for link in entry.get("links", []) or []:
        if "audio" in link.get("type", ""):
            return link.get("href")
    return None


def fetch_latest_episode() -> Episode:
    logger.info("RSS 가져오는 중: %s", RSS_URL)
    feed = feedparser.parse(RSS_URL)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS 파싱 실패: {feed.bozo_exception}")
    if not feed.entries:
        raise RuntimeError("RSS에 에피소드가 없습니다.")

    entry = feed.entries[0]
    description_html = entry.get("summary") or entry.get("description") or ""
    description = _dedup_description(_strip_html(description_html))

    return Episode(
        title=entry.get("title", "").strip(),
        description=description,
        description_html=description_html,
        pub_date=entry.get("published", "").strip(),
        audio_url=_audio_url(entry),
        guid=entry.get("id", "") or entry.get("guid", ""),
        source_feed=RSS_URL,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def fetch_recent_episodes(n: int = 5) -> list[Episode]:
    """디버깅·아카이브용: 최근 N개 에피소드."""
    feed = feedparser.parse(RSS_URL)
    episodes = []
    for entry in feed.entries[:n]:
        description_html = entry.get("summary") or entry.get("description") or ""
        episodes.append(
            Episode(
                title=entry.get("title", "").strip(),
                description=_dedup_description(_strip_html(description_html)),
                description_html=description_html,
                pub_date=entry.get("published", "").strip(),
                audio_url=_audio_url(entry),
                guid=entry.get("id", "") or entry.get("guid", ""),
                source_feed=RSS_URL,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        )
    return episodes


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=1, help="최근 N개 (기본 1)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.n == 1:
        ep = fetch_latest_episode()
        print(json.dumps(asdict(ep), ensure_ascii=False, indent=2))
    else:
        eps = fetch_recent_episodes(args.n)
        print(json.dumps([asdict(e) for e in eps], ensure_ascii=False, indent=2))
