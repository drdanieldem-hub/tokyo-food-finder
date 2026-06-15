#!/usr/bin/env python3
"""
Google Place Details (hours) enrichment for the tokyo-food-finder map.

Reads final_restaurants_merged.json, and for each restaurant with a
google_place_id, fetches regular + current opening hours from the
Places API (New) at no charge. Output is the same list shape, with
two new keys:
    regular_opening_hours: list[7] of {day, open, close}  (or None)
    current_open_now:      bool | None
    hours_source:          "google" | "missing" | "text_only"

Notes
-----
* Place Details with the right FieldMask is free on the New API.
  We only request the hours fields.
* Google's ToS restricts *permanent* storage of some Places fields;
  hours displayed in a live UI with periodic refresh is fine.
* The cache key is google_place_id (stable), so re-running the
  cross-ref pass later will not invalidate the hours cache.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# New API: Place Details (GET)
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

# Day order in Google API response: Sunday=0 .. Saturday=6
DAY_NAMES_EN = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


# --- HTTP ------------------------------------------------------------------
def _http_json(url: str, *, headers=None, retries=4):
    headers = headers or {}
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace")), resp.status
        except HTTPError as e:
            payload = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503):
                wait = 2 ** attempt
                print(f"    HTTP {e.code}, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            try:
                return json.loads(payload), e.code
            except json.JSONDecodeError:
                return {"_raw_error": payload}, e.code
        except URLError as e:
            wait = 2 ** attempt
            print(f"    {e} retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None, 0


# --- Fetch hours for a single place_id ------------------------------------
def fetch_hours(key: str, place_id: str) -> tuple[dict | None, str | None]:
    """Return ({regular, current_open_now, weekday_text}, error_str|None)."""
    if not place_id:
        return None, "no_place_id"
    url = DETAILS_URL.format(place_id=place_id) + "?" + urlencode({
        "languageCode": "en",
        "regionCode": "JP",
    })
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": (
            "id,"
            "regularOpeningHours,"
            "currentOpeningHours"
        ),
    }
    data, status = _http_json(url, headers=headers)
    if data is None:
        return None, "network"
    if status != 200:
        if not isinstance(data, dict):
            return None, f"api_error:http_{status}"
        err_block = data.get("error")
        if not isinstance(err_block, dict):
            return None, f"api_error:http_{status}"
        msg = err_block.get("message", f"http_{status}")
        return None, f"api_error:{str(msg)[:80]}"
    return data, None


# --- Normalize the hours payload ------------------------------------------
def normalize(data: dict) -> dict:
    """Turn a Place Details response into our compact hours record."""
    regular = data.get("regularOpeningHours") or {}
    current = data.get("currentOpeningHours") or {}
    weekday_text = regular.get("weekdayDescriptions") or []

    # Compact: list of 7 entries (Sun..Sat), each {day, open, close, closed}
    # Always return 7 entries to make popup rendering trivial.
    periods = regular.get("periods") or []
    # periods[] shape: [{"open": {"day": 0, "hour": 11, "minute": 0},
    #                    "close": {"day": 0, "hour": 14, "minute": 0}}]
    by_day: dict[int, list[dict]] = {i: [] for i in range(7)}
    for p in periods:
        o = p.get("open") or {}
        c = p.get("close") or {}
        od = o.get("day")
        if od is None:
            continue
        by_day[od].append({
            "open":  f"{o.get('hour', 0):02d}:{o.get('minute', 0):02d}",
            "close": (f"{c.get('hour', 0):02d}:{c.get('minute', 0):02d}"
                      if c else None),  # open 24h if no close
        })

    compact = []
    for i in range(7):
        slots = by_day[i]
        compact.append({
            "day":    DAY_NAMES_EN[i],
            "day_idx": i,
            "slots":  slots,           # list of {open, close}
            "closed": len(slots) == 0,
        })

    return {
        "regular_opening_hours": compact,
        "weekday_text":          weekday_text,
        "current_open_now":      current.get("openNow"),
    }


# --- IO --------------------------------------------------------------------
def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --- Main ------------------------------------------------------------------
def enrich(src_path: str, out_path: str, *, delay: float, limit: int | None,
           dry_run: bool):
    restaurants = _load(src_path, None)
    if restaurants is None:
        sys.exit(f"Cannot read {src_path}.")
    if limit:
        restaurants = restaurants[:limit]

    n_with_id = sum(1 for r in restaurants if r.get("google_place_id"))
    print(f"{len(restaurants)} restaurants, {n_with_id} have google_place_id.")
    if dry_run:
        print(f"Estimated duration @ {delay}s/req: ~{n_with_id*delay/60:.1f} min, 0 cost.")
        return

    key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not key:
        sys.exit("Set GOOGLE_PLACES_API_KEY in your environment (do not commit it).")

    cache_path = out_path + ".hours_cache.json"
    cache: dict = _load(cache_path, {})

    done = ok = err = skipped = 0
    for i, r in enumerate(restaurants, 1):
        pid = r.get("google_place_id", "")
        if not pid:
            skipped += 1
            r["hours_source"] = "no_place_id"
            continue
        if pid in cache:
            cached = cache[pid]
            r["regular_opening_hours"] = cached.get("regular_opening_hours")
            r["weekday_text"]           = cached.get("weekday_text")
            r["current_open_now"]       = cached.get("current_open_now")
            r["hours_source"]           = cached.get("hours_source", "cached")
            done += 1
            if cached.get("hours_source") == "google":
                ok += 1
            continue

        data, err_str = fetch_hours(key, pid)
        if err_str:
            r["hours_source"] = "error"
            cache[pid] = {"hours_source": "error", "error": err_str}
            err += 1
        elif not data or not (data.get("regularOpeningHours") or data.get("currentOpeningHours")):
            r["hours_source"] = "missing"
            cache[pid] = {"hours_source": "missing"}
            err += 1
        else:
            norm = normalize(data)
            r["regular_opening_hours"] = norm["regular_opening_hours"]
            r["weekday_text"]           = norm["weekday_text"]
            r["current_open_now"]       = norm["current_open_now"]
            r["hours_source"]           = "google"
            cache[pid] = norm | {"hours_source": "google"}
            ok += 1
        done += 1
        time.sleep(delay)
        if i % 25 == 0 or i == len(restaurants):
            _save(cache_path, cache)
            _save(out_path, restaurants)
            print(f"  {i}/{len(restaurants)} "
                  f"(ok={ok} err={err} skip={skipped})")

    _save(cache_path, cache)
    _save(out_path, restaurants)
    print(f"\nDone. {ok} with hours, {err} missing/error, {skipped} no place_id.")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="final_restaurants_merged.json",
                    help="input restaurants json")
    ap.add_argument("--out", default="final_restaurants_with_hours.json",
                    help="output restaurants json (with hours fields)")
    ap.add_argument("--delay", type=float, default=0.1,
                    help="seconds between requests (default 0.1)")
    ap.add_argument("--limit", type=int, default=0,
                    help="process only first N (smoke test)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    enrich(args.src, args.out,
           delay=args.delay,
           limit=args.limit or None,
           dry_run=args.dry_run)
