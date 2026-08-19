"""Claude API로 손경제 RSS + 지표를 받아 통합 보고서 데이터를 생성.

단일 호출로 share / full 모드 모두에 필요한 데이터를 만든다:
  - news_cards (5개): RSS 3개 + web_search 추가 2개, 직장인 체감도 순 정렬
  - insight: 오늘의 한줄 인사이트 (래빗해빛 톤)
  - explainer: 경제 기초 다지기 (전 모드 사용)
  - rabbithat_ideas: 콘텐츠 소재 (full 모드 사용)
  - policy_outlook: 한국·미국 기준금리 짧은 전망 (50자 이내)
  - group_note: publ 그룹톡 발송용 하루치 멘트 (2~3문장)

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

from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
ARCHIVE_DIR = Path(__file__).resolve().parent.parent / "docs" / "archive"

# 이 날짜 이후 공유본에 실제로 나간 explainer 주제는 엄격 회피.
# (그 이전 이력은 대표님만 열람 - 독자 노출 없었으므로 중복 무관)
EXPLAINER_HISTORY_SINCE = "2026-08-18"

_EXPLAINER_TITLE_RE = re.compile(r'class="explainer-title">([^<]+)<')
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def recent_explainer_titles(
    since: str = EXPLAINER_HISTORY_SINCE, exclude_date: Optional[str] = None
) -> list[tuple[str, str]]:
    """공유본 아카이브에서 since 이후 독자에게 실제 노출된 explainer 제목 수집.

    full 모드가 아닌 *-share.html만 스캔한다 (full은 내부 열람용).
    exclude_date는 재실행 시 오늘자 산출물이 자기 자신을 회피 목록에 넣는 것을 막는다.
    """
    if exclude_date is None:
        exclude_date = datetime.now(KST).strftime("%Y-%m-%d")

    found: list[tuple[str, str]] = []
    if not ARCHIVE_DIR.is_dir():
        logger.warning("archive 디렉터리 없음: %s - explainer 회피 목록 생략", ARCHIVE_DIR)
        return found

    for path in sorted(ARCHIVE_DIR.glob("*-share.html")):
        date_str = path.name[:10]
        if not _DATE_RE.fullmatch(date_str):
            continue
        if date_str < since or date_str == exclude_date:
            continue
        try:
            m = _EXPLAINER_TITLE_RE.search(path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("아카이브 읽기 실패 %s: %s", path.name, exc)
            continue
        if m:
            found.append((date_str, m.group(1).strip()))
    return found


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

### STEP 1. 손경제 헤드라인에서 실제 다룬 토픽만 추출 (개수는 방송마다 다름)
손경제 description의 "[깊이 있는 경제뉴스]" 섹션에서 실제 다룬 토픽을 그대로 뽑아요.
방송마다 개수가 다릅니다 (보통 2~3개, 예외로 1개나 4개도 가능).
description에 명시된 개수만큼만 T로 취급 · 절대 인위적으로 개수를 늘리지 말 것.
각 토픽에 web_search로 관련 기사·수치를 풍부하게 수집. 출처 URL은 반드시
web_search 결과의 실제 URL만 사용 (가짜 URL 절대 금지).

예시 description 파싱:
  "[깊이 있는 경제뉴스]
   1) LH, 무순위 청약 물량 사들인다
   2) GPU 선물 시장 출범"
  → T1 = LH 무순위 청약, T2 = GPU 선물 시장. **T3는 존재하지 않음** (총 2개).
description을 무시하고 오늘 화제 뉴스를 T로 채우는 것은 절대 금지.

### STEP 2. 추가 경제뉴스 발굴 (web_search) — 총 5개가 되도록 채움
web_search로 (5 - 손경제 T 개수)개를 추가 발굴 (W1·W2·... 형태).
  · 손경제 3개 → 웹 2개 (W1·W2)
  · 손경제 2개 → 웹 3개 (W1·W2·W3)
  · 손경제 1개 → 웹 4개 (W1~W4)
오늘 또는 어제 발표된 한국/글로벌 경제 뉴스 중 직장인 체감도 높은 것.
손경제 T 주제와 중복 금지. 카테고리 예: 미국 금리·물가·고용, 글로벌 채권·환율,
한국 부동산·세금·정책, 대기업 실적, 신재테크 트렌드.
W1이 가장 중요, W2, W3, ... 순으로 배치.
(우선순위 참고: 금리/대출 > 환율/물가 > 주식/투자 > 일자리/기업 > 경제일정)

### STEP 3. 총 5개 뉴스 배열 순서 (손경제 T 원본 순서 유지 · 교차 배치)
T를 앞쪽에서 원본 순서대로 배치하고, 사이/뒤에 W를 끼워 넣어요.
  · 손경제 3개 + 웹 2개: T1 → W1 → T2 → W2 → T3
  · 손경제 2개 + 웹 3개: T1 → W1 → T2 → W2 → W3
  · 손경제 1개 + 웹 4개: T1 → W1 → W2 → W3 → W4
  · 손경제 4개 + 웹 1개: T1 → W1 → T2 → T3 → T4
원칙: T는 반드시 원본 순서를 유지. W는 T 사이/뒤에 W1부터 순서대로 채움.

### STEP 4. 각 뉴스카드 작성
1. title: 한 줄 (30~40자, 이모지 1개), 자극적이지 않게.
2. body: 2~3개 문단 (배열). 각 문단 1~3 문장. 친근한 해요체. 숫자 구체적.
3. key_numbers: 핵심 수치 2~4개. 각: {{label, value, direction}}
   - direction은 "up" | "down" | "" (중립) 중 하나.
4. why_for_workers: "직장인이 알아야 하는 이유" 2~4 문장. ★ 재테크 초보 눈높이로 쓸 것.
   - 직장인 관점에서 지갑·대출·투자·일자리에 어떤 영향인지.
   - 어려운 용어는 그 자리에서 쉬운 말로 풀어줄 것
     (예: "여러 번 나눠서 거래(=분할 매수·매도)하시는 게 안전해요").
   - 독자가 당장 접근 가능한 구체적 상품·경로를 예시로 제시
     (예: "증권사 앱에서 금 ETF(예: ACE KRX금현물)로 몇만원부터 살 수 있어요",
      "3억 대출 기준 연 이자 약 390만원 증가").
   - "이런 분이라면"으로 독자 상황을 짚어 감정이입시킬 것
     (예: "반도체 ETF 담고 계신 분이라면", "부동산에 조금이라도 투자해보고 싶은 분에게").
   - 겁주지 말 것. 무엇을 지켜보면 되는지 행동 힌트로 끝맺기.
5. sources: [{{name, url}}] 1~3개 (web_search 실제 URL만).

### STEP 5. 오늘의 한줄 인사이트 (insight)
5개 뉴스를 관통하는 핵심 메시지를 2~3 문장으로 정리.
래빗해빛 톤. 직장인 액션 시사점 포함.
HTML <strong> 태그 사용 가능 (강조 1~2개).

### STEP 6. 경제 기초 다지기 (explainer) - 전 모드 노출, 항상 생성
★ 선정 기준: "흥미로운 개념"을 고르지 말 것. **오늘 이 보고서 본문(뉴스카드 body·
why_for_workers·지표·insight)에 실제로 등장한 용어·표현 중, 재테크 초보가 읽다가
걸릴 만한 것 1개**를 고른다.
- 좋은 예: 지표 섹션에 "매파적 동결"이 나왔다면 → "매파와 비둘기파, 뭐가 다른 거예요?"
- 나쁜 예: 본문에 없는 용어를 새로 끌어와 설명 (독자가 왜 읽어야 하는지 모름)
- 후보가 여럿이면 초보가 가장 자주 마주치는 기본 용어를 우선한다.
  단 아래 [이미 다룬 주제]에 있으면 제외하고 다음 후보로 넘어간다.
title: 질문형 권장 ("~가 뭐예요?", "~하면 무슨 일이 생기나요?").
body: 3~5 문장. 첫 문장에서 그 용어가 오늘 본문 어디에 나왔는지 짚어줄 것.
대비되는 개념 둘을 다루면 HTML <table> 비교표 권장 (초보 이해도가 크게 올라감).

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

### STEP 9. 그룹톡 멘트 (group_note) - publ 구독자에게 보낼 하루치 한마디
브리핑 링크와 함께 그룹 채팅방에 나가는 멘트. **대표님이 직접 쓴 것처럼** 1인칭으로 쓴다.
자동 발송이 아니라 사람이 오늘 자료를 만들고 한마디 붙인 느낌이어야 한다.

★ 소재는 오늘 내용에 맞춰 **직접 판단해서 고른다** (고정 틀 금지):
- 기초다지기 개념이 오늘 뉴스 전체를 이해하는 열쇠라면 → 그 개념 중심
- 시장이 크게 움직였거나 독자 지갑에 바로 닿는 뉴스가 있으면 → 그 뉴스 중심
- 둘 다 약한 날은 오늘 5개를 관통하는 흐름 한 줄

★ 톤은 **그날 분위기를 따라간다** (이 규칙이 가장 중요):
- 평온한 날: 친근하게. "여러분!" 시작, "저도 ~했어요" 경험 공유, "ㅎㅎ" 1회까지 허용
- 급락·위기·손실 뉴스가 헤드라인인 날: **"ㅎㅎ"와 들뜬 이모지 금지.** 차분하고
  담담하게. 독자가 이미 놀란 상태라는 전제로 "왜 그런지 정리해뒀다"는 안내 톤
- 겁주거나 재촉하지 않는다. 클릭을 구걸하는 표현("꼭 보셔야 해요!!") 금지

형식:
- 2~3문장, 전체 200자 이내. 짧을수록 좋다.
- 이모지는 0~1개. 남발 금지.
- URL·링크는 넣지 않는다 (발송 코드가 따로 붙인다).
- 마무리는 부드러운 안내형 ("정리해뒀어요", "하단에서 확인해보세요", "천천히 보세요").
- 상대 날짜 금지 (아래 규칙과 동일). 긴 대시(-) 대신 하이픈.

좋은 예 (평온한 날):
"여러분! 오늘 기초다지기는 '기간프리미엄'이에요. 저도 '물가는 잡혔다는데 왜 장기금리는
안 내리지?' 싶었던 적이 있는데, 이 개념 하나 알고 나니 오늘 뉴스가 다 연결되더라구요ㅎㅎ"

좋은 예 (급락일):
"여러분, 오늘 계좌 열어보고 놀라셨을 것 같아요. 코스피가 7.2% 빠졌는데 방아쇠는
우리나라가 아니라 미국 30년물 국채금리였어요. 왜 그런지 차근차근 정리해뒀습니다."

나쁜 예:
"오늘도 알찬 브리핑 준비했어요! 꼭 확인해주세요!!😍🔥" (내용 없음·톤 과함·매일 똑같음)

## ★ 출처 비공개 규칙 (반드시 지킬 것)
보고서를 받아보는 독자는 자료 원천이 어디인지 몰라야 합니다. **모든 본문(body, why_for_workers,
insight, explainer.body, rabbithat_ideas.text, group_note)에서 다음 표현을 절대 쓰지 마세요:**
  - "손경제", "이진우", "MBC", "라디오", "팟캐스트", "방송에서"
  - "오늘 손경제에서 다룬", "손경제는 분석했어요" 등 출처를 암시하는 모든 표현
대신 일반적 표현으로 바꾸세요:
  - ❌ "손경제는 4조원을 추가로 채워줄 거라 분석했어요"
  - ✅ "시장 분석가들은 4조원 추가 매수를 예상하고 있어요"
  - ✅ "업계에서는 4조원이 추가로 유입될 것으로 보고 있어요"
  - ❌ "오늘 손경제에서 다룬 ..."
  - ✅ "오늘 핵심 이슈는 ..." 또는 "최근 시장의 주목 포인트는 ..."

## ★ 시장 데이터 시점 검증 규칙 (반드시 지킬 것)
web_search로 얻은 국내 시장 지표(KOSPI, KOSDAQ, 원·달러 환율, 국고채 등)를 인용할 때:

1. **한국 증시 휴장일 확인 필수**
   발행일이 다음에 해당하면 국내 증시 휴장:
   - 주말(토·일)
   - 대한민국 법정공휴일: 신정(1/1), 설날 연휴, 삼일절(3/1), 어린이날(5/5),
     부처님오신날, 현충일(6/6), 광복절(8/15), 개천절(10/3), 한글날(10/9),
     성탄절(12/25), 국회·대통령 선거일, 그리고 위 공휴일이 주말과 겹칠 때의 대체휴일
   - 특히 광복절(8/15)이 토요일인 해는 다음 월요일이 대체휴일 → 그날 증시 휴장

2. **휴장일에는 KOSPI·환율 등을 "오늘 기록/발행일 급등"으로 서술 금지**
   반드시 "직전 거래일(M/D) 종가 기준"으로 명시.
   ❌ "8/17 코스피가 급등해 6,977p를 기록했어요"
   ✅ "8/14(금) 종가 기준 코스피 6,977p (직전 거래일 대비 +2.42%).
        8/17은 광복절 대체휴일로 국내 증시 휴장이에요."

3. **web_search 결과의 관측 날짜와 발행일 다르면 반드시 관측일 명시**
   발행일에 관측된 것처럼 서술 절대 금지. "8/14 발표된", "8/14 기준" 등으로.

4. **국내와 글로벌 시장 구분**
   미국 증시(NYSE·NASDAQ)는 한국 공휴일과 무관. 다만 한국 시간 새벽 마감이므로
   "미국 8/14(현지) 종가" 또는 "8/15 새벽 마감"처럼 시점 명시.

5. **억지로 시장 지표를 넣지 말 것**
   발행일이 휴장이라 국내 시장 뉴스가 어색하면 다른 소재(정책·기업·해외·산업 등)로 대체.

## ★ 날짜 표기 규칙 (반드시 지킬 것)
본문에서 시점을 언급할 때 "오늘" · "어제" · "그저께" 같은 상대 표현 대신 실제 날짜(M/D)를 씁니다.
브리핑은 발행 후에도 아카이브에서 계속 열람되므로 상대 시점은 혼란을 줍니다.
  - ❌ "오늘 발표된 CPI가..."
  - ✅ "8/12 발표된 CPI가..."
  - ❌ "어제 코스피가 급등"
  - ✅ "8/12 코스피가 급등"
  - ❌ "오늘 원·달러 환율도 1,413원으로 6원 올랐으니"
  - ✅ "8/12 원·달러 환율도 1,413원으로 6원 올랐으니"
예외: insight의 오늘 뉴스 종합 요약처럼 "오늘 뉴스들을 종합하면..."처럼
발행일 자체를 가리키는 서두 표현은 허용.

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
      "why_for_workers": "직장인이 알아야 하는 이유 (2~4문장, 초보 눈높이)",
      "sources": [
        {"name": "매체명", "url": "https://실제URL"}
      ]
    }
    // ... 총 5개, 직장인 체감도 순
  ],
  "insight": "오늘의 한줄 인사이트 (2~3문장, <strong> 강조 가능)",
  "explainer": {
    "title": "오늘 본문에 나온 용어 풀이 (질문형 권장)",
    "body": "3~5문장 설명, HTML <table> 비교표 선택"
  },
  "rabbithat_ideas": [
    {"label": "유튜브 본편 10분", "text": "후킹 제목  🎯 타깃  도입·전개·CTA"}
  ],
  "policy_outlook": {
    "korea": "5/28 금통위 동결, 7월 인하 검토 (50자 이내)",
    "us": "6/18 FOMC 동결, 9월 25bp 인하 (CME 65%)"
  },
  "group_note": "그룹톡 멘트 (2~3문장, 200자 이내, URL 없이, 그날 톤에 맞춰)"
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

    history = recent_explainer_titles()
    if history:
        history_lines = "\n".join(f"- {d}: {t}" for d, t in history)
        history_text = f"""
