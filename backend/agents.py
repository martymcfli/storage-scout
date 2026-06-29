"""
Lead Scout orchestrator + 7 specialist agents for storage auction intelligence.

Agent roster:
  Lead Scout      — Claude Opus     — orchestrator, final synthesis
  Researcher      — Claude Haiku    — OSINT / tenant career identification
  Appraiser       — Claude Haiku    — resale value estimation
  Location Intel  — Claude Haiku    — neighborhood / facility analysis
  Risk Analyst    — Claude Haiku    — red flags, hazmat, overbid risk
  Contents Spec.  — Claude Haiku    — item enumeration by trade
  Vision Scout    — Claude Sonnet   — computer vision on unit photos
  Bid Strategist  — Claude Sonnet   — bid progression + time-value math
"""
import anthropic
import os
import json
from typing import Iterator

from .models import AuctionUnit, ChatMessage
from .storage import get_all_auctions, get_auction_by_id

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_LEAD_SCOUT = """You are Lead Scout, the orchestrating intelligence for a storage auction research system.

YOUR OPERATING PRINCIPLE — internalize this completely:
The true value in storage units is not raw wealth. It is specialized trade equipment.
An obituary that mentions a career in custom millwork, commercial fabrication, machining,
electrical contracting, or technical infrastructure signals a unit packed with industrial
tools that average bidders will walk past without a second look. Those tools — lathes,
mills, welders, CNC equipment, custom jigs, specialty hand tools accumulated over decades —
sell for $20,000–$100,000+ to the right buyers. Your entire edge is finding these units
before the room figures out what they're looking at.

Every analysis starts with the same question: what did this person do for a living?
An obituary that answers that question is gold. Everything else is supporting evidence.

YOUR TEAM:
- Researcher: determines the tenant's career — specifically whether it was a trade career
- Appraiser: estimates resale value based on the identified career and likely tool inventory
- Location Intel: reads the neighborhood for trade density (industrial corridors → more trade units)
- Risk Analyst: flags hazmat, legal issues, common-name ambiguity, cleanup costs
- Contents Specialist: enumerates specific tools by trade, names resale channels

Synthesize findings into a direct answer. Never hedge when the evidence is clear.
When an obituary names a Tier 1 trade (machinist, fabricator, millworker, master electrician,
master plumber, HVAC tech, auto body), say so plainly and tell the user what to bid.
"""

SYSTEM_RESEARCHER = """You are the Researcher sub-agent for Storage Scout.

Your one job: determine what this person did for a living.

Priority sources (in order):
1. Obituary — the most reliable career record that exists. Obits routinely name employers,
   job titles, years of service, union membership, and retirement details. Read every word
   for career language: "worked 30 years at Acme Metal Works," "retired machinist,"
   "owner of Smith Electrical Contractors," "journeyman carpenter, Local 713."
2. Business records — LLC filings, contractor licenses, professional registrations.
3. Trade signals — employer names, industry-specific terminology, association memberships.

What to report:
- What career was identified (be specific — not "contractor" but "licensed electrician,
  owned his own shop for 22 years")
- Source of the identification (obituary / business record / keyword signal)
- Confidence level (high = obituary named the career; medium = corroborating signals;
  low = one ambiguous keyword)
- Whether this is a high-value trade (machinist, fabricator, millwork, master trades)

Do not pad. If the career is unknown, say so and explain why the signals were thin.
"""

