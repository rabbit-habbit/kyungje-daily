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

# 실제로 나간 멘트의 마무리들. 발행 57편 중 43편이 "~보세요!"였다.# 2026-11-06에 대표님이 초안 4편의 마무리를 전부 손봤다. 수정 방향이 하나였고,
# 이 두 목록이 그 전후다. 아래 테스트는 "내가 쓴 쪽은 걸리고 대표님이 고친 쪽은
# 통과한다"를 고정한다. 규칙 문장을 테스트에 옮겨 적는 것보다 이게 낫다 -
# 규칙은 또 바뀌지만 이 여덟 문장은 실제로 있었던 일이다.
DRAFT = [
    "코스피가 개장 3분 만에 서킷브레이커를 맞았어요. 왜 이렇게 됐는지랑 "
    "커버드콜 세금 환급 이슈까지 담았어요. 한번 읽어보세요!",
    "미국은 웃고 한국 반도체만 급락한 하루예요. 선거 결과 하나가 이렇게 "
    "엇갈린 반응을 낳았습니다!",
    "근원물가가 2.8%로 꺾이지 않고, 성장률은 예상의 3배였어요. 다음 금통위가 11/26이에요.",
    "삼성전자가 100조 넘게 벌었는데 주가는 4% 빠졌어요. 숫자가 많은 날이라 "
    "급한 것부터 앞에 뒀습니다!",
]
FIXED = [
    "코스피가 개장 3분 만에 서킷브레이커를 맞았어요. 왜 이렇게 됐는지랑 "
    "커버드콜 세금 환급 이슈까지 담아봤습니다!",
    "미국은 웃고 한국 반도체만 급락한 하루예요. 선거 결과 하나가 이렇게 "
    "엇갈린 반응을 낳았습니다ㅠ 꼭 확인해보세요!",
    "근원물가가 2.8%로 꺾이지 않고, 성장률은 예상의 3배였어요. 다음 금통위는 11/26로 같이 알아둡시다!",
    "삼성전자가 100조 넘게 벌었는데 주가는 4% 빠졌어요. 왜 이런일이 생기는지 같이 정리해봤습니다!",
]

# 실제로 나갔던 멘트들. 전부 걸려야 한다.
REAL_NOTES = [
    "코스피가 개장 3분 만에 서킷브레이커를 맞은 날이에요. 오늘 굵직한 뉴스를 한데 묶어뒀으니 훑어보세요!",
    "숫자 하나하나 풀어서 정리해뒀으니 찬찬히 읽어보세요!",
    "변동금리 대출 있으신 분은 오늘 브리핑부터 살펴보세요!",
    "내일 금통위 결과에 따라 대출 전략도 달라질 수 있으니 브리핑에서 미리 확인해두세요!",
    "맥락을 한 번에 정리해뒀으니 훑어봐 주세요!",
]


def test_대표님이_고친_쪽은_통과한다():
    """린트가 정답지를 걸면 그 린트는 틀린 것이다.

    앞에서부터 쌓아가며 본다. 4편을 연달아 보내도 아무것도 걸리지 않아야
    한다 - 네 편 모두 느낌표로 끝나지만 그건 반복이 아니다.
    """
    for i, note in enumerate(FIXED):
        recent = list(reversed(FIXED[:i]))
        assert run_mod._lint_group_note(note, recent) == [], f"오탐: {note[-30:]}"


def test_초안에서_고쳐진_것이_걸린다():
    """DRAFT 1번(맨손 안내형)·3번(중립 사실 마침표)·4번(편집 사정)."""
    for idx in (0, 2, 3):
        assert run_mod._lint_group_note(DRAFT[idx], []), f"못 잡는다: {DRAFT[idx][-30:]}"


def test_자모가_안내형을_살린다():
    """같은 "~보세요!"가 앞의 "ㅠ" 한 자로 갈렸다.

    "담았어요. 한번 읽어보세요!"는 지워지고 "낳았습니다ㅠ 꼭 확인해보세요!"는
    남았다. 감정 신호 없이 사실 뒤에 붙는 안내형이 발송 안내문으로 읽힌다.
    """
    bare = "오늘 굵직한 뉴스를 담았어요. 한번 읽어보세요!"
    hits = run_mod._lint_group_note(bare, [])
    assert any("자모" in h for h in hits), hits
    # ㅠ 하나를 넣으면 통과한다.
    assert run_mod._lint_group_note("오늘 굵직한 뉴스를 담았어요ㅠ 한번 읽어보세요!", []) == []
    # 이모지도 감정 신호다.
    assert run_mod._lint_group_note("오늘 굵직한 뉴스를 담았어요💚 한번 읽어보세요!", []) == []


