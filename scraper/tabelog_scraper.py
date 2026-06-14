#!/usr/bin/env python3
"""
Tabelog scraper for Tokyo's 23 special wards (Tabelog rating >= 3.4).

Why this exists
---------------
Tabelog's ranked restaurant list is capped at 60 pages / 1,200 results per
query. A single Tokyo-wide list therefore only ever exposes the top ~1,200
restaurants, which is why earlier scrapes topped out around 2,000. This script
*segments the search by ward* (and optionally by genre when a ward still
overflows the cap), so each query stays under 1,200 and the union covers far
more of the 3.4+ long tail. Results are de-duplicated by Tabelog URL.

Two stages
----------
  list     Stage 1 - walk each ward's rating-sorted list, collect every
           restaurant with rating >= MIN_RATING. Fast. No coordinates yet.
  details  Stage 2 - visit each restaurant page to pull lat/lng, full address
           and review count from the page's JSON-LD. Slow (1 request each).
  all      list, then details.

Both stages checkpoint to disk and resume, so an interrupted run continues
where it left off (important on flaky connections / anti-bot throttling).

Anti-bot note
-------------
Tabelog blocks many datacenter IPs with HTTP 403 regardless of headers. From a
normal residential connection the default `requests` engine usually works. If
you still get 403s, install Playwright and pass `--engine playwright` to drive a
real headless browser (see README).

Usage
-----
  python tabelog_scraper.py all                 # full run, requests engine
  python tabelog_scraper.py list --min-rating 3.4
  python tabelog_scraper.py details
  python tabelog_scraper.py all --engine playwright --delay 3
  python tabelog_scraper.py selftest            # offline parser test, no network
  python tabelog_scraper.py debug-html C13104   # dump one ward page for inspection

Scraping Tabelog is against their Terms of Service. Use responsibly, keep the
delay polite, and accept the risk yourself.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time

try:
    import requests
except ImportError:  # pragma: no cover - guidance only
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - guidance only
    BeautifulSoup = None


# --- Tokyo 23 special wards -> Tabelog municipality codes -------------------
# Codes are the JIS ward codes prefixed with "C". URL form:
#   https://tabelog.com/tokyo/<CODE>/rstLst/?SrtT=rt
WARDS: list[tuple[str, str]] = [
    ("C13101", "Chiyoda"),
    ("C13102", "Chuo"),
    ("C13103", "Minato"),
    ("C13104", "Shinjuku"),
    ("C13105", "Bunkyo"),
    ("C13106", "Taito"),
    ("C13107", "Sumida"),
    ("C13108", "Koto"),
    ("C13109", "Shinagawa"),
    ("C13110", "Meguro"),
    ("C13111", "Ota"),
    ("C13112", "Setagaya"),
    ("C13113", "Shibuya"),
    ("C13114", "Nakano"),
    ("C13115", "Suginami"),
    ("C13116", "Toshima"),
    ("C13117", "Kita"),
    ("C13118", "Arakawa"),
    ("C13119", "Itabashi"),
    ("C13120", "Nerima"),
    ("C13121", "Adachi"),
    ("C13122", "Katsushika"),
    ("C13123", "Edogawa"),
]

BASE = "https://tabelog.com"
MAX_PAGES = 60  # Tabelog hard cap per query
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://tabelog.com/tokyo/",
    "Upgrade-Insecure-Requests": "1",
}


# --- Fetching ---------------------------------------------------------------
class Fetcher:
    """HTML fetcher with retry/backoff. Engine: 'requests' or 'playwright'."""

    def __init__(self, engine: str = "requests", delay: float = 2.0, retries: int = 4):
        self.engine = engine
        self.delay = delay
        self.retries = retries
        self._session = None
        self._pw = None  # (playwright, browser, context) tuple when used

    def _session_requests(self):
        if self._session is None:
            if requests is None:
                sys.exit("The 'requests' package is required. pip install -r requirements.txt")
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
        return self._session

    def _ensure_playwright(self):
        if self._pw is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                sys.exit("Playwright not installed. pip install playwright && playwright install chromium")
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="ja-JP",
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
            )
            self._pw = (pw, browser, context)
        return self._pw

    def get(self, url: str) -> str | None:
        """Return HTML for url, or None after exhausting retries."""
        for attempt in range(self.retries):
            try:
                if self.engine == "playwright":
                    _, _, context = self._ensure_playwright()
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    html = page.content()
                    page.close()
                    return html
                resp = self._session_requests().get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code == 404:
                    return None
                # 403 / 429 / 5xx -> back off and retry
                wait = self.delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"    HTTP {resp.status_code} on {url} - retry in {wait:.1f}s", file=sys.stderr)
                time.sleep(wait)
            except Exception as exc:  # network errors
                wait = self.delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"    {type(exc).__name__}: {exc} - retry in {wait:.1f}s", file=sys.stderr)
                time.sleep(wait)
        return None

    def close(self):
        if self._pw is not None:
            pw, browser, _ = self._pw
            browser.close()
            pw.stop()


# --- Parsing ----------------------------------------------------------------
def parse_list_page(html: str) -> list[dict]:
    """Extract restaurant rows from a Tabelog rstLst page.

    Defensive: tries several selectors because Tabelog markup drifts over time.
    Each row -> {name, tabelog_rating, area, cuisine, url}.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []

    items = (
        soup.select("div.list-rst__wrap")
        or soup.select("li.list-rst__item")
        or soup.select("div.list-rst")
    )
    for it in items:
        name_el = it.select_one("a.list-rst__rst-name-target")
        if not name_el:
            continue
        href = name_el.get("href", "")
        url = href if href.startswith("http") else BASE + href

        rating_el = (
            it.select_one("span.c-rating__val")
            or it.select_one("span.list-rst__rating-val")
            or it.select_one(".c-rating-v3__val")
        )
        rating = _to_float(rating_el.get_text(strip=True)) if rating_el else None

        area = cuisine = ""
        ag = it.select_one(".list-rst__area-genre")
        if ag:
            text = ag.get_text(" ", strip=True)
            parts = [p.strip() for p in re.split(r"[/・]", text) if p.strip()]
            if parts:
                area = parts[0]
                cuisine = " / ".join(parts[1:]) if len(parts) > 1 else ""
        else:
            a = it.select_one(".list-rst__area")
            g = it.select_one(".list-rst__genre")
            area = a.get_text(strip=True) if a else ""
            cuisine = g.get_text(strip=True) if g else ""

        rows.append({
            "name": name_el.get_text(strip=True),
            "tabelog_rating": rating,
            "area": area,
            "cuisine": cuisine,
            "url": url.split("?")[0],
        })
    return rows


