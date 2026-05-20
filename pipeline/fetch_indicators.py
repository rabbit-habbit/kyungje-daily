"""7대 경제지표 수집.

국내 3개: 환율(USD/KRW), 코스피, 국고채10년
글로벌 4개: S&P500, 다우, WTI, 금(1g 한화)

기준금리(한국 2.50%, 미국 3.75%)는 고정값으로 별도 노출.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

import requests
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TROY_OZ_TO_GRAM = 31.1034768

POLICY_RATES = {
    "korea": {"name": "🇰🇷 한국 기준금리", "value": 2.50, "outlook": "동결 전망"},
    "us": {"name": "🇺🇸 미국 기준금리", "value": 3.75, "outlook": "인하 가능성"},
}


@dataclass
class Indicator:
    key: str
    name: str
    value: float
    prev: float
    change: float
    change_pct: float
    unit: str
    source: str
    fetched_at: str

    @property
    def direction(self) -> str:
        if self.change > 0:
            return "up"
        if self.change < 0:
            return "down"
        return "flat"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch_yf(ticker: str, name: str, key: str, unit: str) -> Indicator:
    """Fetch last 2 trading-day closes from Yahoo Finance."""
    hist = yf.Ticker(ticker).history(period="7d", auto_adjust=False)
    if hist.empty or len(hist) < 2:
        raise RuntimeError(f"Yahoo Finance returned insufficient data for {ticker}")
    last = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2])
    return Indicator(
        key=key,
        name=name,
        value=round(last, 4),
        prev=round(prev, 4),
        change=round(last - prev, 4),
        change_pct=round((last - prev) / prev * 100, 2),
        unit=unit,
        source=f"Yahoo Finance ({ticker})",
        fetched_at=_now_iso(),
    )


def fetch_usd_krw() -> Indicator:
    ind = _fetch_yf("KRW=X", "원/달러 환율", "usd_krw", "원")
    ind.value = round(ind.value, 2)
    ind.prev = round(ind.prev, 2)
    ind.change = round(ind.change, 2)
    return ind


def fetch_kospi() -> Indicator:
    return _fetch_yf("^KS11", "코스피", "kospi", "p")


def fetch_sp500() -> Indicator:
    return _fetch_yf("^GSPC", "S&P 500", "sp500", "p")


def fetch_dow() -> Indicator:
    return _fetch_yf("^DJI", "다우존스", "dow", "p")


def fetch_wti() -> Indicator:
    ind = _fetch_yf("CL=F", "WTI 원유", "wti", "$/배럴")
    ind.value = round(ind.value, 2)
    ind.prev = round(ind.prev, 2)
    ind.change = round(ind.change, 2)
    return ind


def fetch_gold_krw_per_gram(usd_krw_last: float, usd_krw_prev: float) -> Indicator:
    """KRW/g 환산 금 가격.

    중요: prev 금 USD 가격에는 prev USDKRW를 적용해야 환율 변동을 이중 계상하지 않음.
    (오늘 환율로 어제 금 가격 환산하면 환율 변동이 금 변동에 잘못 섞임)
    """
    base = _fetch_yf("GC=F", "금 (1g 한화)", "gold_krw_g", "원/g")
    last_krw_g = base.value * usd_krw_last / TROY_OZ_TO_GRAM
    prev_krw_g = base.prev * usd_krw_prev / TROY_OZ_TO_GRAM
    return Indicator(
        key="gold_krw_g",
        name="금 (1g 한화)",
        value=round(last_krw_g, 0),
        prev=round(prev_krw_g, 0),
        change=round(last_krw_g - prev_krw_g, 0),
        change_pct=round((last_krw_g - prev_krw_g) / prev_krw_g * 100, 2),
        unit="원/g",
        source="Yahoo Finance (GC=F) × USDKRW (last/prev 각각 적용)",
        fetched_at=_now_iso(),
    )


def _parse_te_yield(html: str) -> Optional[tuple[float, float]]:
    """Parse the country bond yield's Actual + Previous from tradingeconomics.

    한국 국채 10년 페이지 (`/south-korea/government-bond-yield`)는 다음 테이블들을 포함:
      table #0 'Bonds | Yield ...'     → "South Korea 10Y 4.24" (메인 yield + 변동)
      table #1 'Related | Last | ...'  → CPI, Interest Rate 등 다른 지표 (X)
      table #2 ' | Actual | Previous'  → 메인 10년물 yield Actual/Previous

    우선순위: 'actual'+'previous' 헤더 테이블 → 'South Korea 10Y' 행 fallback.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1순위: Actual + Previous 헤더 (10Y 메인 테이블)
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "actual" in headers and "previous" in headers:
            a_idx = headers.index("actual")
            p_idx = headers.index("previous")
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(cells) <= max(a_idx, p_idx):
                    continue
                try:
                    actual = float(cells[a_idx].replace(",", ""))
                    prev = float(cells[p_idx].replace(",", ""))
                    return actual, prev
                except (ValueError, IndexError):
                    continue

    # 2순위: "South Korea 10Y" 라벨이 있는 행 (Previous 없으면 actual=prev)
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) >= 2 and "korea" in cells[0].lower() and "10y" in cells[0].lower():
                try:
                    val = float(cells[1].replace(",", ""))
                    return val, val
                except (ValueError, IndexError):
                    continue
    return None


