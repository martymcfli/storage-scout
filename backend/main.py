import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from .models import ScrapeRequest, ChatRequest, DiscoverRequest, Alert, UserProfile
from .scraper import scrape_auction_page
from .enrichment import enrich_tenant
from .evaluator import evaluate_unit
from .vision import analyze_unit_visually
from .bid_strategy import build_bid_strategy
from .agents import chat_stream, deep_research_unit
from .storage import (
    get_all_auctions, get_auction_by_id, save_auction, delete_auction,
    save_alert, alert_exists, get_all_alerts,
)
from .discovery import discover_new_auctions, filter_units_by_day
from .profile import load_profile, save_profile, profile_exists
from .zipradius import get_zips_in_radius, get_zip_location

VISION_SCORE_THRESHOLD = 5  # run vision only on units scoring 5+

app = FastAPI(title="Storage Scout API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_ALERT_THRESHOLD = 7


# --- Pipeline helpers ---

def _alert_threshold() -> int:
    p = load_profile()
    return p.alert_score_threshold if p else DEFAULT_ALERT_THRESHOLD


def _maybe_alert(unit, threshold: int) -> None:
    if unit.evaluation.score >= threshold and not alert_exists(unit.id):
        alert = Alert(
            unit_id=unit.id,
            tenant_name=unit.tenant.name,
            facility_address=unit.facility_address or unit.tenant.facility_address,
            score=unit.evaluation.score,
            likely_contents=unit.evaluation.likely_contents,
            trade_equipment_probability=unit.evaluation.trade_equipment_probability,
            estimated_value_range=unit.evaluation.estimated_value_range,
            source_url=unit.source_url,
        )
        save_alert(alert)
        print(f"[ALERT] Score {unit.evaluation.score}/10 — {unit.tenant.name} (unit {unit.tenant.unit_number})")


async def _run_full_pipeline(url: str, available_days: Optional[list[str]] = None) -> list:
    """Scrape → [day filter] → enrich → evaluate → [vision + bid strategy] → save → alert."""
    threshold = _alert_threshold()
    profile = load_profile()
    units = await scrape_auction_page(url)

    # apply available-days filter before spending API calls on enrichment
    if available_days:
        units = filter_units_by_day(units, available_days)

    results = []
    for unit in units:
        unit.enrichment = enrich_tenant(unit.tenant.name)
        unit.evaluation = evaluate_unit(unit)

        # run vision + bid strategy on high-scoring units that have listing photos
        if unit.evaluation.score >= VISION_SCORE_THRESHOLD:
            try:
                unit.visual_inventory = await analyze_unit_visually(unit.source_url)
                print(f"[Pipeline] Vision: {unit.visual_inventory.photos_analyzed} photos analyzed "
                      f"for {unit.tenant.name}")
            except Exception as e:
                print(f"[Pipeline] Vision failed for {unit.tenant.name}: {e}")

            try:
                unit.bid_strategy = build_bid_strategy(unit, unit.visual_inventory, profile)
                print(f"[Pipeline] Bid strategy: max bid ${unit.bid_strategy.max_bid} "
                      f"for {unit.tenant.name}")
            except Exception as e:
                print(f"[Pipeline] Bid strategy failed for {unit.tenant.name}: {e}")

        unit.pipeline_completed = True
        save_auction(unit)
        _maybe_alert(unit, threshold)
        results.append(unit)

    return results


# --- Profile endpoints ---

@app.get("/profile")
def get_profile():
    p = load_profile()
    if not p:
        raise HTTPException(status_code=404, detail="No profile configured yet")
    return p


@app.post("/profile")
def set_profile(profile: UserProfile):
    save_profile(profile)
    return profile


@app.get("/profile/coverage")
def profile_coverage():
    """Return the number of ZIPs and location info for the current profile — no scraping."""
    p = load_profile()
    if not p:
        raise HTTPException(status_code=404, detail="No profile configured yet")

    zips = get_zips_in_radius(p.home_zip, p.max_miles)
    location = get_zip_location(p.home_zip)

    return {
        "home_zip": p.home_zip,
        "max_miles": p.max_miles,
        "zip_count": len(zips),
        "location": location,
        "available_days": p.available_days,
        "alert_score_threshold": p.alert_score_threshold,
        "budget_ceiling": p.budget_ceiling,
    }


# --- Core endpoints ---

@app.get("/")
def root():
    return {"status": "ok", "service": "Storage Scout API", "profile_configured": profile_exists()}


@app.get("/auctions")
def list_auctions():
    return get_all_auctions()


@app.get("/auctions/{auction_id}")
def get_auction(auction_id: str):
    unit = get_auction_by_id(auction_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Auction not found")
    return unit


@app.delete("/auctions/{auction_id}")
def remove_auction(auction_id: str):
    if not delete_auction(auction_id):
        raise HTTPException(status_code=404, detail="Auction not found")
    return {"deleted": auction_id}


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    """Scrape a single URL and run the full pipeline."""
    p = load_profile()
    available_days = p.available_days if p else None
    try:
        units = await _run_full_pipeline(req.url, available_days=available_days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"units_found": len(units), "units": units}


@app.post("/enrich/{auction_id}")
def enrich(auction_id: str):
    unit = get_auction_by_id(auction_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Auction not found")
    unit.enrichment = enrich_tenant(unit.tenant.name)
    save_auction(unit)
    return unit


@app.post("/evaluate/{auction_id}")
def evaluate(auction_id: str):
    unit = get_auction_by_id(auction_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Auction not found")
    unit.evaluation = evaluate_unit(unit)
    unit.pipeline_completed = True
    save_auction(unit)
    _maybe_alert(unit, _alert_threshold())
    return unit


@app.post("/discover")
async def discover(req: Optional[DiscoverRequest] = None):
    """Auto-discover auction URLs. Uses profile ZIPs + day filter unless zip_codes overridden."""
    p = load_profile()

    # resolve ZIP list: explicit override > profile radius > error
    if req and req.zip_codes:
        zip_codes = req.zip_codes
    elif p:
        zip_codes = get_zips_in_radius(p.home_zip, p.max_miles)
    else:
        raise HTTPException(
            status_code=400,
            detail="No ZIP codes provided and no profile configured. Set up your profile first.",
        )

    available_days = p.available_days if p else []

    try:
        new_urls = await discover_new_auctions(zip_codes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discovery failed: {e}")

    new_units_count = 0
    skipped_day_filter = 0
    errors = []

    for url in new_urls:
        try:
            before = new_units_count
            units = await _run_full_pipeline(url, available_days=available_days)
            added = len(units)
            new_units_count += added
            # track how many were filtered by day (approximate: units scraped - units added)
        except Exception as e:
            errors.append({"url": url, "error": str(e)})

    return {
        "zip_codes_searched": len(zip_codes),
        "new_urls_found": len(new_urls),
        "new_units_added": new_units_count,
        "day_filter_active": bool(available_days),
        "errors": errors,
    }


@app.post("/vision/{auction_id}")
async def run_vision(auction_id: str):
    """Run computer vision analysis on a unit's listing photos."""
    unit = get_auction_by_id(auction_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Auction not found")
    try:
        unit.visual_inventory = await analyze_unit_visually(unit.source_url)
        profile = load_profile()
        if unit.evaluation:
            unit.bid_strategy = build_bid_strategy(unit, unit.visual_inventory, profile)
        save_auction(unit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return unit


@app.post("/bid-strategy/{auction_id}")
def run_bid_strategy(auction_id: str):
    """(Re)calculate bid strategy from existing visual inventory + evaluation."""
    unit = get_auction_by_id(auction_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Auction not found")
    if not unit.evaluation:
        raise HTTPException(status_code=400, detail="Evaluate the unit first")
    profile = load_profile()
    unit.bid_strategy = build_bid_strategy(unit, unit.visual_inventory, profile)
    save_auction(unit)
    return unit


@app.post("/research/{auction_id}")
async def deep_research(auction_id: str):
    """Streaming /deep-research report for a specific unit."""
    unit = get_auction_by_id(auction_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Auction not found")
    if not unit.evaluation:
        raise HTTPException(status_code=400, detail="Evaluate the unit before running deep research")

    def generate():
        for chunk in deep_research_unit(unit):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/alerts")
def list_alerts():
    return get_all_alerts()


@app.post("/chat")
async def chat(req: ChatRequest):
    """Streaming chat endpoint — Server-Sent Events."""
    def generate():
        for chunk in chat_stream(req.message, req.history, req.auction_id):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
