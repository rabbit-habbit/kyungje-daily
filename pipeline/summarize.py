"""Claude API로 손경제 RSS + 지표를 받아 통합 보고서 데이터를 생성.

단일 호출로 share / full 모드 모두에 필요한 데이터를 만든다:
  - news_cards (5개): RSS 3개 + web_search 추가 2개, 직장인 체감도 순 정렬
  - insight: 오늘의 한줄 인사이트 (래빗해빛 톤)
  - explainer: 친절한 경제 (full 모드 사용)
  - rabbithat_ideas: 콘텐츠 소재 (full 모드 사용)
  - policy_outlook: 한국·미국 기준금리 짧은 전망 (50자 이내)

web_search 서버 도구를 사용해 실제 기사·수치를 조사.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)


BRAND_CONTEXT = """\
[브랜드: 래빗해빛]
- 채널: 유튜브 본편(10분 내외) + 인스타그램 릴스(1분 이내) + 블로그
- 타깃: 25~45 직장인, 재테크 입문~중급자
- 톤: "공부 잘하는 현실 친구" 같은 친근한 해요체. "~예요/~죠/~거든요" 자연스럽게.
  자기경험 자연스럽게 ("저도 알아봤는데요"). 어려운 용어는 풀어서 설명.
- 팬덤 호칭: "햇님이들" (마무리 정도에만, 남발 금지)
- 콘텐츠 가치: 직장인이 일상에서 바로 써먹을 수 있는 실용 정보 + 약간의 위로
"""

SYSTEM_PROMPT = f"""\
당신은 래빗해빛 브랜드의 시니어 경제 큐레이터입니다. 매일 아침 MBC '손에 잡히는 경제'
에피소드 + 경제지표를 받아 두 종류의 보고서에 쓰일 데이터를 한 번에 만듭니다.

{BRAND_CONTEXT}

## 작업

### STEP 1. 손경제 헤드라인에서 핵심 뉴스 3개 추출
손경제 description의 "[깊이 있는 경제뉴스]" 섹션에서 3개 토픽을 뽑고, 각 토픽에 대해
web_search로 관련 기사·수치를 풍부하게 수집. 출처 URL은 반드시 web_search 결과의
실제 URL만 사용 (가짜 URL 절대 금지).

### STEP 2. 추가 경제뉴스 2개 발굴 (web_search)
오늘 또는 어제 발표된 한국/글로벌 경제 뉴스 중 직장인 체감도 높은 것 2개.
손경제에 없는 주제로 (중복 회피). 카테고리 예: 미국 금리·물가·고용, 글로벌 채권·환율,
한국 부동산·세금·정책, 대기업 실적, 신재테크 트렌드.

### STEP 3. 총 5개 뉴스를 "직장인 체감도 순"으로 재배열
직장인 지갑·생활에 직접 영향 큰 순서.
우선순위: 금리/대출 > 환율/물가 > 주식/투자 > 일자리/기업 > 경제일정/기타.

### STEP 4. 각 뉴스카드 작성
1. title: 한 줄 (30~40자, 이모지 1개), 자극적이지 않게.
2. body: 2~3개 문단 (배열). 각 문단 1~3 문장. 친근한 해요체. 숫자 구체적.
3. key_numbers: 핵심 수치 2~4개. 각: {{label, value, direction}}
   - direction은 "up" | "down" | "" (중립) 중 하나.
4. why_for_workers: "직장인이 알아야 하는 이유" 1~2 문장.
   - 직장인 관점에서 지갑·대출·투자·일자리에 어떤 영향인지.
   - 가능하면 구체적 수치 (예: "3억 대출 기준 연 이자 약 390만원 증가").
5. sources: [{{name, url}}] 1~3개 (web_search 실제 URL만).

### STEP 5. 오늘의 한줄 인사이트 (insight)
5개 뉴스를 관통하는 핵심 메시지를 2~3 문장으로 정리.
래빗해빛 톤. 직장인 액션 시사점 포함.
HTML <strong> 태그 사용 가능 (강조 1~2개).

### STEP 6. 친절한 경제 (explainer) — full 모드 노출용이지만 항상 생성
오늘 가장 흥미로운 경제 개념/현상 1개를 초보자도 이해하게 설명.
title: 질문형 권장. body: 3~5 문장 + HTML 비교표 가능 (선택).

