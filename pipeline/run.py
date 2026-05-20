"""손경제 Daily Brief 오케스트레이터.

흐름:
  1) MBC RSS에서 오늘 손경제 에피소드
  2) 경제지표 7개 (환율/코스피/국고채10년 + S&P500/다우/WTI/금)
  3) Claude API로 뉴스카드 + 친절한 경제 + 래빗해빛 콘텐츠 소재 생성 (web_search)
  4) HTML 보고서 렌더링 → docs/latest.html, docs/index.html, docs/archive/{date}.html
  5) (옵션 --push) git commit + push
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import fetch_indicators, fetch_rss, notify_kakao, render_report  # noqa: E402
from pipeline import summarize as sm  # noqa: E402

REPORT_URL_FULL = "https://arum0807.github.io/sonkyungje-daily/latest.html"
REPORT_URL_SHARE = "https://arum0807.github.io/sonkyungje-daily/share.html"

load_dotenv(override=True)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]

# 표시 순서
DOMESTIC_KEYS = ["usd_krw", "kospi", "kr_10y"]
WORLD_KEYS = ["sp500", "dow", "wti", "gold_krw_g"]


def _kst_now() -> datetime:
    return datetime.now(KST)


def _date_kr(dt: datetime) -> str:
    return f"{dt.year}년 {dt.month}월 {dt.day}일 {WEEKDAYS_KR[dt.weekday()]}요일"


def _group_indicators(ind_data: dict) -> dict:
    inds = ind_data.get("indicators", {})
    return {
        "domestic": [inds[k] for k in DOMESTIC_KEYS if k in inds],
        "world": [inds[k] for k in WORLD_KEYS if k in inds],
    }


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _git_commit_push(repo: Path, date_str: str, *, dry_run: bool) -> bool:
    status = _git(["status", "--porcelain", "docs/"], cwd=repo).stdout.strip()
    if not status:
        logger.info("git: docs/에 변경사항 없음 — skip")
        return False
    if dry_run:
        logger.info("git (dry-run) 변경 파일:\n%s", status)
        return False
    _git(["add", "docs/"], cwd=repo)
    msg = f"chore: Daily Brief {date_str}"
    r = _git(["commit", "-m", msg], cwd=repo)
    if r.returncode != 0:
        logger.error("git commit 실패: %s", r.stderr)
        return False
    push = _git(["push"], cwd=repo)
    if push.returncode != 0:
        logger.error("git push 실패: %s", push.stderr)
        return False
    logger.info("✅ git push 완료: %s", msg)
    return True


def run(
    *,
    use_search: bool = True,
    save_intermediate: bool = True,
    push: bool = False,
    dry_run_push: bool = False,
    notify: bool = True,
) -> dict:
    now = _kst_now()
    date_str = now.strftime("%Y-%m-%d")
    logger.info("=== 손경제 Daily Brief 파이프라인 시작 (%s) ===", date_str)

    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)

    # 1) RSS
    logger.info("[1/4] MBC 손경제 RSS 가져오는 중...")
    episode = fetch_rss.fetch_latest_episode()
    logger.info("  ✓ %s", episode.title)
    episode_dict = asdict(episode)
    if save_intermediate:
        (out_dir / "episode.json").write_text(
            json.dumps(episode_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 2) 경제지표
    logger.info("[2/4] 경제지표 7개 수집 중...")
    ind_data = fetch_indicators.fetch_all()
    if ind_data["errors"]:
        logger.warning("  일부 지표 실패: %s", list(ind_data["errors"].keys()))
    if save_intermediate:
        (out_dir / "indicators.json").write_text(
            json.dumps(ind_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 3) Claude API
    logger.info("[3/4] Claude API로 요약·인사이트·콘텐츠 소재 생성 중...")
    summary = sm.summarize(episode_dict, ind_data, use_web_search=use_search)
    if save_intermediate:
        (out_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    meta = summary.get("_meta", {})
    logger.info(
        "  ✓ model=%s, in=%s, out=%s",
        meta.get("model"),
        meta.get("input_tokens"),
        meta.get("output_tokens"),
    )

    # 4) 렌더링 — Claude가 생성한 policy_outlook을 ind_data에 머지 (실패 시 기본값 유지)
    policy_rates = {
        k: {**v} for k, v in ind_data["policy_rates"].items()
    }  # 얕은 복사
    outlook_overrides = summary.get("policy_outlook") or {}
    for country, text in outlook_overrides.items():
        if country in policy_rates and isinstance(text, str) and text.strip():
            policy_rates[country]["outlook"] = text.strip()
            logger.info("  ✓ %s outlook 갱신: %s", country, text.strip())

    logger.info("[4/4] HTML 보고서 렌더 중...")
    report_data = {
        "date": date_str,
        "date_kr": _date_kr(now),
        "episode": {
            "title": episode.title,
            "audio_url": episode.audio_url,
            "pub_date": episode.pub_date,
        },
        "indicators": _group_indicators(ind_data),
        "policy_rates": policy_rates,
        "news_cards": summary.get("news_cards", []),
        "friendly_economics": summary.get("friendly_economics"),
        "rabbithat_ideas": summary.get("rabbithat_ideas", []),
        "generated_at": now.strftime("%Y-%m-%d %H:%M KST"),
    }
    if save_intermediate:
        (out_dir / "report_data.json").write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 2벌 렌더: full (대표님용) + share (햇님이들용)
    for mode in ("full", "share"):
        html = render_report.render(report_data, mode=mode)
        paths = render_report.save(
            html, date_str, mode=mode, also_index=(mode == "full")
        )
        for label, p in paths.items():
            try:
                rel = p.relative_to(ROOT)
            except ValueError:
                rel = p
            logger.info("  ✓ [%s] %s: %s", mode, label, rel)

    # 5) git
    if push or dry_run_push:
        logger.info("[git] 커밋·푸시...")
        _git_commit_push(ROOT, date_str, dry_run=dry_run_push)

    # 6) 카카오톡 알림 (best-effort — 실패해도 메인 흐름 OK)
    if notify:
        logger.info("[kakao] 알림 전송 중 (2버튼: 대표/공유)...")
        try:
            notify_kakao.notify_from_report(
                report_data, REPORT_URL_FULL, REPORT_URL_SHARE
            )
            logger.info("  ✓ 카카오톡 알림 전송 완료")
        except Exception as exc:
            logger.warning("  ⚠️  카카오톡 알림 실패 (보고서 자체는 정상): %s", exc)

    logger.info("=== 완료 ===")
    return report_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-search", action="store_true", help="web_search 비활성화 (API 비용 절감)")
    parser.add_argument("--no-save", action="store_true", help="중간 JSON 저장 안 함")
    parser.add_argument("--push", action="store_true", help="git commit + push 실행")
    parser.add_argument("--dry-run-push", action="store_true", help="git 변경사항 확인만")
    parser.add_argument("--no-notify", action="store_true", help="카카오톡 알림 비활성화")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        run(
            use_search=not args.no_search,
            save_intermediate=not args.no_save,
            push=args.push,
            dry_run_push=args.dry_run_push,
            notify=not args.no_notify,
        )
    except Exception as exc:
        logger.exception("파이프라인 실패: %s", exc)
        sys.exit(1)
