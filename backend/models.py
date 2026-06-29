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
    high_value_trade_signals: list[str] = Field(default_factory=list)  # top-tier trades only
    obituary_found: bool = False
    obit_career_description: Optional[str] = None  # career text extracted from obituary snippets
    business_found: bool = False
    raw_snippets: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    score: int = Field(ge=1, le=10)
    career_identified: str = "unknown"  # what trade/career was found; drives the whole score
    likely_contents: list[str] = Field(default_factory=list)
    interest_signals: list[str] = Field(default_factory=list)
    reasoning: str
    trade_equipment_probability: str = "low"  # low/medium/high
    estimated_value_range: str = "unknown"
    recommendation: str


class AuctionUnit(BaseModel):
    id: str
    source_url: str
    facility_name: Optional[str] = None
    facility_address: Optional[str] = None
    tenant: TenantProfile
    enrichment: Optional[EnrichmentResult] = None
    evaluation: Optional[EvaluationResult] = None
    scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    pipeline_completed: bool = False


class ScrapeRequest(BaseModel):
    url: str


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
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
    zip_codes: Optional[list[str]] = None  # if None, uses profile home_zip + radius


class UserProfile(BaseModel):
    home_zip: str
    max_miles: int = 50
    available_days: list[str] = Field(default_factory=list)  # e.g. ["saturday", "sunday"]
    budget_ceiling: Optional[int] = None   # max bid in dollars; None = no limit
    alert_score_threshold: int = 7
