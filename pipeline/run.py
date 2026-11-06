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
import os
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import build_inline, fetch_indicators, fetch_rss, notify_kakao, products, render_report  # noqa: E402
from pipeline import summarize as sm  # noqa: E402

load_dotenv(override=True)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]

DOMESTIC_KEYS = ["usd_krw", "kospi", "kr_10y"]
WORLD_KEYS = ["sp500", "dow", "wti", "gold_krw_g"]

PAGES_BASE = "https://rabbit-habbit.github.io/kyungje-daily"
# latest.html / share.html은 매일 덮어쓰므로 카톡으로는 영구 archive URL을 보냄
# (어제 받은 카톡 링크를 클릭하면 어제 보고서가 그대로 보이도록)


def _archive_urls(date_str: str) -> tuple[str, str]:
    """그 날짜 영구 archive URL (full, share-inline).

    공유용은 인라인 강화 버전(-share-inline.html)으로 연결 —
    블로그·티스토리에 그대로 붙여넣기 가능한 self-contained 스타일.
    원본 -share.html도 배포하되 카톡 링크는 인라인 버전.
    """
    return (
        f"{PAGES_BASE}/archive/{date_str}.html",
        f"{PAGES_BASE}/archive/{date_str}-share-inline.html",
    )


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


# "현 기준금리 3.00%" / "현 기준금리 3.50~3.75%" 형태에서 현재 금리를 뽑는다.
# 범위로 적히면(미국 목표범위) 상단을 쓴다.
_CUR_RATE_RE = re.compile(r"현\s*기준금리\s*([0-9]+(?:\.[0-9]+)?)\s*(?:~\s*([0-9]+(?:\.[0-9]+)?))?\s*%")


def _cross_check_rate(const_val, outlook_text: str, label: str):
    """하드코딩 기준금리를 web_search 전망 텍스트와 교차검증.

    POLICY_RATES는 손으로 갱신하는 상수라 금통위 후 갱신을 잊으면 조용히 낡는다
    (실제 사고: 8/27 인상 후 6편이 2.50%로 발행). 전망 텍스트는 매일 새로 받아오므로
    둘이 어긋나면 전망 쪽을 믿고 보정한 뒤 경고를 남긴다.
    """
    if not outlook_text or not isinstance(const_val, (int, float)):
        return const_val
    m = _CUR_RATE_RE.search(outlook_text)
    if not m:
        return const_val
    found = float(m.group(2) or m.group(1))
    if not (0.0 <= found <= 10.0):          # 파싱 오류·환각 방어
        logger.warning("[rate] %s 전망에서 비정상 금리 %.2f%% 파싱 - 상수 유지", label, found)
        return const_val
    if abs(found - const_val) < 0.005:
        return const_val
    logger.error(
        "[rate] ★ %s 기준금리 불일치: 상수 %.2f%% vs 전망 %.2f%% - 전망값으로 보정합니다. "
        "fetch_indicators.py의 POLICY_RATES를 %.2f로 갱신하세요.",
        label, const_val, found, found,
    )
    return found


def _adapt_base_rates(ind_data: dict, outlook: dict) -> dict:
    """policy_rates + summarize의 policy_outlook → base_rates."""
    pr = ind_data.get("policy_rates", {})
    kr_val = pr.get("korea", {}).get("value")
    us_val = pr.get("us", {}).get("value")
    kr_val = _cross_check_rate(kr_val, (outlook or {}).get("korea", ""), "한국")
    us_val = _cross_check_rate(us_val, (outlook or {}).get("us", ""), "미국")
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


