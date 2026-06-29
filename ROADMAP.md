# Storage Scout — Roadmap

## Architecture Overview

Storage Scout is an OSINT + AI automation app for storage auction research (Storage Wars-style bidding).

**Core OSINT Insight:** The true value in storage units isn't raw wealth — it's specialized trade equipment. An obituary mentioning custom millwork, commercial fabrication, or technical infrastructure signals a unit packed with $20K-$100K+ in industrial tools that average bidders completely overlook.

## Tech Stack
- **FastAPI** backend — all pipeline endpoints + `/chat` streaming
- **Streamlit** frontend — 4 pages: Dashboard, Scrape, Auctions, Scout AI
- **Anthropic SDK** — claude-opus-4-5 (Lead Scout + evaluator), claude-haiku-4-5 (sub-agents + scraper)
- **SerpApi** — google-search-results Python SDK
- **Playwright** — async, chromium, for page rendering
- **Pydantic v2** — all data models in `backend/models.py`
- **JSON file persistence** — `backend/storage.py`, stores to `data/auctions.json`

---

## Phase 1: Scraping ✅
- Playwright + Claude Haiku extracts tenant/unit data from auction notice pages
- `backend/scraper.py`

## Phase 2: OSINT Enrichment ✅
- 4-query SerpApi strategy per tenant:
  1. Career/profession search
  2. **Obituary search** (intentional — reads career data, not grief data)
  3. Business/contractor license search
  4. Trade/equipment/workshop signals
- `backend/enrichment.py`

## Phase 3: AI Evaluation ✅
- Claude Opus scores each unit 1-10
- Weights heavily toward trade equipment signals
- Produces: score, likely contents, interest signals, value estimate, recommendation
- `backend/evaluator.py`

## Phase 4: Scout AI Chat ✅
- Lead Scout orchestrator (Claude Opus) + 5 specialist sub-agents (Claude Haiku):
  - **Researcher** — tenant background and career history
  - **Appraiser** — value estimates for likely contents
  - **Location Intel** — facility area, neighborhood demographics, trade density
  - **Risk Analyst** — red flags, hazmat, legal issues, overbid risk
  - **Contents Specialist** — specific item identification and resale channels
- Streaming `/chat` endpoint with SSE
- Streamlit streaming chat UI
- `backend/agents.py`

## Phase 5: Auto-Discovery ✅
- `backend/discovery.py` — scrapes StorageTreasures.com and Bid13 by ZIP code
- `discover_new_auctions(zip_codes)` → filters against existing DB to avoid duplicates
- `POST /discover` endpoint runs full pipeline on new finds
- Score ≥ 7 auto-writes to `data/alerts.json`
- Streamlit Scrape page has ZIP input for auto-discovery

## Phase 6: SQLite Migration (next)
- Swap `storage.py` JSON backend for SQLite
- `storage.py` interface already designed for clean swap
- Add filtering, pagination, and full-text search on unit data

## Phase 7: Scheduled Discovery
- Cron job / background task that runs `/discover` on configured ZIPs daily
- Push alert when high-value unit found
- Config file for ZIP codes + alert thresholds

## Phase 8: Bid Price Intelligence
- Pull recent sold prices from StorageTreasures auction results
- Build per-category value database
- Scout AI can suggest max bid price with confidence interval

## Phase 9: Competitor Intelligence
- Track which bidders show up at which facilities
- Identify facilities where competition is low
- Flag "quiet" auctions with high-value signals

## Phase 10: Mobile Alerts
- Push notifications for ≥7 score units
- Quick-view card with key signals + Scout AI one-liner recommendation
- Map view of upcoming auctions by proximity
