"""카카오 refresh_token 교체 처리 회귀 테스트.

2026-10-20 사고 기록:
  카카오가 refresh_token을 교체했고, 코드는 (1) 새 토큰을 공개 Actions 로그에
  평문으로 찍고 (2) 러너의 임시 파일에만 저장한 뒤 "수동으로 갱신하세요"
  경고만 남겼다. Secret은 옛 토큰 그대로였고 10/21부터 KOE322로 죽었다.
  카톡 실패는 best-effort warning이라 워크플로는 success로 끝나, 이틀 동안
  아무 신호도 없었다.

여기서 지키는 것:
  - 교체된 토큰은 어디에도 평문으로 남지 않는다
  - PAT이 있으면 Secret을 자기 손으로 갱신한다 (인자 아닌 stdin으로)
  - 못 갱신하면 조용히 넘어가지 않는다
  - 카톡 실패는 워크플로가 볼 수 있는 출력으로 남는다
  - 그 실패 처리 스텝은 publ 발송 **뒤에** 있다 (앞이면 구독자 발송을 막는다)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import notify_kakao, run as run_mod  # noqa: E402

ROTATED = "ROTATED-REFRESH-TOKEN-must-never-be-printed"


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def kakao_env(tmp_path, monkeypatch):
    """토큰 파일을 tmp로 돌리고 카카오 응답을 가짜로 바꾼다."""
    monkeypatch.setattr(notify_kakao, "TOKENS_PATH", tmp_path / ".kakao_tokens.json")
    monkeypatch.setenv("KAKAO_REST_API_KEY", "dummy-key")
    monkeypatch.delenv("KAKAO_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("KAKAO_REFRESH_TOKEN", "old-token")
    monkeypatch.setattr(
        notify_kakao.requests,
        "post",
        lambda *a, **k: _Resp(
            {
                "access_token": "new-access",
                "expires_in": 21599,
                "refresh_token": ROTATED,
                "refresh_token_expires_in": 5183999,
            }
        ),
    )
    return tmp_path


def test_교체된_토큰은_로그에_평문으로_남지_않는다(kakao_env, monkeypatch, caplog, capsys):
    """공개 저장소의 Actions 로그는 누구나 본다. 10/20에 그렇게 노출됐다."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv("SECRETS_PAT", raising=False)

    with caplog.at_level("DEBUG"):
        notify_kakao.refresh_access_token()

    out = capsys.readouterr().out
    assert ROTATED not in caplog.text, "로그에 토큰이 찍혔다"
    # ::add-mask:: 한 줄만 토큰을 담을 수 있다. Actions가 이후 출력을 가려준다.
    masked = [l for l in out.splitlines() if l.startswith("::add-mask::")]
    assert masked == [f"::add-mask::{ROTATED}"]
    for line in out.splitlines():
        if not line.startswith("::add-mask::"):
            assert ROTATED not in line, f"토큰이 노출된 줄: {line}"


def test_PAT이_있으면_Secret을_stdin으로_갱신한다(kakao_env, monkeypatch):
    """--body로 넘기면 프로세스 인자 목록에 토큰이 남는다."""
    calls = []

    class _Done:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return _Done()

    monkeypatch.setattr(notify_kakao.subprocess, "run", fake_run)
    monkeypatch.setenv("SECRETS_PAT", "pat-123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    notify_kakao.refresh_access_token()

    assert len(calls) == 1, "Secret 갱신을 시도하지 않았다"
    cmd, kw = calls[0]
    assert cmd[:4] == ["gh", "secret", "set", "KAKAO_REFRESH_TOKEN"]
    assert "--repo" in cmd and "owner/repo" in cmd
    assert ROTATED not in cmd, "토큰이 명령 인자로 들어갔다"
    assert kw["input"] == ROTATED
    assert kw["env"]["GH_TOKEN"] == "pat-123"


def test_Secret_갱신에_실패하면_조용히_넘어가지_않는다(kakao_env, monkeypatch, capsys):
    """다음 실행부터 끊긴다는 걸 이 시점에 알려야 한다."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("SECRETS_PAT", raising=False)

    notify_kakao.refresh_access_token()

    assert "::error" in capsys.readouterr().out


def test_교체된_토큰은_파일에_저장된다(kakao_env, monkeypatch):
    """로컬 개발 머신에서는 파일이 남아야 다음 실행이 이어진다."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("SECRETS_PAT", raising=False)

    notify_kakao.refresh_access_token()

    saved = json.loads(notify_kakao.TOKENS_PATH.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == ROTATED


def test_카톡_실패는_워크플로가_읽을_출력으로_남는다(tmp_path, monkeypatch, capsys):
    """warning 한 줄로 끝나면 성공한 실행 로그에 묻혀 아무도 못 본다."""
    out_file = tmp_path / "gh_output"
    out_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))

    run_mod._flag_kakao_failure(RuntimeError("refresh 실패: 400 KOE322"))

    assert "kakao_failed=true" in out_file.read_text(encoding="utf-8")
    assert "::error" in capsys.readouterr().out


def test_로컬_실행에서는_annotation을_찍지_않는다(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    run_mod._flag_kakao_failure(RuntimeError("boom"))
    assert capsys.readouterr().out == ""


def test_실패_처리_스텝은_publ_트리거_뒤에_있다():
    """앞에 두면 카톡 하나 때문에 구독자 발송이 멈춘다.

    카톡은 본인 확인용이고 그룹톡·아티클이 실제 발송이다. 순서가 뒤집히면
    알림 채널 장애가 서비스 장애로 번진다.
    """
    wf = yaml.safe_load((ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8"))
    names = [s.get("name", "") for s in wf["jobs"]["build-and-publish"]["steps"]]
    trigger = next(i for i, n in enumerate(names) if "Trigger publ" in n)
    guard = next(i for i, n in enumerate(names) if "카톡 알림 실패" in n)
    assert guard > trigger
