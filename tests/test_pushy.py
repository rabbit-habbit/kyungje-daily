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


# ── 그룹톡 멘트 마무리 ────────────────────────────────────────────────

# 실제로 나간 멘트의 마무리들. 발행 57편 중 43편이 "~보세요!"였다.
REAL_NOTES = [
    "코스피가 개장 3분 만에 서킷브레이커를 맞은 날이에요. 오늘 굵직한 뉴스를 한데 묶어뒀으니 훑어보세요!",
    "숫자 하나하나 풀어서 정리해뒀으니 찬찬히 읽어보세요!",
    "변동금리 대출 있으신 분은 오늘 브리핑부터 살펴보세요!",
    "내일 금통위 결과에 따라 대출 전략도 달라질 수 있으니 브리핑에서 미리 확인해두세요!",
    "맥락을 한 번에 정리해뒀으니 훑어봐 주세요!",
]


def test_실제로_나갔던_마무리가_전부_걸린다():
    for note in REAL_NOTES:
        assert run_mod._lint_group_note(note, []), f"린트가 못 잡는다: {note}"


def test_사람_냄새나는_마무리는_걸리지_않는다():
    ok = [
        "코스피가 개장 3분 만에 서킷브레이커를 맞은 날이에요. 저는 이 숫자 보고 한참 들여다봤어요.",
        "근원물가가 2.8%로 꺾이지 않았어요. 다음 금통위가 11/26이에요.",
        "삼성전자가 100조를 벌었는데 주가는 4% 빠졌어요. 오늘 계좌는 좀 괜찮으셨어요?",
        "숫자가 많은 날이라 급한 것부터 앞에 뒀어요.",
    ]
    for note in ok:
        assert run_mod._lint_group_note(note, []) == [], f"오탐: {note}"


def test_최근_멘트와_끝_어절이_같으면_걸린다():
    """같은 어절로 끝나면 독자에겐 같은 말이다.

    실제로 "읽어보세요!"가 16편, "펼쳐보세요!"가 9편이었다. 금지 범위가
    최근 3~4편이라 네댓 개를 돌려쓰면 규칙은 지켜지면서 반복이 남았다.
    """
    recent = ["숫자를 풀어서 담았어요!", "맥락을 짚었어요!", "급한 것부터 앞에 뒀어요!"]
    hits = run_mod._lint_group_note("오늘은 흐름만 짚었어요!", recent)
    assert any("끝 어절" in h for h in hits), hits


def test_프롬프트에서_느낌표_강제를_뺐다():
    src = (ROOT / "pipeline" / "summarize.py").read_text(encoding="utf-8")
    assert "마지막 문장은 반드시 느낌표" not in src
    assert "느낌표로 종료" not in src
    assert '"~보세요" 계열로 끝내지 않는다' in src
