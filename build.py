#!/usr/bin/env python3
"""
Tokyo Food Finder - Map Generator
Reads final_restaurants_merged.json and produces a self-contained index.html
with an interactive Leaflet map, clustering, dual-rating popups, and filters.
"""

import json
import math
import os

# ── Cuisine mapping ──────────────────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    "Sushi":    ["寿司", "すし", "スシ", "Sushi"],
    "Ramen":    ["ラーメン", "らーめん", "つけ麺", "Ramen"],
    "Tempura":  ["天ぷら", "てんぷら", "Tempura"],
    "Yakitori": ["焼き鳥", "やきとり", "Yakitori", "鳥料理"],
    "Yakiniku": ["焼肉", "やきにく", "Yakiniku", "ホルモン"],
    "Tonkatsu": ["とんかつ", "トンカツ", "Tonkatsu", "カツ"],
    "Unagi":    ["うなぎ", "ウナギ", "Unagi", "鰻"],
    "Japanese": ["日本料理", "和食", "Japanese", "懐石", "割烹"],
    "Soba":     ["そば", "ソバ", "Soba", "蕎麦"],
    "Udon":     ["うどん", "ウドン", "Udon"],
    "Curry":    ["カレー", "Curry", "カリー"],
    "Bakery":   ["パン", "ブーランジェリー", "Bakery", "ベーカリー"],
    "Desserts": ["ケーキ", "和菓子", "スイーツ", "Dessert", "パティスリー", "たい焼き"],
    "Pizza":    ["ピザ", "Pizza", "Pizzeria", "ピッツェリア", "Trattoria", "Italian"],
}
ALL_CATEGORIES = list(CATEGORY_KEYWORDS.keys())


def classify(cuisine_text):
    """Return list of matching category names for a cuisine string."""
    cats = []
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in cuisine_text:
                cats.append(cat)
                break
    if not cats:
        cats = ["Other"]
    return cats


def build_geojson(restaurants):
    features = []
    for r in restaurants:
        name_en = (r.get("google_name") or "").strip() or r["name"]
        name_jp = r["name"]
        addr = (r.get("google_address") or "").strip() or r.get("address", "")
        cuisine = r.get("cuisine", "")
        cats = classify(cuisine)
        feat = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r["lng"], r["lat"]],
            },
            "properties": {
                "name":           name_en,
                "name_jp":        name_jp,
                "tabelog_rating": r.get("tabelog_rating", 0),
                "google_rating":  r.get("google_rating", 0),
                "google_reviews": r.get("google_user_ratings_total", 0),
                "cuisine":        cuisine,
                "area":           r.get("area", ""),
                "address":        addr,
                "categories":     cats,
                "place_id":       r.get("google_place_id", ""),
                "lat":            r["lat"],
                "lng":            r["lng"],
                # Hours (only present if google_hours.py has run)
                "regular_opening_hours": r.get("regular_opening_hours") or [],
                "current_open_now":      r.get("current_open_now"),
                "hours_source":          r.get("hours_source", ""),
            },
        }
        features.append(feat)
    return {"type": "FeatureCollection", "features": features}


def category_counts(restaurants):
    counts = {cat: 0 for cat in ALL_CATEGORIES}
    counts["Other"] = 0
    for r in restaurants:
        cuisine = r.get("cuisine", "")
        cats = classify(cuisine)
        for c in cats:
            counts[c] = counts.get(c, 0) + 1
    return counts


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    # Prefer hours-enriched file if it exists, fall back to plain merged
    for candidate in ("final_restaurants_with_hours.json", "final_restaurants_merged.json"):
        data_path = os.path.join(base, candidate)
        if os.path.exists(data_path):
            break
    out_path  = os.path.join(base, "index.html")

    with open(data_path, encoding="utf-8") as f:
        restaurants = json.load(f)

    total = len(restaurants)
    print(f"Loaded {total} restaurants")

    geojson = build_geojson(restaurants)
    counts  = category_counts(restaurants)

    print("\nCategory counts:")
    for cat in ALL_CATEGORIES + ["Other"]:
        print(f"  {cat}: {counts.get(cat, 0)}")

    geojson_str  = json.dumps(geojson,  ensure_ascii=False, separators=(",", ":"))
    counts_str   = json.dumps(counts,   ensure_ascii=False)
    cats_str     = json.dumps(ALL_CATEGORIES, ensure_ascii=False)

    # ── Compute top-15% combined score threshold ──────────────────────────
    scores = []
    for feat in geojson["features"]:
        p = feat["properties"]
        score = (p["tabelog_rating"] / 4.71) * 0.5 + (p["google_rating"] / 5.0) * 0.5
        scores.append(score)
    scores.sort(reverse=True)
    top15_threshold = scores[max(0, int(len(scores) * 0.15) - 1)]

    html = build_html(geojson_str, counts_str, cats_str, total, top15_threshold)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nWrote {out_path}")
    print(f"Total features in GeoJSON: {len(geojson['features'])}")