# 권유 투를 거르는 데 쓰는 표현들. 프롬프트에도 같은 목록이 있지만, 생성은
# 확률적이라 지시만으로는 새어나온다. 2026-11-06 5번(지분적립형 아파트)에서
# "주목할 만한 제도예요"·"공고문을 꼭 확인해 보세요"가 그대로 발행됐고,
# 사람 눈에 걸려서야 알았다.
#
# 둘로 나눠 둔 이유: 본문과 그룹톡 멘트의 사정이 다르다. 본문에서 "꼭
# 확인해"는 정책·상품을 권하는 말이라 걸러야 하지만, 그룹톡 멘트에서는
# 대표님이 직접 쓰는 한마디다. 2026-11-06 수정본 "엇갈린 반응을
# 낳았습니다ㅠ 꼭 확인해보세요!"는 대표님이 손으로 고쳐 넣은 문장이고,
# 한 목록으로 묶어두면 그게 매일 경고로 뜬다. 멘트의 안내형 과용은
# _lint_group_note가 빈도로 따로 본다.
_PUSHY_INVEST = [
    "주목할 만", "노려볼 만", "눈여겨볼", "관심 가져볼", "특히 주목",
    "게 유리", "이 유리", "게 좋아요", "이 현명", "게 현명",
    "이 기회", "놓치지 마", "서두르",
]
_PUSHY_GUIDE = [
    "꼭 확인해", "알아보세요", "신청해 보세요", "챙기세요",
]
_PUSHY = _PUSHY_INVEST + _PUSHY_GUIDE


# 그룹톡 멘트의 마무리가 "~보세요!" 한 형태로 굳는 걸 잡는다. 프롬프트에서
# 느낌표를 강제하고 마무리를 "안내형"으로 정의한 탓에, 발행 57편 중 43편이
# 거기로 수렴했다. 금지 범위가 "최근 3~4편"이라 읽어보세요·펼쳐보세요·
# 훑어보세요·살펴보세요를 돌려쓰면 규칙은 지켜지면서 독자에겐 같은 말이 됐다.
_NOTE_CLOSERS = [
    "읽어보세요", "훑어보세요", "펼쳐보세요", "살펴보세요", "확인해보세요",
    "확인해두세요", "참고하세요", "챙기세요", "정리해보세요", "봐 주세요",
    "잡아두세요", "읽어두세요", "점검해보세요", "봐주세요", "보세요",
]


# "급한 것부터 앞에 뒀습니다" 류. 어느 뉴스를 앞에 놨는지는 독자 일이 아니다.
# 2026-11-06에 대표님이 이 문장을 "왜 이런 일이 생기는지 같이 정리해봤습니다!"로
# 바꿨다. 편집 사정을 설명하던 자리에 독자의 질문이 들어간 것이다.
_NOTE_BACKSTAGE = [
    "앞에 뒀", "앞에 놨", "맨 앞에", "뒤로 미뤘", "순서를 바꿔", "순서를 바꿨",
    "먼저 담았", "먼저 뒀",
]


def _has_feeling(note: str) -> bool:
    """자모나 이모지로 감정이 표시됐는지 본다.

    문장으로 감정을 지어내는 것은 금지지만("저는 한참 들여다봤어요"), 자모
    한 개는 없던 일을 서술하지 않으면서 톤만 얹는다. 2026-11-06 수정본에서
    같은 "~보세요!"가 "ㅠ" 하나를 앞에 두느냐로 갈렸다. "낳았습니다ㅠ 꼭
    확인해보세요!"는 살고, "담았어요. 한번 읽어보세요!"는 지워졌다.
    """
    if any(j in note for j in ("ㅠ", "ㅜ", "ㅎㅎ", "ㅋㅋ", "ㅎ!", "ㅠㅠ")):
        return True
    return any(
        "\U0001F300" <= ch <= "\U0001FAFF" or "\u2600" <= ch <= "\u27BF"
        for ch in note
    )


def _ends_with_guide(note: str) -> str:
    """안내형 마무리로 끝나면 그 표현을 돌려준다."""
    tail = note.strip()[-24:]
    for bad in _NOTE_CLOSERS:
        if tail.endswith(bad) or tail.endswith(bad + "!") or tail.endswith(bad + "."):
            return bad
    return ""