def fetch_kr_10y() -> Indicator:
    """한국 10년물 국고채 금리 — tradingeconomics 스크래핑.

    실패 시 yfinance 백업 시도 (^TNX 한국 버전은 없으므로 raise).
    """
    url = "https://tradingeconomics.com/south-korea/government-bond-yield"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        r.raise_for_status()
        parsed = _parse_te_yield(r.text)
        if parsed is None:
            raise RuntimeError("Could not locate yield row in tradingeconomics HTML")
        last, prev = parsed
        return Indicator(
            key="kr_10y",
            name="국고채 10년",
            value=round(last, 3),
            prev=round(prev, 3),
            change=round(last - prev, 3),
            change_pct=round((last - prev) / prev * 100, 2),
            unit="%",
            source="tradingeconomics.com",
            fetched_at=_now_iso(),
        )
    except Exception as exc:
        logger.warning("국고채10년 수집 실패: %s — 백업 소스 시도", exc)
        # 백업: investing.com (구조 다르므로 별도 파서 필요)
        raise


def fetch_all() -> dict:
    """Fetch all indicators. Each one is attempted independently — failures are reported per-key."""
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    def attempt(key: str, fn):
        try:
            ind = fn()
            results[key] = asdict(ind) | {"direction": ind.direction}
            logger.info("✓ %s: %s %s (Δ%+g %s)", key, ind.value, ind.unit, ind.change, ind.unit)
        except Exception as exc:
            errors[key] = str(exc)
            logger.error("✗ %s 실패: %s", key, exc)

    attempt("usd_krw", fetch_usd_krw)
    attempt("kospi", fetch_kospi)
    attempt("kr_10y", fetch_kr_10y)
    attempt("sp500", fetch_sp500)
    attempt("dow", fetch_dow)
    attempt("wti", fetch_wti)

    # 금은 환율에 의존 — last와 prev에 각각 그날 환율 적용
    if "usd_krw" in results:
        try:
            ind = fetch_gold_krw_per_gram(
                usd_krw_last=results["usd_krw"]["value"],
                usd_krw_prev=results["usd_krw"]["prev"],
            )
            results["gold_krw_g"] = asdict(ind) | {"direction": ind.direction}
            logger.info("✓ gold_krw_g: %s 원/g (Δ%+g)", ind.value, ind.change)
        except Exception as exc:
            errors["gold_krw_g"] = str(exc)
            logger.error("✗ gold_krw_g 실패: %s", exc)
    else:
        errors["gold_krw_g"] = "환율(usd_krw) 수집 실패로 인한 의존성 차단"

    return {
        "indicators": results,
        "policy_rates": POLICY_RATES,
        "errors": errors,
        "fetched_at": _now_iso(),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data = fetch_all()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if data["errors"]:
        sys.exit(1)
