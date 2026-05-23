"""Jinja2로 손경제 Daily Brief HTML 보고서를 렌더링.

데이터 모델 (new spec):
    {
        "date": "2026-05-23",
        "date_kr": "2026년 5월 23일 토요일",
        "headline": "...",                          # full 모드 헤더 (옵션)
        "episode": {"title": "...", "description": "..."},  # full 모드만 표시
        "indicators": {
            "domestic": [{"label", "display", "change_display", "direction"}, ...],
            "global":   [{"label", "display", "change_display", "direction"}, ...],
        },
        "base_rates": {
            "kr": "2.50%", "us": "3.75%", "spread": "-1.25%p",
            "kr_outlook": "...", "us_outlook": "...",
        },
        "news_cards": [
            {
                "title": "...",
                "body": ["문단1", "문단2"],
                "key_numbers": [{"label", "value", "direction"}, ...],
                "why_for_workers": "...",
                "sources": [{"name", "url"}, ...],
                "tags": [{"label", "color"}, ...],   # optional, full 모드
            },
            ...  # 보통 5개
        ],
        "insight": "<strong>html</strong> 가능한 텍스트",
        "explainer": {"title": "...", "body": "html"},   # full 모드만
        "rabbithat_ideas": [{"label", "text"}, ...],     # full 모드만
        "generated_at": "..."
    }

run.py가 위 형식을 직접 만들어 render()에 전달합니다.
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


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(context: dict, mode: str = "full") -> str:
    """report.html.j2 → HTML 문자열.

    mode='full'  : 뉴스+insight + explainer + rabbithat_ideas + episode
    mode='share' : 뉴스+insight만
    """
    env = _make_env()
    tmpl = env.get_template("report.html.j2")
    return tmpl.render(mode=mode, **context)


def save(
    html: str, date_str: str, mode: str = "full", also_index: bool = False
) -> dict[str, Path]:
    """모드별 파일 경로에 저장."""
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
    if also_index and mode == "full":
        index = DOCS_DIR / "index.html"
        index.write_text(html, encoding="utf-8")
        out["index"] = index
    return out


# ── Mock 데이터 (new spec 그대로) ─────────────────────────────────


def mock_data() -> dict:
    return {
        "date": "2026-05-23",
        "date_kr": "2026년 5월 23일 토요일",
        "headline": "환율 1,507원 돌파 · 한·미 금리차 -1.25%p · CXMT 메모리 위협",
        "episode": {
            "title": "[손경제] 5/23(토) 소아 필수의약품 | 삼성전자 사후조정 | 중국 CXMT",
            "description": "오늘 손경제 에피소드 요약 텍스트가 들어가는 자리입니다.",
        },
        "indicators": {
            "domestic": [
                {"label": "환율 (KRW/USD)", "display": "1,506.58", "change_display": "▲ 9.43 (+0.63%)", "direction": "up"},
                {"label": "코스피",           "display": "7,271.66", "change_display": "▼ 244.38 (-3.25%)", "direction": "down"},
                {"label": "국고채 10년",     "display": "4.13%",     "change_display": "▼ 0.050%p",       "direction": "down"},
            ],
            "global": [
                {"label": "S&P 500", "display": "7,403.05",  "change_display": "▼ 5.45 (-0.07%)",    "direction": "down"},
                {"label": "다우",     "display": "49,686.12", "change_display": "▲ 159.95 (+0.32%)",  "direction": "up"},
                {"label": "WTI",     "display": "$103.77",   "change_display": "▼ $4.89 (-4.50%)",   "direction": "down"},
                {"label": "금/g",     "display": "220,265원", "change_display": "▼ 1,881원 (-0.85%)",  "direction": "down"},
            ],
        },
        "base_rates": {
            "kr": "2.50%",
            "us": "3.75%",
            "spread": "-1.25%p",
            "kr_outlook": "5/28 금통위 동결, 7월 인하 재개 검토",
            "us_outlook": "6/18 FOMC 동결, 9월 25bp 인하 (CME 65%)",
        },
        "news_cards": [
            {
                "title": "🏦 한·미 금리차 -1.25%p 확대 — 환율 1,507원 돌파",
                "body": [
                    "원/달러 환율이 1,506원을 넘어서며 외환시장에 긴장이 흐르고 있어요. 한·미 금리차가 -1.25%p로 벌어진 게 직접 원인이에요.",
                    "한국은행은 5/28 금통위 동결을 시사했지만, 시장은 환율 안정을 위해 인하 속도를 늦출 가능성을 가격에 반영하고 있어요.",
                ],
                "key_numbers": [
                    {"label": "환율 (KRW/USD)", "value": "1,506.58", "direction": "up"},
                    {"label": "한·미 금리차",    "value": "-1.25%p",   "direction": "down"},
                    {"label": "전일 대비",        "value": "+9.43원",   "direction": "up"},
                ],
                "why_for_workers": "달러 예금·미국 ETF 평가액은 단기 호재예요. 다만 수입물가가 따라 오르면서 휘발유·항공권·해외직구 비용이 6~8주 시차로 오를 수 있어 가계 지출 점검이 필요해요.",
                "sources": [
                    {"name": "연합인포맥스", "url": "https://example.com/fx"},
                    {"name": "한국경제",     "url": "https://example.com/rate"},
                ],
            },
            {
                "title": "💊 소아 필수의약품 반복 품절 — 7월 진료 대란 우려",
                "body": [
                    "수익성이 낮은 소아용 항생제·해열제가 다시 품절돼 진료 현장에 비상이에요. 약값이 원가에 못 미쳐 제약사가 만들지 않는 구조적 문제예요.",
                    "전국 소아청소년병원의 71%가 올여름 이전에 마비를 경고했어요.",
                ],
                "key_numbers": [
                    {"label": "위기 병원 비율",   "value": "71%",  "direction": "up"},
                    {"label": "단기 공급부족 품목", "value": "12개", "direction": "up"},
                ],
                "why_for_workers": "유아가 있는 직장인은 약국 재고를 가족 단톡에 미리 공유해두면 좋아요. 정부 가격 보전이 없으면 매년 반복될 구조라 대비가 필요해요.",
                "sources": [
                    {"name": "아시아경제", "url": "https://example.com/meds1"},
                    {"name": "메디게이트", "url": "https://example.com/meds2"},
                ],
            },
            {
                "title": "🏭 삼성전자 2차 사후조정 — 한은 \"총파업 시 GDP -0.5%p\"",
                "body": [
                    "삼성전자 노사가 2차 사후조정에 들어갔어요. 핵심 쟁점은 성과급 산정 공식의 단체협약 명시 여부예요.",
                    "한국은행은 총파업 시 경제성장률이 0.5%p 떨어질 수 있다고 분석했어요.",
                ],
                "key_numbers": [
                    {"label": "총파업 시 GDP 하락", "value": "-0.5%p", "direction": "down"},
                ],
                "why_for_workers": "삼성·SK 직접 보유자는 변동성 주의. 코스피·환율도 연쇄 흔들릴 수 있어 ETF·펀드 비중도 점검할 시점이에요.",
                "sources": [{"name": "파이낸셜뉴스", "url": "https://example.com/samsung"}],
            },
            {
                "title": "🇨🇳 중국 CXMT D램 매출 +719% — 한국 메모리 점유율 위협",
                "body": [
                    "중국 메모리 기업 CXMT의 1분기 매출이 전년 대비 약 8배 폭증했어요. 삼성·SK하이닉스 점유율을 빠르게 잠식 중이에요.",
                ],
                "key_numbers": [
                    {"label": "1분기 매출 증감", "value": "+719%", "direction": "up"},
                ],
                "why_for_workers": "반도체 ETF·종목 투자자라면 중국 메모리 굴기를 주시. 단기 수익보다 중장기 점유율 변화에 베팅 비중 점검 권장.",
                "sources": [{"name": "머니투데이", "url": "https://example.com/cxmt"}],
            },
            {
                "title": "🧓 6월부터 일 많이 해도 국민연금 안 깎인다",
                "body": [
                    "보건복지부가 노령연금 감액 제도를 폐지해요. 65세 이후 근로소득이 있어도 연금이 줄지 않게 됩니다.",
                ],
                "key_numbers": [
                    {"label": "적용 시점", "value": "2026-06", "direction": ""},
                    {"label": "예상 수혜자", "value": "약 12만명", "direction": "up"},
                ],
                "why_for_workers": "부모님이 은퇴 후에도 일하시는 경우 연금이 깎이지 않아요. 60~65세 시니어 직장인 본인도 직접 수혜.",
                "sources": [{"name": "보건복지부 보도자료", "url": "https://example.com/pension"}],
            },
        ],
        "insight": (
            "오늘은 <strong>환율과 금리차가 모든 자산을 움직이는 날</strong>이에요. "
            "달러 강세는 미국 자산 보유자에겐 호재지만, 수입물가가 6~8주 시차로 따라 오르거든요. "
            "햇님이들의 가계부에 환율 변동이 어떻게 스며드는지 한 번 점검해보면 좋겠어요."
        ),
        "explainer": {
            "title": "한·미 금리차가 환율을 흔드는 이유",
            "body": (
                "기준금리는 단순히 은행 예적금 금리만 정하는 게 아니에요. 국가 간 금리차이는 자금이 어디로 흐를지를 결정하는 가장 강력한 신호예요."
                "<table style='width:100%; margin-top:12px; border-collapse:collapse; font-size:13px;'>"
                "<thead><tr><th>금리차</th><th>자금 흐름</th><th>환율 영향</th></tr></thead>"
                "<tbody>"
                "<tr><td>한국 &gt; 미국</td><td>외국 자금 한국 유입</td><td>원화 강세</td></tr>"
                "<tr><td>한국 &lt; 미국 (현재)</td><td>한국 자금 미국 유출</td><td>원화 약세</td></tr>"
                "</tbody></table>"
            ),
        },
        "rabbithat_ideas": [
            {
                "label": "유튜브 본편 10분",
                "text": "왜 소아 감기약은 늘 품절일까? 약값 구조의 비밀  🎯 30~40대 직장인 부모  도입(약국 5곳 돈 경험) · 구조(원가<약가) · 정책 비교 · 마무리 CTA",
            },
            {
                "label": "인스타 릴스 60초",
                "text": "기준금리 2.5%인데 미국 3.75%? 30초 정리  🎯 25~35 재테크 입문자  후킹·정의·예시·CTA",
            },
        ],
        "generated_at": "2026-05-23 17:35 KST",
    }


def _load_input(input_arg: Optional[str]) -> dict:
    if input_arg is None or input_arg == "-":
        return json.load(sys.stdin)
    return json.loads(Path(input_arg).read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="손경제 Daily Brief 렌더러")
    parser.add_argument("--input", help="JSON 입력 경로 (또는 '-'로 stdin)")
    parser.add_argument("--mock", action="store_true", help="내장 mock 데이터로 렌더")
    parser.add_argument("--also-index", action="store_true", help="docs/index.html도 같이 갱신 (full만)")
    parser.add_argument(
        "--mode", choices=["full", "share", "both"], default="both", help="렌더 모드"
    )
    args = parser.parse_args()

    data = mock_data() if args.mock else _load_input(args.input)

    modes = ["full", "share"] if args.mode == "both" else [args.mode]
    for m in modes:
        html = render(data, mode=m)
        paths = save(html, data["date"], mode=m, also_index=args.also_index)
        for label, p in paths.items():
            print(f"✓ [{m}] {label}: {p}")
