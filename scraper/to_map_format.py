#!/usr/bin/env python3
"""
Convert the scraper's output (tabelog_full_flat.json) into the record shape the
map generator (../build.py) consumes, keeping only restaurants that have
coordinates and rating >= the threshold.

This is the Tabelog-only bridge: there are no Google fields yet. The map's
google_* fields are left blank / mirrored so build.py still runs. When you later
add a Google Places cross-reference, fill google_rating / google_place_id and
re-filter to Google >= 4.2.

Usage:
  python to_map_format.py tabelog_full_flat.json ../final_restaurants_tabelog.json
"""
import json
import sys


def convert(src_path: str, out_path: str, min_rating: float = 3.4):
    with open(src_path, encoding="utf-8") as f:
        rows = json.load(f)

    out = []
    skipped_nocoord = 0
    for r in rows:
        if not (r.get("lat") and r.get("lng")):
            skipped_nocoord += 1
            continue
        if (r.get("tabelog_rating") or 0) < min_rating:
            continue
        out.append({
            "name": r.get("name", ""),
            "google_name": "",  # no Google cross-ref yet
            "tabelog_rating": r.get("tabelog_rating"),
            "google_rating": None,
            "google_user_ratings_total": r.get("tabelog_review_count", 0),
            "cuisine": r.get("cuisine", ""),
            "area": r.get("area", ""),
            "address": r.get("address", ""),
            "google_address": r.get("address", ""),
            "google_place_id": "",
            "tabelog_url": r.get("url", ""),
            "ward": r.get("ward", ""),
            "lat": r["lat"],
            "lng": r["lng"],
        })

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(out)} restaurants -> {out_path}")
    print(f"Skipped {skipped_nocoord} without coordinates (run stage 'details' to fill them)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python to_map_format.py <tabelog_full_flat.json> <out.json>")
    convert(sys.argv[1], sys.argv[2])