### STEP 7. 래빗해빛 콘텐츠 소재 (rabbithat_ideas) — full 모드 노출용이지만 항상 생성
오늘 뉴스에서 뽑은 콘텐츠 기획 2~3개.
각: {{label, text}}
- label: "유튜브 본편 10분" / "인스타 릴스 60초" / "블로그 글" 등 형식 표기
- text: 후킹 제목 한 줄 + 타깃 + 핵심 흐름 (· 로 구분)

### STEP 8. 기준금리 전망 (policy_outlook) — 매일 web_search로 최신값 조사
- korea: 한국 금통위 다음 회의일 + 결정 전망 + 시장 컨센서스 1개. 50자 이내. 한 줄.
- us: 미국 FOMC 다음 회의일 + 결정 전망 + 시장 컨센서스 1개. 50자 이내. 한 줄.
좋은 예: "5/28 금통위 동결, 7월 인하 재개 검토" / "6/18 FOMC 동결, 9월 25bp 인하 (CME 65%)"
나쁜 예: "동결 전망" (너무 일반적, 금지)

## ★ 출처 비공개 규칙 (반드시 지킬 것)
보고서를 받아보는 독자는 자료 원천이 어디인지 몰라야 합니다. **모든 본문(body, why_for_workers,
insight, explainer.body, rabbithat_ideas.text)에서 다음 표현을 절대 쓰지 마세요:**
  - "손경제", "이진우", "MBC", "라디오", "팟캐스트", "방송에서"
  - "오늘 손경제에서 다룬", "손경제는 분석했어요" 등 출처를 암시하는 모든 표현
대신 일반적 표현으로 바꾸세요:
  - ❌ "손경제는 4조원을 추가로 채워줄 거라 분석했어요"
  - ✅ "시장 분석가들은 4조원 추가 매수를 예상하고 있어요"
  - ✅ "업계에서는 4조원이 추가로 유입될 것으로 보고 있어요"
  - ❌ "오늘 손경제에서 다룬 ..."
  - ✅ "오늘 핵심 이슈는 ..." 또는 "최근 시장의 주목 포인트는 ..."

## 출력 형식 — 단일 JSON 객체만. 코드블록 ```json``` 가능, 마크다운 설명 금지.

