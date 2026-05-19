# sonkyungje-daily

손에 잡히는 경제(MBC) Daily Brief 자동화 보고서.

매일 아침 손경제 에피소드 + 7대 경제지표 + Claude API의 뉴스 요약·인사이트·"래빗해빛" 콘텐츠 소재를 묶어 HTML 보고서로 생성하고 GitHub Pages로 배포합니다.

## 구조

```
sonkyungje-daily/
├── pipeline/
│   ├── fetch_rss.py        # MBC 손경제 RSS 수집
│   ├── fetch_indicators.py # 환율/코스피/국고채/S&P500/다우/WTI/금 수집
│   ├── summarize.py        # Claude API + web_search 도구로 뉴스 요약
│   ├── render_report.py    # Jinja2 HTML 렌더링
│   ├── run.py              # 오케스트레이터 (전 단계 + git push)
│   └── check_api_key.py    # ANTHROPIC_API_KEY 검증
├── templates/
│   └── report.html.j2      # 보고서 템플릿 (래빗해빛 디자인)
├── docs/                   # GitHub Pages 루트 (/docs)
│   ├── index.html          # 최신 보고서
│   ├── latest.html         # 최신 보고서 (동일 파일)
│   └── archive/{date}.html # 일자별 아카이브
├── out/                    # 중간 산출물 (git ignore)
├── .env                    # ANTHROPIC_API_KEY 등 (git ignore)
└── requirements.txt
```

## 셋업 (1회)

```bash
# 1. venv + 패키지
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. API 키
cp .env.example .env
# .env 열어서 ANTHROPIC_API_KEY 입력
python pipeline/check_api_key.py   # ✅ 응답: pong 확인
```

## 사용

### 매일 실행 (수동)

```bash
source .venv/bin/activate
python pipeline/run.py --push       # 전체 파이프라인 + git push
```

옵션:
- `--no-search` — Claude API 비용 절감 (web_search 비활성화)
- `--no-save` — 중간 JSON(`out/`) 저장 안 함
- `--dry-run-push` — git 변경사항만 출력 (실제 푸시 X)

### 단위 호출 (디버깅)

```bash
python pipeline/fetch_rss.py            # RSS 단독
python pipeline/fetch_indicators.py     # 지표 단독
python pipeline/render_report.py --mock # mock 데이터로 렌더 미리보기

# 캐시된 데이터로 요약만
python pipeline/summarize.py \
  --episode out/episode.json \
  --indicators out/indicators.json \
  --out out/summary.json
```

## 데이터 소스

| 지표 | 소스 |
|------|------|
| 원/달러 환율, 코스피, S&P500, 다우, WTI, 금(GC=F) | Yahoo Finance |
| 국고채 10년물 | tradingeconomics.com (스크래핑) |
| 한국·미국 기준금리 | 고정값 (`pipeline/fetch_indicators.py` 상단의 `POLICY_RATES`) |
| RSS | MBC 손경제 podcast feed |

## 비용 (대략)

| 항목 | 1회 | 월 (30일) |
|------|-----|-----------|
| Claude API (sonnet-4-6 + web_search) | ~$0.40 | ~$12 |
| Yahoo / tradingeconomics / RSS | 무료 | 무료 |

`--no-search`로 web_search를 끄면 회당 ~$0.05 수준. `.env`의 `ANTHROPIC_MODEL`을 `claude-opus-4-7`로 바꾸면 회당 약 5배.

## 자동화 (선택)

매일 한국 시간 9시(손경제 방송 30분 후)에 실행하려면 GitHub Actions 워크플로 추가 (예: `.github/workflows/daily.yml`). 로컬 cron으로도 가능:

```
0 9 * * 1-5 cd /path/to/sonkyungje-daily && .venv/bin/python pipeline/run.py --push
```

## GitHub Pages

- Settings → Pages에서 `Branch: main / Folder: /docs` 활성화
- URL: https://arum0807.github.io/sonkyungje-daily/

## 알려진 이슈

- MBC 손경제 RSS는 가끔 description 텍스트가 중간에 잘려 반복됨. `pipeline/fetch_rss.py`의 `_dedup_description()`이 후처리.
- tradingeconomics는 자주 페이지 구조를 바꿈. 실패 시 백업 소스 추가 필요.
- yfinance는 비공식 API. 장 중 vs 마감 데이터 차이가 있을 수 있음.
