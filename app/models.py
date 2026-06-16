"""Pydantic models for Arcadia data structures."""
from datetime import datetime
from typing import Optional, List, Literal
from enum import Enum
from pydantic import BaseModel, Field


class CampaignStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    FULL = "full"
    ENDED = "ended"


class CampaignType(str, Enum):
    UGC = "ugc"
    CPM = "cpm"


class Campaign(BaseModel):
    """Represents an Arcadia campaign."""
    id: str = Field(..., alias="_id")                  # MongoDB ID
    campaignCode: str                                   # e.g., "CLASHO-UGC-01"
    title: str
    description: str
    briefUrl: Optional[str] = None
    brandImageUrl: Optional[str] = None
    referenceClipUrls: List[str] = []
    hashtags: List[str] = []
    mandatoryTags: List[str] = []
    startDate: datetime
    endDate: datetime
    maxSlots: int
    slotsLocked: int
    slotsRemaining: Optional[int] = None                # null = unlimited
    kind: Literal["ugc", "scheduled", "fcfs"]
    status: Literal["active", "locked"]
    postPrice: Optional[float] = None                   # UGC flat payout
    ugcCapacityMode: Optional[str] = None               # "open" or "limited"
    ugcMaxPosts: Optional[int] = None
    ugcSlotMode: Optional[str] = None                   # "open_submit" or "claim_slot"
    myLock: Optional[dict] = None                       # null = not locked
    mySubmission: Optional[dict] = None                 # null = not submitted
    cpmRules: List[dict] = []                           # tier-based CPM rates
    reservation: Optional[dict] = None                  # gold tier reservation

    @property
    def _id(self) -> str:
        return self.id

    @property
    def slug(self) -> str:
        return self.campaignCode

    @property
    def type(self) -> str:
        # Backward compatibility property
        return self.kind

    @property
    def ends_at(self) -> Optional[datetime]:
        return self.endDate

    @property
    def slots_remaining(self) -> Optional[int]:
        return self.slotsRemaining

    @property
    def is_locked_by_user(self) -> bool:
        return self.myLock is not None

    @property
    def is_submitted(self) -> bool:
        return self.mySubmission is not None

    @property
    def needs_claim(self) -> bool:
        return self.ugcSlotMode == "claim_slot"

    @property
    def is_lockable(self) -> bool:
        if self.status != "active":
            return False
        if self.myLock is not None:
            return False
        if self.mySubmission is not None:
            return False
        if self.slotsRemaining is not None and self.slotsRemaining <= 0:
            return False
        if self.ends_at:
            now = datetime.now(self.ends_at.tzinfo) if self.ends_at.tzinfo else datetime.utcnow()
            if now > self.ends_at:
                return False
        if self.reservation and not self.reservation.get("reservedEligibleForMe", False):
            # Check if general slots are available
            general_locked = self.reservation.get("generalLocked", 0)
            general_capacity = self.reservation.get("generalCapacity", 0)
            if general_locked >= general_capacity:
                return False
        return True

    @property
    def payout_amount(self) -> float:
        if self.kind == "ugc" and self.postPrice:
            return self.postPrice
        # For CPM campaigns, get bronze tier rate
        for rule in self.cpmRules:
            if rule.get("tier") == "bronze":
                return rule.get("ratePerThousand", 0)
        return 0

    @property
    def payout_unit(self) -> str:
        if self.kind == "ugc":
            return "post"
        return "1K"

    @property
    def url(self) -> str:
        return f"https://arcadia-roster.up.railway.app/clip/campaigns/{self.id}"

    @property
    def lock_url(self) -> str:
        return f"https://arcadia-roster.up.railway.app/api/clip/campaigns/{self.id}/lock"


class SlotLockResult(BaseModel):
    """Result of attempting to lock a slot."""
    success: bool
    campaign_id: str
    campaign_title: str
    slot_number: Optional[int] = None
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    strategy_used: str
    response_time_ms: float
    definitive: bool = False


class UserStats(BaseModel):
    """User dashboard stats."""
    display_name: str
    handle: str
    tier: Literal["Bronze", "Silver", "Gold"]
    pending_payout: float
    active_slots: int
    total_clips: int
    thirty_day_views: int
    approval_rate: float
    day_streak: int


class BotHealth(BaseModel):
    """Health check response."""
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str = "1.0.0"
    strategies: dict
    last_poll: Optional[datetime] = None
    campaigns_monitored: int = 0
    slots_locked_today: int = 0
    errors_last_hour: int = 0


class LockRequest(BaseModel):
    """Manual lock request via API."""
    campaign_id: str
    strategy: Optional[Literal["api", "playwright", "ai_agent"]] = None
    force: bool = False


class CampaignFilter(BaseModel):
    """Filter for campaign monitoring."""
    kind: Optional[List[Literal["ugc", "scheduled", "fcfs"]]] = None
    min_payout: Optional[float] = None
    exclude_locked: bool = True
    exclude_submitted: bool = True
    max_slots_per_day: Optional[int] = None
    auto_lock: bool = False
    preferred_types: Optional[List[CampaignType]] = None