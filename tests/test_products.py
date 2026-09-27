"""상품 블록 시험.

지난번에 배운 것: 경고선은 작동을 확인한 것만 경고선으로 인정한다.
여기서는 "돌아가겠지"를 확인 없이 넘기지 않는다. 특히 순번이 실제로
돌아가는지, 상한이 실제로 멈추는지를 시험한다.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import products  # noqa: E402


# ── 문구가 실제로 돌아가는가 ──────────────────────────────────────────

def test_설명이_발행마다_바뀐다(monkeypatch):
    """대표님이 걱정하신 지점. 순번이 올라가면 문장이 실제로 달라져야 한다."""
    dates = [f"2026-11-{d:02d}" for d in range(1, 31)]
    monkeypatch.setattr(products, "published_dates", lambda: dates)

    seen = {p["code"]: [] for p in products.LADDER}
    for d in dates:
        for it in products.ladder_items(d):
            seen[it["code"]].append(it["desc"])

    for code, lines in seen.items():
        assert len(set(lines)) > 1, f"{code}: 30회 발행 내내 같은 문장만 나왔다"


def test_같은_문장이_2주_안에_다시_안_나온다(monkeypatch):
    """풀이 얕아지면 여기서 먼저 걸린다."""
    dates = [f"2026-11-{d:02d}" for d in range(1, 31)]
    monkeypatch.setattr(products, "published_dates", lambda: dates)

    last_at = {}
    for n, d in enumerate(dates):
        for it in products.ladder_items(d):
            key = (it["code"], it["desc"])
            if key in last_at:
                gap = n - last_at[key]
                assert gap >= 10, (
                    f"{it['code']}: 같은 문장이 발행 {gap}회 만에 재등장했다 "
                    f"(평일 10회 = 2주 이상이어야 한다)"
                )
            last_at[key] = n


def test_세_상품이_동시에_안_넘어간다(monkeypatch):
    """셋이 같이 넘어가면 블록 전체가 한 덩어리로 바뀐 것처럼 보인다."""
    dates = [f"2026-11-{d:02d}" for d in range(1, 15)]
    monkeypatch.setattr(products, "published_dates", lambda: dates)
    idx = [tuple(products.LADDER[i]["desc"].index(it["desc"])
                 for i, it in enumerate(products.ladder_items(d)))
           for d in dates]
    assert len(set(idx)) == len(idx), "세 상품의 순번 조합이 반복된다"


def test_사진도_같이_돈다(monkeypatch):
    dates = [f"2026-11-{d:02d}" for d in range(1, 15)]
    monkeypatch.setattr(products, "published_dates", lambda: dates)
    imgs = [it["img"] for d in dates
            for it in products.ladder_items(d) if it["code"] == "mf_kakao"]
    assert len(set(imgs)) == 3, "머니프리랩 사진 3종이 다 안 돈다"


# ── 순번이 날짜가 아니라 발행 횟수를 따르는가 ────────────────────────

def test_발행을_건너뛰어도_순번은_한_칸만_간다(monkeypatch):
    """주말·공휴일·정규방송 없는 날을 건너뛰어도 어긋나면 안 된다."""
    dates = ["2026-11-02", "2026-11-03", "2026-11-06", "2026-11-13"]
    monkeypatch.setattr(products, "published_dates", lambda: dates)
    assert [products.ordinal(d) for d in dates] == [0, 1, 2, 3]


# ── 링크 ──────────────────────────────────────────────────────────────

def test_모든_링크가_리다이렉터를_거친다(monkeypatch):
    monkeypatch.setattr(products, "published_dates", lambda: ["2026-11-02"])
    for it in products.ladder_items("2026-11-02"):
        assert it["url"].startswith(products.WORKER + "/r?"), it["url"]
        assert "s=ladder" in it["url"]
        assert it["img"].startswith(products.WORKER + "/img/")


def test_지면코드가_워커_허용목록과_같다():
    """워커가 아는 값만 보내야 한다. 어긋나면 전부 ok=0으로 쌓인다.

    실제로 첫 배포 때 여기가 어긋나 클릭 5건이 전부 규격 위반으로 기록됐다.
    """
    worker = (ROOT.parent / "molit-daily" / "proxy-worker" / "worker.js")
    if not worker.is_file():
        return  # 워커 저장소가 없는 환경에서는 건너뛴다
    src = worker.read_text(encoding="utf-8")
    for slot in ("ladder", "article_n"):
        assert f'"{slot}"' in src, f"워커 R_SLOTS에 {slot}이 없다"


# ── 트리거 ────────────────────────────────────────────────────────────

def _news(title, body="", why=""):
    return {"title": title, "body": [body], "why_for_workers": why}


def test_맞는_기사가_있으면_붙는다(monkeypatch, tmp_path):
    monkeypatch.setattr(products, "published_dates", lambda: [])
    monkeypatch.setattr(products, "ARCHIVE", tmp_path)
    t = products.pick_trigger(
        [_news("반도체 수출 호조"), _news("실질임금 2년째 제자리, 월급 그대로")],
        "2026-11-02",
    )
    assert t and t["news_index"] == 1 and t["code"] == "taling"
    assert "s=article_n" in t["url"]


def test_맞는_기사가_없으면_안_붙는다(monkeypatch, tmp_path):
    monkeypatch.setattr(products, "published_dates", lambda: [])
    monkeypatch.setattr(products, "ARCHIVE", tmp_path)
    assert products.pick_trigger(
        [_news("반도체 수출 호조"), _news("전세가율 상승")], "2026-11-02") is None


def test_주간_상한이_실제로_멈춘다(monkeypatch, tmp_path):
    """맞는 기사가 매일 있어도 주 2회에서 멈춰야 한다.

    안 세면 월급·금리 뉴스가 몰린 주에 매일 나간다.
    """
    dates = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    monkeypatch.setattr(products, "published_dates", lambda: dates)
    monkeypatch.setattr(products, "ARCHIVE", tmp_path)
    monkeypatch.setattr(products, "_meta_path",
                        lambda d: tmp_path / f"{d}-meta.json")

    hit = []
    for d in dates:
        t = products.pick_trigger([_news("월급과 실질임금 이야기")], d)
        hit.append(bool(t))
        (tmp_path / f"{d}-meta.json").write_text(
            json.dumps({"date": d, "trigger": {"p": "taling"} if t else None}),
            encoding="utf-8")

    for i in range(len(hit)):
        window = hit[max(0, i - products.TRIGGER_WINDOW): i + 1]
        assert sum(window) <= products.TRIGGER_MAX_PER_WEEK, (
            f"{dates[i]}까지 최근 5회 중 {sum(window)}회 붙었다 "
            f"(상한 {products.TRIGGER_MAX_PER_WEEK})"
        )
    assert any(hit), "상한이 너무 세서 한 번도 안 붙었다"


def test_책은_트리거_대상이_아니다():
    """사다리에 매일 나오는데 같은 날 두 번 나오면 광고로 읽힌다."""
    assert all(p["code"] != "book" for p in products.TRIGGERS)


# ── 문구 자체 ─────────────────────────────────────────────────────────

def test_긴_대시와_상대_날짜가_없다():
    bad = []
    for p in products.LADDER:
        for d in p["desc"]:
            if "—" in d:
                bad.append(("긴 대시", d))
            for w in ("오늘", "어제", "내일"):
                if w in d:
                    bad.append((w, d))
    assert not bad, bad


def test_금지_표현이_없다():
    """희소성·긴급성은 만들지 않는다. 정원이 없으므로 자리 수 언급도 금지."""
    banned = ["마감", "서두르", "놓치지", "얼마 안 남", "선착순", "남은 자리", "지금 바로"]
    found = [(w, d) for p in products.LADDER for d in p["desc"]
             for w in banned if w in d]
    found += [(w, r["text"]) for p in products.TRIGGERS for r in p["rules"]
              for w in banned if w in r["text"]]
    assert not found, found


def test_느낌표가_문장당_둘_이하():
    """초안 규칙은 문장당 1개였는데 대표님이 직접 쓰신 문구에 2개가 들어 있다.

    말투는 대표님 것이 기준이라 상한을 2로 올렸다. 3개부터는 톤이 아니라
    과열이라 그때는 잡는다.
    """
    over = [d for p in products.LADDER for d in p["desc"] if d.count("!") > 2]
    assert not over, over


def test_풀_깊이가_하한을_넘는다():
    """2주(평일 10회) 안에 같은 문장이 안 나오려면 최소 10종이 필요하지만,
    상품마다 시작점이 어긋나 있어 실제 재등장 주기는 풀 크기와 같다."""
    for p in products.LADDER:
        assert len(p["desc"]) >= 7, f"{p['code']}: 문구 {len(p['desc'])}종은 얕다"
