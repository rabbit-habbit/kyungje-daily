"""Jinja2로 손경제 Daily Brief HTML 보고서를 렌더링.

입력: report_data dict (run.py가 조립)
출력: docs/latest.html + docs/archive/{date}.html
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates"
DOCS_DIR = ROOT / "docs"


def _fmt_value(value, unit: str) -> str:
    """현재 값 포맷팅."""
    if value is None:
        return "—"
    if unit == "원":
        return f"{value:,.2f}원"
    if unit == "p":
        return f"{value:,.2f}"
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "$/배럴":
        return f"${value:,.2f}"
    if unit == "원/g":
        return f"{value:,.0f}원/g"
    return f"{value:,}"


def _fmt_abs(value, unit: str) -> str:
    """변동 절댓값 + 단위."""
    return _fmt_value(abs(value), unit)


def _fmt_pct(value) -> str:
    """% 표기 — 음수는 자연스럽게 부호 유지, 양수는 +붙임."""
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["fmt_value"] = _fmt_value
    env.filters["fmt_abs"] = _fmt_abs
    env.filters["fmt_pct"] = _fmt_pct
    return env


def render(context: dict, mode: str = "full") -> str:
    """report.html.j2 → HTML 문자열.

    mode='full'  : 대표님용 — 뉴스/지표/친절한경제/래빗해빛 콘텐츠 소재
    mode='share' : 공유용 (햇님이들) — 래빗해빛 콘텐츠 소재 제외, 푸터 브랜딩
    """
    env = _make_env()
    tmpl = env.get_template("report.html.j2")
    return tmpl.render(mode=mode, **context)


def save(
    html: str, date_str: str, mode: str = "full", also_index: bool = False
) -> dict[str, Path]:
    """모드별 파일 경로에 저장.

    full  → docs/latest.html, docs/archive/{date}.html (+ optional docs/index.html)
    share → docs/share.html,  docs/archive/{date}-share.html
    """
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "archive").mkdir(parents=True, exist_ok=True)
    if mode == "share":
        latest = DOCS_DIR / "share.html"
        archive = DOCS_DIR / "archive" / f"{date_str}-share.html"
    else:
        latest = DOCS_DIR / "latest.html"
        archive = DOCS_DIR / "archive" / f"{date_str}.html"
    latest.write_text(html, encoding="utf-8")
    archive.write_text(html, encoding="utf-8")
    out = {"latest": latest, "archive": archive}
    # index.html은 full 버전(대표님용)이 메인
    if also_index and mode == "full":
        index = DOCS_DIR / "index.html"
        index.write_text(html, encoding="utf-8")
        out["index"] = index
    return out


def mock_data() -> dict:
    """렌더링 테스트용 더미 데이터."""
    return {
        "date": "2026-05-19",
        "date_kr": "2026년 5월 19일 화요일",
        "episode": {
            "title": "[손경제] 5/19(화) 소아 필수의약품 | 삼성전자 2차 사후조정 | 중국 CXMT 실적 | 국민연금법 개편",
            "audio_url": "https://podcastfile.imbc.com/cgi-bin/podcast.fcgi/podcast/economy/ECONOMY_20260519.mp3",
        },
        "indicators": {
            "domestic": [
                {"name": "원/달러 환율", "value": 1506.58, "change": 9.43, "change_pct": 0.63, "unit": "원", "direction": "up"},
                {"name": "코스피", "value": 7271.66, "change": -244.38, "change_pct": -3.25, "unit": "p", "direction": "down"},
                {"name": "국고채 10년", "value": 2.60, "change": 0.40, "change_pct": 18.18, "unit": "%", "direction": "up"},
            ],
            "world": [
                {"name": "S&P 500", "value": 7403.05, "change": -5.45, "change_pct": -0.07, "unit": "p", "direction": "down"},
                {"name": "다우존스", "value": 49686.12, "change": 159.95, "change_pct": 0.32, "unit": "p", "direction": "up"},
                {"name": "WTI 원유", "value": 103.77, "change": -4.89, "change_pct": -4.50, "unit": "$/배럴", "direction": "down"},
                {"name": "금 (1g 한화)", "value": 220265, "change": -247, "change_pct": -0.11, "unit": "원/g", "direction": "down"},
            ],
        },
        "policy_rates": {
            "korea": {"name": "한국 기준금리", "value": 2.50, "outlook": "동결 전망"},
            "us": {"name": "미국 기준금리", "value": 3.75, "outlook": "인하 가능성"},
        },
        "news_cards": [
            {
                "title": "💊 소아 필수의약품 반복 품절 — 진료 대란 우려",
                "summary": "수익성이 낮은 소아용 항생제·해열제가 반복적으로 품절되며 진료 현장에 비상이 걸렸어요. 약값이 너무 싸서 제약사가 만들지 않는 구조적 문제예요.",
                "why_it_matters": "내 아이 약이 약국에서 사라질 수 있다는 신호예요. 단가 보전 정책이 없으면 공급 차질은 반복될 가능성이 크죠.",
                "key_points": [
                    "대표 품목: 소아용 시럽 항생제, 해열제",
                    "원인: 약가가 원가에 못 미쳐 제약사 손실",
                    "대안: 정부 직접 가격 보전 또는 의약품 공공 생산 확대 논의",
                ],
                "sources": [
                    {"title": "연합뉴스", "url": "https://example.com/1"},
                    {"title": "메디게이트", "url": "https://example.com/2"},
                ],
            },
            {
                "title": "🏭 삼성전자 노사 2차 사후조정 — 합의점 찾을까",
                "summary": "삼성전자 노사가 2차 사후조정에 들어갔어요. 한은은 총파업 시 경제성장률이 0.5%p 하락할 수 있다고 분석했습니다.",
                "why_it_matters": "삼성전자 한 회사의 분쟁이 GDP를 흔드는 수준이라는 점에서, 코스피·환율도 함께 출렁일 가능성이 있어요.",
                "key_points": [
                    "한은 분석: 총파업 시 성장률 0.5%p 하락",
                    "노조 요구: 임금 인상 + 사후조정 절차 개선",
                    "시장 영향: 외국인 매도세 가능성",
                ],
                "sources": [{"title": "한국경제", "url": "https://example.com/3"}],
            },
        ],
        "friendly_economics": {
            "topic": "기준금리와 국고채 yield는 어떻게 다를까?",
            "explanation": "기준금리는 한국은행이 정하는 단기 금리이고, 국고채 yield는 시장에서 매일 결정되는 중장기 금리예요. 시장 기대가 바뀌면 yield는 기준금리와 따로 움직일 수 있어요.",
            "comparison_table": {
                "headers": ["항목", "기준금리", "10년 국고채 yield"],
                "rows": [
                    ["결정 주체", "한국은행 금통위", "채권 시장 참여자들"],
                    ["변동성", "분기 1회 정도, 천천히", "매일 변동"],
                    ["의미", "중앙은행의 통화 기조", "시장이 보는 미래 금리·성장 기대"],
                    ["현재", "2.50%", "2.60%"],
                ],
            },
        },
        "rabbithat_ideas": [
            {
                "format": "유튜브 본편 10분",
                "hook": "왜 소아 감기약은 늘 품절일까? 약값 구조의 비밀",
                "target_audience": "30~40대 직장인 부모",
                "outline": [
                    "도입: 약국 5곳 돌아도 약이 없는 실제 경험담",
                    "구조: 원가 < 약가 → 제약사가 만들수록 손해",
                    "정책: 정부 단가 보전 vs 공공 생산 비교",
                    "마무리: 햇님이들의 우리 동네 약국 상황 댓글로",
                ],
            },
            {
                "format": "인스타 릴스 60초",
                "hook": "기준금리 2.50%인데 채권 금리는 왜 2.60%? 30초 정리",
                "target_audience": "25~35 재테크 입문자",
                "outline": [
                    "후킹: '금리가 두 개라고요?'",
                    "정의: 단기(중앙은행) vs 장기(시장)",
                    "예시: 대출 vs 예금 vs 채권",
                    "CTA: 댓글로 추가 질문 받기",
                ],
            },
        ],
        "generated_at": "2026-05-19 17:35 KST",
    }


def _load_input(input_arg: Optional[str]) -> dict:
    if input_arg is None or input_arg == "-":
        return json.load(sys.stdin)
    path = Path(input_arg)
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="손경제 Daily Brief 렌더러")
    parser.add_argument("--input", help="JSON 입력 경로 (또는 '-'로 stdin). 미지정+--mock 가능")
    parser.add_argument("--mock", action="store_true", help="내장 mock 데이터로 렌더")
    parser.add_argument("--also-index", action="store_true", help="docs/index.html도 같이 갱신 (full만)")
    parser.add_argument("--mode", choices=["full", "share", "both"], default="both", help="렌더 모드")
    args = parser.parse_args()

    if args.mock:
        data = mock_data()
    else:
        data = _load_input(args.input)

    modes = ["full", "share"] if args.mode == "both" else [args.mode]
    for m in modes:
        html = render(data, mode=m)
        paths = save(html, data["date"], mode=m, also_index=args.also_index)
        for label, p in paths.items():
            print(f"✓ [{m}] {label}: {p}")