def build_html(geojson_str, counts_str, cats_str, total, top15_threshold):
    # Using plain string concatenation to avoid f-string brace issues with JS/CSS
    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        "<title>🗼 Tokyo Food Finder</title>\n"
        "<link rel=\"manifest\" href=\"manifest.json\">\n"
        "<meta name=\"theme-color\" content=\"#10b981\">\n"
        "<link rel=\"apple-touch-icon\" href=\"icon-192.png\">\n"
        "<!-- Leaflet CSS -->\n"
        "<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\">\n"
        "<!-- MarkerCluster CSS -->\n"
        "<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css\">\n"
        "<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css\">\n"
        "<style>\n"
        "* { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "body { display: flex; flex-direction: column; background: #f8fafc; color: #1e293b; }\n"
        "body.dark { background: #0f172a; color: #e2e8f0; }\n"

        "/* Header */\n"
        "#header { background: #10b981; color: #fff; padding: 10px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; box-shadow: 0 2px 8px rgba(0,0,0,.2); z-index: 1000; position: relative; }\n"
        "body.dark #header { background: #064e3b; }\n"
        "#header h1 { font-size: 1.2rem; font-weight: 700; flex: 1; white-space: nowrap; }\n"
        "#stats-line { font-size: 0.78rem; opacity: .9; white-space: nowrap; }\n"
        "#dark-toggle { background: rgba(255,255,255,.2); border: none; color: #fff; border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 0.85rem; white-space: nowrap; }\n"
        "#dark-toggle:hover { background: rgba(255,255,255,.35); }\n"

        "/* Layout */\n"
        "#main { display: flex; flex: 1; overflow: hidden; }\n"
        "#sidebar { width: 280px; background: #fff; border-right: 1px solid #e2e8f0; overflow-y: auto; flex-shrink: 0; transition: transform .25s; z-index: 500; }\n"
        "body.dark #sidebar { background: #1e293b; border-color: #334155; }\n"
        "#map { flex: 1; }\n"

        "/* Sidebar inner */\n"
        "#sidebar-inner { padding: 14px; }\n"
        ".filter-section { margin-bottom: 14px; }\n"
        ".filter-section h3 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: .08em; color: #64748b; margin-bottom: 6px; }\n"
        "body.dark .filter-section h3 { color: #94a3b8; }\n"
        "select, input[type=text] { width: 100%; padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 0.85rem; background: #f8fafc; color: #1e293b; }\n"
        "body.dark select, body.dark input[type=text] { background: #0f172a; border-color: #475569; color: #e2e8f0; }\n"
        ".checkbox-list { display: flex; flex-direction: column; gap: 5px; max-height: 260px; overflow-y: auto; }\n"
        ".checkbox-list label { display: flex; align-items: center; gap: 7px; font-size: 0.84rem; cursor: pointer; }\n"
        ".checkbox-list input[type=checkbox] { accent-color: #10b981; width: 15px; height: 15px; }\n"
        ".cat-count { color: #94a3b8; font-size: 0.75rem; margin-left: auto; }\n"
        "#top-picks-label { display: flex; align-items: center; gap: 7px; font-size: 0.88rem; cursor: pointer; }\n"
        "#top-picks-label input { accent-color: #10b981; width: 15px; height: 15px; }\n"
        "#open-now-label { display: flex; align-items: center; gap: 7px; font-size: 0.88rem; cursor: pointer; }\n"
        "#open-now-label input { accent-color: #10b981; width: 15px; height: 15px; }\n"
        ".japan-time { font-size: 0.74rem; color: #64748b; margin-top: 4px; padding-left: 22px; font-variant-numeric: tabular-nums; }\n"
        "body.dark .japan-time { color: #94a3b8; }\n"
        ".japan-time.live { color: #10b981; font-weight: 600; }\n"
        "body.dark .japan-time.live { color: #34d399; }\n"
        "button.reset-btn { width: 100%; padding: 8px; border: 1px solid #10b981; background: transparent; color: #10b981; border-radius: 8px; cursor: pointer; font-size: 0.85rem; margin-top: 8px; }\n"
        "button.reset-btn:hover { background: #10b981; color: #fff; }\n"
        "body.dark button.reset-btn { border-color: #34d399; color: #34d399; }\n"
        "body.dark button.reset-btn:hover { background: #34d399; color: #0f172a; }\n"

        "/* Floating toggle for sidebar */\n"
        "#sidebar-toggle { display: none; position: fixed; bottom: 70px; left: 12px; z-index: 2000; background: #10b981; color: #fff; border: none; border-radius: 50%; width: 44px; height: 44px; font-size: 1.2rem; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.3); }\n"
        "body.dark #sidebar-toggle { background: #064e3b; }\n"
        "#gps-btn { position: fixed; bottom: 16px; left: 12px; z-index: 2000; background: #3b82f6; color: #fff; border: none; border-radius: 50%; width: 44px; height: 44px; font-size: 1.1rem; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.3); }\n"
        "#gps-btn.active { background: #ef4444; }\n"

        "/* Legend */\n"
        "#legend { position: fixed; bottom: 16px; right: 12px; z-index: 2000; background: #fff; border-radius: 10px; padding: 10px 14px; box-shadow: 0 2px 8px rgba(0,0,0,.15); font-size: 0.78rem; }\n"
        "body.dark #legend { background: #1e293b; color: #e2e8f0; }\n"
        ".legend-item { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }\n"
        ".legend-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }\n"

        "/* Popup */\n"
        ".popup-title { font-size: 1rem; font-weight: 700; margin-bottom: 2px; }\n"
        ".popup-name-jp { font-size: 0.8rem; color: #64748b; margin-bottom: 8px; }\n"
        ".popup-ratings { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }\n"
        ".rating-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 20px; font-size: 0.82rem; font-weight: 600; text-decoration: none; }\n"
        ".rating-chip.tabelog { background: #fef3c7; color: #92400e; }\n"
        ".rating-chip.google { background: #dbeafe; color: #1e40af; }\n"
        ".rating-chip:hover { opacity: .85; }\n"
        ".popup-meta { font-size: 0.82rem; line-height: 1.7; }\n"
        ".popup-meta span { display: block; }\n"
        "/* Open/Closed badge */\n"
        ".popup-status-row { margin-bottom: 8px; }\n"
        ".status-badge { display: inline-flex; align-items: center; gap: 4px; padding: 5px 12px; border-radius: 14px; font-size: 0.85rem; font-weight: 700; box-shadow: 0 1px 3px rgba(0,0,0,.08); }\n"
        ".status-badge.open { background: #10b981; color: #fff; }\n"
        ".status-badge.closed { background: #6b7280; color: #fff; }\n"
        ".status-badge.unknown { background: #f59e0b; color: #fff; }\n"
        "body.dark .status-badge.open { background: #059669; color: #d1fae5; }\n"
        "body.dark .status-badge.closed { background: #4b5563; color: #e5e7eb; }\n"
        "body.dark .status-badge.unknown { background: #d97706; color: #fef3c7; }\n"
        "/* Next opening hint */\n"
        ".next-opening { font-size: 0.78rem; color: #64748b; margin-top: 8px; margin-bottom: 2px; font-weight: 600; }\n"
        "body.dark .next-opening { color: #cbd5e1; }\n"
        "/* Hours table (collapsible) */\n"
        ".hours-details { margin-top: 6px; font-size: 0.78rem; }\n"
        ".hours-details summary { cursor: pointer; color: #3b82f6; font-weight: 600; user-select: none; padding: 2px 0; }\n"
        ".hours-details summary:hover { text-decoration: underline; }\n"
        ".hours-table { width: 100%; border-collapse: collapse; margin-top: 4px; }\n"
        ".hours-table td { padding: 2px 4px; vertical-align: top; }\n"
        ".hours-table td.day { color: #64748b; width: 70px; }\n"
        "body.dark .hours-table td.day { color: #94a3b8; }\n"
        ".hours-table tr.today td { font-weight: 700; color: #0f172a; }\n"
        ".hours-table tr.today td.day { color: #3b82f6; }\n"
        "body.dark .hours-table tr.today td { color: #f1f5f9; }\n"
        ".hours-table tr.closed td { color: #94a3b8; }\n"

        "@media (max-width: 767px) {\n"
        "  #sidebar { position: fixed; top: 0; left: 0; height: 100%; transform: translateX(-100%); box-shadow: 2px 0 12px rgba(0,0,0,.2); }\n"
        "  #sidebar.open { transform: translateX(0); }\n"
        "  #sidebar-toggle { display: flex; align-items: center; justify-content: center; }\n"
        "  #header h1 { font-size: 1rem; }\n"
        "  #stats-line { display: none; }\n"
        "}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"

        "<div id=\"header\">\n"
        "  <h1>🗼 Tokyo Food Finder</h1>\n"
        "  <span id=\"stats-line\">" + str(total) + " Restaurants &bull; Tabelog 3.4+ &cap; Google 4.2+</span>\n"
        "  <button id=\"dark-toggle\">🌙 Dark</button>\n"
        "</div>\n"

        "<div id=\"main\">\n"
        "  <div id=\"sidebar\">\n"
        "    <div id=\"sidebar-inner\">\n"

        "      <div class=\"filter-section\">\n"
        "        <h3>Tabelog Rating</h3>\n"
        "        <select id=\"tabelog-min\">\n"
        "          <option value=\"3.4\">3.4+</option>\n"
        "          <option value=\"3.6\">3.6+</option>\n"
        "          <option value=\"3.8\">3.8+</option>\n"
        "          <option value=\"4.0\">4.0+</option>\n"
        "        </select>\n"
        "      </div>\n"

        "      <div class=\"filter-section\">\n"
        "        <h3>Google Rating</h3>\n"
        "        <select id=\"google-min\">\n"
        "          <option value=\"4.2\">4.2+</option>\n"
        "          <option value=\"4.5\">4.5+</option>\n"
        "          <option value=\"4.7\">4.7+</option>\n"
        "          <option value=\"4.9\">4.9+</option>\n"
        "        </select>\n"
        "      </div>\n"

        "      <div class=\"filter-section\">\n"
        "        <h3>Min Google Reviews</h3>\n"
        "        <select id=\"reviews-min\">\n"
        "          <option value=\"0\">Any</option>\n"
        "          <option value=\"50\">50+</option>\n"
        "          <option value=\"100\">100+</option>\n"
        "          <option value=\"500\">500+</option>\n"
        "        </select>\n"
        "      </div>\n"

        "      <div class=\"filter-section\">\n"
        "        <h3>Cuisine</h3>\n"
        "        <div class=\"checkbox-list\" id=\"cuisine-checks\">\n"
        "          <!-- populated by JS -->\n"
        "        </div>\n"
        "      </div>\n"

        "      <div class=\"filter-section\">\n"
        "        <h3>Area / Address</h3>\n"
        "        <input type=\"text\" id=\"area-search\" placeholder=\"e.g. Shinjuku, Ginza...\">\n"
        "      </div>\n"

        "      <div class=\"filter-section\">\n"
        "        <label id=\"open-now-label\">\n"
        "          <input type=\"checkbox\" id=\"open-now\"> 🕒 Open now (Japan)\n"
        "        </label>\n"
        "        <div class=\"japan-time\" id=\"japan-time\">—</div>\n"
        "      </div>\n"
        "\n"
        "      <div class=\"filter-section\">\n"
        "        <label id=\"top-picks-label\">\n"
        "          <input type=\"checkbox\" id=\"top-picks\"> ⭐ Top picks only\n"
        "        </label>\n"
        "      </div>\n"
        "\n"
        "      <button class=\"reset-btn\" id=\"reset-filters\">Reset Filters</button>\n"
        "    </div>\n"
        "  </div>\n"
        "  <div id=\"map\"></div>\n"
        "</div>\n"

        "<button id=\"sidebar-toggle\" title=\"Toggle filters\">⚙</button>\n"
        "<button id=\"gps-btn\" title=\"Toggle GPS\">📍</button>\n"

        "<div id=\"legend\">\n"
        "  <div style=\"font-weight:600;margin-bottom:5px\">Tabelog</div>\n"
        "  <div class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#10b981\"></span> 4.0+</div>\n"
        "  <div class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#3b82f6\"></span> 3.7–3.99</div>\n"
        "  <div class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#8b5cf6\"></span> &lt;3.7</div>\n"
        "</div>\n"

        "<!-- Leaflet JS -->\n"
        "<script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>\n"
        "<script src=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js\"></script>\n"
        "<script>\n"
        "(function() {\n"
        "'use strict';\n"
        "\n"
        "// ── Data ──────────────────────────────────────────────────────────────\n"
        "var GEOJSON = " + geojson_str + ";\n"
        "var COUNTS  = " + counts_str + ";\n"
        "var CATS    = " + cats_str + ";\n"
        "var TOTAL   = " + str(total) + ";\n"
        "var TOP15_THRESHOLD = " + str(top15_threshold) + ";\n"
        "\n"
        "// ── Dark mode ─────────────────────────────────────────────────────────\n"
        "var darkMode = localStorage.getItem('darkMode') === 'true';\n"
        "function applyDark() {\n"
        "  document.body.classList.toggle('dark', darkMode);\n"
        "  document.getElementById('dark-toggle').textContent = darkMode ? '☀ Light' : '🌙 Dark';\n"
        "  if (window.lightLayer && window.darkLayer && window.map) {\n"
        "    if (darkMode) {\n"
        "      if (map.hasLayer(lightLayer)) { map.removeLayer(lightLayer); map.addLayer(darkLayer); }\n"
        "    } else {\n"
        "      if (map.hasLayer(darkLayer)) { map.removeLayer(darkLayer); map.addLayer(lightLayer); }\n"
        "    }\n"
        "  }\n"
        "}\n"
        "applyDark();\n"
        "document.getElementById('dark-toggle').addEventListener('click', function() {\n"
        "  darkMode = !darkMode;\n"
        "  localStorage.setItem('darkMode', darkMode);\n"
        "  applyDark();\n"
        "});\n"
        "\n"
        "// ── Map init ──────────────────────────────────────────────────────────\n"
        "var map = L.map('map').setView([35.6762, 139.6503], 12);\n"
        "\n"
        "var lightLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {\n"
        "  attribution: '&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors',\n"
        "  maxZoom: 19\n"
        "});\n"
        "var darkLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {\n"
        "  attribution: '&copy; <a href=\"https://www.openstreetmap.org/copyright\">OSM</a> &copy; <a href=\"https://carto.com/\">CARTO</a>',\n"
        "  maxZoom: 19\n"
        "});\n"
        "window.lightLayer = lightLayer;\n"
        "window.darkLayer  = darkLayer;\n"
        "window.map = map;\n"
        "(darkMode ? darkLayer : lightLayer).addTo(map);\n"
        "\n"
        "// ── Cuisine checkboxes ────────────────────────────────────────────────\n"
        "var container = document.getElementById('cuisine-checks');\n"
        "CATS.forEach(function(cat) {\n"
        "  var lbl = document.createElement('label');\n"
        "  var cb  = document.createElement('input');\n"
        "  cb.type = 'checkbox';\n"
        "  cb.value = cat;\n"
        "  cb.dataset.cat = cat;\n"
        "  cb.className = 'cat-cb';\n"
        "  cb.addEventListener('change', applyFilters);\n"
        "  var cnt = document.createElement('span');\n"
        "  cnt.className = 'cat-count';\n"
        "  cnt.textContent = '(' + (COUNTS[cat] || 0) + ')';\n"
        "  lbl.appendChild(cb);\n"
        "  lbl.appendChild(document.createTextNode(' ' + cat));\n"
        "  lbl.appendChild(cnt);\n"
        "  container.appendChild(lbl);\n"
        "});\n"
        "\n"
        "// ── Cluster group ─────────────────────────────────────────────────────\n"
        "var clusterGroup = L.markerClusterGroup({\n"
        "  maxClusterRadius: 50,\n"
        "  spiderfyOnMaxZoom: true,\n"
        "  showCoverageOnHover: false,\n"
        "  zoomToBoundsOnClick: true\n"
        "});\n"
        "map.addLayer(clusterGroup);\n"
        "\n"
        "// ── Helpers ───────────────────────────────────────────────────────────\n"
        "function haversine(lat1, lng1, lat2, lng2) {\n"
        "  var R = 6371;\n"
        "  var dLat = (lat2 - lat1) * Math.PI / 180;\n"
        "  var dLng = (lng2 - lng1) * Math.PI / 180;\n"
        "  var a = Math.sin(dLat/2)*Math.sin(dLat/2) +\n"
        "          Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*\n"
        "          Math.sin(dLng/2)*Math.sin(dLng/2);\n"
        "  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));\n"
        "}\n"
        "function walkTime(km) {\n"
        "  var mins = Math.round(km / 5 * 60);\n"
        "  if (mins < 1) return '< 1 min';\n"
        "  if (mins < 60) return mins + ' min';\n"
        "  return Math.floor(mins/60) + 'h ' + (mins%60) + 'min';\n"
        "}\n"
        "function markerColor(tabelog) {\n"
        "  if (tabelog >= 4.0) return '#10b981';\n"
        "  if (tabelog >= 3.7) return '#3b82f6';\n"
        "  return '#8b5cf6';\n"
        "}\n"
        "function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;'); }\n"
        "// Render a single slot range: \"17:00–23:00\" or \"11:30–14:30, 17:30–22:00\"\n"
        "function slotLabel(slots) { return slots.map(function(s){ return s.open + '–' + (s.close || '24h'); }).join(', '); }\n"
        "// Find the next opening from now. Returns string like \"Tue 17:00\" or null if open right now or unknown.\n"
        "function nextOpening(p) {\n"
        "  var now = getTokyoDate();\n"
        "  return _nextOpeningFrom(p, now);\n"
        "}\n"
        "// Pure Asia/Tokyo time helpers. _TokyoDate is the wall-clock time in Tokyo,\n"
        "// used by every open/close check so the filter is synced with the actual\n"
        "// time of day in Japan regardless of where the user is.\n"
        "function getTokyoDate() {\n"
        "  // Trick: format the local Date as a string in Tokyo TZ, then re-parse it.\n"
        "  // This gives a Date object whose getHours()/getDay() reflect Tokyo wall time.\n"
        "  var s = new Date().toLocaleString('en-US', { timeZone: 'Asia/Tokyo' });\n"
        "  return new Date(s);\n"
        "}\n"
        "function getTokyoMinutesNow() {\n"
        "  // More accurate minutes-since-midnight using Intl (no DST in Tokyo, safe).\n"
        "  var parts = new Intl.DateTimeFormat('en-US', {\n"
        "    timeZone: 'Asia/Tokyo', hour12: false,\n"
        "    hour: '2-digit', minute: '2-digit', weekday: 'short'\n"
        "  }).formatToParts(new Date());\n"
        "  var h = 0, m = 0, weekday = 0;\n"
        "  for (var i = 0; i < parts.length; i++) {\n"
        "    if (parts[i].type === 'hour') h = parseInt(parts[i].value, 10) % 24;\n"
        "    if (parts[i].type === 'minute') m = parseInt(parts[i].value, 10);\n"
        "    if (parts[i].type === 'weekday') {\n"
        "      weekday = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].indexOf(parts[i].value);\n"
        "    }\n"
        "  }\n"
        "  return { mins: h * 60 + m, dayIdx: weekday };\n"
        "}\n"
        "// Is the restaurant open at the given Tokyo time? Returns:\n"
        "//   true  → has a slot covering the current minute on the current day\n"
        "//   false → explicit closed status, or no slot covering now\n"
        "//   null  → no hours data available (don't filter)\n"
        "function isOpenAt(p) {\n"
        "  var days = p.regular_opening_hours;\n"
        "  if (!days || days.length !== 7) return null;\n"
        "  var t = getTokyoMinutesNow();\n"
        "  var day = days[t.dayIdx];\n"
        "  if (!day || day.closed) return false;\n"
        "  for (var i = 0; i < day.slots.length; i++) {\n"
        "    var s = day.slots[i];\n"
        "    var oh = parseInt(s.open.split(':')[0]);\n"
        "    var om = parseInt(s.open.split(':')[1]);\n"
        "    var openMin = oh * 60 + om;\n"
        "    var closeMin;\n"
        "    if (!s.close) {\n"
        "      // \"24h\" → treat as open through end of day\n"
        "      closeMin = 24 * 60;\n"
        "    } else {\n"
        "      var ch = parseInt(s.close.split(':')[0]);\n"
        "      var cm = parseInt(s.close.split(':')[1]);\n"
        "      closeMin = ch * 60 + cm;\n"
        "      // If close <= open, assume it crosses midnight → extend past midnight\n"
        "      if (closeMin <= openMin) closeMin = 24 * 60;\n"
        "    }\n"
        "    if (t.mins >= openMin && t.mins < closeMin) return true;\n"
        "  }\n"
        "  return false;\n"
        "}\n"
        "// Body of the old nextOpening, parameterized over the input date.\n"
        "function _nextOpeningFrom(p, tokyo) {\n"
        "  if (p.current_open_now === true) return null;\n"
        "  var days = p.regular_opening_hours;\n"
        "  if (!days || days.length !== 7) return null;\n"
        "  var startDay = tokyo.getDay();\n"
        "  var startMin = tokyo.getHours() * 60 + tokyo.getMinutes();\n"
        "  var today = days[startDay];\n"
        "  if (today && !today.closed) {\n"
        "    for (var i = 0; i < today.slots.length; i++) {\n"
        "      var s = today.slots[i];\n"
        "      var openMin = parseInt(s.open.split(':')[0]) * 60 + parseInt(s.open.split(':')[1]);\n"
        "      if (openMin > startMin) return 'today at ' + s.open;\n"
        "    }\n"
        "  }\n"
        "  for (var d = 1; d <= 7; d++) {\n"
        "    var idx = (startDay + d) % 7;\n"
        "    var day = days[idx];\n"
        "    if (day && !day.closed && day.slots.length) {\n"
        "      var prefix = d === 1 ? 'tomorrow' : day.day;\n"
        "      return prefix + ' at ' + day.slots[0].open;\n"
        "    }\n"
        "  }\n"
        "  return null;\n"
        "}\n"
        "function formatHours(p) {\n"
        "  if (!p.regular_opening_hours || p.regular_opening_hours.length !== 7) return '';\n"
        "  var days = p.regular_opening_hours;\n"
        "  var now = new Date();\n"
        "  var todayIdx = now.getDay();\n"
        "  var rows = '';\n"
        "  days.forEach(function(d) {\n"
        "    var cell = d.closed ? 'Closed' : slotLabel(d.slots);\n"
        "    var cls = d.closed ? 'closed' : '';\n"
        "    if (d.day_idx === todayIdx) cls += ' today';\n"
        "    rows += '<tr class=\"' + cls + '\"><td class=\"day\">' + d.day + '</td><td>' + escHtml(cell) + '</td></tr>';\n"
        "  });\n"
        "  // Auto-expand the details so hours are visible on first open\n"
        "  var next = nextOpening(p);\n"
        "  var nextHtml = next ? '<div class=\"next-opening\">Next: ' + escHtml(next) + '</div>' : '';\n"
        "  return nextHtml\n"
        "       + '<details class=\"hours-details\" open>'\n"
        "       +   '<summary>🕒 Opening hours</summary>'\n"
        "       +   '<table class=\"hours-table\">' + rows + '</table>'\n"
        "       + '</details>';\n"
        "}\n"
        "function statusBadge(p) {\n"
        "  if (p.current_open_now === true)  return '<span class=\"status-badge open\">● Open now</span>';\n"
        "  if (p.current_open_now === false) return '<span class=\"status-badge closed\">● Closed</span>';\n"
        "  return '<span class=\"status-badge unknown\">● Hours unknown</span>';\n"
        "}\n"
        "function makePopup(p) {\n"
        "  var nameJpPart = (p.name_jp && p.name_jp !== p.name)\n"
        "    ? '<div class=\"popup-name-jp\">' + escHtml(p.name_jp) + '</div>' : '';\n"
        "  var tabelogSearch = 'https://tabelog.com/en/rstLst/?sw=' + encodeURIComponent(p.name_jp || p.name);\n"
        "  var gmapsUrl = p.place_id\n"
        "    ? 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(p.name) + '&query_place_id=' + encodeURIComponent(p.place_id)\n"
        "    : 'https://www.google.com/maps/search/?api=1&query=' + p.lat + ',' + p.lng;\n"
        "  var distHtml = '';\n"
        "  if (userLat !== null) {\n"
        "    var km = haversine(userLat, userLng, p.lat, p.lng);\n"
        "    distHtml = '<span>🚶 ' + walkTime(km) + ' (' + km.toFixed(2) + ' km)</span>';\n"
        "  }\n"
        "  return '<div class=\"popup-title\">' + escHtml(p.name) + '</div>'\n"
        "       + nameJpPart\n"
        "       + '<div class=\"popup-ratings\">'\n"
        "       + '<a class=\"rating-chip tabelog\" href=\"' + tabelogSearch + '\" target=\"_blank\" rel=\"noopener\">📊 Tabelog: ' + p.tabelog_rating.toFixed(2) + '</a>'\n"
        "       + '<a class=\"rating-chip google\" href=\"' + gmapsUrl + '\" target=\"_blank\" rel=\"noopener\">⭐ Google: ' + p.google_rating.toFixed(1) + '</a>'\n"
        "       + '</div>'\n"
        "       + '<div class=\"popup-status-row\">' + statusBadge(p) + '</div>'\n"
        "       + '<div class=\"popup-meta\">'\n"
        "       + '<span>💬 ' + (p.google_reviews || 0).toLocaleString() + ' reviews</span>'\n"
        "       + '<span>🍽️ ' + escHtml(p.cuisine || 'N/A') + '</span>'\n"
        "       + '<span>📍 ' + escHtml(p.area || p.address || '') + '</span>'\n"
        "       + distHtml\n"
        "       + '</div>'\n"
        "       + formatHours(p);\n"
        "}\n"
        "\n"
        "// ── Pre-build markers array ────────────────────────────────────────────\n"
        "var allMarkers = [];\n"
        "GEOJSON.features.forEach(function(feat) {\n"
        "  var p   = feat.properties;\n"
        "  var coords = feat.geometry.coordinates;\n"
        "  var color = markerColor(p.tabelog_rating);\n"
        "  var m = L.circleMarker([coords[1], coords[0]], {\n"
        "    radius: 7,\n"
        "    fillColor: color,\n"
        "    color: '#fff',\n"
        "    weight: 1.5,\n"
        "    opacity: 1,\n"
        "    fillOpacity: 0.85\n"
        "  });\n"
        "  m.bindPopup(function() { return makePopup(p); }, { maxWidth: 280 });\n"
        "  m._foodProps = p;\n"
        "  allMarkers.push(m);\n"
        "});\n"
        "\n"
        "// ── Filter logic ──────────────────────────────────────────────────────\n"
        "var userLat = null, userLng = null;\n"
        "\n"
        "function applyFilters() {\n"
        "  var tMin   = parseFloat(document.getElementById('tabelog-min').value);\n"
        "  var gMin   = parseFloat(document.getElementById('google-min').value);\n"
        "  var rMin   = parseInt(document.getElementById('reviews-min').value, 10);\n"
        "  var areaQ  = document.getElementById('area-search').value.trim().toLowerCase();\n"
        "  var topOnly= document.getElementById('top-picks').checked;\n"
        "  var openNow= document.getElementById('open-now').checked;\n"
        "  var checkedCats = [];\n"
        "  document.querySelectorAll('.cat-cb:checked').forEach(function(cb) {\n"
        "    checkedCats.push(cb.value);\n"
        "  });\n"
        "  clusterGroup.clearLayers();\n"
        "  var shown = 0, openMatched = 0;\n"
        "  allMarkers.forEach(function(m) {\n"
        "    var p = m._foodProps;\n"
        "    if (p.tabelog_rating < tMin) return;\n"
        "    if (p.google_rating  < gMin) return;\n"
        "    if (p.google_reviews < rMin) return;\n"
        "    if (checkedCats.length > 0) {\n"
        "      var match = checkedCats.some(function(c) { return p.categories.indexOf(c) !== -1; });\n"
        "      if (!match) return;\n"
        "    }\n"
        "    if (areaQ) {\n"
        "      var haystack = ((p.area || '') + ' ' + (p.address || '')).toLowerCase();\n"
        "      if (haystack.indexOf(areaQ) === -1) return;\n"
        "    }\n"
        "    if (topOnly) {\n"
        "      var score = (p.tabelog_rating / 4.71) * 0.5 + (p.google_rating / 5.0) * 0.5;\n"
        "      if (score < TOP15_THRESHOLD) return;\n"
        "    }\n"
        "    if (openNow) {\n"
        "      var isOpen = isOpenAt(p);\n"
        "      // null = no hours data → keep visible (don't hide what we can't verify)\n"
        "      if (isOpen === false) return;\n"
        "      if (isOpen === true) openMatched++;\n"
        "    }\n"
        "    clusterGroup.addLayer(m);\n"
        "    shown++;\n"
        "  });\n"
        "  var line = shown.toLocaleString() + ' Restaurants' + (shown < TOTAL ? ' (filtered)' : '') +\n"
        "    ' \\u2022 Tabelog 3.4+ \\u2229 Google 4.2+';\n"
        "  if (openNow) {\n"
        "    line += ' \\u2022 ' + openMatched.toLocaleString() + ' open now';\n"
        "  }\n"
        "  document.getElementById('stats-line').textContent = line;\n"
        "}\n"
        "applyFilters();\n"
        "\n"
        "// ── Filter event wiring ───────────────────────────────────────────────\n"
        "['tabelog-min','google-min','reviews-min'].forEach(function(id) {\n"
        "  document.getElementById(id).addEventListener('change', applyFilters);\n"
        "});\n"
        "document.getElementById('area-search').addEventListener('input', applyFilters);\n"
        "document.getElementById('top-picks').addEventListener('change', applyFilters);\n"
        "document.getElementById('open-now').addEventListener('change', applyFilters);\n"
        "\n"
        "document.getElementById('reset-filters').addEventListener('click', function() {\n"
        "  document.getElementById('tabelog-min').value = '3.4';\n"
        "  document.getElementById('google-min').value  = '4.2';\n"
        "  document.getElementById('reviews-min').value = '0';\n"
        "  document.getElementById('area-search').value = '';\n"
        "  document.getElementById('top-picks').checked  = false;\n"
        "  document.getElementById('open-now').checked   = false;\n"
        "  document.querySelectorAll('.cat-cb').forEach(function(cb) { cb.checked = false; });\n"
        "  applyFilters();\n"
        "});\n"
        "\n"
        "// ── Live Japan time ticker (re-evaluates open-now filter every minute) ──\n"
        "var jtEl = document.getElementById('japan-time');\n"
        "var JST_WEEKDAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];\n"
        "function updateJapanTime() {\n"
        "  var t = getTokyoMinutesNow();\n"
        "  var h = Math.floor(t.mins / 60), m = t.mins % 60;\n"
        "  var hh = h < 10 ? '0' + h : '' + h;\n"
        "  var mm = m < 10 ? '0' + m : '' + m;\n"
        "  jtEl.textContent = 'Japan ' + JST_WEEKDAYS[t.dayIdx] + ' ' + hh + ':' + mm;\n"
        "  jtEl.classList.add('live');\n"
        "}\n"
        "updateJapanTime();\n"
        "// Re-render every 30 seconds so the filter stays in sync as time ticks over.\n"
        "setInterval(function() {\n"
        "  updateJapanTime();\n"
        "  if (document.getElementById('open-now').checked) applyFilters();\n"
        "}, 30000);\n"
        "\n"
        "// ── Sidebar toggle (mobile) ───────────────────────────────────────────\n"
        "var sidebar = document.getElementById('sidebar');\n"
        "var toggleBtn = document.getElementById('sidebar-toggle');\n"
        "function isMobile() { return window.innerWidth < 768; }\n"
        "if (isMobile()) { sidebar.classList.remove('open'); }\n"
        "toggleBtn.addEventListener('click', function() {\n"
        "  sidebar.classList.toggle('open');\n"
        "});\n"
        "// close sidebar when clicking map on mobile\n"
        "document.getElementById('map').addEventListener('click', function() {\n"
        "  if (isMobile()) sidebar.classList.remove('open');\n"
        "});\n"
        "\n"
        "// ── GPS ───────────────────────────────────────────────────────────────\n"
        "var gpsBtn       = document.getElementById('gps-btn');\n"
        "var gpsWatchId   = null;\n"
        "var userMarker   = null;\n"
        "gpsBtn.addEventListener('click', function() {\n"
        "  if (gpsWatchId !== null) {\n"
        "    navigator.geolocation.clearWatch(gpsWatchId);\n"
        "    gpsWatchId = null;\n"
        "    if (userMarker) { map.removeLayer(userMarker); userMarker = null; }\n"
        "    userLat = null; userLng = null;\n"
        "    gpsBtn.classList.remove('active');\n"
        "    return;\n"
        "  }\n"
        "  if (!navigator.geolocation) { alert('Geolocation not supported.'); return; }\n"
        "  gpsBtn.classList.add('active');\n"
        "  gpsWatchId = navigator.geolocation.watchPosition(function(pos) {\n"
        "    userLat = pos.coords.latitude;\n"
        "    userLng = pos.coords.longitude;\n"
        "    if (userMarker) { map.removeLayer(userMarker); }\n"
        "    userMarker = L.circleMarker([userLat, userLng], {\n"
        "      radius: 9, fillColor: '#ef4444', color: '#fff', weight: 2, fillOpacity: 1\n"
        "    }).addTo(map);\n"
        "    map.setView([userLat, userLng], 15);\n"
        "  }, function() {\n"
        "    alert('Unable to retrieve location.');\n"
        "    gpsBtn.classList.remove('active');\n"
        "  }, { enableHighAccuracy: true });\n"
        "});\n"
        "\n"
        "// ── Service Worker ────────────────────────────────────────────────────\n"
        "if ('serviceWorker' in navigator) {\n"
        "  try {\n"
        "    navigator.serviceWorker.register('/tokyo-food-finder/sw.js');\n"
        "  } catch(e) {\n"
        "    console.warn('SW registration failed:', e);\n"
        "  }\n"
        "}\n"
        "\n"
        "})();\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )


if __name__ == "__main__":
    main()