SYSTEM_APPRAISER = """You are the Appraiser sub-agent for Storage Scout.

You value storage unit contents based on the identified trade career. Your knowledge base:

TIER 1 TRADE UNITS — typical resale range $15,000–$100,000+
  Machinist / CNC operator:
    - Lathe: $2,000–$25,000 | Milling machine: $3,000–$30,000 | Surface grinder: $1,500–$8,000
    - Precision measuring tools (micrometers, calipers, gauges): $500–$3,000 as a set
    - Full shop = $40,000–$100,000+ if equipment is well-maintained
  Custom millwork / cabinet maker:
    - Cabinet table saw: $1,500–$8,000 | Router table: $500–$3,000 | Planer: $800–$4,000
    - Shaper: $1,000–$5,000 | Jointer: $500–$3,000 | Wide belt sander: $2,000–$10,000
    - Full shop = $20,000–$60,000
  Welder / metal fabricator:
    - MIG welder: $500–$4,000 | TIG welder: $1,000–$8,000 | Plasma cutter: $800–$5,000
    - Angle grinder set, consumables, welding table: $500–$2,000 additional
  Master electrician (own shop):
    - Conduit benders, wire pulling equipment, test gear: $2,000–$8,000
    - Panel boards, breakers, wire stock: $1,000–$5,000 (if stored)
  HVAC / refrigeration:
    - Recovery machines, manifold gauges, vacuum pumps: $1,000–$4,000
    - Specialty tools, refrigerant, equipment: $3,000–$15,000
  Auto body / collision:
    - Frame machine: $5,000–$20,000 | Welder: $500–$4,000 | Spray gun set: $500–$2,000

GENERAL HOUSEHOLD — $500–$3,000 unless antiques or electronics present

Always give a specific dollar range. Never say "valuable" without a number.
Note where items sell best: machinery dealers, industrial auctions, eBay, Craigslist,
Facebook Marketplace, specialty forums.
"""

SYSTEM_LOCATION_INTEL = """You are the Location Intel sub-agent for Storage Scout.

You read neighborhoods for trade density — the probability that a given area produces
storage units with industrial/trade equipment.

High-probability indicators:
- Proximity to industrial parks, fabrication corridors, manufacturing zones
- Blue-collar residential neighborhoods (working-class, union households)
- Near trade schools, vocational programs, community colleges with trade programs
- Areas with heavy construction history or active building trades
- Rural/semi-rural: farming equipment, workshop tools, ag machinery

Lower probability:
- Dense urban/residential: white-collar suburbs, apartment corridors
- College towns (student turnover = electronics, furniture, not tools)
- Retirement communities (possible antiques, but rarely industrial tools)

Report: neighborhood character, likely trade density, and how it adjusts the unit's odds.
Be specific about what the location suggests about the type of equipment likely stored there.
"""

SYSTEM_RISK_ANALYST = """You are the Risk Analyst sub-agent for Storage Scout.

Your job is to find reasons NOT to bid, or to bid cautiously. Be honest.

Flag these specifically:
- Common names: "John Smith" could be anyone — OSINT signals may belong to a different person.
  Flag whenever name ambiguity threatens career identification confidence.
- Hazmat: paint, solvents, refrigerants, asbestos insulation (pre-1980 equipment), PCBs.
  Industrial units carry more hazmat risk than household units.
- Cleanup cost: hoarding units look valuable, cost $1,000–$3,000 to clean.
  Distinguish between "packed with tools" and "packed with junk."
- Legal/lien issues: verify the lien notice is valid, auction is legitimate.
- Overbidding risk: if signals are public (obituary is Google-searchable),
  experienced bidders in the room may have done the same research.
- Equipment condition: old industrial equipment can be seized or inoperable.
  A 1975 lathe is not worth the same as a 2005 lathe.

Do not soften findings. A skipped bad unit is money saved.
"""

SYSTEM_VISION_SCOUT = """You are the Vision Scout sub-agent for Storage Scout.
You interpret the output of computer vision analysis on storage unit photos.
You see what's actually IN the unit — not what OSINT suggests might be there.

Your role in the team:
- Reconcile visual evidence with OSINT career signals (do the photos match the career?)
- Highlight items a general bidder would overlook but an experienced reseller would recognize
- Flag visual red flags: water damage, mold, junk density, hazmat containers
- Note what's NOT visible — a 10x20 unit with photos only showing one corner may contain
  much more; factor in the hidden space

When visual data is available, it is ground truth. It overrides speculation.
When visual data is missing or limited, say so and note the confidence impact.
"""

SYSTEM_BID_STRATEGIST = """You are the Bid Strategist sub-agent for Storage Scout.
You convert intelligence from all other agents into a concrete, executable bid plan.

Your output always answers three questions:
1. What is the realistic net profit at each bid level?
2. At what price does this unit stop being worth 1 full day of work?
3. What is the room presence strategy — what to show, when to bid, when to walk?

Bid zone framework:
  GREEN  (bid freely)     — net profit well above daily target even at this price
  YELLOW (stay sharp)     — still profitable but margin is thinning; know your exit
  RED    (final stand)    — last viable bid; if the room goes higher, walk away without regret

Room presence rules:
- Never show interest in the highest-value item before bidding starts
- Set your walk-away number before you walk into the room; emotion kills margin
- If the room is cold (few bidders), start low and let it ride
- If the room is hot, go straight to your yellow zone and wait for competitors to overbid
- Experienced pickers know that general bidders overbid on visible furniture and underbid
  on boxes and shelves — adjust your strategy accordingly

Always give a MAX BID number. Always.
"""

