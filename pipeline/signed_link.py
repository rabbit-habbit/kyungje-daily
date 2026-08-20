"""유료 브리핑 서명 만료 링크 생성 (Cloudflare Worker /brief 게이트와 쌍).

앱 코드: k = 경제 share-inline (이 리포 전용).
워커: economy-proxy (2026-08-20 분리. 이전에는 국토부와 공용인 molit-proxy를 썼다).
  ※ LINK_SIGN_KEY도 이때 경제 전용으로 분리 발급함 - 국토부 키와 다르다.
유효기간 기본 5일 (LINK_TTL_DAYS env로 조정, 점진 축소 예정 - 최종 목표 1일).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

WORKER_BASE = "https://economy-proxy.rabbit-habbit.workers.dev"


def signed_brief_url(app: str, date_iso: str) -> str:
    key = os.environ.get("LINK_SIGN_KEY", "")
    if not key:
        raise RuntimeError("LINK_SIGN_KEY 환경변수가 필요합니다 (서명 링크 생성용).")
    ttl_days = float(os.environ.get("LINK_TTL_DAYS", "5"))
    exp = int(time.time() + ttl_days * 86400)
    sig = hmac.new(key.encode(), f"{app}/{date_iso}/{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{WORKER_BASE}/brief/{app}/{date_iso}?e={exp}&s={sig}"
