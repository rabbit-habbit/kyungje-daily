"""share.html을 인라인 스타일 강화 버전으로 변환.

용도:
  · 매일 워크플로가 share.html 렌더 후 이 모듈로 인라인 버전 생성
  · docs/archive/{date}-share-inline.html 로 저장
  · 카톡 알림의 "공유용 보기" 링크를 이 인라인 버전으로 연결
  · 블로그·티스토리·워드프레스 등에 붙여넣을 때 스타일 유실 없음

처리 내용:
  1. :root { --foo: X } CSS 변수를 실제 값으로 치환 (블로그가 :root 스트립해도 안전)
  2. premailer로 <style> → 각 요소의 style="..." 인라인
  3. body 안에 배경색 wrapper 삽입 (body 태그 제거돼도 배경 유지)
  4. 카드/박스류에 !important 강제 배경·테두리 (블로그 CSP 방어)
"""
from __future__ import annotations
import logging
import re

import premailer

logging.getLogger("CSSUTILS").setLevel(logging.CRITICAL)


CARD_STYLE = (
    "background:#ffffff!important;border:1px solid #EFE8D6!important;"
    "border-radius:14px!important;padding:18px!important;margin-bottom:12px!important;"
    "box-shadow:0 2px 6px rgba(0,0,0,0.04)!important;"
)
BOX_STYLE = (
    "background:#FFF9E6!important;border-left:4px solid #FFD43B!important;"
    "padding:14px 16px!important;border-radius:8px!important;margin:12px 0!important;"
)
INSIGHT_STYLE = (
    "background:#FFF3D0!important;"
    "background:linear-gradient(135deg,#FFF8DC 0%,#FFE8A3 100%)!important;"
    "border:1px solid #FFD97A!important;border-radius:16px!important;"
    "padding:20px!important;margin:20px 0!important;"
)
PULSE_STYLE = (
    "background:#ffffff!important;border:1px solid #EFE8D6!important;"
    "border-radius:14px!important;padding:20px!important;margin-bottom:16px!important;"
    "box-shadow:0 2px 6px rgba(0,0,0,0.04)!important;"
)


def _resolve_css_vars(html: str) -> str:
    """:root { --foo: X } 를 실제 값으로 치환. var(--foo) 및 var(--foo, fallback) 모두."""
    vars_map: dict[str, str] = {}
    for block in re.findall(r":root\s*\{([^}]+)\}", html):
        for line in block.split(";"):
            m = re.match(r"\s*(--[\w-]+)\s*:\s*(.+?)\s*$", line.strip())
            if m:
                vars_map[m.group(1)] = m.group(2).strip()

    def _resolve(match: re.Match) -> str:
        return vars_map.get(match.group(1), match.group(0))

    return re.sub(r"var\((--[\w-]+)(?:,\s*[^)]+)?\)", _resolve, html)


def _add_style(html: str, class_name: str, extra: str) -> str:
    """class 매칭 요소의 style 속성 끝에 extra 추가. style 없으면 새로 생성."""
    def _repl(m: re.Match) -> str:
        existing = m.group(2) or ""
        if existing.strip() and not existing.strip().endswith(";"):
            existing += ";"
        return f'class="{m.group(1)}" style="{existing}{extra}"'

    p1 = re.compile(
        rf'class="([^"]*\b{re.escape(class_name)}\b[^"]*)"\s*style="([^"]*)"'
    )
    html = p1.sub(_repl, html)
    p2 = re.compile(
        rf'class="([^"]*\b{re.escape(class_name)}\b[^"]*)"(?!\s*style)'
    )
    html = p2.sub(lambda m: f'class="{m.group(1)}" style="{extra}"', html)
    return html


def build_inline(html: str, base_url: str | None = None) -> str:
    """share.html 원본 문자열 → 인라인 강화 문자열."""
    # 1) CSS 변수 치환
    html = _resolve_css_vars(html)

    # 2) premailer 인라인
    inlined = premailer.transform(
        html,
        base_url=base_url,
        keep_style_tags=False,
        strip_important=False,
    )

    # 3) body wrapper (배경 유지)
    inlined = re.sub(
        r"(<body[^>]*>)",
        r'\1<div style="background:#FFFDF5;padding:0;margin:0;">',
        inlined,
        count=1,
    )
    inlined = re.sub(r"(</body>)", r"</div>\1", inlined, count=1)

    # 4) 카드/박스류 강제 배경·테두리
    inlined = _add_style(inlined, "news-card", CARD_STYLE)
    inlined = _add_style(inlined, "data-box", BOX_STYLE)
    inlined = _add_style(inlined, "why-box", BOX_STYLE)
    inlined = _add_style(inlined, "insight-box", INSIGHT_STYLE)
    inlined = _add_style(inlined, "market-pulse", PULSE_STYLE)

    return inlined


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="share.html → 인라인 강화")
    parser.add_argument("input", help="입력 HTML 파일 또는 '-' (stdin)")
    parser.add_argument("--out", help="출력 파일 (미지정 시 stdout)")
    parser.add_argument("--base-url", help="premailer base_url", default=None)
    args = parser.parse_args()

    if args.input == "-":
        html = sys.stdin.read()
    else:
        html = Path(args.input).read_text(encoding="utf-8")

    result = build_inline(html, base_url=args.base_url)

    if args.out:
        Path(args.out).write_text(result, encoding="utf-8")
        print(f"✓ {args.out} ({len(result):,} bytes)", file=sys.stderr)
    else:
        print(result)
