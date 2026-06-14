# Tabelog 23-ward scraper

Re-scrapes Tokyo's 23 special wards for every restaurant with a **Tabelog rating
≥ 3.4**, working around Tabelog's 1,200-results-per-query cap by searching one
ward at a time and de-duplicating. Tabelog-only for now (no Google cross-ref).

## Why the old dataset was incomplete

Tabelog's ranked list maxes out at **60 pages × 20 = 1,200 results per query**.
The previous scraper paginated a single *Tokyo-wide* list sorted by rating, so it
could only ever see the top ~1,200 restaurants — that's why coverage stalled
around 2,000. This scraper issues one rating-sorted query **per ward** (23
queries), each comfortably under the cap, then merges and de-dupes by URL. Expect
substantially more than 2,198 (plausibly 5,000–10,000+).

## Install

```bash
cd scraper
python -m venv .venv && source .venv/bin/activate    # optional
pip install -r requirements.txt
```

## Verify it works before a long run

```bash
python tabelog_scraper.py selftest        # offline: proves the parsers work
python tabelog_scraper.py debug-html C13104   # live: fetch one Shinjuku page, save HTML
```

`debug-html` writes `debug_page.html` and prints how many rows the parser found.
**If it prints `0 rows`**, Tabelog changed its markup — open `debug_page.html`,
find the current class names, and update the selectors in
`parse_list_page()` / `has_next_page()`. **If the fetch fails with 403**, see
*Anti-bot* below.

## Run

```bash
# Stage 1 — list scrape (fast, no coordinates):
python tabelog_scraper.py list

# Stage 2 — visit each restaurant page for lat/lng + address (slow):
python tabelog_scraper.py details

# Or both:
python tabelog_scraper.py all --delay 2.5
```

Both stages **checkpoint and resume** — re-running continues where it stopped
(`tabelog_list.json` tracks finished wards; `tabelog_full.json` tracks enriched
restaurants). Safe to Ctrl-C and restart.

Outputs:
- `tabelog_list.json` / `tabelog_list_flat.json` — stage 1
- `tabelog_full.json` / `tabelog_full_flat.json` — stage 2 (with coordinates)

## Stage 3 (optional) — Google Places cross-reference

Attaches a Google rating/review-count/place_id to each Tabelog restaurant and
keeps only those at **Google ≥ 4.2** — giving the Tabelog 3.4+ ∩ Google 4.2+ set,
written directly in `build.py`'s record shape.

```bash
export GOOGLE_PLACES_API_KEY=...            # never commit; .env is gitignored
python google_crossref.py selftest          # offline sanity check
python google_crossref.py tabelog_full_flat.json ../final_restaurants_merged.json --dry-run   # cost estimate
python google_crossref.py tabelog_full_flat.json ../final_restaurants_merged.json --limit 20  # cheap test
python google_crossref.py tabelog_full_flat.json ../final_restaurants_merged.json             # full run
```

- **One Google call per restaurant** (rating, reviews, coords, place_id all come
  back from Text Search). Estimate ≈ **$0.032 each** → run `--dry-run` first to
  see the total. Google's monthly free credit offsets part of it.
- **Engines:** `--engine new` (Places API New, default) or `--engine legacy`
  (classic Places API). New Google Cloud projects often have only one enabled —
  if you get a permission error, switch engines or enable the other API.
- **Resumable:** progress is cached in `<out>.cache.json`; re-running skips
  done restaurants. Ctrl-C safe.
- **Match quality:** when a restaurant has Tabelog coordinates, a Google hit more
  than `--max-distance` metres away (default 400) is rejected as a mismatch.
- Outputs the kept set to `<out>` and a `<out>_dropped.json` (low rating /
  mismatch / not found / errors) for review.
- Markers use the **Google** coordinates when available.

Then regenerate the map — `build.py` already reads `final_restaurants_merged.json`:

```bash
cd .. && python build.py        # rebuilds index.html with the new data
```

## Feed it back into the map (Tabelog-only, no Google)

If you're skipping the Google step:

```bash
python to_map_format.py tabelog_full_flat.json ../final_restaurants_tabelog.json
# then point build.py at that file and regenerate index.html
```

`build.py` currently reads `final_restaurants_merged.json`; change that one path
to `final_restaurants_tabelog.json` (or merge the two) to map the new data.

## Anti-bot (HTTP 403)

Tabelog blocks many **datacenter/cloud IPs** with `403 Forbidden` regardless of
headers (confirmed from this build environment). From a **residential
connection** the default `requests` engine usually works. If you still get 403s:

```bash
pip install playwright && playwright install chromium
python tabelog_scraper.py all --engine playwright --delay 3
```

This drives a real headless Chromium, which clears most bot checks. Keep
`--delay` polite (2–3s); going faster invites rate-limiting and is rude to their
servers.

## Tuning

| Flag | Default | Meaning |
|------|---------|---------|
| `--min-rating` | `3.4` | Lower bound on Tabelog rating |
| `--engine` | `requests` | `requests` or `playwright` |
| `--delay` | `2.0` | Base polite delay (jittered) between requests |
| `--list-out` | `tabelog_list.json` | Stage 1 checkpoint file |
| `--details-out` | `tabelog_full.json` | Stage 2 checkpoint file |

## Caveats

- **A few large wards could still exceed 1,200 entries at 3.4+.** If a ward hits
  the 60-page cap (you'll see it stop at page 60 while still above 3.4), split it
  further by Tabelog genre code and union the results. Most wards won't hit this.
- Tabelog's selectors drift; the parser has fallbacks but may still need the
  `debug-html` adjustment above after a site redesign.
- Scraping Tabelog is **against their Terms of Service**. This is provided for
  your own use; run it responsibly and at your own risk.
