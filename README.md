# 네이버 부동산 자동 수집 프로그램 (아파트)

아래 링크의 네이버 부동산 서비스(`new.land.naver.com`)를 대상으로,

- 아파트 단지 검색
- 검색 결과에서 특정 1개 단지를 골라 매물 전체 페이지 수집

을 수행하는 Python CLI입니다.

대상 예시 URL:
`https://new.land.naver.com/complexes?ms=37.3595704,127.105399,16&a=APT:ABYG:JGC:PRE&e=RETAIL`

## 파일
- `naver_land_collector.py`: 실행 스크립트

## 요구사항
- Python 3.9+
- 추가 패키지 없음(표준 라이브러리만 사용)

> 선택 기능: `--bootstrap-browser-cookies`를 사용하려면 `playwright`와 Chromium 설치가 필요합니다.
> ```bash
> pip install playwright
> playwright install chromium
> ```

## 사용법

### 1) 아파트(단지) 검색
```bash
python naver_land_collector.py search --keyword "판교푸르지오" --output complex_search.json
```

403 차단 시(택1):
```bash
# 브라우저에서 복사한 Cookie 헤더 문자열 전달
python naver_land_collector.py search --keyword "판교푸르지오" --cookie "NNB=...; NID_AUT=..."

# Netscape 포맷 쿠키 파일 전달
python naver_land_collector.py search --keyword "판교푸르지오" --cookie-file ./naver.cookies.txt

# Playwright로 쿠키 자동 부트스트랩
python naver_land_collector.py search --keyword "판교푸르지오" --bootstrap-browser-cookies
```

429(TOO_MANY_REQUESTS) 발생 시 재시도 튜닝 예시:
```bash
python naver_land_collector.py search \
  --keyword "범어서한포레스트" \
  --max-retries 8 \
  --retry-backoff 2.0 \
  --retry-max-wait 60
```

출력 JSON 예시:
- `count`: 검색된 단지 개수
- `complexes[].complexNo`: 단지 번호
- `complexes[].complexName`: 단지명

### 2) 단지 번호로 매물 전체 페이지 수집
```bash
python naver_land_collector.py crawl --complex-no 12345 --output articles.json
```

옵션:
- `--max-pages 3`: 최대 3페이지까지만
- `--page-delay 0.3`: 페이지 요청 간격 0.3초
- `--real-estate-types "APT:ABYG:JGC:PRE"`
- `--trade-types "A1:B1:B2:B3"`
- `--cookie "..."` / `--cookie-file ./naver.cookies.txt`
- `--bootstrap-browser-cookies`
- `--max-retries 8 --retry-backoff 2.0 --retry-max-wait 60` (429 대응)

### 3) 검색 결과에서 1개 단지 선택 후 전체 수집
```bash
python naver_land_collector.py crawl-from-search \
  --keyword "판교푸르지오" \
  --pick-index 0 \
  --output articles_from_search.json
```

`--pick-index`는 검색 결과 목록의 0-based 인덱스입니다.

## 참고/주의
- 서비스 정책 또는 IP/봇 차단 상태에서는 API 응답이 `HTTP 403`으로 실패할 수 있습니다.
- 이 경우 브라우저에서 먼저 접속한 뒤 재시도하거나, 요청 간격(`--page-delay`)을 늘리고 쿠키 옵션(`--cookie`, `--cookie-file`, `--bootstrap-browser-cookies`)을 활용하세요.
- `HTTP 429 (TOO_MANY_REQUESTS)`가 나오면 자동 지수 백오프 재시도를 수행합니다. 필요하면 `--max-retries`, `--retry-backoff`, `--retry-max-wait`를 키워 조정하세요.
- 네이버 서비스 약관/robots 정책 및 관련 법령을 준수해서 사용하세요.