def test_편집_사정_설명이_걸린다():
    """어느 뉴스를 앞에 놨는지는 독자 일이 아니다."""
    hits = run_mod._lint_group_note("숫자가 많은 날이라 급한 것부터 앞에 뒀습니다!", [])
    assert any("편집 사정" in h for h in hits), hits
    # 그 자리에 독자 질문이 들어가면 통과한다.
    assert run_mod._lint_group_note("왜 이런 일이 생기는지 같이 정리해봤습니다!", []) == []


def test_마침표로_닫으면_걸린다():
    """중립 사실을 마침표로 통보하면 사람이 쓴 한마디가 아니다.

    "다음 금통위가 11/26이에요."가 "11/26로 같이 알아둡시다!"로 고쳐졌다.
    """
    hits = run_mod._lint_group_note("성장률은 예상의 3배였어요. 다음 금통위가 11/26이에요.", [])
    assert any("마침표" in h for h in hits), hits


def test_합니다체를_마침표로_닫으면_걸린다():
    """공문처럼 딱딱해진다. 느낌표로 맺거나 해요체로 바꾼다."""
    hits = run_mod._lint_group_note("왜 이런 일이 생기는지 같이 정리해봤습니다.", [])
    assert any("합니다체" in h for h in hits), hits
    assert run_mod._lint_group_note("왜 이런 일이 생기는지 같이 정리해봤습니다!", []) == []


def test_안내형이_연달아_나오면_걸린다():
    """안내형은 금지가 아니라 빈도 상한이다. 쓸 수는 있고 매일은 아니다."""
    # 최근에 안내형이 없으면 자모를 붙인 안내형은 통과한다.
    clean = ["같이 알아둡시다!", "같이 정리해봤습니다!"]
    assert run_mod._lint_group_note("뉴스를 담았어요ㅠ 한번 읽어보세요!", clean) == []
    # 최근 3편에 이미 있으면 걸린다. 표현을 바꿔도 같다.
    for note in REAL_NOTES:
        hits = run_mod._lint_group_note(note, ["어제 것도 한번 훑어보세요!"])
        assert hits, f"린트가 못 잡는다: {note}"


def test_ㅠ를_최근_3편에_두_번_썼으면_걸린다():
    """"ㅠ 매일 남발하지 말라"는 지시를 받았다 (2026-11-06).

    처음엔 3편 전부일 때만 걸게 해뒀는데 그건 4편 연속을 허용하는 것이었다.
    느낌표가 57편 중 56편이 된 경로와 같다 - 상한이 느슨하면 거기까지 간다.
    """
    two = ["담아봤습니다ㅠ", "흐름만 짚었어요!", "정리해봤습니다ㅠ"]
    hits = run_mod._lint_group_note("오늘도 조용했어요ㅠ", two)
    assert any("ㅠ" in h and "매일" in h for h in hits), hits
    # 최근 3편에 한 번만 있으면 아직 상한이 아니다.
    one = ["담아봤습니다ㅠ", "흐름만 짚었어요!", "같이 알아둡시다!"]
    assert run_mod._lint_group_note("오늘도 조용했어요ㅠ", one) == []


def test_자모_종류를_따로_센다():
    """ㅠ가 막혔다고 ㅎㅎ까지 막히면 가라앉은 날과 평온한 날이 같아진다."""
    recent = ["담아봤습니다ㅠ", "짚어봤습니다ㅠ", "정리해봤습니다ㅠ"]
    assert run_mod._lint_group_note("오늘은 좀 가벼웠어요ㅎㅎ", recent) == []


def test_자모가_없는_날은_안내형을_빼라고_적혀있다():
    """자모를 안내형 허가증으로 쓰려고 억지로 붙이면 그게 ㅠ 남발이 된다."""
    src = (ROOT / "pipeline" / "summarize.py").read_text(encoding="utf-8")
    assert '"ㅠ"를 매일 쓰지 않는다' in src
    assert "안내형을 빼고" in src
    assert "평온한 날에 \"ㅠ\"를 붙이는 것은" in src


def test_종결부호가_연달아_같은_것은_더_보지_않는다():
    """수정본 4편이 모두 느낌표였다. 섞는 자리는 종결부호가 아니라 자모다."""
    recent = ["담아봤습니다!", "짚어봤습니다!", "같이 알아둡시다!"]
    hits = run_mod._lint_group_note("왜 그런지 같이 정리해봤습니다!", recent)
    assert not any("연달아" in h for h in hits), hits
    src = (ROOT / "pipeline" / "run.py").read_text(encoding="utf-8")
    assert "연달아 \"{mark}\"로 끝났는데" not in src