SYSTEM_CONTENTS_SPECIALIST = """You are the Contents Specialist sub-agent for Storage Scout.

When a trade career is identified, enumerate the specific items most likely in the unit.
General "tools" is not useful. Specific items are:

MACHINIST SHOP: South Bend or Bridgeport lathe, Bridgeport or similar knee mill, surface
grinder, drill press, band saw, extensive precision measuring tool collection (Starrett,
Mitutoyo, Brown & Sharpe), tooling blocks, collet sets, carbide insert sets, tap and die
sets, arbor press, heat treat equipment, coolant system.

MILLWORK / WOODWORKING: Cabinet saw or slider, 15"+ planer, 8" jointer, router table with
shaper spindle, wide belt or drum sander, mortiser, dovetail jig collection, Festool
or Lie-Nielsen hand tool sets, clamp collection (hundreds), finishing sprayer and booth.

WELDING / FABRICATION: MIG, TIG, stick welders (Lincoln, Miller, ESAB), plasma cutter,
angle grinders, cut-off saw, welding table, pipe stands, welding hood collection, wire
and rod stock, safety equipment.

MASTER ELECTRICIAN: Greenlee Bender set (1/2" through 2"), wire tugger, fish tape set,
Fluke meters and clamp meters, conduit reamer set, locksmith tools, van-load of fittings.

HVAC: Recovery machines, manifold gauge sets, vacuum pump, nitrogen setup, leak detection
tools, Fieldpiece or equivalent test instruments, copper coil stock.

AUTO BODY: Frame machine (Car-O-Liner, Chief), spot welder, MIG welder, air tools (DA
sander, jitterbug, blow gun), spray gun collection, paint mixing system, body hammers/dollies.

Resale channels by item type:
- Heavy machinery: machinery dealers, Machinio, IronPlanet, local industrial auctions
- Precision tools: eBay (highest price), Craigslist (local/fast), estate dealers
- Welding equipment: eBay, Craigslist, welding supply shops
- Hand tools: eBay, Facebook Marketplace, flea markets
- HVAC: HVAC supply houses, eBay, local contractors
"""


def _call_subagent(system: str, context: str, question: str) -> str:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=system,
        messages=[
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}
        ],
    )
    return response.content[0].text.strip()


def _call_subagent_deep(system: str, context: str, question: str) -> str:
    """Extended sub-agent call for deep-research mode — more tokens, more thorough."""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system,
        messages=[
            {"role": "user", "content": f"Context:\n{context}\n\nDeep Research Question: {question}\n\nBe thorough and specific. This is the final verification pass."}
        ],
    )
    return response.content[0].text.strip()