def _lint_group_note(note: str, recent: list[str]) -> list[str]:
    """멘트의 마무리가 굳어가는지 본다. 막지는 않고 드러내기만 한다."""
    if not note:
        return []
    out = []
    # 안내형은 금지가 아니라 빈도 상한이다. 쓸 수는 있고 매일은 아니다.
    # 읽어보세요·펼쳐보세요·훑어보세요·살펴보세요를 돌려쓰면 규칙은 지켜지면서
    # 독자에게는 같은 문장이 된다. 최근 3편에 이미 있으면 걸린다.
    mine = _ends_with_guide(note)
    if mine:
        used = [r for r in recent[:3] if _ends_with_guide(r)]
        if used:
            out.append(f'"{mine}" - 안내형 마무리가 최근 3편에 이미 {len(used)}번 나왔다')
        # 맨손 안내형. 감정 신호 없이 사실 뒤에 붙으면 자동 발송 문구로 읽힌다.
        if not _has_feeling(note):
            out.append(f'"{mine}" - 자모(ㅠ·ㅎㅎ) 없이 붙은 안내형은 발송 안내문으로 읽힌다')
    # 편집 사정 설명. 독자가 궁금한 것으로 바꿔야 한다.
    for bad in _NOTE_BACKSTAGE:
        if bad in note:
            out.append(f'"{bad}" - 편집 사정 설명. 독자 질문("왜 이런 일이 생기는지")으로 바꿀 것')
            break
    # 합니다체를 마침표로 닫으면 공문처럼 읽힌다.
    body = note.strip()
    if body.endswith("습니다.") or body.endswith("합니다."):
        out.append('합니다체를 마침표로 닫았다 - 느낌표로 맺거나 해요체로 바꿀 것')
    # 자료 소개 투. 링크가 이미 같이 나가므로 매일 쓸 말이 아니다.
    # "뒀"만 보던 걸 "놨"까지 넓혔다. 2026-11-05 "차근차근 풀어놨어요!"가
    # 같은 투인데 빠져나갔다.
    for bad in ("정리해뒀", "담아뒀", "풀어뒀", "묶어뒀",
                "정리해놨", "담아놨", "풀어놨", "묶어놨"):
        if bad in note:
            out.append(f'"{bad}" - 자료 소개 투')
            break
    # 최근 멘트와 끝 어절이 같으면 형태가 굳은 것으로 본다.
    last = note.strip().split()[-1] if note.strip().split() else ""
    same = [r for r in recent[:5] if r.strip().split() and r.strip().split()[-1] == last]
    if last and same:
        out.append(f'최근 5편 중 {len(same)}편과 끝 어절이 같음 ("{last}")')
    # 마침표로 닫은 경우. 2026-11-06에 "다음 금통위가 11/26이에요."가
    # "11/26로 같이 알아둡시다!"로 고쳐졌다. 중립 사실을 마침표로 통보하면
    # 사람이 쓴 한마디가 아니라 안내 문구가 된다. 짧은 한마디("오늘은 좀 긴
    # 하루였네요.")는 마침표로 끝나도 되므로 막지 않고 한 번 보게만 한다.
    if body.endswith(".") and not body.endswith("습니다."):
        out.append('마침표로 닫았다 - 짧은 한마디가 아니면 느낌표로 맺을 것')
    # 자모도 매일 쓰면 그게 새 틱이 된다. 느낌표 때와 같은 실패다.
    # 종결부호 연속은 더 보지 않는다. 2026-11-06 수정본 4편이 모두 느낌표였고,
    # 섞는 자리는 종결부호가 아니라 자모라는 게 그때 정해졌다.
    if _has_feeling(note):
        same = [r for r in recent[:3] if _has_feeling(r)]
        if len(same) >= 3:
            out.append('최근 3편도 자모(ㅠ·ㅎㅎ)를 썼다 - 이것도 매일이면 틱이 된다')
    return out


