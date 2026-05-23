"""손경제 Daily Brief 오케스트레이터.

흐름:
  1) MBC RSS — 오늘 손경제 에피소드
  2) 경제지표 7개 — 환율/코스피/국고채/S&P/다우/WTI/금
  3) Claude API 통합 호출 — news 5개 + insight + explainer + rabbithat_ideas + policy_outlook
  4) 데이터 모델을 new spec(indicators.global/base_rates 등)으로 정리해 보고서 데이터 조립
  5) HTML 렌더 — full(latest.html, index.html) + share(share.html) + 일자별 archive
  6) (옵션 --push) git commit + push
  7) (옵션 --notify) 카카오톡 알림
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

load_dotenv(override=True)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]

DOMESTIC_KEYS = ["usd_krw", "kospi", "kr_10y"]
WORLD_KEYS = ["sp500", "dow", "wti", "gold_krw_g"]

REPORT_URL_FULL = "https://rabbit-habbit.github.io/kyungje-daily/latest.html"
REPORT_URL_SHARE = "https://rabbit-habbit.github.io/kyungje-daily/share.html"


# ── 시간 / 표시 ─────────────────────────────────────────────────────


def _kst_now() -> datetime:
    return datetime.now(KST)


def _date_kr(dt: datetime) -> str:
    return f"{dt.year}년 {dt.month}월 {dt.day}일 {WEEKDAYS_KR[dt.weekday()]}요일"


# ── 숫자 포매팅 (fetch_indicators 출력 → 표시용) ──────────────────


def _fmt_value(value, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "원":
        return f"{value:,.2f}"
    if unit == "p":
        return f"{value:,.2f}"
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "$/배럴":
        return f"${value:,.2f}"
    if unit == "원/g":
        return f"{value:,.0f}원"
    return f"{value:,}"


def _fmt_change_display(ind: dict) -> str:
    """'▲ 9.43 (+0.63%)' / '▼ 0.050%p' 형태."""
    direction = ind.get("direction", "flat")
    arrow = "▲" if direction == "up" else "▼" if direction == "down" else "―"
    unit = ind.get("unit", "")
    chg = abs(ind.get("change", 0))
    if unit == "%":
        return f"{arrow} {chg:.3f}%p"
    if unit == "원":
        chg_str = f"{chg:,.2f}"
    elif unit == "p":
        chg_str = f"{chg:,.2f}"
    elif unit == "$/배럴":
        chg_str = f"${chg:,.2f}"
    elif unit == "원/g":
        chg_str = f"{chg:,.0f}원"
    else:
        chg_str = f"{chg:,}"
    pct = ind.get("change_pct")
    if pct is None:
        return f"{arrow} {chg_str}"
    sign = "+" if pct > 0 else ""
    return f"{arrow} {chg_str} ({sign}{pct:.2f}%)"


# ── 데이터 모델 변환: fetch_indicators 결과 → new spec ──────────────


# 짧은 라벨 (UI 좁은 column 대응)
INDICATOR_LABEL = {
    "usd_krw": "환율 (KRW/USD)",
    "kospi": "코스피",
    "kr_10y": "국고채 10년",
    "sp500": "S&P 500",
    "dow": "다우",
    "wti": "WTI",
    "gold_krw_g": "금/g",
}


def _adapt_indicator(key: str, ind: dict) -> dict:
    return {
        "label": INDICATOR_LABEL.get(key, ind.get("name", key)),
        "display": _fmt_value(ind.get("value"), ind.get("unit", "")),
        "change_display": _fmt_change_display(ind),
        "direction": ind.get("direction", "flat"),
    }


def _adapt_indicators_block(ind_data: dict) -> dict:
    """fetch_indicators 결과 → {domestic: [...], global: [...]}."""
    inds = ind_data.get("indicators", {})
    return {
        "domestic": [_adapt_indicator(k, inds[k]) for k in DOMESTIC_KEYS if k in inds],
        "global": [_adapt_indicator(k, inds[k]) for k in WORLD_KEYS if k in inds],
    }


def _adapt_base_rates(ind_data: dict, outlook: dict) -> dict:
    """policy_rates + summarize의 policy_outlook → base_rates."""
    pr = ind_data.get("policy_rates", {})
    kr_val = pr.get("korea", {}).get("value")
    us_val = pr.get("us", {}).get("value")
    spread_text = ""
    if isinstance(kr_val, (int, float)) and isinstance(us_val, (int, float)):
        diff = kr_val - us_val
        sign = "+" if diff > 0 else ""
        spread_text = f"{sign}{diff:.2f}%p"
    kr_outlook = (outlook or {}).get("korea") or pr.get("korea", {}).get("outlook", "")
    us_outlook = (outlook or {}).get("us") or pr.get("us", {}).get("outlook", "")
    return {
        "kr": f"{kr_val:.2f}%" if isinstance(kr_val, (int, float)) else "—",
        "us": f"{us_val:.2f}%" if isinstance(us_val, (int, float)) else "—",
        "spread": spread_text,
        "kr_outlook": kr_outlook,
        "us_outlook": us_outlook,
    }


# ── git ─────────────────────────────────────────────────────────────


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


# ── 메인 ────────────────────────────────────────────────────────────


def run(
    *,
    use_search: bool = True,
    save_intermediate: bool = True,
    push: bool = False,
    dry_run_push: bool = False,
    notify: bool = True,
    force: bool = False,
) -> dict | None:
    now = _kst_now()
    date_str = now.strftime("%Y-%m-%d")

    # Idempotent: 같은 날 archive 있으면 skip (workflow_dispatch는 --force로 우회)
    archive_path = ROOT / "docs" / "archive" / f"{date_str}.html"
    if archive_path.exists() and not force:
        logger.info(
            "=== %s 보고서 이미 존재 — skip (재생성하려면 --force) ===", date_str
        )
        return None

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

    # 3) Claude API 통합 호출
    logger.info("[3/4] Claude API 통합 요약 (news 5 + insight + explainer + ideas + outlook)...")
    summary = sm.summarize(episode_dict, ind_data, use_web_search=use_search)
    if save_intermediate:
        (out_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    meta = summary.get("_meta", {})
    logger.info(
        "  ✓ model=%s, in=%s, out=%s, news=%d, ideas=%d",
        meta.get("model"),
        meta.get("input_tokens"),
        meta.get("output_tokens"),
        len(summary.get("news_cards", [])),
        len(summary.get("rabbithat_ideas", [])),
    )

    # 4) 데이터 모델 정리 (new spec) + 렌더
    logger.info("[4/4] 보고서 데이터 조립 + HTML 렌더 (full + share)...")
    report_data = {
        "date": date_str,
        "date_kr": _date_kr(now),
        "headline": "",  # 현재는 헤더 fallback에 의존, 추후 LLM에서 채울 수 있음
        "episode": {
            "title": episode.title,
            "description": episode.description,
            "audio_url": episode.audio_url,
            "pub_date": episode.pub_date,
        },
        "indicators": _adapt_indicators_block(ind_data),
        "base_rates": _adapt_base_rates(ind_data, summary.get("policy_outlook") or {}),
        "news_cards": summary.get("news_cards", []),
        "insight": summary.get("insight", ""),
        "explainer": summary.get("explainer"),
        "rabbithat_ideas": summary.get("rabbithat_ideas", []),
        "generated_at": now.strftime("%Y-%m-%d %H:%M KST"),
    }
    if save_intermediate:
        (out_dir / "report_data.json").write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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

    # 6) 카카오톡 알림 (best-effort)
    if notify:
        logger.info("[kakao] 알림 전송 중 (2 링크: 대표/공유)...")
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
    parser.add_argument("--force", action="store_true", help="오늘 보고서가 이미 있어도 재생성")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        run(
            use_search=not args.no_search,
            save_intermediate=not args.no_save,
            push=args.push,
            dry_run_push=args.dry_run_push,
            notify=not args.no_notify,
            force=args.force,
        )
    except Exception as exc:
        logger.exception("파이프라인 실패: %s", exc)
        sys.exit(1)