def has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    nxt = soup.select_one("a.c-pagination__target--next, a.c-pagination__arrow--next")
    if not nxt:
        return False
    cls = nxt.get("class", [])
    return "is-disabled" not in cls and "c-pagination__arrow--disable" not in " ".join(cls)


def parse_detail_page(html: str) -> dict:
    """Pull lat/lng, address and review count from a restaurant page's JSON-LD,
    with regex fallbacks. Returns possibly-partial dict."""
    out: dict = {}
    for block in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            geo = node.get("geo") or {}
            if geo.get("latitude") and geo.get("longitude"):
                out["lat"] = _to_float(geo["latitude"])
                out["lng"] = _to_float(geo["longitude"])
            addr = node.get("address")
            if isinstance(addr, dict):
                out["address"] = " ".join(
                    str(addr.get(k, "")) for k in
                    ("addressRegion", "addressLocality", "streetAddress")
                ).strip()
            elif isinstance(addr, str):
                out["address"] = addr
            agg = node.get("aggregateRating") or {}
            if agg.get("reviewCount"):
                out["tabelog_review_count"] = _to_int(agg["reviewCount"])
            if agg.get("ratingValue") and "tabelog_rating" not in out:
                out["tabelog_rating"] = _to_float(agg["ratingValue"])

    if "lat" not in out:  # fallback: inline coords (raw or HTML-escaped)
        m = re.search(r'"latitude":\s*"?(-?\d+\.\d+)"?', html)
        n = re.search(r'"longitude":\s*"?(-?\d+\.\d+)"?', html)
        if m and n:
            out["lat"] = float(m.group(1))
            out["lng"] = float(n.group(1))
    return out


