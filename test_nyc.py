"""
NYC area test script — run with: venv/bin/python3 test_nyc.py
Tests each layer of the pipeline separately so you can see exactly where things stand.
"""
import asyncio
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "PLACEHOLDER")
os.environ.setdefault("SERPAPI_KEY", "PLACEHOLDER")

# ── Layer 1: ZIP radius ───────────────────────────────────────────────────────
print("\n━━━ LAYER 1: ZIP RADIUS EXPANSION ━━━")
from backend.zipradius import get_zips_in_radius, get_zip_location

NYC_ZIPS = ["11201", "10001", "10036", "11215", "10453"]  # Brooklyn, Midtown, Hell's Kitchen, Park Slope, Bronx

for z in NYC_ZIPS[:2]:
    loc = get_zip_location(z)
    area_zips = get_zips_in_radius(z, 25)
    print(f"  {z} ({loc['city'] if loc else '?'}): {len(area_zips)} ZIPs within 25 miles")


# ── Layer 2: Discovery (URL scraping — no API key needed) ────────────────────
print("\n━━━ LAYER 2: URL DISCOVERY (StorageTreasures + Bid13) ━━━")
from backend.discovery import _discover_storage_treasures, _discover_bid13

TEST_ZIPS = ["11201", "10001"]

async def test_discovery():
    st_urls = await _discover_storage_treasures(TEST_ZIPS)
    b13_urls = await _discover_bid13(TEST_ZIPS)
    print(f"  StorageTreasures: {len(st_urls)} auction URLs found")
    for u in st_urls[:5]:
        print(f"    {u}")
    print(f"  Bid13: {len(b13_urls)} auction URLs found")
    for u in b13_urls[:5]:
        print(f"    {u}")
    return st_urls, b13_urls

st_urls, b13_urls = asyncio.run(test_discovery())
all_urls = st_urls + b13_urls


# ── Layer 3: Scraping (needs ANTHROPIC_API_KEY) ───────────────────────────────
print("\n━━━ LAYER 3: PAGE SCRAPING + CLAUDE HAIKU EXTRACTION ━━━")
if os.getenv("ANTHROPIC_API_KEY") == "PLACEHOLDER":
    print("  ⚠ ANTHROPIC_API_KEY not set — skipping scrape layer")
    print("  Set it in .env to continue the pipeline")
    sys.exit(0)

if not all_urls:
    print("  No URLs found from discovery — check network / site structure")
    sys.exit(0)

from backend.scraper import scrape_auction_page

async def test_scrape():
    test_url = all_urls[0]
    print(f"  Testing scrape on: {test_url}")
    units = await scrape_auction_page(test_url)
    print(f"  Extracted {len(units)} tenant units")
    for u in units[:3]:
        print(f"    {u.tenant.name} — Unit {u.tenant.unit_number} — {u.tenant.auction_date or 'no date'}")
    return units

units = asyncio.run(test_scrape())


# ── Layer 4: Enrichment (needs SERPAPI_KEY) ───────────────────────────────────
print("\n━━━ LAYER 4: OSINT ENRICHMENT (SerpApi) ━━━")
if os.getenv("SERPAPI_KEY") == "PLACEHOLDER":
    print("  ⚠ SERPAPI_KEY not set — skipping enrichment layer")
    print("  Get a key at serpapi.com (100 free searches/month)")
else:
    from backend.enrichment import enrich_tenant
    if units:
        first = units[0]
        print(f"  Enriching: {first.tenant.name}")
        result = enrich_tenant(first.tenant.name)
        print(f"  Obituary found: {result.obituary_found}")
        print(f"  Obit career: {result.obit_career_description or 'not found'}")
        print(f"  High-value trade signals: {result.high_value_trade_signals or 'none'}")


# ── Layer 5: Evaluation (needs ANTHROPIC_API_KEY) ────────────────────────────
print("\n━━━ LAYER 5: CLAUDE OPUS EVALUATION ━━━")
if units and os.getenv("ANTHROPIC_API_KEY") != "PLACEHOLDER":
    from backend.evaluator import evaluate_unit
    first = units[0]
    print(f"  Evaluating: {first.tenant.name}")
    ev = evaluate_unit(first)
    print(f"  Career identified: {ev.career_identified}")
    print(f"  Score: {ev.score}/10")
    print(f"  Trade equipment probability: {ev.trade_equipment_probability}")
    print(f"  Estimated value: {ev.estimated_value_range}")
    print(f"  Recommendation: {ev.recommendation}")
    print(f"  Reasoning: {ev.reasoning}")
