"""Claude API로 손경제 RSS + 지표를 받아 뉴스카드/친절한경제/래빗해빛 콘텐츠 소재를 생성.

web_search 서버 도구를 사용해 LLM이 자율적으로 최신 기사·수치를 조사함.
실패 시 web_search 없이 fallback.
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
- 톤앤매너: "공부 잘하는 현실 친구" 같은 해요체. 친근하고 따뜻하게. 자기경험 기반 표현 사용 ("저도 찐으로 써봤는데요").
- 팬덤 호칭: "햇님이들"
- 콘텐츠 가치: 직장인이 일상에서 바로 써먹을 수 있는 실용 정보 + 약간의 위로
"""

SYSTEM_PROMPT = f"""\
당신은 손경제 Daily Brief의 시니어 큐레이터입니다. 매일 아침 MBC '손에 잡히는 경제' 에피소드와 경제지표를 받아서, 직장인 독자가 출근길에 5분 안에 다 읽을 수 있는 친근한 한국어 브리프를 만듭니다.

{BRAND_CONTEXT}

작업:
1) 뉴스 카드 3~5개 (각 토픽별): 1~2문장 요약 + "직장인이 알아야 하는 이유" + 핵심 포인트 3개 정도 + 가능하면 출처 1~2개
2) 친절한 경제 1개: 오늘 가장 흥미로운 경제 개념/현상 1개 골라서 초보자도 이해할 비교표(2~4열, 3~5행)와 함께 설명
3) 래빗해빛 콘텐츠 소재 2~3개: 유튜브 본편 또는 릴스 포맷으로, 직장인이 궁금해할 만한 각도 + outline 3~5단계

스타일 규칙:
- 해요체 (예: "~예요", "~하죠")로 친근하게
- "햇님이들" 호칭은 마지막 마무리 정도에만 (남발 금지)
- 숫자/통계는 정확하게, 출처가 있으면 명시
- 직장인 관점 ("출근길에 알면 좋은", "내 돈에 영향 주는") 강조
- 정치적 편향 없이 사실 기반

[중요] 응답은 반드시 단일 JSON 객체로만 출력. 코드블록 ```json``` 으로 감싸도 됨. 마크다운 설명 금지.
"""

OUTPUT_SCHEMA = """\
{
  "news_cards": [
    {
      "title": "이모지 + 짧은 헤드라인 (40자 이내)",
      "summary": "1~2문장 요약",
      "why_it_matters": "직장인 관점에서 왜 알아야 하는지 1~2문장",
      "key_points": ["핵심 포인트1", "핵심 포인트2", "핵심 포인트3"],
      "sources": [{"title": "매체명", "url": "https://..."}]
    }
  ],
  "friendly_economics": {
    "topic": "오늘의 개념 (질문형 권장)",
    "explanation": "1단락 친근한 설명 (3~5문장)",
    "comparison_table": {
      "headers": ["항목", "A", "B"],
      "rows": [
        ["행1", "...", "..."],
        ["행2", "...", "..."]
      ]
    }
  },
  "rabbithat_ideas": [
    {
      "format": "유튜브 본편 10분 | 인스타 릴스 60초 | 블로그 글 등",
      "hook": "썸네일/제목 후보 (호기심 자극 1줄)",
      "target_audience": "구체적 타깃 (예: 30대 맞벌이 부부)",
      "outline": ["도입/후킹", "전개1", "전개2", "마무리/CTA"]
    }
  ]
}
"""


def _build_user_prompt(episode: dict, indicators: dict) -> str:
    title = episode.get("title", "")
    description = episode.get("description", "")
    pub_date = episode.get("pub_date", "")

    inds_dom = indicators.get("indicators", {})
    ind_lines = []
    for key, ind in inds_dom.items():
        arrow = "▲" if ind["direction"] == "up" else "▼" if ind["direction"] == "down" else "―"
        ind_lines.append(
            f"- {ind['name']}: {ind['value']}{ind['unit']} ({arrow}{ind['change']:+}, {ind['change_pct']:+.2f}%)"
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

위 정보를 바탕으로 뉴스 카드 / 친절한 경제 / 래빗해빛 콘텐츠 소재를 생성하세요.
필요하면 web_search 도구로 각 뉴스 토픽의 최신 기사·수치를 1~2개씩 찾아서 사실관계 확인 + 출처 링크를 sources에 포함하세요.

JSON 스키마:
{OUTPUT_SCHEMA}
"""


def _extract_json(text: str) -> dict:
    """모델 응답에서 JSON 객체 추출."""
    # ```json ... ``` 또는 ``` ... ``` 코드블록
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # 첫 { 부터 마지막 } 까지
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("응답에서 JSON 객체를 찾지 못했습니다.")


def _collect_response_text(response) -> str:
    """모든 text 블록을 합쳐서 반환 (web_search 결과 + 최종 답변)."""
    parts: list[str] = []
    for block in response.content:
        # SDK는 block.type을 'text'로, block.text를 본문으로 노출
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


def summarize(
    episode: dict,
    indicators: dict,
    *,
    use_web_search: bool = True,
    max_search_uses: int = 5,
    model: Optional[str] = None,
) -> dict:
    """Claude API 호출 → 구조화된 dict 반환."""
    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = Anthropic()

    tools = []
    if use_web_search:
        tools.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_search_uses,
        })

    user_prompt = _build_user_prompt(episode, indicators)

    logger.info("Claude API 호출: model=%s, web_search=%s", model, use_web_search)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            tools=tools or None,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        if use_web_search:
            logger.warning("web_search 도구 호출 실패: %s — 도구 없이 재시도", exc)
            return summarize(episode, indicators, use_web_search=False, model=model)
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

    data = _extract_json(text)

    # 사후 검증: 누락 키 채우기
    data.setdefault("news_cards", [])
    data.setdefault("friendly_economics", None)
    data.setdefault("rabbithat_ideas", [])

    # 사용량 정보 첨부 (디버깅용, 후속 단계에서 무시 가능)
    data["_meta"] = {
        "model": model,
        "stop_reason": response.stop_reason,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True, help="fetch_rss.py 출력 JSON 경로 (또는 '-' stdin)")
    parser.add_argument("--indicators", required=True, help="fetch_indicators.py 출력 JSON 경로")
    parser.add_argument("--out", help="결과 저장 경로 (미지정 시 stdout)")
    parser.add_argument("--no-search", action="store_true", help="web_search 도구 비활성화")
    parser.add_argument("--max-search", type=int, default=5)
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
