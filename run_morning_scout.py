#!/usr/bin/env python3
"""
Storage Scout — scheduled morning runner.
Runs the full discovery + pipeline without needing the FastAPI server.

Cron schedule (5am, 6am, 7am daily):
  0 5,6,7 * * * /Users/owenmccormick/storage-scout/venv/bin/python3 \
    /Users/owenmccormick/storage-scout/run_morning_scout.py \
    >> /Users/owenmccormick/storage-scout/logs/scout.log 2>&1

Target: 25 miles of ZIP 11215 (Brooklyn, NY)
"""
import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Load .env before importing backend modules
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
HOME_ZIP    = "11215"        # Brooklyn, NY (Park Slope / Gowanus)
MAX_MILES   = 25
SCORE_FLOOR = 5              # run vision + bid strategy on units scoring ≥ this

# ── Logging helper ────────────────────────────────────────────────────────────
LOG_FILE = PROJECT_ROOT / "logs" / "scout.log"
LOG_FILE.parent.mkdir(exist_ok=True)

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


# ── Main pipeline ─────────────────────────────────────────────────────────────
async def run() -> None:
    log("=" * 60)
    log(f"Morning Scout starting — ZIP {HOME_ZIP}, {MAX_MILES}mi radius")

    from backend.zipradius import get_zips_in_radius
    from backend.discovery import discover_new_auctions, filter_units_by_day
    from backend.scraper import scrape_auction_page
    from backend.enrichment import enrich_tenant
    from backend.evaluator import evaluate_unit
    from backend.vision import analyze_unit_visually
    from backend.bid_strategy import build_bid_strategy
    from backend.storage import save_auction, alert_exists, save_alert, get_existing_urls
    from backend.profile import load_profile
    from backend.models import Alert

    profile = load_profile()

    # Use profile's available_days and alert threshold if set; fall back to defaults
    available_days = profile.available_days if profile else []
    alert_threshold = profile.alert_score_threshold if profile else 7
    target_daily_profit = profile.target_daily_profit if profile else 300

    zip_codes = get_zips_in_radius(HOME_ZIP, MAX_MILES)
    log(f"Searching {len(zip_codes)} ZIP codes")

    # ── Discovery ──────────────────────────────────────────────────────────────
    try:
        new_urls = await discover_new_auctions(zip_codes)
    except Exception as e:
        log(f"ERROR during discovery: {e}")
        return

    log(f"Found {len(new_urls)} new auction URLs to process")

    if not new_urls:
        log("Nothing new — exiting early")
        return

    # ── Pipeline ───────────────────────────────────────────────────────────────
    processed = 0
    alerted   = 0
    errors    = 0

    for url in new_urls:
        try:
            units = await scrape_auction_page(url)
            if available_days:
                units = filter_units_by_day(units, available_days)

            for unit in units:
                unit.enrichment = enrich_tenant(unit.tenant.name)
                unit.evaluation = evaluate_unit(unit)
                score = unit.evaluation.score

                log(f"  {unit.tenant.name} — Unit {unit.tenant.unit_number} — Score {score}/10 "
                    f"— {unit.evaluation.career_identified}")

                # Vision + bid strategy for high-scoring units
                if score >= SCORE_FLOOR:
                    try:
                        unit.visual_inventory = await analyze_unit_visually(unit.source_url)
                        log(f"    Vision: {unit.visual_inventory.photos_analyzed} photos "
                            f"${unit.visual_inventory.total_value_low}–${unit.visual_inventory.total_value_high}")
                    except Exception as ve:
                        log(f"    Vision error: {ve}")

                    try:
                        unit.bid_strategy = build_bid_strategy(unit, unit.visual_inventory, profile)
                        log(f"    Bid strategy: max bid ${unit.bid_strategy.max_bid}")
                    except Exception as be:
                        log(f"    Bid strategy error: {be}")

                unit.pipeline_completed = True
                save_auction(unit)
                processed += 1

                # Alert
                if score >= alert_threshold and not alert_exists(unit.id):
                    alert = Alert(
                        unit_id=unit.id,
                        tenant_name=unit.tenant.name,
                        facility_address=unit.facility_address or unit.tenant.facility_address,
                        score=score,
                        likely_contents=unit.evaluation.likely_contents,
                        trade_equipment_probability=unit.evaluation.trade_equipment_probability,
                        estimated_value_range=unit.evaluation.estimated_value_range,
                        source_url=unit.source_url,
                    )
                    save_alert(alert)
                    alerted += 1
                    log(f"    *** ALERT: score {score}/10 — {unit.evaluation.trade_equipment_probability} "
                        f"trade probability — {unit.evaluation.estimated_value_range} ***")

        except Exception as e:
            log(f"  ERROR processing {url}: {e}")
            errors += 1

    log(f"Run complete — processed={processed} alerts={alerted} errors={errors}")
    log("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())
