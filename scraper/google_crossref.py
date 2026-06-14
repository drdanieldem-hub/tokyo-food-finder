#!/usr/bin/env python3
"""
Google Places cross-reference for the Tabelog scrape.

Takes the Tabelog output (tabelog_full_flat.json) and, for each restaurant,
looks it up on Google Places by name + area (biased to its Tabelog
coordinates), attaches the Google rating / review count / place_id, and keeps
only those at Google rating >= MIN_GOOGLE (default 4.2). The result is the
Tabelog 3.4+ INTERSECT Google 4.2+ set, written in the record shape that
../build.py already consumes.

Engines (auto-selectable; new projects often have only one enabled):
  new      Places API (New)  -> places.googleapis.com/v1/places:searchText
  legacy   Places API        -> maps.googleapis.com/maps/api/place/textsearch
Both make ONE request per restaurant (rating + reviews + coords come back in
the search result), so cost is ~1 Text Search call each.

Setup:
  export GOOGLE_PLACES_API_KEY=...      # never commit this; .env is gitignored
  pip install -r requirements.txt

Usage:
  python google_crossref.py tabelog_full_flat.json ../final_restaurants_merged.json
  python google_crossref.py tabelog_full_flat.json out.json --limit 20      # test run
  python google_crossref.py tabelog_full_flat.json out.json --dry-run       # cost only
  python google_crossref.py selftest                                        # offline

Notes:
- Google's Terms restrict permanently storing most Places fields; place_id may be
  cached, but treat ratings as refreshable rather than frozen forever.
- Matching is fuzzy. When a restaurant has Tabelog coordinates, a Google hit
  more than --max-distance metres away is rejected as a likely mismatch.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

NEW_URL = "https://places.googleapis.com/v1/places:searchText"
LEGACY_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
COST_PER_CALL = 0.032  # ~Text Search Pro SKU, USD; rough estimate for budgeting


# --- HTTP -------------------------------------------------------------------
def _http_json(url: str, *, method="GET", headers=None, body=None, retries=4):
    headers = headers or {}
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries):
        try:
            req = Request(url, data=data, headers=headers, method=method)
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace")), resp.status
        except HTTPError as e:
            payload = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503):  # transient -> back off
                wait = 2 ** attempt
                print(f"    HTTP {e.code}, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            # 4xx (e.g. 403 PERMISSION_DENIED / API not enabled) -> surface it
            try:
                return json.loads(payload), e.code
            except json.JSONDecodeError:
                return {"_raw_error": payload}, e.code
        except URLError as e:
            wait = 2 ** attempt
            print(f"    {e} retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None, 0


# --- Query engines (each returns a normalized hit dict or None) -------------
def query_new(key: str, name: str, area: str, lat, lng):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.rating,"
            "places.userRatingCount,places.location,places.formattedAddress"
        ),
    }
    body = {
        "textQuery": f"{name} {area}".strip() + " Tokyo",
        "languageCode": "en",
        "regionCode": "JP",
        "maxResultCount": 1,
    }
    if lat and lng:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 500.0}}
    data, status = _http_json(NEW_URL, method="POST", headers=headers, body=body)
    if data is None:
        return None, "network"
    if status != 200:
        return None, _err_message(data, status)
    places = data.get("places") or []
    if not places:
        return None, "no_result"
    return _normalize_new(places[0]), None


def query_legacy(key: str, name: str, area: str, lat, lng):
    params = {
        "query": f"{name} {area} Tokyo".strip(),
        "key": key,
        "language": "en",
        "region": "jp",
    }
    if lat and lng:
        params["location"] = f"{lat},{lng}"
        params["radius"] = "500"
    data, status = _http_json(LEGACY_URL + "?" + urlencode(params))
    if data is None:
        return None, "network"
    api_status = (data or {}).get("status")
    if api_status == "ZERO_RESULTS":
        return None, "no_result"
    if api_status not in ("OK",):
        return None, _err_message(data, status)
    results = data.get("results") or []
    if not results:
        return None, "no_result"
    return _normalize_legacy(results[0]), None


def _normalize_new(p: dict) -> dict:
    loc = p.get("location") or {}
    return {
        "place_id": p.get("id", ""),
        "google_name": (p.get("displayName") or {}).get("text", ""),
        "google_rating": p.get("rating"),
        "google_reviews": p.get("userRatingCount", 0),
        "glat": loc.get("latitude"),
        "glng": loc.get("longitude"),
        "google_address": p.get("formattedAddress", ""),
    }


def _normalize_legacy(r: dict) -> dict:
    loc = (r.get("geometry") or {}).get("location") or {}
    return {
        "place_id": r.get("place_id", ""),
        "google_name": r.get("name", ""),
        "google_rating": r.get("rating"),
        "google_reviews": r.get("user_ratings_total", 0),
        "glat": loc.get("lat"),
        "glng": loc.get("lng"),
        "google_address": r.get("formatted_address", ""),
    }


def _err_message(data: dict, status: int) -> str:
    msg = ""
    if isinstance(data, dict):
        msg = (data.get("error") or {}).get("message") or data.get("error_message") or data.get("status") or ""
    return f"api_error:{status}:{msg}"[:200]


# --- Geo --------------------------------------------------------------------
def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --- Main cross-reference ---------------------------------------------------
def crossref(src_path, out_path, *, engine, min_google, max_distance, delay, limit, dry_run):
    rows = _load(src_path, None)
    if rows is None:
        sys.exit(f"Cannot read {src_path}. Run the scraper first.")
    if isinstance(rows, dict):
        rows = list(rows.get("restaurants", rows).values()) if "restaurants" in rows else list(rows.values())
    if limit:
        rows = rows[:limit]

    if dry_run:
        print(f"{len(rows)} restaurants to look up.")
        print(f"Estimated cost: ~${len(rows) * COST_PER_CALL:,.2f} "
              f"(~${COST_PER_CALL} per Text Search call; check your billing/free credit).")
        return

    key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not key:
        sys.exit("Set GOOGLE_PLACES_API_KEY in your environment (do not commit it).")

    print(f"Cross-referencing {len(rows)} restaurants via Places API ({engine}).")
    print(f"Estimated cost: ~${len(rows) * COST_PER_CALL:,.2f}. Keeping Google >= {min_google}.\n")
    do_query = query_new if engine == "new" else query_legacy

    cache_path = out_path + ".cache.json"
    cache = _load(cache_path, {})        # tabelog_url -> result record (kept or dropped)
    kept, dropped, errors = [], [], []

    for i, r in enumerate(rows, 1):
        url = r.get("url") or r.get("tabelog_url") or f"row{i}"
        if url in cache:
            rec = cache[url]
        else:
            hit, err = do_query(key, r.get("name", ""), r.get("area", ""), r.get("lat"), r.get("lng"))
            rec = _build_record(r, hit, err, min_google, max_distance)
            cache[url] = rec
            time.sleep(delay)
            if i % 25 == 0 or i == len(rows):
                _save(cache_path, cache)
                print(f"  {i}/{len(rows)} (kept {sum(1 for v in cache.values() if v['_status']=='kept')})")

        if rec["_status"] == "kept":
            kept.append(_public(rec))
        elif rec["_status"] == "error":
            errors.append(rec)
        else:
            dropped.append(rec)

    _save(cache_path, cache)
    _save(out_path, kept)
    _save(out_path.replace(".json", "_dropped.json"), dropped + errors)

    print(f"\nDone. Kept {len(kept)} (Tabelog>={'?'} INTERSECT Google>={min_google}).")
    print(f"Dropped {len(dropped)} (low rating / mismatch / not found), {len(errors)} errors.")
    print(f"Wrote {out_path}  (+ {out_path.replace('.json','_dropped.json')} for review)")
    if errors:
        ex = errors[0].get("_reason", "")
        print(f"First error reason: {ex}  (e.g. enable the API / check the key if it's a permission error)")


def _build_record(tab: dict, hit, err, min_google, max_distance) -> dict:
    base = {
        "name": tab.get("name", ""),
        "tabelog_rating": tab.get("tabelog_rating"),
        "cuisine": tab.get("cuisine", ""),
        "area": tab.get("area", ""),
        "address": tab.get("address", ""),
        "tabelog_url": tab.get("url", ""),
        "ward": tab.get("ward", ""),
        "tabelog_lat": tab.get("lat"),
        "tabelog_lng": tab.get("lng"),
    }
    if hit is None:
        base.update(_status="error" if err and err.startswith(("api_error", "network")) else "dropped",
                    _reason=err or "no_result")
        return base
    # distance sanity check when we have both coordinates
    dist = None
    if tab.get("lat") and tab.get("lng") and hit.get("glat") and hit.get("glng"):
        dist = haversine_m(tab["lat"], tab["lng"], hit["glat"], hit["glng"])
    base.update(
        google_name=hit["google_name"],
        google_rating=hit["google_rating"],
        google_user_ratings_total=hit["google_reviews"] or 0,
        google_place_id=hit["place_id"],
        google_address=hit["google_address"],
        google_lat=hit["glat"],
        google_lng=hit["glng"],
        match_distance_m=round(dist, 1) if dist is not None else None,
    )
    if dist is not None and dist > max_distance:
        base.update(_status="dropped", _reason=f"mismatch_{int(dist)}m")
    elif hit["google_rating"] is None or hit["google_rating"] < min_google:
        base.update(_status="dropped", _reason=f"google_{hit['google_rating']}")
    else:
        base["_status"] = "kept"
    return base


def _public(rec: dict) -> dict:
    """Strip internal fields and emit the build.py record shape."""
    return {
        "name": rec["name"],
        "google_name": rec.get("google_name", ""),
        "tabelog_rating": rec.get("tabelog_rating"),
        "google_rating": rec.get("google_rating"),
        "google_user_ratings_total": rec.get("google_user_ratings_total", 0),
        "cuisine": rec.get("cuisine", ""),
        "area": rec.get("area", ""),
        "address": rec.get("address", ""),
        "google_address": rec.get("google_address", ""),
        "google_place_id": rec.get("google_place_id", ""),
        "tabelog_url": rec.get("tabelog_url", ""),
        "ward": rec.get("ward", ""),
        # prefer Google coordinates (what the marker should sit on)
        "lat": rec.get("google_lat") or rec.get("tabelog_lat"),
        "lng": rec.get("google_lng") or rec.get("tabelog_lng"),
    }


# --- IO ---------------------------------------------------------------------
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


# --- Offline self test ------------------------------------------------------
SAMPLE_NEW = {"places": [{
    "id": "ChIJxxxx", "displayName": {"text": "Sushi Sakura"},
    "rating": 4.4, "userRatingCount": 530,
    "location": {"latitude": 35.6717, "longitude": 139.7649},
    "formattedAddress": "1-2-3 Ginza, Chuo City, Tokyo",
}]}
SAMPLE_LEGACY = {"status": "OK", "results": [{
    "place_id": "ChIJyyyy", "name": "Ramen Taro", "rating": 4.1,
    "user_ratings_total": 88, "formatted_address": "Shinjuku, Tokyo",
    "geometry": {"location": {"lat": 35.69, "lng": 139.70}},
}]}


def selftest():
    n = _normalize_new(SAMPLE_NEW["places"][0])
    assert n["place_id"] == "ChIJxxxx" and n["google_rating"] == 4.4 and n["google_reviews"] == 530, n
    lg = _normalize_legacy(SAMPLE_LEGACY["results"][0])
    assert lg["google_name"] == "Ramen Taro" and lg["glat"] == 35.69, lg

    tab = {"name": "Sushi Sakura", "area": "Ginza", "tabelog_rating": 3.85,
           "lat": 35.6717, "lng": 139.7649, "url": "https://tabelog.com/x/1/"}
    kept = _build_record(tab, n, None, min_google=4.2, max_distance=400)
    assert kept["_status"] == "kept", kept
    assert _public(kept)["lat"] == 35.6717, _public(kept)

    low = _build_record(tab, lg, None, min_google=4.2, max_distance=400)  # 4.1 < 4.2 + far away
    assert low["_status"] == "dropped", low

    d = haversine_m(35.6717, 139.7649, 35.6717, 139.7649)
    assert d == 0.0, d
    missing = _build_record(tab, None, "no_result", 4.2, 400)
    assert missing["_status"] == "dropped" and missing["_reason"] == "no_result", missing
    err = _build_record(tab, None, "api_error:403:PERMISSION_DENIED", 4.2, 400)
    assert err["_status"] == "error", err
    print("selftest OK - both engine parsers, distance/rating filtering, error handling pass")


# --- CLI --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Google Places cross-reference for the Tabelog scrape")
    ap.add_argument("src", nargs="?", help="tabelog_full_flat.json (or 'selftest')")
    ap.add_argument("out", nargs="?", help="output merged json")
    ap.add_argument("--engine", choices=["new", "legacy"], default="new")
    ap.add_argument("--min-google", type=float, default=4.2)
    ap.add_argument("--max-distance", type=float, default=400.0,
                    help="reject Google match farther than this (m) from Tabelog coords")
    ap.add_argument("--delay", type=float, default=0.1)
    ap.add_argument("--limit", type=int, default=0, help="only process first N (test runs)")
    ap.add_argument("--dry-run", action="store_true", help="print count + cost estimate only")
    args = ap.parse_args()

    if args.src == "selftest":
        return selftest()
    if not args.src or not args.out:
        ap.error("need <src> and <out> (or 'selftest')")
    crossref(args.src, args.out, engine=args.engine, min_google=args.min_google,
             max_distance=args.max_distance, delay=args.delay, limit=args.limit,
             dry_run=args.dry_run)


if __name__ == "__main__":
    main()
