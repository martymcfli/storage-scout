"""
Claude Opus evaluator.

Scoring philosophy:
  The single most valuable signal in storage auction research is an obituary that names
  a trade career. It is a career record, not a grief record. "Retired machinist" or
  "worked 35 years in custom millwork" signals a unit full of industrial tools that
  general bidders will walk past — tools worth $20K-$100K+ at resale.

  Score is driven first by what career was identified, second by evidence quality.
  A unit with no career signal is always ≤ 5 regardless of other factors.
"""
import json
import re
import anthropic
import os

from .models import AuctionUnit, EvaluationResult

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def evaluate_unit(unit: AuctionUnit) -> EvaluationResult:
    en = unit.enrichment

    # Build the fullest possible enrichment picture for the model
    enrichment_block = ""
    if en:
        enrichment_block = f"""
ENRICHMENT DATA:
  Obituary found: {en.obituary_found}
  Obituary career description: {en.obit_career_description or "not extracted"}
  Career signals (from all searches): {en.career_signals or "none"}
  High-value trade signals: {en.high_value_trade_signals or "none"}
  General trade signals: {en.trade_profession_signals or "none"}
  Business / contractor found: {en.business_found}
  Raw search snippets (all {len(en.raw_snippets)}):
{chr(10).join(f"    [{i+1}] {s}" for i, s in enumerate(en.raw_snippets))}
"""

    prompt = f"""You are a specialist storage auction analyst. Your entire edge in this market comes from one insight:

CORE INSIGHT
The true value in storage units is not raw wealth — it is specialized trade equipment.
An obituary that mentions a career in custom millwork, commercial fabrication, machining,
welding, electrical contracting, or technical infrastructure signals a unit packed with
industrial tools that average bidders will completely overlook. These tools sell for
$20K–$100K+ and move quickly to the right buyers.
Your job is to find these units. Everything else is noise.

UNIT TO EVALUATE:
  Tenant: {unit.tenant.name}
  Unit: {unit.tenant.unit_number}
  Facility: {unit.facility_name or "unknown"} — {unit.facility_address or unit.tenant.facility_address}
  Default owed: {unit.tenant.default_amount or "unknown"}
  Auction date: {unit.tenant.auction_date or "unknown"}
{enrichment_block}

SCORING DECISION MATRIX — work through this in order:

STEP 1 — IDENTIFY THE CAREER
Read all enrichment data above. What trade or profession was this person in?
If an obituary names a career, that is your primary source — obituaries are career records.
If no career is identifiable from the data, say "unknown."

STEP 2 — ASSIGN BASE SCORE FROM CAREER TIER

  TIER 1 (base 9-10): Obituary confirms a high-value trade career
    → machinist, CNC operator, tool-and-die maker, millwright
    → custom millwork / cabinet maker / finish carpenter
    → metal fabricator / welder / ironworker
    → master electrician / electrical contractor
    → master plumber / pipefitter / steamfitter
    → HVAC / refrigeration mechanic
    → auto body / collision repair / automotive technician
    → instrumentation / controls technician
    Rule: if obituary_found=true AND career is Tier 1 → score is 9 or 10.

  TIER 2 (base 7-8): Career signals without obituary confirmation, OR moderate trade
    → general contractor, journeyman carpenter, construction foreman
    → business owner in a trade field (LLC + trades keyword)
    → engineer or drafter with industrial background
    → multiple corroborating trade signals without obituary
    Rule: if high_value_trade_signals is non-empty OR business_found + trade signals → 7-8.

  TIER 3 (base 5-6): Weak signals, could go either way
    → profession found but not trade-related (retail, office, etc.)
    → one or two generic trade keywords with no obituary or business confirmation
    → some signals but contradictory or thin evidence

  TIER 4 (base 1-4): No useful signal
    → no career identified
    → clearly non-trade profession (teacher, nurse, clerk)
    → signals of low-value contents (clothing, books, general household)
    Rule: score CANNOT exceed 5 if career_identified = "unknown."

STEP 3 — ADJUST FOR EVIDENCE QUALITY (±1)
  +1 if obituary directly names employer AND trade role
  +1 if multiple independent sources corroborate same career
  -1 if signals are ambiguous (common name, could be different person)
  -1 if the only trade signals are from Q4 (tool search) with no corroboration

STEP 4 — ENUMERATE LIKELY CONTENTS
Based on the identified career, list the specific tools and equipment most likely present.
Be concrete: not "tools" but "10-inch table saw, router table, band saw, thickness planer,
random-orbit sanders, hand tool collection." This specificity is what separates a useful
analysis from a generic one.

STEP 5 — ESTIMATE VALUE
Give a realistic resale range. For Tier 1 units: $15,000–$100,000 is not unusual.
For Tier 2: $5,000–$25,000. For Tier 3/4: $500–$3,000 (general household).

Return ONLY a JSON object with these exact fields — no other text:
{{
  "career_identified": "<what trade/career was found, or 'unknown'>",
  "score": <1-10 integer>,
  "trade_equipment_probability": "<low|medium|high>",
  "likely_contents": ["specific item 1", "specific item 2", ...],
  "interest_signals": ["signal that drove this score", ...],
  "estimated_value_range": "$X,000 – $Y,000",
  "reasoning": "<2-3 sentences: what career, why that score, what a smart bidder should know>",
  "recommendation": "<bid aggressively|bid cautiously|investigate further|skip>"
}}"""

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "career_identified": "unknown",
            "score": 3,
            "trade_equipment_probability": "low",
            "likely_contents": ["household items"],
            "interest_signals": [],
            "reasoning": "Could not parse evaluation response. Defaulting to conservative score.",
            "estimated_value_range": "$500 – $2,000",
            "recommendation": "skip",
        }

    return EvaluationResult(**data)
