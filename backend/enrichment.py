"""
4-query OSINT enrichment strategy.

Query priority rationale:
  Q1 — Obituary (prime source: public record, often names the employer + career verbatim)
  Q2 — Obituary + career phrasing (deepens Q1: extracts "worked as", "retired from", employer)
  Q3 — Business / contractor credential (LLC, license, union membership)
  Q4 — High-value trade keywords (machinist, fabricator, millwork, CNC, welder, electrician)

The insight driving this: an obituary that names a trade career is not a grief record —
it's a career record. "Retired machinist at Acme Metal Works" = unit full of lathes,
mills, and precision tooling that general bidders will walk past.
"""
import os
import re
from serpapi import GoogleSearch
from .models import EnrichmentResult

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

# ── Trade tiers ──────────────────────────────────────────────────────────────
# Tier 1 = highest resale value. A single unit from these trades can hold $20K-$100K+.
HIGH_VALUE_TRADES = [
    "machinist", "cnc", "lathe", "mill operator", "tool and die", "die maker",
    "millwork", "custom millwork", "cabinet maker", "cabinetry", "finish carpenter",
    "metal fabricat", "fabricator", "welding", "welder", "ironwork",
    "master electrician", "electrical contractor", "electrician",
    "master plumber", "plumber", "pipefitter", "steamfitter",
    "hvac", "refrigeration mechanic", "mechanical contractor",
    "auto body", "collision repair", "automotive technician",
    "instrumentation technician", "controls technician",
    "industrial mechanic", "millwright",
]

# Tier 2 = solid signals; value depends on specialization.
MEDIUM_VALUE_TRADES = [
    "contractor", "general contractor", "subcontractor",
    "carpenter", "journeyman", "construction", "builder", "superintendent",
    "engineer", "drafter", "designer", "architect",
    "technician", "operator", "specialist", "inspector",
    "mechanic", "automotive", "diesel", "heavy equipment",
    "painter", "finisher", "tile", "flooring", "roofing",
]

# Obituary career markers — phrases that signal the obit names a profession.
OBIT_CAREER_PATTERNS = [
    r"(?:worked|employed)\s+(?:at|for|with|by)\s+([\w\s&,\.]+?)(?:\.|,|for \d+|\band\b|$)",
    r"(?:retired from|retired after|career at|career with)\s+([\w\s&,\.]+?)(?:\.|,|\band\b|$)",
    r"(?:was a|was an|served as|worked as)\s+([\w\s]+?)(?:\.|,|\band\b|\bfor\b|$)",
    r"(?:owner of|founder of|co-founder of|operated)\s+([\w\s&,\.]+?)(?:\.|,|\band\b|$)",
    r"(\d{2,3})\s+years?\s+(?:of service|with|at|in the)",
    r"member of\s+(?:the\s+)?([\w\s]+?(?:union|local|guild|association|brotherhood))",
]


def _run_search(query: str) -> list[str]:
    if not SERPAPI_KEY:
        return []
    params = {"q": query, "api_key": SERPAPI_KEY, "num": 5}
    try:
        results = GoogleSearch(params).get_dict()
    except Exception as e:
        print(f"[Enrichment] SerpApi error: {e}")
        return []

    snippets = []
    for r in results.get("organic_results", []):
        if r.get("snippet"):
            snippets.append(r["snippet"])
        if r.get("title"):
            snippets.append(r["title"])
    return snippets


def _extract_obit_career(snippets: list[str]) -> str | None:
    """Pull the most specific career description found in obituary snippets."""
    obit_snippets = [
        s for s in snippets
        if any(w in s.lower() for w in ["obituary", "obit", "passed away", "in loving memory",
                                         "survived by", "memorial", "funeral", "laid to rest"])
    ]
    if not obit_snippets:
        return None

    combined = " ".join(obit_snippets)
    found = []
    for pattern in OBIT_CAREER_PATTERNS:
        for match in re.finditer(pattern, combined, re.IGNORECASE):
            phrase = match.group(0).strip().rstrip(".,")
            if len(phrase) > 8:
                found.append(phrase)

    return "; ".join(found[:4]) if found else None


def _classify_trades(snippets: list[str]) -> tuple[list[str], list[str]]:
    """Return (high_value_trades, medium_value_trades) found across snippets."""
    combined = " ".join(snippets).lower()
    high = [t for t in HIGH_VALUE_TRADES if t.lower() in combined]
    medium = [t for t in MEDIUM_VALUE_TRADES if t.lower() in combined]
    return list(set(high)), list(set(medium))


def _extract_career_signals(snippets: list[str]) -> list[str]:
    """Extract readable career phrases from all snippets."""
    combined = " ".join(snippets)
    signals = []
    for pattern in OBIT_CAREER_PATTERNS:
        for match in re.finditer(pattern, combined, re.IGNORECASE):
            phrase = match.group(0).strip().rstrip(".,")
            if len(phrase) > 5:
                signals.append(phrase)
    return list(dict.fromkeys(signals))[:12]  # deduplicate, keep order


def enrich_tenant(name: str) -> EnrichmentResult:
    queries = [
        f'"{name}" obituary',
        f'"{name}" obituary "worked" OR "employed" OR "retired" OR "career" OR "owner"',
        f'"{name}" contractor OR LLC OR license OR union OR "master electrician" OR "journeyman"',
        f'"{name}" machinist OR fabricator OR millwork OR welder OR electrician OR carpenter OR HVAC',
    ]

    all_snippets: list[str] = []
    search_results: dict = {}

    for i, query in enumerate(queries):
        snippets = _run_search(query)
        search_results[f"q{i+1}"] = {"query": query, "snippets": snippets}
        all_snippets.extend(snippets)

    combined_lower = " ".join(all_snippets).lower()

    obituary_found = any(
        w in combined_lower
        for w in ["obituary", "obit", "passed away", "in loving memory", "survived by", "memorial"]
    )
    business_found = any(
        w in combined_lower
        for w in ["llc", "inc.", "corp", "company", "business", "owner", "founded", "operated"]
    )

    obit_career = _extract_obit_career(all_snippets)
    career_signals = _extract_career_signals(all_snippets)
    high_value, medium_value = _classify_trades(all_snippets)

    return EnrichmentResult(
        tenant_name=name,
        search_results=search_results,
        career_signals=career_signals,
        trade_profession_signals=medium_value,
        high_value_trade_signals=high_value,
        obituary_found=obituary_found,
        obit_career_description=obit_career,
        business_found=business_found,
        raw_snippets=all_snippets[:30],
    )