def _to_float(text) -> float | None:
    try:
        return float(re.sub(r"[^\d.]", "", str(text)))
    except (ValueError, TypeError):
        return None


def _to_int(text) -> int | None:
    try:
        return int(re.sub(r"[^\d]", "", str(text)))
    except (ValueError, TypeError):
        return None


# --- Stages -----------------------------------------------------------------
def stage_list(fetcher: Fetcher, min_rating: float, out_path: str):
    """Scrape every ward's rating-sorted list down to min_rating."""
    state = _load_json(out_path, {"done_wards": [], "restaurants": {}})
    done = set(state["done_wards"])
    by_url: dict[str, dict] = state["restaurants"]

    for code, ward in WARDS:
        if code in done:
            print(f"[skip] {ward} ({code}) already done")
            continue
        print(f"[ward] {ward} ({code})")
        ward_count = 0
        for page in range(1, MAX_PAGES + 1):
            url = f"{BASE}/tokyo/{code}/rstLst/{page}/?SrtT=rt"
            html = fetcher.get(url)
            if not html:
                print(f"    page {page}: no html, stopping ward")
                break
            rows = parse_list_page(html)
            if not rows:
                print(f"    page {page}: no rows, stopping ward")
                break
            stop = False
            for r in rows:
                if r["tabelog_rating"] is None:
                    continue
                if r["tabelog_rating"] < min_rating:
                    stop = True  # rating-sorted -> rest are lower
                    break
                r["ward"] = ward
                by_url[r["url"]] = r
                ward_count += 1
            print(f"    page {page}: +{len(rows)} rows (ward kept {ward_count}, total {len(by_url)})")
            if stop or not has_next_page(html):
                break
            time.sleep(fetcher.delay + random.uniform(0, fetcher.delay))
        state["done_wards"] = sorted(done | {code})
        done.add(code)
        state["restaurants"] = by_url
        _save_json(out_path, state)

    flat = list(by_url.values())
    print(f"\nStage 1 complete: {len(flat)} unique restaurants >= {min_rating}")
    _save_json(out_path.replace(".json", "_flat.json"), flat)
    return flat


def stage_details(fetcher: Fetcher, list_path: str, out_path: str):
    """Enrich each restaurant with coordinates/address from its detail page."""
    src = _load_json(list_path, {"restaurants": {}})
    restaurants = src.get("restaurants", src if isinstance(src, dict) else {})
    if isinstance(restaurants, list):
        restaurants = {r["url"]: r for r in restaurants}

    enriched = _load_json(out_path, {})
    urls = [u for u in restaurants if u not in enriched]
    print(f"Stage 2: {len(urls)} to enrich ({len(enriched)} already done)")

    for i, url in enumerate(urls, 1):
        html = fetcher.get(url)
        rec = dict(restaurants[url])
        if html:
            rec.update(parse_detail_page(html))
        enriched[url] = rec
        if i % 25 == 0 or i == len(urls):
            _save_json(out_path, enriched)
            geo = sum(1 for r in enriched.values() if r.get("lat"))
            print(f"    {i}/{len(urls)} done ({geo} with coords)")
        time.sleep(fetcher.delay + random.uniform(0, fetcher.delay))

    _save_json(out_path, enriched)
    flat = list(enriched.values())
    _save_json(out_path.replace(".json", "_flat.json"), flat)
    geo = sum(1 for r in flat if r.get("lat"))
    print(f"\nStage 2 complete: {len(flat)} restaurants, {geo} with coordinates")
    return flat