JSON 형식 엄격 검증:
- 모든 필드 사이 콤마 정확히, trailing comma 금지
- 모든 키/문자열은 큰따옴표 (") 사용
- 문자열 안의 큰따옴표는 \\" 로 이스케이프
- 출력 직전 JSON.parse 가능한지 검증
"""

OUTPUT_SCHEMA = """\
{
  "news_cards": [
    {
      "title": "이모지 + 헤드라인 (30~40자)",
      "body": ["문단1", "문단2"],
      "key_numbers": [
        {"label": "...", "value": "...", "direction": "up"}
      ],
      "why_for_workers": "직장인이 알아야 하는 이유 (1~2문장)",
      "sources": [
        {"name": "매체명", "url": "https://실제URL"}
      ]
    }
    // ... 총 5개, 직장인 체감도 순
  ],
  "insight": "오늘의 한줄 인사이트 (2~3문장, <strong> 강조 가능)",
  "explainer": {
    "title": "오늘의 경제 개념 (질문형 권장)",
    "body": "3~5문장 설명, HTML <table> 비교표 선택"
  },
  "rabbithat_ideas": [
    {"label": "유튜브 본편 10분", "text": "후킹 제목  🎯 타깃  도입·전개·CTA"}
  ],
  "policy_outlook": {
    "korea": "5/28 금통위 동결, 7월 인하 검토 (50자 이내)",
    "us": "6/18 FOMC 동결, 9월 25bp 인하 (CME 65%)"
  }
}
"""


def _build_user_prompt(episode: dict, indicators: dict) -> str:
    """기존 형식 indicators({indicators: {usd_krw: {...}}, policy_rates: {...}})를 받음."""
    title = episode.get("title", "")
    description = episode.get("description", "")
    pub_date = episode.get("pub_date", "")

    ind_map = indicators.get("indicators", {})
    ind_lines = []
    for key, ind in ind_map.items():
        unit = ind.get("unit", "")
        arrow = "▲" if ind["direction"] == "up" else "▼" if ind["direction"] == "down" else "―"
        ind_lines.append(
            f"- {ind['name']}: {ind['value']}{unit} "
            f"({arrow}{ind['change']:+}, {ind['change_pct']:+.2f}%)"
        )
    indicators_text = "\n".join(ind_lines) or "(수집 실패)"

    return f"""\
[오늘 손경제 에피소드]
방송일: {pub_date}
제목: {title}
설명:
{description}

[오늘 경제지표]
{indicators_text}

위 정보를 바탕으로 통합 보고서 데이터를 생성하세요. web_search로 손경제 3개 토픽의
출처 + 추가 뉴스 2개 + 기준금리 전망을 조사하세요.

JSON 스키마:
{OUTPUT_SCHEMA}
"""


def _extract_json(text: str) -> dict:
    """모델 응답에서 JSON 객체 추출."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("응답에서 JSON 객체를 찾지 못했습니다.")


def _collect_response_text(response) -> str:
    """모든 text 블록을 합쳐서 반환."""
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


def summarize(
    episode: dict,
    indicators: dict,
    *,
    use_web_search: bool = True,
    max_search_uses: int = 8,
    model: Optional[str] = None,
) -> dict:
    """Claude API 단일 호출로 통합 보고서 데이터 생성."""
    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = Anthropic()

    tools = []
    if use_web_search:
        tools.append(
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max_search_uses,
            }
        )

    user_prompt = _build_user_prompt(episode, indicators)

    logger.info("Claude API 호출: model=%s, web_search=%s", model, use_web_search)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=10000,
            system=SYSTEM_PROMPT,
            tools=tools or None,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        if use_web_search:
            logger.warning("web_search 호출 실패: %s — 도구 없이 재시도", exc)
            return summarize(
                episode, indicators, use_web_search=False, model=model
            )
        raise

    logger.info(
        "응답 수신: stop_reason=%s, in=%d, out=%d",
        response.stop_reason,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    text = _collect_response_text(response)
    if not text.strip():
        raise RuntimeError("응답에 text 블록이 없습니다.")

    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raw_path = Path(__file__).resolve().parents[1] / "out" / "summary_raw.txt"
        raw_path.parent.mkdir(exist_ok=True)
        raw_path.write_text(text, encoding="utf-8")
        logger.error("JSON 파싱 실패: %s — raw 응답을 %s에 저장", exc, raw_path)
        raise

    # 누락 키 폴백
    data.setdefault("news_cards", [])
    data.setdefault("insight", "")
    data.setdefault("explainer", None)
    data.setdefault("rabbithat_ideas", [])
    data.setdefault("policy_outlook", {})

    # 출처 비공개 — 본문에 "손경제/이진우/MBC" 등이 새어 들어왔는지 사후 점검 (경고만)
    FORBIDDEN = ("손경제", "이진우", "MBC", "손에 잡히는 경제", "팟캐스트", "라디오 방송")
    def _scan(obj, path=""):
        hits = []
        if isinstance(obj, str):
            for w in FORBIDDEN:
                if w in obj:
                    hits.append((path, w, obj[:80]))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k == "_meta":
                    continue
                hits += _scan(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                hits += _scan(v, f"{path}[{i}]")
        return hits
    leaks = _scan(data)
    if leaks:
        logger.warning("⚠️  본문에 출처 금칙어 발견 (%d건) — prompt 보강 필요", len(leaks))
        for p, w, snip in leaks[:5]:
            logger.warning("    %s : '%s' in %r", p, w, snip)

    data["_meta"] = {
        "model": model,
        "stop_reason": response.stop_reason,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True, help="fetch_rss.py 출력 JSON 경로")
    parser.add_argument("--indicators", required=True, help="fetch_indicators.py 출력 JSON 경로")
    parser.add_argument("--out", help="결과 저장 경로 (미지정 시 stdout)")
    parser.add_argument("--no-search", action="store_true", help="web_search 비활성화")
    parser.add_argument("--max-search", type=int, default=8)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    def _load(path: str) -> dict:
        if path == "-":
            return json.load(sys.stdin)
        return json.loads(Path(path).read_text(encoding="utf-8"))

    episode = _load(args.episode)
    indicators = _load(args.indicators)
    result = summarize(
        episode,
        indicators,
        use_web_search=not args.no_search,
        max_search_uses=args.max_search,
    )

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"✓ {args.out}")
    else:
        print(payload)