def _lint_pushy(report_data: dict) -> list[tuple[str, str]]:
    """발행물 본문에서 권유 투를 찾아낸다.

    막지는 않는다. 톤 판단에는 오탐이 있고, 오탐 하나로 발행을 멈추면
    브리핑이 안 나가는 쪽이 더 큰 손해다. 대신 보이게 만든다.
    상품 블록(ladder·trigger)은 대상이 아니다. 거기는 권유가 제 일이다.
    """
    hits = []

    def scan(where: str, text) -> None:
        if not text:
            return
        if isinstance(text, (list, tuple)):
            for t in text:
                scan(where, t)
            return
        if not isinstance(text, str):
            return
        words = _PUSHY_INVEST if where == "group_note" else _PUSHY
        for bad in words:
            if bad in text:
                hits.append((where, bad))

    for i, card in enumerate(report_data.get("news_cards") or [], 1):
        scan(f"뉴스{i}.body", card.get("body"))
        scan(f"뉴스{i}.why", card.get("why_for_workers"))
    scan("insight", (report_data.get("insight") or {}).get("body")
         if isinstance(report_data.get("insight"), dict) else report_data.get("insight"))
    exp = report_data.get("explainer") or {}
    scan("explainer", exp.get("body") if isinstance(exp, dict) else exp)
    scan("group_note", report_data.get("group_note"))
    return hits