def test_그룹톡_멘트는_안내형_권유_린트의_대상이_아니다():
    """본문에서 "꼭 확인해"는 권유지만, 멘트에서는 대표님이 쓴 한마디다.

    한 목록으로 묶어두면 2026-11-06 수정본이 매일 경고로 뜬다. 멘트의 안내형
    과용은 _lint_group_note가 빈도로 따로 본다.
    """
    note = {"group_note": "엇갈린 반응을 낳았습니다ㅠ 꼭 확인해보세요!"}
    assert run_mod._lint_pushy(note) == []
    # 투자 판단 권유는 멘트에서도 걸린다.
    assert run_mod._lint_pushy({"group_note": "지금이 노려볼 만한 기회예요!"})
    # 본문에서는 안내형도 그대로 걸린다.
    assert run_mod._lint_pushy({"news_cards": [{"why_for_workers": "공고를 꼭 확인해 보세요"}]})


def test_안내형을_아예_금지하지는_않는다():
    """전부 빼지 말라는 지시를 받았다. 금지가 아니라 빈도 상한이다."""
    src = (ROOT / "pipeline" / "summarize.py").read_text(encoding="utf-8")
    assert '"~보세요" 계열로 끝내지 않는다' not in src
    assert '"~보세요!"는 쓸 수 있다' in src


def test_감정은_문장으로만_금지된다():
    """자모 한 개는 없던 일을 서술하지 않으면서 톤만 얹는다."""
    src = (ROOT / "pipeline" / "summarize.py").read_text(encoding="utf-8")
    assert "감정을 문장으로 지어내지 않는다" in src
    assert "자모 한 개는 다르다" in src
    assert "마무리 동작을 억지로 붙이지 않는다" in src
    # 내가 제안했다가 퇴짜 맞은 두 형태가 되살아나면 안 된다.
    assert "내 반응으로 끝내기" not in src
    assert "독자에게 묻기" not in src


def test_수정_전후가_프롬프트에_남아있다():
    """규칙만 적어두면 다음에 또 "담담하게 끝내라"로 흘러간다.

    실제로 무엇이 어떻게 고쳐졌는지가 같이 있어야 방향이 유지된다.
    """
    src = (ROOT / "pipeline" / "summarize.py").read_text(encoding="utf-8")
    for fragment in (
        "같이 알아둡시다",          # 같이 하자
        "담아봤습니다",              # ~해봤습니다로 낮추기
        "낳았습니다ㅠ 꼭 확인해보세요",  # 자모 뒤의 안내형
        "편집 사정은 쓰지 않는다",     # 앞에 뒀습니다 삭제
        "중립 사실로 조용히 닫지 않는다",
    ):
        assert fragment in src, fragment


def test_최근_멘트와_끝_어절이_같으면_걸린다():
    """같은 어절로 끝나면 독자에겐 같은 말이다.

    실제로 "읽어보세요!"가 16편, "펼쳐보세요!"가 9편이었다. 금지 범위가
    최근 3~4편이라 네댓 개를 돌려쓰면 규칙은 지켜지면서 반복이 남았다.
    """
    recent = ["숫자를 풀어서 담았어요!", "맥락을 짚었어요!", "흐름을 담았어요!"]
    hits = run_mod._lint_group_note("오늘은 흐름만 짚었어요!", recent)
    assert any("끝 어절" in h for h in hits), hits


def test_프롬프트에서_느낌표_강제를_뺐다():
    src = (ROOT / "pipeline" / "summarize.py").read_text(encoding="utf-8")
    assert "마지막 문장은 반드시 느낌표" not in src
    assert "느낌표로 종료" not in src
    # 느낌표가 기본값이라는 것과 "매일 같은 형태 금지"는 다른 층의 규칙이다.
    assert "종결은 느낌표가 기본이다" in src
    assert "반복으로 읽히는 건" in src


def test_린트가_멘트_때문에_발행을_막지_않는다():
    """톤 판단에는 오탐이 있다. 오탐 하나로 브리핑이 안 나가는 게 더 비싸다."""
    for note in DRAFT + FIXED + REAL_NOTES + ["", "   "]:
        assert isinstance(run_mod._lint_group_note(note, REAL_NOTES), list)
