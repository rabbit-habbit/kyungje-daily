"""상위 퍼널 상품 블록.

브리핑 안에 두 종류의 블록을 넣는다.

  사다리 (매일)      기초 다지기와 한줄 인사이트 사이. 세 상품을 한 블록에.
  기사 트리거 (가끔) 그날 기사가 상품과 맞아떨어질 때 그 기사 밑에. 주 1~2회.

설계 원칙 셋. 전부 앞서 데인 자리라 코드로 박아둔다.

1. 문구는 여기 상수로 둔다. 프롬프트가 지어내면 몇 개 남았는지 알 수 없고,
   같은 말이 반복돼도 지표가 조용하다.
2. 순번은 발행 횟수로 센다. 날짜로 세면 주말·휴일에 건너뛰어 순번이
   들쭉날쭉해지고, 특정 문장이 특정 요일에만 걸리는 쏠림이 생긴다.
3. 트리거 판정과 주간 상한은 코드가 한다. 프롬프트에 맡기면 기준이 날마다
   흔들려서 왜 그날 나갔는지 사후에 설명할 수 없다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs" / "archive"

WORKER = "https://economy-proxy.rabbit-habbit.workers.dev"

# 링크는 전부 리다이렉터를 거친다. 목적지를 여기 직접 쓰면 클릭이 안 잡힌다.
def link(product: str, slot: str, copy_idx: int, angle: str) -> str:
    return f"{WORKER}/r?p={product}&s={slot}&v=c{copy_idx}&a={angle}"


def image(name: str) -> str:
    return f"{WORKER}/img/{name}"


# ── 사다리 3종 ────────────────────────────────────────────────────────
# desc는 순번대로 돈다. 매일 같은 문장이면 3주쯤 뒤 눈이 그 자리를 건너뛴다.
# img가 여러 개인 상품은 사진도 같이 돈다.

LADDER = [
    {
        "code": "book",
        "title": "잘잘잘돈",
        "angle": "role",
        "cta": "보러 가기",
        "images": ["book.jpg"],
        "desc": [
            "용어는 알겠는데 뭘 먼저 할지 모르겠을 때가 있잖아요. 책에는 전체 로드맵과 생생한 제 스토리를 담았어요!",
            "0원에서 시작해 20대에 20억을 만든 과정, 순서대로 다 적어뒀어요!",
            "월급은 안 느는데 불안만 느는 것 같다면, 딱 그 얘기로 시작하는 책입니다!",
            "퇴근 후 2시간으로 돈이 일하게 만든 방법 모두를 「잘잘잘돈」에 담았어요!",
            "통장 세팅부터 주식, 부동산, N잡까지 순서대로 따라올 수 있게 쓴 책이 궁금하다면?",
            "재테크를 어디서부터 어떻게 시작할지 모르겠다면, 여기서부터 읽어보세요!",
            "내 돈 한 푼 안 쓰고 집을 산 이야기도 들어 있어요. 재테크는 운이 아니라 순서입니다.",
            "불안한 마음을 단단하게 만든 건 결국 돈 공부였어요.",
            "회사 다니면서도 부자 되는 법이 궁금하셨다면, 그 방법을 담았어요!",
            "돈에 휘둘리지 않고 주도적으로 살고 싶다면, 그 시작을 여기 적어뒀어요.",
        ],
    },
    {
        "code": "mf_kakao",
        "title": "머니프리랩 4주 챌린지",
        "angle": "ask",
        "cta": "오픈 알림 먼저 받기",
        "images": ["moneyfreelab-1.jpg", "moneyfreelab-2.jpg", "moneyfreelab-3.jpg"],
        "desc": [
            "혼자 하면 자꾸 멈추게 되죠. 4주 동안 함께 하는 챌린지도 있어요!",
            "자본주의 살아남기 챌린지! 머니프리랩 1기, 친구 추가해두시면 오픈되자마자 알림 받아볼 수 있어요!",
            "시작은 했는데 흐지부지된다면, 이번엔 챌린지로 같이 가봐요!",
            "돈 공부해야 하는 건 알겠는데 혼자서 뭐부터 할지 막막하셨다면, 머니프리랩 1기 오픈 알림 먼저 받아보세요!",
            "의지가 문제였던 게 아니라, 혼자였던 걸 수도 있어요. 챌린지에서 함께해요💛",
            "자본주의 '룰'부터 주식, 부동산까지 4주 동안 같이 훑어볼 거예요. 친구 추가 해두면 1기 오픈 알림 바로 받아볼 수 있어요!",
            "머니프리랩으로 4주 동안 같이 달려요. 미션 수행 시 보증금 전액 환급!",
            "래빗해빛 x 채린의쓰임 돈 공부 스터디 “머니프리랩”! 친구 추가 해두시면 열리는 날 알려드릴게요!",
            "4주 뒤에 “해냈다” 소리 한 번 해보실래요?",
            "처음 배우는 자본주의 경제, 머니프리랩 1기가 곧 열려요. 친구 추가 먼저 해두세요!",
            "경제 기사는 읽는데 내 돈이랑 어떻게 연결되는지 모르겠다면? 4주 스터디 알림 받기 신청하세요!",
        ],
    },
    {
        "code": "taling",
        "title": "60일 월급테크 챌린지",
        "angle": "role",
        "cta": "보러 가기",
        "images": ["taling.jpg"],
        "desc": [
            "좀 더 구체적인 실행 플랜이 필요하다면? 60일 월급테크 챌린지, 따라만 오면 어느새 계좌 세팅이 완성되어 있을 거예요!",
            "브리핑에서 매일 보는 용어들, 60일 챌린지에서는 경제 기사 읽는 법까지 실습으로 다룹니다!",
            "예적금, ISA, ETF, 채권, 공모주. 이름만 알던 것들을 하나씩 정리해드려요!",
            "벌써 6000명이 넘게 함께한 1위 챌린지!",
            "미션만 해도 재테크 지원금이 나와요. 끝까지 완주하시라고 만든 구조입니다!",
            # 후기 인용. 줄이되 뜻은 바꾸지 않는다. 닉네임은 원문 그대로.
            "“연금도, ISA도, 채권도 뉴스에서만 스쳐 지나가던 남의 이야기였어요” 수강생 시샘달 님 후기예요.",
            "“완벽하게 다 해내지는 못했지만 부담스럽지 않게 따라갔어요” 수강생 Sofia 님 후기예요.",
            "“퇴근하고 늘어지는 저를 끝끝내 공부시켜주셔서 감사합니다” 수강생 서연 님 후기예요.",
            "“일일 미션이나 주간 미션이 긍정적인 강제성을 부여하는 것 같아 좋았어요” 수강생 현수 님 후기예요.",
            "연준, 기준금리, 환율, PER까지. 경제 상식 파트만 들어도 뉴스가 다르게 읽혀요!",
        ],
    },
]


# ── 기사 트리거 ───────────────────────────────────────────────────────
# 그날 기사 하나가 상품과 정면으로 맞을 때만 그 기사 밑에 붙는다.
# 책은 대상에서 뺐다. 이미 사다리에 매일 나오는데 같은 날 두 번 나오면
# 그때부터 광고로 읽힌다.

TRIGGERS = [
    {
        "code": "taling",
        "angle": "link",
        "title": "탈잉 60일 월급테크 챌린지",
        # 처음 보는 사람도 뭔지 알게. 상품명만 던지면 왜 눌러야 하는지 모른다.
        "intro": "통장 세팅부터 주식·부동산까지, 60일 동안 직접 해보며 배우는 챌린지예요.",
        "facts": ["60일 온라인", "수강생 6000명+", "미션 수행 시 재테크 지원금"],
        "image": "taling.jpg",
        "cta": "60일 월급테크 챌린지 보러 가기",
        "rules": [
            {
                "kw": ["월급", "임금", "실질임금", "급여", "연봉"],
                "text": "월급이 오르는 속도는 정하기 어렵지만, 나가는 순서는 정할 수 있거든요.\n"
                        "60일 동안 통장 세팅부터 투자까지 한 바퀴 돌아보는 챌린지가 있어요!",
            },
            {
                "kw": ["가계부채", "대출", "이자 부담", "원리금"],
                "text": "빚을 줄이는 것도 결국 돈이 나가는 순서를 정하는 일이라서요.\n"
                        "60일 월급테크 챌린지가 그 순서를 잡는 쪽이에요!",
            },
            {
                "kw": ["ISA", "연금", "채권", "공모주", "퇴직연금", "IRP"],
                "text": "“연금도, ISA도, 채권도 뉴스에서만 스쳐 지나가던 남의 이야기였어요.”\n"
                        "수강생 시샘달 님 후기예요. 60일 챌린지에서 직접 계좌까지 세팅해봅니다!",
            },
            {
                "kw": ["연말정산", "소득공제", "세액공제"],
                "text": "연말정산은 1월에 몰아서 되는 게 아니라 지금 쓰는 돈에서 갈려요.\n"
                        "챌린지에 연말정산 대비 소비 전략 파트가 따로 있어요!",
            },
        ],
    },
    {
        "code": "mf_kakao",
        "angle": "ask",
        "title": "머니프리랩 4주 챌린지",
        "intro": "래빗해빛 x 채린의쓰임이 함께 만든 4주 자본주의 경제 스터디예요. 1기를 준비하고 있어요.",
        "facts": ["11월 4주", "카카오톡 진행", "미션 수행 시 보증금 전액 환급"],
        "image": "moneyfreelab-1.jpg",
        "cta": "머니프리랩 오픈 알림 먼저 받기",
        "rules": [
            {
                "kw": ["저축", "적금", "예금", "목돈", "종잣돈"],
                "text": "저축은 방법을 몰라서보다 혼자 하다 흐지부지돼서 못 하는 경우가 더 많더라고요.\n"
                        "4주 동안 같이 해보는 챌린지를 준비 중이에요. 오픈 알림 먼저 받아보세요!",
            },
            {
                "kw": ["소비", "생활비", "물가", "장바구니"],
                "text": "쓰는 걸 줄이는 건 하루 만에 되는데, 그게 4주를 가는 게 어렵죠.\n"
                        "머니프리랩 1기 알림 신청받고 있어요!",
            },
        ],
    },
]

# 한 주에 몇 번까지 붙일지. 최근 발행분을 훑어 센다.
TRIGGER_MAX_PER_WEEK = 2
TRIGGER_WINDOW = 4  # 직전 발행 4회를 본다 (오늘 포함 5회 = 평일 한 주)


# ── 발행 순번 ─────────────────────────────────────────────────────────

_ARCHIVE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-share\.html$")


def published_dates() -> list[str]:
    """지금까지 발행된 날짜를 오름차순으로."""
    if not ARCHIVE.is_dir():
        return []
    out = []
    for p in ARCHIVE.iterdir():
        m = _ARCHIVE_RE.match(p.name)
        if m:
            out.append(m.group(1))
    return sorted(out)


def ordinal(date_str: str) -> int:
    """이번이 몇 번째 발행인가.

    날짜가 아니라 발행 횟수로 세는 이유가 있다. 주말·공휴일·정규 방송분이
    없는 날은 발행을 건너뛰는데, 날짜 기준이면 그만큼 순번이 뛰어서 특정
    문장이 특정 요일에만 걸리는 쏠림이 생긴다. 발행 횟수로 세면 하루를
    건너뛰어도 순번은 정확히 한 칸만 간다.
    """
    dates = published_dates()
    if date_str in dates:
        return dates.index(date_str)
    # 아직 저장 전이면 오늘이 맨 뒤에 붙는다고 본다.
    return len([d for d in dates if d < date_str])


# ── 사다리 블록 ───────────────────────────────────────────────────────

def ladder_items(date_str: str) -> list[dict]:
    """오늘 내보낼 사다리 3종. 문구와 사진이 순번대로 돈다."""
    n = ordinal(date_str)
    items = []
    for offset, p in enumerate(LADDER):
        # 상품마다 시작점을 어긋나게 둔다. 안 그러면 세 줄이 늘 같이 넘어가
        # 블록 전체가 한 덩어리로 바뀐 것처럼 보인다.
        i = (n + offset) % len(p["desc"])
        img = p["images"][(n + offset) % len(p["images"])]
        items.append({
            "code": p["code"],
            "title": p["title"],
            "desc": p["desc"][i],
            "cta": p["cta"],
            "img": image(img),
            "url": link(p["code"], "ladder", i, p["angle"]),
        })
    return items


# ── 기사 트리거 ───────────────────────────────────────────────────────

def _meta_path(date_str: str) -> Path:
    return ARCHIVE / f"{date_str}-meta.json"


def recent_trigger_count(date_str: str) -> int:
    """직전 발행 몇 회에 트리거가 몇 번 붙었나."""
    prev = [d for d in published_dates() if d < date_str][-TRIGGER_WINDOW:]
    n = 0
    for d in prev:
        p = _meta_path(d)
        if not p.is_file():
            continue
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("trigger"):
                n += 1
        except Exception:
            continue
    return n


def _match(title: str, body: str, kws: list[str]) -> tuple[int, int]:
    """(제목 일치 수, 본문 일치 수).

    제목과 본문을 나눠 세는 이유가 있다. 거시 기사는 본문 어딘가에서
    소비·물가를 한 번씩 스치고 지나간다. 그걸 "이 기사는 소비 이야기"로
    읽으면 유가 기사 밑에 절약 챌린지가 붙는다. 실제로 9/28에 그랬다.

    기사가 그 주제를 **다루는지**는 제목이 말해준다.
    """
    tl, bl = title.lower(), body.lower()
    return (sum(1 for k in kws if k.lower() in tl),
            sum(1 for k in kws if k.lower() in bl))


def pick_trigger(news_cards: list[dict], date_str: str) -> dict | None:
    """오늘 기사 중 상품과 가장 강하게 맞는 것 하나. 없으면 None.

    상한에 걸리면 맞는 기사가 있어도 붙이지 않는다. 안 세면 월급·금리
    뉴스가 몰린 주에 매일 나간다.
    """
    used = recent_trigger_count(date_str)
    if used >= TRIGGER_MAX_PER_WEEK:
        logger.info("  · 트리거 상한 도달 (직전 %d회 중 %d회) - 오늘은 붙이지 않습니다",
                    TRIGGER_WINDOW, used)
        return None

    best = None
    for idx, news in enumerate(news_cards):
        title = news.get("title") or ""
        body = " ".join([
            " ".join(news.get("body") or []),
            news.get("why_for_workers") or "",
        ])
        for prod in TRIGGERS:
            for rule in prod["rules"]:
                t_hit, b_hit = _match(title, body, rule["kw"])
                # 제목에 안 걸리면 그 기사의 주제가 아니다. 붙이지 않는다.
                if not t_hit:
                    continue
                score = t_hit * 3 + b_hit
                if best is None or score > best["score"]:
                    best = {
                        "score": score,
                        "news_index": idx,
                        "code": prod["code"],
                        "title": prod["title"],
                        "intro": prod["intro"],
                        "facts": prod["facts"],
                        "img": image(prod["image"]),
                        "text": rule["text"],
                        "cta": prod["cta"],
                        "angle": prod["angle"],
                    }
    if not best:
        logger.info("  · 오늘 기사에 맞는 상품 없음 - 트리거 없이 갑니다")
        return None

    best["url"] = link(best["code"], "article_n", 0, best["angle"])
    logger.info("  ✓ 트리거: %d번 기사 → %s (%d점, 제목 일치 있음)",
                best["news_index"] + 1, best["code"], best["score"])
    return best
