"""publ.biz 관리자 콘솔 그룹 채팅방에 매일 브리핑 링크 자동 게시.

Playwright 기반 브라우저 자동화 (publ은 공식 API 없음).

환경변수:
  PUBL_EMAIL     — 로그인 이메일 (필수)
  PUBL_PASSWORD  — 로그인 비밀번호 (필수)
  PUBL_ROOM_URL  — 게시할 그룹 채팅방 URL (선택, 기본값 아래 상수)
  PUBL_HEADLESS  — 'false' 하면 브라우저 창 표시 (디버깅용, 기본 true)

CLI:
  python pipeline/notify_publ.py --message "🐰 오늘 브리핑 → https://..."
  python pipeline/notify_publ.py --today   # date 기반 자동 메시지 생성
  python pipeline/notify_publ.py --today --dry-run   # 발송 없이 메시지만 확인
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SESSION_PATH = ROOT / ".publ_session.json"  # 로그인 세션 저장 (.gitignore)

LOGIN_URL = "https://console.publ.biz/"
DEFAULT_ROOM_URL = (
    "https://console.publ.biz/channels/L2NoYW5uZWxzLzIzMDY0"
    "/p-apps/D00003/chat/group/basic/rooms/bbe171db-83d3-42b1-8cc2-041d5dc0e395"
)
PAGES_BASE = "https://rabbit-habbit.github.io/kyungje-daily"

KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _kst_today_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _load_group_note(date_iso: str) -> str:
    """summarize가 생성해 docs/에 커밋해 둔 오늘치 그룹톡 멘트를 읽는다.

    daily.yml이 `docs/archive/{date}-meta.json`에 써 두고 커밋한다.
    파일이 없거나 비어있으면 빈 문자열 → 기존 고정 문구만 발송 (하위 호환).
    """
    path = Path(__file__).resolve().parent.parent / "docs" / "archive" / f"{date_iso}-meta.json"
    if not path.is_file():
        logger.warning("멘트 파일 없음: %s - 기본 문구만 발송", path.name)
        return ""
    try:
        note = (json.loads(path.read_text(encoding="utf-8")).get("group_note") or "").strip()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("멘트 파일 읽기 실패 %s: %s - 기본 문구만 발송", path.name, exc)
        return ""
    if not note:
        logger.warning("멘트가 비어있음 (%s) - 기본 문구만 발송", path.name)
    return note


try:
    from pipeline.signed_link import signed_brief_url
except ImportError:  # 스크립트 직접 실행 시 (python pipeline/notify_publ.py)
    from signed_link import signed_brief_url


# publ 그룹톡은 300자에서 메시지를 자른다. 이모지는 2자로 세는 JS 문자열 길이 기준.
# 넘치면 문장 중간이 잘려 "...천천히" 처럼 끝난다 (8/21 사고).
PUBL_LIMIT = 300
_SENTENCE_END = ("!", "?", ".", "요", "다")


def _js_len(text: str) -> int:
    """publ이 세는 방식(JS UTF-16 코드유닛). 이모지 등 BMP 밖 문자는 2로 센다."""
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


def _fit_note(note: str, head: str) -> str:
    """멘트가 제한을 넘으면 문장 경계에서 줄인다. 단어 중간 절단은 하지 않는다."""
    budget = PUBL_LIMIT - _js_len(head) - 2  # 2 = 사이 개행 두 줄
    if budget <= 0:
        logger.warning("링크만으로 publ 제한을 채워 멘트를 생략합니다.")
        return ""
    if _js_len(note) <= budget:
        return note

    # 예산 안에서 마지막 문장 종결 지점을 찾는다.
    cut, acc = 0, 0
    for i, ch in enumerate(note):
        acc += 2 if ord(ch) > 0xFFFF else 1
        if acc > budget:
            break
        if ch in _SENTENCE_END:
            cut = i + 1
    if cut:
        trimmed = note[:cut].rstrip()
        # 종결어미(요/다)에서 끊긴 경우 느낌표를 붙여 대표님 말투로 마무리한다.
        # ("...훨씬 이해가 잘 될 거예요" -> "...훨씬 이해가 잘 될 거예요!")
        if trimmed and trimmed[-1] not in "!?.":
            trimmed = trimmed.rstrip(",·- ") + "!"
        logger.warning(
            "멘트 %d자가 publ 제한을 넘어 문장 단위로 줄였습니다 (%d자). "
            "프롬프트의 120자 규칙을 확인하세요.", len(note), len(trimmed),
        )
        return trimmed

    logger.warning(
        "멘트 %d자가 제한을 넘는데 문장 경계를 찾지 못해 생략합니다.", len(note)
    )
    return ""


def _today_message() -> str:
    """오늘 날짜 기반 메시지 (M/D · 인라인 URL · 하루치 멘트)."""
    now = datetime.now(KST)
    date_short = f"{now.month}/{now.day}"
    date_iso = now.strftime("%Y-%m-%d")
    url = signed_brief_url("k", date_iso)
    msg = (
        f"🐰 [{date_short} 데일리 경제 브리핑]\n"
        f"매일 5분, 오늘의 경제 한입!🍰\n"
        f"→ {url}"
    )
    note = _load_group_note(date_iso)
    if note:
        # URL 다음에 빈 줄을 두고 멘트를 붙인다 (URL이 줄 끝이라 링크 인식에 영향 없음).
        note = _fit_note(note, msg)
        if note:
            msg = f"{msg}\n\n{note}"
    return msg


def _perform_login(page, email: str, password: str) -> None:
    """publ 로그인. 이메일·비밀번호 form 자동 감지."""
    logger.info("로그인 페이지 이동: %s", LOGIN_URL)
    page.goto(LOGIN_URL, wait_until="networkidle")

    # 이메일 필드 (readonly·autofill 방지용 fake 필드 제외)
    email_input = page.locator(
        'input[type="email"]:not([readonly]), '
        'input[name="email"]:not([readonly]):not([name="removeEmail"]), '
        'input[autocomplete="username"]:not([readonly]), '
        'input[placeholder*="이메일"]:not([readonly]), '
        'input[placeholder*="아이디"]:not([readonly])'
    ).first
    email_input.wait_for(state="visible", timeout=15_000)
    email_input.click()
    page.wait_for_timeout(200)
    email_input.fill(email)
    page.wait_for_timeout(400)

    # publ이 2단계 로그인이면 여기서 "다음" 버튼을 눌러야 password 필드가 뜸
    next_btn = page.locator(
        'button:has-text("다음"), button:has-text("계속"), button:has-text("Next")'
    ).first
    if next_btn.count() > 0 and next_btn.is_visible():
        next_btn.click()
        page.wait_for_timeout(1_500)

    # 비밀번호 필드 (readonly·autofill 방지 fake 필드 제외 · name=removePassword 배제)
    pw_input = page.locator(
        'input[type="password"]:not([readonly]):not([name="removePassword"]):not([tabindex="-1"])'
    ).first
    pw_input.wait_for(state="visible", timeout=15_000)
    pw_input.click()
    page.wait_for_timeout(200)
    pw_input.fill(password)
    page.wait_for_timeout(300)

    # 로그인 버튼: type=submit 우선, "로그인" 텍스트 fallback
    submit_btn = page.locator('button[type="submit"]:visible').first
    if submit_btn.count() == 0:
        submit_btn = page.get_by_role("button", name="로그인").first
    submit_btn.click()

    # 로그인 후 URL 전환 대기 (console 대시보드로 이동)
    page.wait_for_load_state("networkidle", timeout=20_000)
    page.wait_for_timeout(1_500)
    if "login" in page.url.lower():
        raise RuntimeError(f"로그인 실패로 보임 · 현재 URL: {page.url}")
    logger.info("로그인 성공 → %s", page.url)


def _send_message(page, room_url: str, message: str) -> None:
    logger.info("채팅방 이동: %s", room_url)
    page.goto(room_url, wait_until="networkidle")
    page.wait_for_timeout(1_500)  # 채팅 UI 로딩

    # 메시지 입력창: publ UI가 한/영 오갈 수 있어 다국어 placeholder 커버
    # (한글: "메시지를 입력해 주세요." · 영문: "Enter chat")
    input_box = page.locator(
        'textarea[placeholder*="메시지"], input[placeholder*="메시지"], '
        'textarea[placeholder*="Enter chat"], textarea[placeholder="Enter chat"], '
        'textarea[placeholder*="Type a message"], textarea[placeholder*="chat"], '
        '[contenteditable="true"]'
    ).first
    input_box.wait_for(state="visible", timeout=15_000)
    input_box.click()
    input_box.fill(message)
    page.wait_for_timeout(300)

    # 전송: Enter 시도 → 실패 시 전송 버튼 클릭
    try:
        input_box.press("Enter")
        page.wait_for_timeout(2_000)
    except Exception:
        pass

    # Enter가 안 먹으면 (일부 에디터는 Enter=줄바꿈) 버튼 클릭
    # 이미 전송됐으면 input이 비어있을 것
    remaining = input_box.input_value() if hasattr(input_box, "input_value") else ""
    if remaining and message in remaining:
        logger.info("Enter로 전송 안 됨 · 전송 버튼 클릭 시도")
        send_btn = page.locator(
            'button[aria-label*="전송"], button[aria-label*="Send"], button[type="submit"]'
        ).first
        if send_btn.count() > 0:
            send_btn.click()
            page.wait_for_timeout(2_000)

    logger.info("메시지 전송 완료")


def post_daily(
    message: str,
    room_url: str | None = None,
    headless: bool = True,
    use_session: bool = True,
) -> None:
    """publ 채팅방에 메시지 게시.

    - 세션 파일 있으면 로그인 skip → 방으로 바로 이동
    - 세션 만료·오류 시 재로그인
    """
    from playwright.sync_api import sync_playwright  # 지연 import (설치 안 된 환경 배려)

    email = os.environ.get("PUBL_EMAIL")
    password = os.environ.get("PUBL_PASSWORD")
    if not email or not password:
        raise RuntimeError("PUBL_EMAIL / PUBL_PASSWORD 환경변수가 필요합니다.")

    room_url = room_url or os.environ.get("PUBL_ROOM_URL", DEFAULT_ROOM_URL)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        session_available = use_session and SESSION_PATH.exists()
        # publ은 브라우저 로케일에 따라 UI 언어를 바꿈 → 한글로 고정
        context_kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "locale": "ko-KR",
            "extra_http_headers": {"Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5"},
        }
        if session_available:
            context_kwargs["storage_state"] = str(SESSION_PATH)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        try:
            if session_available:
                logger.info("세션 파일 로드: %s", SESSION_PATH.name)
                page.goto(room_url, wait_until="networkidle")
                page.wait_for_timeout(1_500)
                # 세션 만료 감지: 로그인 페이지로 리다이렉트됐으면 재로그인
                if "login" in page.url.lower() or "console.publ.biz" not in page.url:
                    logger.warning("세션 만료 · 재로그인")
                    _perform_login(page, email, password)
                    page.goto(room_url, wait_until="networkidle")
                    page.wait_for_timeout(1_500)
            else:
                _perform_login(page, email, password)

            _send_message(page, room_url, message)

            # 세션 저장 (다음 실행에서 로그인 skip)
            context.storage_state(path=str(SESSION_PATH))
            logger.info("세션 저장: %s", SESSION_PATH.name)
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", help="게시할 텍스트")
    parser.add_argument("--today", action="store_true", help="오늘 날짜 기반 자동 메시지")
    parser.add_argument("--room-url", help="publ 방 URL override")
    parser.add_argument("--no-session", action="store_true", help="세션 파일 무시 · 매번 재로그인")
    parser.add_argument("--headed", action="store_true", help="브라우저 창 표시 (디버깅)")
    parser.add_argument("--dry-run", action="store_true",
                        help="발송하지 않고 조립된 메시지만 출력 (발송 전 확인용)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.today:
        message = _today_message()
    elif args.message:
        message = args.message
    else:
        parser.error("--message 또는 --today 필요")

    logger.info("메시지:\n%s\n", message)

    if args.dry_run:
        print("-" * 46)
        print(message)
        print("-" * 46)
        print("※ --dry-run: 실제 발송하지 않았습니다.")
        raise SystemExit(0)

    headless = not args.headed
    if os.environ.get("PUBL_HEADLESS", "").lower() == "false":
        headless = False

    post_daily(
        message=message,
        room_url=args.room_url,
        headless=headless,
        use_session=not args.no_session,
    )
    print("✅ publ 게시 완료")
