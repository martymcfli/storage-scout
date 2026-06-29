"""
Bid Strategist — Claude Sonnet 4.6 reasoning agent.

Combines visual inventory + OSINT evaluation into a concrete bid progression plan.
Central question: what is 1 full day of flip work worth to the user, and does this
unit clear that bar at any realistic bid price?

Time-value model:
  target_daily_profit  = user setting (default $300)
  target_hourly_rate   = target_daily_profit / 8
  total_flip_hours     = visual inventory hours + load/transport estimate
  min_required_profit  = total_flip_hours × target_hourly_rate
  overhead             = transport + platform fees + cleanup estimate
  max_bid              = gross_resale − overhead − min_required_profit
  break_even_bid       = gross_resale − overhead

Bid zones:
  GREEN  = 0 to 60% of max_bid — bid without hesitation
  YELLOW = 60-90% of max_bid — still good, stay disciplined
  RED    = 90-100% of max_bid — final territory, commit mentally before entering
"""
import json
import re
import os
import anthropic

from .models import AuctionUnit, VisualInventory, BidStrategy, UserProfile

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PLATFORM_FEE_RATES = {
    "eBay": 0.1327,          # 13.27% final value fee
    "Facebook Marketplace": 0.05,  # 5% for shipped; 0% local
    "Craigslist": 0.0,
    "specialty auction": 0.20,
    "scrap": 0.0,
}

TRANSPORT_BASE = 40          # $ — gas/vehicle for local pickup
TRANSPORT_PER_MILE = 0.35   # additional $/mile beyond local
CLEANUP_PER_CUBIC_FOOT = 2  # rough cleanup cost for junk items


def _estimate_platform_fees(items: list) -> int:
    total = 0
    for item in items:
        rate = PLATFORM_FEE_RATES.get(item.best_platform, 0.08)
        midpoint = (item.resale_low + item.resale_high) / 2
        total += midpoint * rate
    return int(total)


def _estimate_load_hours(item_count: int) -> float:
    """Rough estimate: loading, transport, unload."""
    base = 2.5   # drive to unit, load, drive home, unload
    per_item = 0.15
    return round(base + item_count * per_item, 1)