def _flag_kakao_failure(exc: Exception) -> None:
    """카톡 실패를 Actions 밖에서도 보이게 만든다.

    카톡은 best-effort라 실패해도 브리핑·그룹톡은 정상 발송된다. 그래서 예전엔
    성공한 실행 로그 속 warning 한 줄로 끝났고, 아무도 안 봤다. 2026-10-20
    토큰 교체로 10/21·10/22 이틀이 조용히 묵음이 됐는데 로그에는 매일
    "⚠️ 카카오톡 알림 실패"가 찍혀 있었다.

    annotation은 눈에 띄게 해주고, kakao_failed 출력은 워크플로가 **publ
    발송을 모두 마친 뒤에** job을 실패시켜 알림 메일을 띄우는 데 쓴다.
    구독자 발송을 막지 않으면서 사람에게 닿는 유일한 경로다.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    print(f"::error title=카카오톡 알림 실패::{exc}", flush=True)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("kakao_failed=true\n")


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
    try:
        episode = fetch_rss.fetch_latest_episode()
    except fetch_rss.NoRegularEpisode as exc:
        # 연휴 등으로 정규 방송이 없는 날은 주말과 똑같이 발행하지 않는다.
        # 오류가 아니므로 정상 종료한다 (대표님 방침 2026-09-24).
        logger.info("=== %s 정규 방송분 없음 - 발행하지 않습니다 ===", date_str)
        logger.info("    사유: %s", exc)
        return None
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
        "group_note": summary.get("group_note", ""),
        "generated_at": now.strftime("%Y-%m-%d %H:%M KST"),
    }

    # 4-0) 상품 블록. 사다리는 매일, 기사 트리거는 조건이 맞는 날만.
    report_data["ladder"] = products.ladder_items(date_str)
    report_data["trigger"] = products.pick_trigger(
        report_data.get("news_cards") or [], date_str
    )

    # 4-1) 권유 투 점검. 발행을 막지는 않고 드러내기만 한다.
    note_issues = _lint_group_note(
        report_data.get("group_note") or "",
        [n for _, n in sm.recent_group_notes(limit=5, exclude_date=date_str)],
    )
    if note_issues:
        logger.warning("  ⚠️  그룹톡 멘트 마무리 점검:")
        for msg in note_issues:
            logger.warning("       %s", msg)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::warning title=그룹톡 멘트 마무리::{' / '.join(note_issues)}", flush=True)

    pushy = _lint_pushy(report_data)
    if pushy:
        logger.warning("  ⚠️  권유 투로 읽힐 표현 %d건:", len(pushy))
        for where, bad in pushy:
            logger.warning("       %s - \"%s\"", where, bad)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            detail = ", ".join(f"{w}:{b}" for w, b in pushy)
            print(f"::warning title=권유 투 표현 {len(pushy)}건::{detail}", flush=True)
    if save_intermediate:
        (out_dir / "report_data.json").write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 4a) 그룹톡 멘트를 docs/로 저장.
    # publ-post.yml은 daily.yml과 별개 실행 = 별도 checkout이라, out_dir의 중간 JSON은
    # 보이지 않는다. docs/는 git commit 대상이므로 여기 두면 다음 워크플로우가 읽는다.
    group_note = (summary.get("group_note") or "").strip()
    meta_path = ROOT / "docs" / "archive" / f"{date_str}-meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    _trig = report_data.get("trigger")
    meta_path.write_text(
        json.dumps({
            "date": date_str,
            "group_note": group_note,
            # 다음 발행이 주간 상한을 세려면 이 기록이 있어야 한다.
            "trigger": ({"p": _trig["code"], "news_index": _trig["news_index"]}
                        if _trig else None),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if group_note:
        logger.info("  ✓ [meta] 그룹톡 멘트 %d자: %s", len(group_note), meta_path.name)
    else:
        logger.warning("  ! group_note 비어있음 - 그룹톡은 기본 문구만 발송됨")

    share_html: str | None = None
    for mode in ("full", "share"):
        html = render_report.render(report_data, mode=mode)
        if mode == "share":
            share_html = html
        paths = render_report.save(
            html, date_str, mode=mode, also_index=(mode == "full")
        )
        for label, p in paths.items():
            try:
                rel = p.relative_to(ROOT)
            except ValueError:
                rel = p
            logger.info("  ✓ [%s] %s: %s", mode, label, rel)

    # 4b) share.html → 인라인 강화 버전 저장 (블로그·티스토리 붙여넣기용, 카톡 링크 대상)
    if share_html:
        try:
            inline_html = build_inline.build_inline(
                share_html, base_url=f"{PAGES_BASE}/"
            )
            inline_path = ROOT / "docs" / "archive" / f"{date_str}-share-inline.html"
            inline_path.write_text(inline_html, encoding="utf-8")
            logger.info(
                "  ✓ [share-inline] %s (%d KB)",
                inline_path.relative_to(ROOT),
                len(inline_html) // 1024,
            )
        except Exception as exc:
            logger.warning("  ⚠️  인라인 변환 실패 (원본 share는 정상): %s", exc)

    # 5) git
    if push or dry_run_push:
        logger.info("[git] 커밋·푸시...")
        _git_commit_push(ROOT, date_str, dry_run=dry_run_push)

    # 6) 카카오톡 알림 (best-effort) — 영구 archive URL 사용
    if notify:
        # 공개 Pages 폐쇄(2026-08-19) - 카톡도 서명 만료 링크로 통일
        try:
            from pipeline.signed_link import signed_brief_url
        except ImportError:
            from signed_link import signed_brief_url
        # 링크는 공유본(share-inline) 하나만. 예전엔 "내 보고서"·"공유용" 두 줄을
        # 보냈지만 둘 다 같은 app 코드 k(=share-inline)라 내용이 동일했고,
        # 112자 URL이 두 번 들어가 카톡 200자 제한을 넘겨 뒤쪽이 잘렸다 (8/20 사고).
        share_url = signed_brief_url("k", date_str)
        logger.info("[kakao] 알림 전송 중 (서명 링크): %s", share_url)
        try:
            notify_kakao.notify_from_report(
                report_data, share_url, share_url=None
            )
            logger.info("  ✓ 카카오톡 알림 전송 완료")
        except Exception as exc:
            logger.warning("  ⚠️  카카오톡 알림 실패 (보고서 자체는 정상): %s", exc)
            _flag_kakao_failure(exc)

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