[이미 다룬 '경제 기초 다지기' 주제 - 엄격 회피]
{history_lines}

위 주제는 독자에게 이미 나갔습니다. 같은 주제를 다시 고르지 마세요.
예외: 오늘 본문 이해에 그 개념이 반드시 필요한 경우에만 다시 다룰 수 있습니다.
      단 반드시 '새로운 각도'여야 하며, title에서 각도 차이가 드러나야 합니다.
      같은 질문을 표현만 바꿔 되묻는 것은 금지입니다.
"""
        logger.info("explainer 회피 목록 %d건 주입 (기준일 %s 이후)",
                    len(history), EXPLAINER_HISTORY_SINCE)
    else:
        history_text = ""

    return f"""\
[오늘 손경제 에피소드]
방송일: {pub_date}
제목: {title}
설명:
{description}

[오늘 경제지표]
{indicators_text}
{history_text}
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

    # JSON 파싱 실패 시 최대 1회 자동 재시도 (LLM이 가끔 형식 어긋난 응답 반환).
    MAX_ATTEMPTS = 2
    last_text = ""
    last_response = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info(
            "Claude API 호출 (%d/%d): model=%s, web_search=%s",
            attempt, MAX_ATTEMPTS, model, use_web_search,
        )
        try:
            # tools는 비어있으면 파라미터 자체를 생략해야 한다.
            # tools=[] 또는 tools=None을 넘기면 API가 400을 반환한다
            # ("tools: Input should be a valid array"). web_search 실패 후
            # use_web_search=False로 재시도하는 경로가 이 때문에 죽었다.
            kwargs = {
                "model": model,
                "max_tokens": 10000,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if tools:
                kwargs["tools"] = tools
            response = client.messages.create(**kwargs)
        except Exception as exc:
            if use_web_search and attempt == 1:
                logger.warning("web_search 호출 실패: %s — 도구 없이 재시도", exc)
                return summarize(
                    episode, indicators, use_web_search=False, model=model
                )
            raise

        last_response = response
        logger.info(
            "응답 수신: stop_reason=%s, in=%d, out=%d",
            response.stop_reason,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        text = _collect_response_text(response)
        last_text = text
        if not text.strip():
            raise RuntimeError("응답에 text 블록이 없습니다.")

        try:
            data = _extract_json(text)
            break  # 파싱 성공 → 루프 종료
        except (ValueError, json.JSONDecodeError) as exc:
            if attempt < MAX_ATTEMPTS:
                logger.warning(
                    "JSON 파싱 실패 (%d/%d): %s — Claude에 재요청",
                    attempt, MAX_ATTEMPTS, exc,
                )
                continue
            # 마지막 시도도 실패 → raw 저장 + raise
            raw_path = Path(__file__).resolve().parents[1] / "out" / "summary_raw.txt"
            raw_path.parent.mkdir(exist_ok=True)
            raw_path.write_text(last_text, encoding="utf-8")
            logger.error("JSON 파싱 최종 실패: %s — raw 응답을 %s에 저장", exc, raw_path)
            raise

    response = last_response  # 아래 코드 호환성용

    # 누락 키 폴백
    data.setdefault("news_cards", [])
    data.setdefault("insight", "")
    data.setdefault("explainer", None)
    data.setdefault("group_note", "")
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