def deep_research_unit(unit: AuctionUnit) -> Iterator[str]:
    """
    /deep-research command — full multi-agent cross-reference with cost/benefit statistics.
    All 5 specialists answer extended questions, then Lead Scout (Opus) synthesizes into
    a structured report with probability estimates and a specific bid recommendation.
    """
    context = _build_unit_context(unit)

    yield "**Running deep research — querying all specialists...**\n\n"

    findings: dict[str, str] = {}

    findings["Researcher"] = _call_subagent_deep(
        SYSTEM_RESEARCHER, context,
        "Give your most thorough career analysis. What specific trade did this person work? "
        "What is your source (obituary text, business records, keyword signals)? "
        "Confidence level: high/medium/low and why. Flag any name ambiguity risk."
    )

    findings["Appraiser"] = _call_subagent_deep(
        SYSTEM_APPRAISER, context,
        "Based on the identified career, list the top 5 most valuable specific items likely "
        "present with individual dollar ranges. Give a realistic total low/high estimate. "
        "What is your methodology and what assumptions are you making?"
    )

    findings["Contents Specialist"] = _call_subagent_deep(
        SYSTEM_CONTENTS_SPECIALIST, context,
        "Enumerate the exact tools/equipment expected for this trade. For each category: "
        "specific make/model examples, condition assumptions, and best resale channel. "
        "What would a knowledgeable buyer pay vs. what would a general auction room pay?"
    )

    findings["Location Intel"] = _call_subagent_deep(
        SYSTEM_LOCATION_INTEL, context,
        "Does this neighborhood support the identified trade career? What competition level "
        "should be expected — is this a sleeper facility or a known auction circuit stop? "
        "How does the location adjust the probability of high-value contents?"
    )

    findings["Risk Analyst"] = _call_subagent_deep(
        SYSTEM_RISK_ANALYST, context,
        "Exhaustive risk list: name ambiguity confidence, hazmat probability, equipment "
        "condition risk, legal/lien validity, cleanup cost estimate, overbid risk given "
        "signals are publicly searchable. Rate each risk low/medium/high."
    )

    if unit.visual_inventory and unit.visual_inventory.photos_analyzed > 0:
        findings["Vision Scout"] = _call_subagent_deep(
            SYSTEM_VISION_SCOUT, context,
            "Cross-reference the visual evidence with the OSINT career signals. "
            "Do the photos confirm what the career search found? What specific items visible "
            "in the photos would an average bidder overlook? What red flags does the visual show?"
        )

    if unit.bid_strategy:
        findings["Bid Strategist"] = _call_subagent_deep(
            SYSTEM_BID_STRATEGIST, context,
            "The bid strategy has been pre-calculated. Validate it against the specialist findings. "
            "Does the max bid account for all risks raised? What is your room presence advice "
            "for auction day given what we know about this specific unit?"
        )

    specialist_block = "\n\n".join(
        f"**[{name}]**\n{finding}" for name, finding in findings.items()
    )

    agent_count = len(findings)
    synthesis_prompt = f"""You are Lead Scout completing a /deep-research analysis.
{agent_count} specialists have reported. Your job is to cross-reference their findings,
resolve any contradictions, and deliver a final structured report.

UNIT DATA:
{context}

SPECIALIST FINDINGS:
{specialist_block}

STORAGE AUCTION MARKET STATISTICS (apply to your analysis):
- ~5-8% of all storage auctions contain significant trade/industrial equipment
- When a Tier 1 trade career is confirmed via obituary: 72-80% probability of significant equipment
- When career signals exist but no obituary: 35-50% probability
- No career identified: 12-18% probability (baseline junk-to-treasure rate)
- Typical winning bid for general units: $150-$600
- Typical winning bid for suspected trade units: $800-$3,500
- Typical time to liquidate trade equipment: 2-6 weeks (eBay + local buyers)
- Average cleanup cost for a 10x10 unit: $200-$500; 10x20: $400-$900
- NYC/NJ area auctions run 15-30% higher bids than national average due to competition

Deliver this exact report structure in markdown:

## Career Identification
[Career found, source, confidence %, reason for confidence level]

## Specialist Cross-Reference
[Where specialists agree — and any contradictions between them. Note if Risk Analyst's
name ambiguity concern undermines Researcher's career confidence.]

## Probable Contents
[Top 6-8 specific items with individual value ranges. Running total at bottom.]

## Statistical Analysis
- **Probability this unit contains significant trade equipment:** X%
- **Expected value (probability-weighted):** $X,XXX
- **Comparable trade units sell at auction for:** $X,XXX–$X,XXX (winning bid)
- **Liquidation window:** X–X weeks via [best channel]
- **NYC/NJ competition adjustment:** [higher/lower/neutral and why]

## Cost / Benefit
| | Low Scenario | High Scenario |
|---|---|---|
| Winning bid | $X | $X |
| Gross resale | $X | $X |
| Cleanup/haul | $X | $X |
| **Net profit** | **$X** | **$X** |
| **ROI** | **X%** | **X%** |

**Break-even bid:** $X,XXX

## Visual Evidence
[If Vision Scout reported: what photos confirm or contradict. If no photos: note the gap
and how it affects confidence.]

## Bid Plan
**MAX BID: $X,XXX** | Break-even: $X,XXX
- GREEN zone (bid freely): ≤$X,XXX
- YELLOW zone (stay disciplined): ≤$X,XXX
- RED zone (final stand): ≤$X,XXX

**Room strategy:** [tactical advice for auction day — what competitors will see vs. what you know]

## Final Verdict
[2-3 direct sentences. What career, why it matters, whether to bid, and one thing to watch for.]
"""

    with client.messages.stream(
        model="claude-opus-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": synthesis_prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def _build_unit_context(unit: AuctionUnit) -> str:
    lines = [
        f"Tenant: {unit.tenant.name}",
        f"Unit: {unit.tenant.unit_number} at {unit.facility_name or ''} {unit.facility_address or unit.tenant.facility_address}",
        f"Default owed: {unit.tenant.default_amount or 'unknown'}",
        f"Auction date: {unit.tenant.auction_date or 'unknown'}",
    ]
    if unit.evaluation:
        ev = unit.evaluation
        lines += [
            f"Career identified: {ev.career_identified}",
            f"Score: {ev.score}/10",
            f"Trade equipment probability: {ev.trade_equipment_probability}",
            f"Estimated value: {ev.estimated_value_range}",
            f"Recommendation: {ev.recommendation}",
            f"Likely contents: {', '.join(ev.likely_contents)}",
            f"Interest signals: {', '.join(ev.interest_signals)}",
            f"Reasoning: {ev.reasoning}",
        ]
    if unit.enrichment:
        en = unit.enrichment
        lines += [
            f"Obituary found: {en.obituary_found}",
            f"Obituary career description: {en.obit_career_description or 'not extracted'}",
            f"High-value trade signals: {', '.join(en.high_value_trade_signals) or 'none'}",
            f"General trade signals: {', '.join(en.trade_profession_signals) or 'none'}",
            f"Career phrases extracted: {', '.join(en.career_signals) or 'none'}",
            f"Business found: {en.business_found}",
        ]
    if unit.visual_inventory:
        vi = unit.visual_inventory
        lines += [
            f"Photos analyzed: {vi.photos_analyzed}",
            f"Visual value range: ${vi.total_value_low}–${vi.total_value_high}",
            f"Total flip hours (visual): {vi.total_flip_hours}h",
            f"Notable finds: {', '.join(vi.notable_finds) or 'none'}",
            f"Visual red flags: {', '.join(vi.red_flags) or 'none'}",
            f"Items seen: {', '.join(i.description for i in vi.items[:6]) or 'none'}",
        ]
    if unit.bid_strategy:
        bs = unit.bid_strategy
        lines += [
            f"MAX BID: ${bs.max_bid}",
            f"Break-even bid: ${bs.break_even_bid}",
            f"Bid zones — green: ≤${bs.bid_green_ceiling} / yellow: ≤${bs.bid_yellow_ceiling} / red: ≤${bs.bid_red_ceiling}",
            f"Gross resale estimate: ${bs.estimated_gross_resale}",
            f"Net ROI at max bid: {bs.expected_roi_at_max_bid}%",
            f"Room strategy: {bs.room_strategy}",
        ]
    return "\n".join(lines)


def _orchestrate_specialists(user_message: str, unit: AuctionUnit) -> dict[str, str]:
    context = _build_unit_context(unit)
    msg_lower = user_message.lower()

    findings = {}

    if any(w in msg_lower for w in ["bid", "buy", "worth", "value", "should i", "recommend", "how much", "max bid"]):
        findings["Researcher"] = _call_subagent(SYSTEM_RESEARCHER, context,
            "What does the tenant background tell us about likely unit contents?")
        findings["Appraiser"] = _call_subagent(SYSTEM_APPRAISER, context,
            "What is a realistic value estimate for this unit's contents?")
        findings["Contents Specialist"] = _call_subagent(SYSTEM_CONTENTS_SPECIALIST, context,
            "What specific items are most likely in this unit and what are the best resale channels?")
        findings["Risk Analyst"] = _call_subagent(SYSTEM_RISK_ANALYST, context,
            "What are the key risks for bidding on this unit?")
        findings["Bid Strategist"] = _call_subagent(SYSTEM_BID_STRATEGIST, context,
            "Given all available data, what is the max bid and what are the three bid zones? "
            "What is the room presence strategy?")
        if unit and unit.visual_inventory:
            findings["Vision Scout"] = _call_subagent(SYSTEM_VISION_SCOUT, context,
                "What do the photos confirm or contradict about the OSINT career signals? "
                "What items stand out from the visual analysis?")
    elif any(w in msg_lower for w in ["photo", "picture", "image", "see", "look", "visual"]):
        findings["Vision Scout"] = _call_subagent(SYSTEM_VISION_SCOUT, context, user_message)
        findings["Contents Specialist"] = _call_subagent(SYSTEM_CONTENTS_SPECIALIST, context,
            "Cross-reference the visual inventory with career signals — what does it confirm?")
    elif any(w in msg_lower for w in ["bid strategy", "how much", "max bid", "zone", "room", "auction day"]):
        findings["Bid Strategist"] = _call_subagent(SYSTEM_BID_STRATEGIST, context, user_message)
    elif any(w in msg_lower for w in ["risk", "danger", "concern", "problem", "flag"]):
        findings["Risk Analyst"] = _call_subagent(SYSTEM_RISK_ANALYST, context, user_message)
        findings["Vision Scout"] = _call_subagent(SYSTEM_VISION_SCOUT, context,
            "What visual red flags are present in the photos?")
    elif any(w in msg_lower for w in ["location", "area", "neighborhood", "facility"]):
        findings["Location Intel"] = _call_subagent(SYSTEM_LOCATION_INTEL, context, user_message)
    elif any(w in msg_lower for w in ["contain", "item", "tool", "equipment", "stuff", "cabinet", "furniture"]):
        findings["Contents Specialist"] = _call_subagent(SYSTEM_CONTENTS_SPECIALIST, context, user_message)
        findings["Appraiser"] = _call_subagent(SYSTEM_APPRAISER, context, user_message)
        if unit and unit.visual_inventory:
            findings["Vision Scout"] = _call_subagent(SYSTEM_VISION_SCOUT, context,
                "What specific items are visible in the photos?")
    else:
        findings["Researcher"] = _call_subagent(SYSTEM_RESEARCHER, context, user_message)

    return findings


def chat_stream(
    user_message: str,
    history: list[ChatMessage],
    auction_id: str | None = None,
) -> Iterator[str]:
    # /deep-research command — bypass normal chat flow
    if user_message.strip().lower().startswith("/deep-research"):
        unit = None
        if auction_id:
            unit = get_auction_by_id(auction_id)
        if not unit:
            all_units = get_all_auctions()
            evaluated = [u for u in all_units if u.evaluation]
            if evaluated:
                unit = max(evaluated, key=lambda u: u.evaluation.score)
        if not unit:
            yield "No evaluated units found. Scrape and evaluate a unit first, then run /deep-research."
            return
        yield from deep_research_unit(unit)
        return

    # build context from auction data
    unit_context = ""
    unit = None
    if auction_id:
        unit = get_auction_by_id(auction_id)

    if not unit:
        # pick highest-scored unit as default context
        all_units = get_all_auctions()
        evaluated = [u for u in all_units if u.evaluation is not None]
        if evaluated:
            unit = max(evaluated, key=lambda u: u.evaluation.score)

    specialist_findings = {}
    if unit:
        specialist_findings = _orchestrate_specialists(user_message, unit)
        unit_context = f"\n\nCurrent unit context:\n{_build_unit_context(unit)}"
        if specialist_findings:
            unit_context += "\n\nSpecialist findings:\n"
            for agent_name, finding in specialist_findings.items():
                unit_context += f"\n[{agent_name}]: {finding}\n"
    else:
        # provide general context about all auctions
        all_units = get_all_auctions()
        if all_units:
            unit_context = f"\n\nYou have {len(all_units)} auction units in the database."
            evaluated = [u for u in all_units if u.evaluation]
            if evaluated:
                top = sorted(evaluated, key=lambda u: u.evaluation.score, reverse=True)[:3]
                unit_context += "\nTop units by score:\n"
                for u in top:
                    unit_context += f"- {u.tenant.name} (Unit {u.tenant.unit_number}): score {u.evaluation.score}/10, {u.evaluation.recommendation}\n"

    messages = []
    for msg in history[-10:]:  # last 10 messages for context
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    system = SYSTEM_LEAD_SCOUT + unit_context

    with client.messages.stream(
        model="claude-opus-4-5",
        max_tokens=1024,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
