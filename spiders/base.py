"""
RealEstork — Base Spider + RawListing Schema
Module 1 (M1) — Spider Engine Foundation
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RawListing:
    """
    Standardized listing schema — output format for all spiders.
    All fields are raw (not normalized). Pipeline handles normalization.
    """

    # === Source identification ===
    source: str              # "nhatot", "batdongsan", "alonhadat", ...
    source_id: str           # Original listing ID on platform
    source_url: str          # Full URL to listing page

    # === Content ===
    title: str
    description: str         # Full description text
    address: str             # Raw address string
    district: str            # Raw district string (e.g. "Quận 3", "Q3", "district 3")
    city: str = "HCMC"

    # === Property details ===
    area_m2: float | None = None
    floor_level: int | None = None      # 1=tầng trệt, 2=lầu 1, etc. None=unknown
                                         # Quan trọng: tầng trệt vs lầu 1+ chênh 50-80% giá
    price_vnd_monthly: int | None = None
    price_text: str = ""                 # Raw price string (e.g. "120 triệu/tháng")

    # === Contact ===
    phone: str = ""           # Raw phone string
    phone_hidden: bool = False  # True = seller chủ động ẩn SĐT (API non-401 error), False = unknown/token expired
    contact_name: str | None = None
    poster_total_listings: int | None = None  # Active listings count for this seller (from platform)
    poster_sold_listings: int | None = None  # Historical total sold/posted listings (strong broker signal)
    account_type: str | None = None          # Platform account type: "u"=user/personal, "s"=store/business. None=unknown
    same_session_account_count: int = 1      # Listings from same account_name in this crawl batch (set by spider post-processing)
    poster_profile_hash: str | None = None   # batdongsan guru.batdongsan.com.vn/pa/{hash} identifier
    poster_join_year: int | None = None      # Year the poster joined the platform (absolute year, not relative)
    has_pro_agent_badge: bool = False        # "Môi giới chuyên nghiệp" badge detected on list/detail page
    is_vip: bool = False                     # True nếu card có VIP tier (silver/gold/diamond) — dùng cho early-stop logic
    avatar_url: str | None = None            # Poster avatar URL for broker detection
    is_main_street: bool | None = None       # True = mặt tiền/mặt phố, False = hẻm. None = unknown
    poster_account_id: str | None = None     # Platform account ID (more stable than name for dedup)
    property_type: str = ""                  # BDS only: "nha_mat_pho"|"shophouse"|"kho_nha_xuong"|"nha_rieng"|"biet_thu_lien_ke"


    # === Media ===
    images: list[str] = field(default_factory=list)  # Image URLs

    # === Timing ===
    posted_at: datetime | None = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    listing_age_hours: float | None = None   # Auto-computed from posted_at vs scraped_at
                                              # Filter: vợ chỉ nhận tin < 48h để tránh noise

    # === Dedup ===
    content_hash: str = ""   # SHA256(title + phone + description[:100]) — set in post_init

    def __post_init__(self) -> None:
        """Auto-compute derived fields after init."""
        # Compute listing_age_hours from posted_at
        if self.posted_at is not None and self.listing_age_hours is None:
            now = datetime.now(timezone.utc)
            # Ensure posted_at is timezone-aware
            if self.posted_at.tzinfo is None:
                posted = self.posted_at.replace(tzinfo=timezone.utc)
            else:
                posted = self.posted_at
            delta = now - posted
            self.listing_age_hours = delta.total_seconds() / 3600

        # Auto-compute content hash for dedup
        if not self.content_hash:
            raw = f"{self.title}|{self.phone}|{self.description[:100]}"
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for Supabase upsert."""
        return {
            "source": self.source,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "title": self.title,
            "description": self.description,
            "address": self.address,
            "district": self.district,
            "city": self.city,
            "area_m2": self.area_m2,
            "floor_level": self.floor_level,
            "price_vnd_monthly": self.price_vnd_monthly,
            "price_text": self.price_text,
            "phone": self.phone,
            "contact_name": self.contact_name,
            "images": self.images,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "scraped_at": self.scraped_at.isoformat(),
            "listing_age_hours": self.listing_age_hours,
            "content_hash": self.content_hash,
            "property_type": self.property_type,
        }


class BaseSpider(ABC):
    """
    Abstract base class for all spiders.
    
    To add a new site:
    1. Create spiders/new_site.py inheriting BaseSpider
    2. Implement fetch_listings() and parse_listing()
    3. Add entry to config/spiders.yaml
    → No other changes needed.
    """

    name: str = "base"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.enabled: bool = config.get("enabled", True)
        self.interval_minutes: int = config.get("interval_minutes", 30)
        self.max_pages: int = config.get("max_pages", 3)
        self.request_delay: float = config.get("request_delay_seconds", 3.0)
        # Orchestrator may seed this with already-seen source_ids (format: "source:source_id")
        # so spider can early-stop when hitting dedup-heavy pages. Empty by default.
        self.seen_ids: set[str] = set()

    @abstractmethod
    async def fetch_listings(self) -> list[RawListing]:
        """
        Fetch raw listings from platform.
        Returns list of RawListing. Must handle pagination internally.
        """
        raise NotImplementedError

    @abstractmethod
    def parse_listing(self, raw: Any) -> RawListing | None:
        """
        Parse a single raw item (dict from API or HTML element) into RawListing.
        Return None to skip this listing (e.g., not relevant category).
        """
        raise NotImplementedError

    async def run(self) -> list[RawListing]:
        """Entry point called by orchestrator. Wraps fetch with error handling."""
        if not self.enabled:
            return []
        return await self.fetch_listings()
