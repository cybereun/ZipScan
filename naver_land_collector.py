#!/usr/bin/env python3
"""네이버 부동산(land.naver.com) 아파트 검색/매물 수집 CLI.

기능
1) 키워드로 아파트(단지) 검색
2) 검색 결과 중 1개 단지를 선택해 매물 전체 페이지 수집

주의: 네이버의 정책/차단에 따라 403이 발생할 수 있습니다.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

BASE_URL = "https://new.land.naver.com"


@dataclass
class CrawlOptions:
    real_estate_types: str = "APT:ABYG:JGC:PRE"
    trade_types: str = "A1:B1:B2:B3"
    page_delay: float = 0.15
    max_pages: Optional[int] = None


@dataclass
class SessionOptions:
    cookie_string: Optional[str] = None
    cookie_file: Optional[str] = None
    bootstrap_browser_cookies: bool = False


class NaverLandCollector:
    def __init__(self, timeout: int = 15, session_options: Optional[SessionOptions] = None):
        self.timeout = timeout
        self.session_options = session_options or SessionOptions()
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))

        if self.session_options.cookie_file:
            self._load_cookie_file(self.session_options.cookie_file)

        if self.session_options.bootstrap_browser_cookies:
            self._bootstrap_cookies_from_browser()

    def _load_cookie_file(self, path: str) -> None:
        if not os.path.exists(path):
            raise RuntimeError(f"쿠키 파일을 찾을 수 없습니다: {path}")
        jar = http.cookiejar.MozillaCookieJar(path)
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception as exc:
            raise RuntimeError(f"쿠키 파일 로딩 실패: {path} ({exc})") from exc
        for cookie in jar:
            self.cookie_jar.set_cookie(cookie)

    def _bootstrap_cookies_from_browser(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError(
                "Playwright가 설치되어 있지 않아 브라우저 쿠키 부트스트랩을 수행할 수 없습니다. "
                "`pip install playwright` 및 `playwright install chromium` 후 재시도하세요."
            ) from exc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(locale="ko-KR")
            page = context.new_page()
            page.goto(f"{BASE_URL}/complexes", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
            for c in context.cookies():
                ck = http.cookiejar.Cookie(
                    version=0,
                    name=c["name"],
                    value=c["value"],
                    port=None,
                    port_specified=False,
                    domain=c.get("domain", "new.land.naver.com"),
                    domain_specified=True,
                    domain_initial_dot=c.get("domain", "").startswith("."),
                    path=c.get("path", "/"),
                    path_specified=True,
                    secure=c.get("secure", False),
                    expires=c.get("expires"),
                    discard=False,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False,
                )
                self.cookie_jar.set_cookie(ck)
            browser.close()

    def _build_headers(self, referer: str, cookie_header: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": referer,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    def _request_json(self, path: str, params: Dict[str, Any], referer: str) -> Dict[str, Any]:
        query = urlencode(params, doseq=True)
        url = f"{BASE_URL}{path}?{query}"
        req = Request(
            url=url,
            headers=self._build_headers(referer, cookie_header=self.session_options.cookie_string),
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as res:
                return json.loads(res.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"HTTP {exc.code} 오류 ({url})\n"
                "네이버 봇 차단/접근 제한일 수 있습니다. "
                "브라우저에서 먼저 접속 후 동일 네트워크에서 재시도하거나 요청 간격을 늘려보세요.\n"
                "필요 시 --cookie-file / --cookie 또는 --bootstrap-browser-cookies 옵션을 사용하세요.\n"
                f"응답: {body[:250]}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"네트워크 오류: {exc}") from exc

    def search_complexes(self, keyword: str) -> List[Dict[str, Any]]:
        payload = self._request_json(
            "/api/search",
            {"keyword": keyword},
            referer=f"{BASE_URL}/complexes",
        )
        return self._extract_complex_candidates(payload)

    def _extract_complex_candidates(self, payload: Any) -> List[Dict[str, Any]]:
        """응답 구조가 종종 바뀌어도 동작하도록 단지 후보를 재귀 탐색."""
        found: List[Dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if "complexNo" in node and "complexName" in node:
                    found.append(
                        {
                            "complexNo": str(node.get("complexNo")),
                            "complexName": node.get("complexName"),
                            "cortarNo": node.get("cortarNo"),
                            "realEstateTypeCode": node.get("realEstateTypeCode"),
                            "detailAddress": node.get("detailAddress"),
                        }
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)

        # complexNo 기준 중복 제거
        dedup: Dict[str, Dict[str, Any]] = {}
        for item in found:
            dedup[item["complexNo"]] = item
        return list(dedup.values())

    def fetch_articles_page(
        self,
        complex_no: str,
        page: int,
        options: CrawlOptions,
    ) -> Dict[str, Any]:
        params = {
            "realEstateType": options.real_estate_types,
            "tradeType": options.trade_types,
            "tag": ":::::",
            "rentPriceMin": 0,
            "rentPriceMax": 900000000,
            "priceMin": 0,
            "priceMax": 9000000000,
            "areaMin": 0,
            "areaMax": 900000000,
            "oldBuildYears": "",
            "recentlyBuildYears": "",
            "minHouseHoldCount": "",
            "maxHouseHoldCount": "",
            "showArticle": "false",
            "sameAddressGroup": "false",
            "minMaintenanceCost": "",
            "maxMaintenanceCost": "",
            "priceType": "RETAIL",
            "directions": "",
            "page": page,
            "complexNo": complex_no,
            "buildingNos": "",
            "areaNos": "",
            "type": "list",
            "order": "rank",
        }
        referer = f"{BASE_URL}/complexes/{quote(str(complex_no))}"
        return self._request_json(f"/api/complexes/{quote(str(complex_no))}/articles", params, referer)

    def crawl_all_articles(self, complex_no: str, options: CrawlOptions) -> Dict[str, Any]:
        all_articles: List[Dict[str, Any]] = []
        pages: List[Dict[str, Any]] = []

        page = 1
        while True:
            if options.max_pages is not None and page > options.max_pages:
                break

            payload = self.fetch_articles_page(complex_no=complex_no, page=page, options=options)
            articles = payload.get("articleList", [])
            is_more_data = payload.get("isMoreData")

            pages.append(
                {
                    "page": page,
                    "articleCount": len(articles),
                    "isMoreData": is_more_data,
                    "raw": payload,
                }
            )
            all_articles.extend(articles)

            if not articles:
                break
            if is_more_data is False:
                break

            page += 1
            time.sleep(options.page_delay)

        return {
            "complexNo": str(complex_no),
            "totalArticles": len(all_articles),
            "totalPagesFetched": len(pages),
            "articles": all_articles,
            "pages": pages,
        }


def save_json(data: Any, output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="네이버 부동산 아파트 검색/매물 전체페이지 수집")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="키워드로 단지 검색")
    search.add_argument("--keyword", required=True, help="검색 키워드 (예: 판교푸르지오)")
    search.add_argument("--output", default="complex_search.json", help="검색 결과 저장 파일")
    search.add_argument("--cookie", default=None, help="Cookie 헤더 문자열")
    search.add_argument("--cookie-file", default=None, help="Netscape 포맷 쿠키 파일 경로")
    search.add_argument("--bootstrap-browser-cookies", action="store_true", help="Playwright로 브라우저 쿠키 자동 획득")

    crawl = sub.add_parser("crawl", help="단지 번호로 매물 전체페이지 수집")
    crawl.add_argument("--complex-no", required=True, help="단지 번호")
    crawl.add_argument("--output", default="articles.json", help="수집 결과 저장 파일")
    crawl.add_argument("--max-pages", type=int, default=None, help="최대 페이지 수 (기본: 끝까지)")
    crawl.add_argument("--page-delay", type=float, default=0.15, help="페이지 요청 간격(초)")
    crawl.add_argument("--real-estate-types", default="APT:ABYG:JGC:PRE")
    crawl.add_argument("--trade-types", default="A1:B1:B2:B3")
    crawl.add_argument("--cookie", default=None, help="Cookie 헤더 문자열")
    crawl.add_argument("--cookie-file", default=None, help="Netscape 포맷 쿠키 파일 경로")
    crawl.add_argument("--bootstrap-browser-cookies", action="store_true", help="Playwright로 브라우저 쿠키 자동 획득")

    crawl_from_search = sub.add_parser(
        "crawl-from-search",
        help="검색 후 결과 중 하나를 선택해 매물 전체페이지 수집",
    )
    crawl_from_search.add_argument("--keyword", required=True)
    crawl_from_search.add_argument("--pick-index", type=int, default=0, help="검색 결과에서 선택할 인덱스(0부터)")
    crawl_from_search.add_argument("--output", default="articles_from_search.json")
    crawl_from_search.add_argument("--max-pages", type=int, default=None)
    crawl_from_search.add_argument("--page-delay", type=float, default=0.15)
    crawl_from_search.add_argument("--real-estate-types", default="APT:ABYG:JGC:PRE")
    crawl_from_search.add_argument("--trade-types", default="A1:B1:B2:B3")
    crawl_from_search.add_argument("--cookie", default=None, help="Cookie 헤더 문자열")
    crawl_from_search.add_argument("--cookie-file", default=None, help="Netscape 포맷 쿠키 파일 경로")
    crawl_from_search.add_argument("--bootstrap-browser-cookies", action="store_true", help="Playwright로 브라우저 쿠키 자동 획득")

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        collector = NaverLandCollector(
            session_options=SessionOptions(
                cookie_string=getattr(args, "cookie", None),
                cookie_file=getattr(args, "cookie_file", None),
                bootstrap_browser_cookies=getattr(args, "bootstrap_browser_cookies", False),
            )
        )
        if args.command == "search":
            complexes = collector.search_complexes(args.keyword)
            result = {
                "keyword": args.keyword,
                "count": len(complexes),
                "complexes": complexes,
            }
            save_json(result, args.output)
            print(f"검색 결과 {len(complexes)}건 저장: {args.output}")
            return 0

        if args.command == "crawl":
            options = CrawlOptions(
                real_estate_types=args.real_estate_types,
                trade_types=args.trade_types,
                page_delay=args.page_delay,
                max_pages=args.max_pages,
            )
            result = collector.crawl_all_articles(args.complex_no, options)
            save_json(result, args.output)
            print(
                f"단지 {args.complex_no} 매물 {result['totalArticles']}건 / "
                f"{result['totalPagesFetched']}페이지 저장: {args.output}"
            )
            return 0

        if args.command == "crawl-from-search":
            complexes = collector.search_complexes(args.keyword)
            if not complexes:
                print("검색 결과가 없습니다.")
                return 1
            if args.pick_index < 0 or args.pick_index >= len(complexes):
                print(f"pick-index 범위 오류: 0 ~ {len(complexes)-1}")
                return 1

            target = complexes[args.pick_index]
            complex_no = target["complexNo"]
            options = CrawlOptions(
                real_estate_types=args.real_estate_types,
                trade_types=args.trade_types,
                page_delay=args.page_delay,
                max_pages=args.max_pages,
            )
            crawled = collector.crawl_all_articles(complex_no, options)
            result = {
                "keyword": args.keyword,
                "pickedIndex": args.pick_index,
                "pickedComplex": target,
                "crawlResult": crawled,
            }
            save_json(result, args.output)
            print(
                f"검색 '{args.keyword}' -> [{args.pick_index}] {target['complexName']}({complex_no}) "
                f"매물 {crawled['totalArticles']}건 저장: {args.output}"
            )
            return 0

    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
