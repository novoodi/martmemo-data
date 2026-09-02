# martmemo-data

마트메모 앱이 쓰는 **한국소비자원 참가격 공공데이터**의 정적 게시본입니다.
GitHub Actions가 매주 토요일 새벽 공공데이터포털 API를 호출해 JSON으로 정리하고, GitHub Pages로 게시합니다.
앱은 이 파일만 내려받습니다(앱에서 API를 직접 호출하지 않으며, 사용자 데이터는 여기로 오지 않습니다).

## 파일

| 경로 | 내용 | 크기 |
|---|---|---|
| `data/index.json` | 판매점·상품 사전, 보유 조사일 목록, 최신 조사일 | 약 200KB |
| `data/prices/YYYYMMDD.json` | 조사일 하나의 전체 가격 `[goodId, entpId, priceWon]` | 약 3MB |
| `data/trend.json` | 상품별 × 조사일별 × 업태별 중앙값(추이·배지용) | 작음 |

게시 URL: `https://novoodi.github.io/martmemo-data/data/index.json`

## 출처·한계

- 출처: 한국소비자원 참가격(price.go.kr), 공공데이터포털 "한국소비자원_생필품 가격 정보_GW". 격주 금요일 조사.
- API가 2026-06-12 이후 조사분만 제공하므로 이력은 이 저장소에 누적된 만큼만 있습니다.
- 인증키는 저장소 Secrets(`KCA_SERVICE_KEY`)에만 있으며 커밋·로그에 남지 않습니다.

## 수동 실행

Actions 탭 → "참가격 데이터 동기화" → Run workflow. `max_new_days`로 이번 실행에서 받을 조사일 수를 정합니다(조사일당 약 604회 호출, 일일 한도 2,000).
