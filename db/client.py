"""
RealEstork — Supabase Database Client
Module 7 (M7) — Database layer

Wraps Supabase Python client with RealEstork-specific operations.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from supabase import Client, create_client

load_dotenv()


def _get_client() -> Client:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env"
        )
    return create_client(url, key)


class SupabaseDB:
    """
    RealEstork database client.
    All methods are synchronous (Supabase Python client is sync by default).
    """

    def __init__(self) -> None:
        self.client = _get_client()
        logger.info("[db] Supabase client initialized")

    # =========================================================
    # LISTINGS
    # =========================================================

    def upsert_listing(self, listing_data: dict[str, Any]) -> dict | None:
        """
        Upsert a listing. Conflict on (source, source_id).
        Returns the upserted row or None on error.
        """
        try:
            result = (
                self.client.table("listings")
                .upsert(listing_data, on_conflict="source,source_id")
                .execute()
            )
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.error(f"[db] upsert_listing error: {e}")
        return None

    def upsert_listings_batch(self, listings: list[dict[str, Any]]) -> int:
        """
        Batch upsert listings. Returns count of successful upserts.
        """
        if not listings:
            return 0
        try:
            result = (
                self.client.table("listings")
                .upsert(listings, on_conflict="source,source_id")
                .execute()
            )
            count = len(result.data) if result.data else 0
            logger.info(f"[db] Batch upserted {count} listings")
            return count
        except Exception as e:
            logger.error(f"[db] upsert_listings_batch error: {e}")
            return 0

    def get_recent_listings(self, limit: int = 500) -> list[dict]:
        """Get recent listings for dedup seeding."""
        try:
            result = (
                self.client.table("listings")
                .select("source, source_id, content_hash, phone, district, address_normalized, price_vnd_monthly")
                .order("scraped_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"[db] get_recent_listings error: {e}")
            return []

    def get_listing_by_id(self, listing_id: str) -> dict | None:
        """Get a single listing by UUID or source-source_id."""
        try:
            query = self.client.table("listings").select("*")
            if "-" in listing_id and not self._is_uuid(listing_id):
                # Try source-source_id format
                parts = listing_id.split("-", 1)
                if len(parts) == 2:
                    source, source_id = parts
                    result = query.eq("source", source).eq("source_id", source_id).maybe_single().execute()
                    return result.data
            
            # Fallback to UUID
            result = query.eq("id", listing_id).maybe_single().execute()
            return result.data
        except Exception:
            return None

    def _is_uuid(self, val: str) -> bool:
        import re
        return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', val.lower()))

    def get_listing_status(self, source: str, source_id: str) -> str | None:
        """Return the current status of a listing, or None if not found."""
        try:
            result = (
                self.client.table("listings")
                .select("status")
                .eq("source", source)
                .eq("source_id", source_id)
                .maybe_single()
                .execute()
            )
            return result.data.get("status") if result.data else None
        except Exception:
            return None

    def update_listing_status(self, listing_id: str, status: str, notes: str = "") -> None:
        """Update listing status (called/confirmed_owner/confirmed_broker/etc.)"""
        try:
            self.client.table("listings").update({
                "status": status,
                "notes": notes,
            }).eq("id", listing_id).execute()
        except Exception as e:
            logger.error(f"[db] update_listing_status error: {e}")

    def update_classification(
        self,
        listing_id: str,
        score: int,
        label: str,
        ai_result: dict | None = None,
        osint_result: dict | None = None,
    ) -> None:
        """Update classification score + label after pipeline."""
        try:
            self.client.table("listings").update({
                "classification_score": score,
                "classification_label": label,
                "ai_result": ai_result,
                "osint_result": osint_result,
                "status": "new",
            }).eq("id", listing_id).execute()
        except Exception as e:
            logger.error(f"[db] update_classification error: {e}")

    def get_daily_stats(self) -> dict[str, Any]:
        """Get stats for daily digest."""
        from datetime import date, timedelta, timezone
        from datetime import datetime as dt
        yesterday = (dt.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        today = dt.now(timezone.utc).date().isoformat()

        try:
            result = (
                self.client.table("listings")
                .select("classification_label, status")
                .gte("scraped_at", yesterday)
                .lt("scraped_at", today)
                .execute()
            )
            rows = result.data or []
            return {
                "total_new": len(rows),
                "chinh_chu": sum(1 for r in rows if r["classification_label"] == "chinh_chu"),
                "can_xac_minh": sum(1 for r in rows if r["classification_label"] == "can_xac_minh"),
                "moi_gioi": sum(1 for r in rows if r["classification_label"] == "moi_gioi"),
                "called": sum(1 for r in rows if r["status"] == "called"),
                "confirmed_owner": sum(1 for r in rows if r["status"] == "confirmed_owner"),
                "confirmed_broker": sum(1 for r in rows if r["status"] == "confirmed_broker"),
            }
        except Exception as e:
            logger.error(f"[db] get_daily_stats error: {e}")
            return {}

    # =========================================================
    # PHONES
    # =========================================================

    def get_phone_stats(self, phone: str) -> dict[str, Any]:
        """Get phone frequency stats from phones table."""
        if not phone:
            return {}
        try:
            result = (
                self.client.table("phones")
                .select("*")
                .eq("phone", phone)
                .maybe_single()
                .execute()
            )
            return result.data or {}
        except Exception:
            return {}

    def is_known_broker(self, phone: str) -> bool:
        """Check if phone is in broker_phones table."""
        if not phone:
            return False
        try:
            result = (
                self.client.table("broker_phones")
                .select("phone")
                .eq("phone", phone)
                .maybe_single()
                .execute()
            )
            return result.data is not None
        except Exception:
            return False

    def upsert_phone(self, phone: str, platform: str) -> None:
        """Increment phone listing count and update platform list."""
        if not phone:
            return
        try:
            # Try to get existing
            existing = self.get_phone_stats(phone)
            if existing:
                platforms = existing.get("platforms", []) or []
                if platform not in platforms:
                    platforms.append(platform)
                self.client.table("phones").update({
                    "total_listings": existing.get("total_listings", 0) + 1,
                    "platforms": platforms,
                    "last_seen": "now()",
                }).eq("phone", phone).execute()
            else:
                self.client.table("phones").insert({
                    "phone": phone,
                    "total_listings": 1,
                    "platforms": [platform],
                }).execute()
        except Exception as e:
            logger.error(f"[db] upsert_phone error: {e}")

    def seed_broker_phones(self, phones: list[dict]) -> int:
        """
        Seed broker_phones table from vợ's known broker list.
        phones: list of {"phone": "0901234567", "name": "...", "company": "...", "source": "manual"}
        """
        if not phones:
            return 0
        try:
            result = (
                self.client.table("broker_phones")
                .upsert(phones, on_conflict="phone")
                .execute()
            )
            count = len(result.data) if result.data else 0
            logger.info(f"[db] Seeded {count} broker phones")
            return count
        except Exception as e:
            logger.error(f"[db] seed_broker_phones error: {e}")
            return 0

    # =========================================================
    # FEEDBACK (Learning Loop)
    # =========================================================

    def save_feedback(
        self,
        listing_id: str,
        predicted_label: str,
        predicted_score: int,
        actual_label: str,
        feedback_source: str,
        signals_at_prediction: dict,
        ai_model_used: str = "",
    ) -> None:
        """Save classification feedback for learning loop."""
        try:
            self.client.table("classification_feedback").insert({
                "listing_id": listing_id,
                "predicted_label": predicted_label,
                "predicted_score": predicted_score,
                "actual_label": actual_label,
                "feedback_source": feedback_source,
                "signals_at_prediction": signals_at_prediction,
                "ai_model_used": ai_model_used,
            }).execute()
        except Exception as e:
            logger.error(f"[db] save_feedback error: {e}")

    def get_recent_feedback(self, days: int = 7) -> list[dict]:
        """Get recent feedback rows for weekly analysis."""
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        try:
            result = (
                self.client.table("classification_feedback")
                .select("*")
                .gte("created_at", since)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"[db] get_recent_feedback error: {e}")
            return []

    # =========================================================
    # SPIDER LOGS
    # =========================================================

    def log_spider_run(
        self,
        spider_name: str,
        status: str,
        listings_found: int = 0,
        new_listings: int = 0,
        error_message: str = "",
        duration_seconds: float = 0,
    ) -> None:
        """Log a spider execution run."""
        try:
            self.client.table("spider_logs").insert({
                "spider_name": spider_name,
                "status": status,
                "listings_found": listings_found,
                "new_listings": new_listings,
                "error_message": error_message,
                "duration_seconds": duration_seconds,
            }).execute()
        except Exception as e:
            logger.error(f"[db] log_spider_run error: {e}")

    # =========================================================
    # SUBSCRIBERS (Hướng 2)
    # =========================================================

    def get_active_subscribers(self) -> list[dict]:
        """Get all active alert subscribers."""
        try:
            result = (
                self.client.table("alert_subscribers")
                .select("*")
                .eq("is_active", True)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"[db] get_active_subscribers error: {e}")
            return []

    def upsert_subscriber(self, subscriber_data: dict) -> None:
        """Create or update a subscriber."""
        try:
            conflict_col = "telegram_chat_id" if subscriber_data.get("telegram_chat_id") else "discord_user_id"
            self.client.table("alert_subscribers").upsert(
                subscriber_data, on_conflict=conflict_col
            ).execute()
        except Exception as e:
            logger.error(f"[db] upsert_subscriber error: {e}")