def build_bid_strategy(
    unit: AuctionUnit,
    visual: VisualInventory | None,
    profile: UserProfile | None,
) -> BidStrategy:
    """
    Runs Claude Sonnet as the Bid Strategist to synthesize all data into a
    bid plan, then applies the time-value formula for hard numbers.
    """
    target_daily_profit = (profile.target_daily_profit if profile else 300)
    target_hourly_rate = target_daily_profit / 8.0

    # ── Build context block for Sonnet ───────────────────────────────────────
    eval_block = ""
    if unit.evaluation:
        ev = unit.evaluation
        eval_block = f"""
OSINT Evaluation:
  Career identified: {ev.career_identified}
  Score: {ev.score}/10
  Trade equipment probability: {ev.trade_equipment_probability}
  Estimated value range (OSINT): {ev.estimated_value_range}
  Likely contents (OSINT): {', '.join(ev.likely_contents)}
  Reasoning: {ev.reasoning}
"""

    visual_block = ""
    if visual and visual.items:
        item_lines = "\n".join(
            f"  - {item.description} [{item.condition}] "
            f"${item.resale_low}–${item.resale_high} | {item.flip_hours}h | {item.best_platform}"
            + (f" | Note: {item.notes}" if item.notes else "")
            for item in visual.items
        )
        visual_block = f"""
Visual Inventory ({visual.photos_analyzed} photos analyzed):
{item_lines}
  Totals: ${visual.total_value_low}–${visual.total_value_high} gross | {visual.total_flip_hours}h flip time
  Notable finds: {', '.join(visual.notable_finds) or 'none'}
  Red flags: {', '.join(visual.red_flags) or 'none'}
"""

    prompt = f"""You are the Bid Strategist for a storage auction intelligence system.
Your job: synthesize the OSINT evaluation and visual inventory into a concrete bid plan.

USER TIME-VALUE PARAMETERS:
  Target daily profit: ${target_daily_profit}
  Target hourly rate: ${target_hourly_rate:.2f}/hr
  (If this unit takes X hours to fully flip, the net profit must be ≥ X × ${target_hourly_rate:.2f})

UNIT DATA:
  Tenant: {unit.tenant.name}
  Unit: {unit.tenant.unit_number} — {unit.facility_address or unit.tenant.facility_address}
  Default owed: {unit.tenant.default_amount or 'unknown'}
  Auction date: {unit.tenant.auction_date or 'unknown'}
{eval_block}
{visual_block}

OVERHEAD ASSUMPTIONS (standard):
  Transport (local): $40 base
  Platform fees: ~8-13% blended depending on where items sell
  Cleanup/disposal for unsellable items: $20-80 depending on junk density

YOUR TASK — produce a bid strategy with these components:

1. GROSS RESALE ESTIMATE
   Reconcile the visual inventory totals with the OSINT estimated value range.
   If visual confirms OSINT career signals (tools visible + trade career found), use higher end.
   If there's a conflict (furniture-only unit but machinist career), explain the gap and be conservative.
   Give a single realistic gross resale number.

2. OVERHEAD ESTIMATE
   Transport + platform fees + cleanup. Be specific.

3. TIME ESTIMATE
   Total flip hours = visual inventory flip hours + load/transport time.
   Load/transport: 2-3h for a standard unit.

4. BID MATH
   Show the calculation:
   min_required_profit = total_hours × ${target_hourly_rate:.2f}
   max_bid = gross_resale − overhead − min_required_profit
   break_even_bid = gross_resale − overhead

5. BID ZONES
   green_ceiling = max_bid × 0.60  (bid freely)
   yellow_ceiling = max_bid × 0.90 (stay disciplined)
   red_ceiling = max_bid           (absolute walk-away)

6. ROOM PRESENCE STRATEGY
   Tactical advice for auction day: what to reveal, when to bid, when to walk,
   what competitors in the room will be looking for vs. what you know they're missing.
   Be specific to the items identified in this unit.

7. SUMMARY
   2-3 sentences: is this worth bidding? At what price? One thing to watch for.

Return ONLY valid JSON:
{{
  "gross_resale_estimate": <int>,
  "overhead_estimate": <int>,
  "flip_hours_estimate": <float>,
  "min_required_profit": <int>,
  "break_even_bid": <int>,
  "max_bid": <int>,
  "bid_green_ceiling": <int>,
  "bid_yellow_ceiling": <int>,
  "room_strategy": "<tactical advice>",
  "summary": "<2-3 sentences>"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # fallback: use pure math from visual inventory
        gross = (visual.total_value_low + visual.total_value_high) // 2 if visual else 500
        overhead = 80
        flip_hrs = (visual.total_flip_hours if visual else 4.0) + 2.5
        min_profit = int(flip_hrs * target_hourly_rate)
        max_bid = max(0, gross - overhead - min_profit)
        data = {
            "gross_resale_estimate": gross,
            "overhead_estimate": overhead,
            "flip_hours_estimate": flip_hrs,
            "min_required_profit": min_profit,
            "break_even_bid": max(0, gross - overhead),
            "max_bid": max_bid,
            "bid_green_ceiling": int(max_bid * 0.60),
            "bid_yellow_ceiling": int(max_bid * 0.90),
            "room_strategy": "Bid normally. Set your max before entering the room.",
            "summary": "Fallback calculation — run visual analysis for refined estimates.",
        }

    gross = data.get("gross_resale_estimate", 500)
    overhead = data.get("overhead_estimate", 80)
    flip_hrs = data.get("flip_hours_estimate", 4.0)
    min_profit = data.get("min_required_profit", int(flip_hrs * target_hourly_rate))
    max_bid = data.get("max_bid", max(0, gross - overhead - min_profit))
    roi = ((gross - overhead - max_bid) / max(max_bid, 1)) * 100 if max_bid > 0 else 0

    return BidStrategy(
        target_daily_profit=target_daily_profit,
        target_hourly_rate=round(target_hourly_rate, 2),
        estimated_gross_resale=gross,
        estimated_overhead=overhead,
        estimated_flip_hours=round(flip_hrs, 1),
        min_required_profit=min_profit,
        break_even_bid=data.get("break_even_bid", max(0, gross - overhead)),
        max_bid=max_bid,
        bid_green_ceiling=data.get("bid_green_ceiling", int(max_bid * 0.60)),
        bid_yellow_ceiling=data.get("bid_yellow_ceiling", int(max_bid * 0.90)),
        bid_red_ceiling=max_bid,
        expected_roi_at_max_bid=round(roi, 1),
        room_strategy=data.get("room_strategy", ""),
        summary=data.get("summary", ""),
    )
