"""권유 투 점검 회귀 테스트.

2026-11-06 발행분 5번(지분적립형 아파트)이 제도를 설명하는 대신 청약을
권하는 투로 나갔다. 맨 아래에 "투자 판단의 근거가 될 수 없습니다"를 붙여놓고
본문에서 청약을 권하면 앞뒤가 맞지 않는다. 사람 눈에 걸려서야 알았다.

여기서 지키는 것:
  - 그날 실제로 나간 문장들이 린트에 걸린다 (안 걸리면 린트가 무의미하다)
  - 상품 블록은 걸리지 않는다 (거기는 권유가 제 일이다)
  - 프롬프트에 금지 규칙이 남아 있다
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import run as run_mod  # noqa: E402

# 2026-11-06 5번 카드에서 실제로 발행된 문장들.
REAL = [
    "자산은 적지만 꾸준한 소득이 있는 직장인 청년·신혼부부라면 주목할 만한 제도예요.",
    "고양창릉은 12월, 광교는 11/9~11 청약이니 청약홈에서 공고문을 꼭 확인해 보세요.",
    "이런 분이라면 특히 주목: 청약통장 있고, 무주택이고, 자산이 아직 많지 않은 30대 직장인.",
    "20년간 집값이 많이 오르면 초기에 지분을 더 많이 확보해 두는 게 유리할 수 있어요.",
]


def test_그날_나간_문장이_전부_걸린다():
    for sentence in REAL:
        hits = run_mod._lint_pushy({"news_cards": [{"why_for_workers": sentence}]})
        assert hits, f"린트가 못 잡는다: {sentence}"


def test_고쳐_쓴_문장은_걸리지_않는다():
    """사실만 적은 문장이 걸리면 린트가 쓸 수 없게 된다."""
    fixed = [
        "무주택 청년·신혼부부를 대상으로 설계된 제도라, 해당되지 않으면 신청 자격부터 막혀요.",
        "청약은 광교가 11/9~11, 고양창릉이 12월이에요.",
        "추가 지분 가격은 최초 분양가에 기간 이자를 더해 정해져요. "
        "집값이 오르면 덜 내는 셈이 되고, 떨어지면 시세보다 비싸게 사들이게 돼요.",
        "아직 내 소유가 아닌 지분에는 임대료를 내야 해서 월 고정 지출이 생겨요.",
    ]
    for sentence in fixed:
        hits = run_mod._lint_pushy({"news_cards": [{"body": sentence}]})
        assert not hits, f"오탐: {sentence} → {hits}"


def test_상품_블록은_대상이_아니다():
    """사다리·트리거는 권유가 제 일이다. 거기까지 걸면 린트를 끄게 된다."""
    data = {
        "news_cards": [],
        "ladder": [{"desc": "1기 절찬리 마감! 2기 열릴 때 가장 먼저 알려드릴게요"}],
        "trigger": {"text": "지금이 시작할 때예요. 놓치지 마세요!"},
    }
    assert run_mod._lint_pushy(data) == []


def test_린트가_발행을_막지_않는다():
    """톤 판단에는 오탐이 있다. 오탐 하나로 브리핑이 안 나가는 게 더 큰 손해다."""
    import inspect
    src = inspect.getsource(run_mod.run)
    i = src.find("_lint_pushy")
    assert i != -1, "run()에서 린트를 호출하지 않는다"
    after = src[i:i + 700]
    assert "raise" not in after and "sys.exit" not in after, "린트가 발행을 중단시킨다"


def test_프롬프트에_권유_금지_규칙이_있다():
    src = (ROOT / "pipeline" / "summarize.py").read_text(encoding="utf-8")
    assert "권유·추천 금지 규칙" in src
    # 추천을 유도했던 옛 지시가 되살아나면 규칙과 충돌한다.
    assert "행동 힌트로 끝맺기" not in src