# --- IO helpers -------------------------------------------------------------
def _load_json(path: str, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --- Self test (offline) ----------------------------------------------------
SAMPLE_LIST_HTML = """
<div class="list-rst__wrap">
  <a class="list-rst__rst-name-target" href="/tokyo/A1301/A130101/13000001/">鮨 さくら</a>
  <span class="c-rating__val">3.85</span>
  <div class="list-rst__area-genre">銀座 / 寿司</div>
</div>
<div class="list-rst__wrap">
  <a class="list-rst__rst-name-target" href="https://tabelog.com/tokyo/13000002/">ら麺 太郎</a>
  <span class="c-rating__val">3.42</span>
  <div class="list-rst__area-genre">新宿 / ラーメン</div>
</div>
"""

SAMPLE_DETAIL_HTML = """
<script type="application/ld+json">
{"@type":"Restaurant","name":"鮨 さくら",
 "address":{"addressRegion":"東京都","addressLocality":"中央区銀座","streetAddress":"1-2-3"},
 "geo":{"@type":"GeoCoordinates","latitude":35.6717,"longitude":139.7649},
 "aggregateRating":{"ratingValue":"3.85","reviewCount":"214"}}
</script>
"""


def selftest():
    if BeautifulSoup is None:
        sys.exit("Install deps first: pip install -r requirements.txt")
    rows = parse_list_page(SAMPLE_LIST_HTML)
    assert len(rows) == 2, rows
    assert rows[0]["name"] == "鮨 さくら", rows[0]
    assert rows[0]["tabelog_rating"] == 3.85, rows[0]
    assert rows[0]["area"] == "銀座" and "寿司" in rows[0]["cuisine"], rows[0]
    assert rows[1]["url"] == "https://tabelog.com/tokyo/13000002/", rows[1]
    det = parse_detail_page(SAMPLE_DETAIL_HTML)
    assert det["lat"] == 35.6717 and det["lng"] == 139.7649, det
    assert det["tabelog_review_count"] == 214, det
    assert "銀座" in det["address"], det
    print("selftest OK - list parser, detail parser, and URL normalisation all pass")


# --- CLI --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Tabelog 23-ward scraper (rating >= 3.4)")
    ap.add_argument("command", choices=["list", "details", "all", "selftest", "debug-html"])
    ap.add_argument("ward_code", nargs="?", help="ward code for debug-html, e.g. C13104")
    ap.add_argument("--min-rating", type=float, default=3.4)
    ap.add_argument("--engine", choices=["requests", "playwright"], default="requests")
    ap.add_argument("--delay", type=float, default=2.0, help="base polite delay (seconds)")
    ap.add_argument("--list-out", default="tabelog_list.json")
    ap.add_argument("--details-out", default="tabelog_full.json")
    args = ap.parse_args()

    if args.command == "selftest":
        return selftest()

    fetcher = Fetcher(engine=args.engine, delay=args.delay)
    try:
        if args.command == "debug-html":
            code = args.ward_code or "C13104"
            html = fetcher.get(f"{BASE}/tokyo/{code}/rstLst/1/?SrtT=rt")
            if not html:
                sys.exit("Fetch failed (likely 403). Try --engine playwright.")
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            rows = parse_list_page(html)
            print(f"Saved debug_page.html ({len(html)} bytes). Parser found {len(rows)} rows.")
            for r in rows[:5]:
                print(" ", r)
            return
        if args.command in ("list", "all"):
            stage_list(fetcher, args.min_rating, args.list_out)
        if args.command in ("details", "all"):
            stage_details(fetcher, args.list_out, args.details_out)
    finally:
        fetcher.close()


if __name__ == "__main__":
    main()
