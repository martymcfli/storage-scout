from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class TenantProfile(BaseModel):
    name: str
    unit_number: str
    facility_address: str
    auction_date: Optional[str] = None
    default_amount: Optional[str] = None


class EnrichmentResult(BaseModel):
    tenant_name: str
    search_results: dict = Field(default_factory=dict)
    career_signals: list[str] = Field(default_factory=list)
    trade_profession_signals: list[str] = Field(default_factory=list)
    high_value_trade_signals: list[str] = Field(default_factory=list)
    obituary_found: bool = False
    obit_career_description: Optional[str] = None
    business_found: bool = False
    raw_snippets: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    score: int = Field(ge=1, le=10)
    career_identified: str = "unknown"
    likely_contents: list[str] = Field(default_factory=list)
    interest_signals: list[str] = Field(default_factory=list)
    reasoning: str
    trade_equipment_probability: str = "low"
    estimated_value_range: str = "unknown"
    recommendation: str


# ── Visual inventory ──────────────────────────────────────────────────────────

class VisualItem(BaseModel):
    description: str                  # e.g. "solid oak cabinet, approx 5ft tall"
    condition: str                    # excellent / good / fair / poor
    resale_low: int                   # $ low estimate
    resale_high: int                  # $ high estimate
    flip_hours: float                 # hours to photograph, list, sell, hand off
    best_platform: str                # Facebook, eBay, Craigslist, specialty
    notes: str = ""


class VisualInventory(BaseModel):
    photo_urls: list[str] = Field(default_factory=list)
    photos_analyzed: int = 0
    items: list[VisualItem] = Field(default_factory=list)
    total_value_low: int = 0
    total_value_high: int = 0
    total_flip_hours: float = 0.0
    notable_finds: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    vision_notes: str = ""            # overall photo quality / coverage notes
    analyzed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Bid strategy ──────────────────────────────────────────────────────────────

class BidStrategy(BaseModel):
    target_daily_profit: int          # user's minimum $/day requirement
    target_hourly_rate: float         # = target_daily_profit / 8
    estimated_gross_resale: int       # what everything should sell for
    estimated_overhead: int           # transport + fees + cleanup
    estimated_flip_hours: float       # total hours to liquidate
    min_required_profit: int          # hours × hourly_rate
    break_even_bid: int               # gross - overhead
    max_bid: int                      # gross - overhead - min_profit
    bid_green_ceiling: int            # bid freely up to here
    bid_yellow_ceiling: int           # bid cautiously up to here
    bid_red_ceiling: int              # absolute walk-away (= max_bid)
    expected_roi_at_max_bid: float    # % return at max bid
    room_strategy: str                # tactical advice for auction day
    summary: str                      # 2-3 sentence plain-English verdict
    calculated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Core auction unit ─────────────────────────────────────────────────────────

class AuctionUnit(BaseModel):
    id: str
    source_url: str
    facility_name: Optional[str] = None
    facility_address: Optional[str] = None
    tenant: TenantProfile
    enrichment: Optional[EnrichmentResult] = None
    evaluation: Optional[EvaluationResult] = None
    visual_inventory: Optional[VisualInventory] = None
    bid_strategy: Optional[BidStrategy] = None
    scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    pipeline_completed: bool = False


# ── API shapes ────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    auction_id: Optional[str] = None


class Alert(BaseModel):
    unit_id: str
    tenant_name: str
    facility_address: str
    score: int
    likely_contents: list[str]
    trade_equipment_probability: str
    estimated_value_range: str
    source_url: str
    alerted_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class DiscoverRequest(BaseModel):
    zip_codes: Optional[list[str]] = None


class UserProfile(BaseModel):
    home_zip: str
    max_miles: int = 50
    available_days: list[str] = Field(default_factory=list)
    budget_ceiling: Optional[int] = None
    alert_score_threshold: int = 7
    target_daily_profit: int = 300    # min $ profit per full day of flip work
