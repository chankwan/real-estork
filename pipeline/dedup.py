"""
RealEstork — Dedup Pipeline
Module 2 (M2) — Deduplication

Rules:
1. Same content_hash → exact duplicate → skip
2. Same phone + same district + price within ±10% → likely duplicate → skip
3. Same address (normalized) → definite duplicate → skip
"""

from __future__ import annotations

import re
from typing import Sequence

from loguru import logger
from unidecode import unidecode

from spiders.base import RawListing


# Abbreviation normalization map for Vietnamese addresses
ADDR_ABBREV: dict[str, str] = {
    "q.": "quan",
    "p.": "phuong",
    "đ.": "duong",
    "tp.": "thanh pho",
    "hbt": "hai ba trung",
    "hbtrung": "hai ba trung",
    "nguyenthiminhkhai": "nguyen thi minh khai",
    "vodidieu": "vo thi sau",
    "vts": "vo thi sau",
}


def normalize_address(address: str) -> str:
    """
    Normalize address for dedup comparison.
    - Lowercase → remove diacritics → expand abbreviations → strip extras
    """
    if not address:
        return ""
    # Remove diacritics (unidecode)
    normalized = unidecode(address).lower()
    # Remove punctuation except digits and letters
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # Apply abbreviation map (word boundaries)
    for abbrev, full in ADDR_ABBREV.items():
        abbrev_clean = abbrev.replace(".", "")
        normalized = re.sub(rf"\b{re.escape(abbrev_clean)}\b", full, normalized)
    return normalized


def normalize_phone(phone: str) -> str:
    """
    Normalize phone to 10-digit format (0XXXXXXXXX).
    Returns empty string if cannot normalize.
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    # +84XXXXXXXXX → 0XXXXXXXXX
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    # 0084XXXXXXXXX → 0XXXXXXXXX
    if digits.startswith("0084") and len(digits) == 13:
        digits = "0" + digits[4:]
    return digits if len(digits) == 10 else ""


class DedupPipeline:
    """
    Deduplication pipeline. Checks against in-memory cache + Supabase DB.
    """

    def __init__(self) -> None:
        # In-memory caches for current run (avoids hitting DB for every listing)
        self._seen_source_ids: set[str] = set()  # "source:source_id" — primary dedup key
        self._seen_hashes: set[str] = set()
        self._seen_phones_districts: dict[str, tuple[str, int | None]] = {}
        # key: normalized_phone → (normalized_district, price)
        self._seen_addresses: set[str] = set()

    @property
    def seen_source_ids(self) -> set[str]:
        """Set of already-seen 'source:source_id' strings. Used by spiders to early-stop."""
        return self._seen_source_ids

    def seed_from_db(self, existing_listings: list[dict]) -> None:
        """
        Seed dedup caches from existing DB records.
        Call at orchestrator startup to avoid re-alerting known listings.
        """
        for row in existing_listings:
            # Source ID — primary key, immutable
            source = row.get("source", "")
            source_id = row.get("source_id", "")
            if source and source_id:
                self._seen_source_ids.add(f"{source}:{source_id}")
            if row.get("content_hash"):
                self._seen_hashes.add(row["content_hash"])
            phone_norm = normalize_phone(row.get("phone", ""))
            if phone_norm:
                district = normalize_address(row.get("district", ""))
                price = row.get("price_vnd_monthly")
                self._seen_phones_districts[phone_norm] = (district, price)
            addr_norm = normalize_address(row.get("address_normalized", "") or row.get("address", ""))
            if addr_norm:
                self._seen_addresses.add(addr_norm)

        logger.info(
            f"[dedup] Seeded: {len(self._seen_source_ids)} source IDs, "
            f"{len(self._seen_hashes)} hashes, "
            f"{len(self._seen_phones_districts)} phone+district combos"
        )

    def filter_new(self, listings: Sequence[RawListing]) -> list[RawListing]:
        """
        Filter out duplicates. Returns only new, unique listings.
        Also updates internal caches with new listings.
        """
        new_listings: list[RawListing] = []
        duplicate_count = 0

        for listing in listings:
            if self._is_duplicate(listing):
                duplicate_count += 1
                # Always register source_id even for content duplicates so future
                # cycles don't re-process the same listing if phone changes / was None
                source_key = f"{listing.source}:{listing.source_id}"
                self._seen_source_ids.add(source_key)
                continue
            # Not a duplicate — add to result and update caches
            new_listings.append(listing)
            self._add_to_cache(listing)

        logger.info(
            f"[dedup] Input: {len(listings)}, "
            f"New: {len(new_listings)}, "
            f"Duplicates: {duplicate_count}"
        )
        return new_listings

    def _is_duplicate(self, listing: RawListing) -> bool:
        """Check all dedup rules."""
        # Rule 0: Source ID match — primary key, immutable across crawls
        # Prevents re-alerting same listing when phone changes between cycles
        source_key = f"{listing.source}:{listing.source_id}"
        if source_key in self._seen_source_ids:
            logger.debug(f"[dedup] Source ID duplicate: {source_key}")
            return True

        # Rule 1: Exact content hash match
        if listing.content_hash and listing.content_hash in self._seen_hashes:
            logger.debug(f"[dedup] Hash duplicate: {listing.source_id}")
            return True

        # Rule 2: Same address (DISABLED: often different houses in same ward/street have same generic address string)
        # addr_norm = normalize_address(listing.address)
        # if addr_norm and addr_norm in self._seen_addresses:
        #     logger.debug(f"[dedup] Address duplicate: {listing.source_id} | '{addr_norm}'")
        #     return True

        # Rule 3: Same phone + same district + price ±10%
        phone_norm = normalize_phone(listing.phone)
        if phone_norm and phone_norm in self._seen_phones_districts:
            existing_district, existing_price = self._seen_phones_districts[phone_norm]
            new_district = normalize_address(listing.district)
            if existing_district == new_district:
                # Same district — check price
                if listing.price_vnd_monthly is None or existing_price is None:
                    # Can't compare price → treat as duplicate (same phone+district)
                    logger.debug(f"[dedup] Phone+district duplicate (no price): {listing.source_id}")
                    return True
                # Price within ±10%
                price_diff = abs(listing.price_vnd_monthly - existing_price)
                if price_diff <= 0.1 * existing_price:
                    logger.debug(
                        f"[dedup] Phone+district+price duplicate: {listing.source_id} | "
                        f"phone={phone_norm} district={new_district}"
                    )
                    return True

        return False

    def _add_to_cache(self, listing: RawListing) -> None:
        """Add a new listing to all dedup caches."""
        self._seen_source_ids.add(f"{listing.source}:{listing.source_id}")
        if listing.content_hash:
            self._seen_hashes.add(listing.content_hash)

        addr_norm = normalize_address(listing.address)
        if addr_norm:
            self._seen_addresses.add(addr_norm)

        phone_norm = normalize_phone(listing.phone)
        if phone_norm:
            district = normalize_address(listing.district)
            self._seen_phones_districts[phone_norm] = (district, listing.price_vnd_monthly)
