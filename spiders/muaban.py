"""
RealEstork — Muaban Spider (muaban.net)
Module 1 (M1) — curl_cffi Firefox133 (no browser needed)

Cloudflare bypass: curl_cffi Firefox133 TLS impersonation — verified 22/04/2026.
httpx plain → 403. StealthyFetcher (camoufox) → works but overkill.

Crawl strategy (v3 — 22/04/2026):
  Stage 1 — List pages (curl_cffi, 1 shared AsyncSession):
    - Parse __NEXT_DATA__ JSON, 20 items/page
    - VIP (service_ids ∩ {16,8,4,128}): skip nếu > 24h, keep nếu trong 24h
    - Normal: early-stop khi gặp non-today listing đầu tiên
    - Dedup ratio early-stop: >70% normal listings đã seen → stop
  Stage 2 — Detail pages (curl_cffi, concurrent sem=3):
    - contact_name (từ classified JSON)
    - Phone (data-phone attr trong body HTML, FREE — không cần auth)
    - Full description (body HTML → plain text)
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

from loguru import logger

from spiders.base import BaseSpider, RawListing

BASE_URL = "https://muaban.net"
_VIP_SERVICE_IDS = {16, 8, 4, 128}
_VN_TZ = timezone(timedelta(hours=7))
_HTML_TAG_RE = re.compile(r"<[^>]+>")

_CURL_HEADERS = {"Referer": "https://www.google.com/"}


class MuabanSpider(BaseSpider):
    """Spider for muaban.net — curl_cffi Firefox133, no browser required."""

    name = "muaban"
    token_expired: bool = False

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.start_url = config.get(
            "url",
            "https://muaban.net/bat-dong-san/cho-thue-van-phong-mat-bang-ho-chi-minh?sort=1&price=15000000-100000000",
        )
        self.dedup_stop_ratio: float = float(config.get("dedup_stop_ratio", 0.7))
        self.detail_concurrency: int = int(config.get("detail_concurrency", 3))
        self._auth = None

    # ─── Auth (cookie-based phone reveal fallback) ─────────────────────────

    async def _get_auth(self):
        if self._auth is None:
            from auth.muaban_auth import MuabanAuthClient
            self._auth = MuabanAuthClient()
        return self._auth

    async def enrich_listing(self, listing: RawListing) -> bool:
        """Cookie-based phone reveal — fallback if detail page didn't get phone."""
        if not listing.source_id:
            return False
        auth = await self._get_auth()
        cookies = auth.load_cookies()
        if not cookies:
            return False
        api_url = f"https://muaban.net/api/v1/classifieds/{listing.source_id}/phone"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    api_url,
                    cookies=cookies,
                    headers={"Referer": listing.source_url or BASE_URL,
                              "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                if resp.status_code == 200:
                    phone_val = resp.json().get("phone")
                    if phone_val:
                        listing.phone = self._clean_phone(phone_val)
                        return True
                elif resp.status_code in (401, 403):
                    logger.warning(
                        f"[muaban] Session expired (HTTP {resp.status_code}). "
                        "Run: python -m cli.main setup-muaban"
                    )
                    self.token_expired = True
        except Exception as e:
            logger.debug(f"[muaban] enrich_listing error: {e}")
        return False

    # ─── Stage 1: List page crawl ──────────────────────────────────────────

    async def fetch_listings(self) -> list[RawListing]:
        from curl_cffi.requests import AsyncSession

        all_listings: list[RawListing] = []
        page_num = 1
        stop_reason = ""

        async with AsyncSession() as session:
            while page_num <= self.max_pages:
                url = self._page_url(page_num)
                logger.info(f"[muaban] Fetching page {page_num}: {url}")

                try:
                    resp = await session.get(
                        url,
                        impersonate="firefox133",
                        timeout=20,
                        headers=_CURL_HEADERS,
                    )

                    if resp.status_code != 200:
                        logger.warning(f"[muaban] Page {page_num}: HTTP {resp.status_code}")
                        break

                    html = resp.text
                    if "Just a moment" in html or "Checking your browser" in html:
                        logger.warning(f"[muaban] Cloudflare challenge on page {page_num}")
                        break

                    match = re.search(
                        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                        html,
                        re.DOTALL,
                    )
                    if not match:
                        logger.warning(f"[muaban] No __NEXT_DATA__ on page {page_num}")
                        break

                    data = json.loads(match.group(1))
                    items = (
                        data.get("props", {})
                        .get("pageProps", {})
                        .get("classified", {})
                        .get("items", [])
                    )

                    if not items:
                        logger.info(f"[muaban] No listings on page {page_num}")
                        break

                    page_parsed: list[RawListing] = []
                    page_non_today = 0
                    page_normal_count = 0
                    page_normal_dedup_hit = 0
                    vip_count = 0

                    for item in items:
                        listing = self._parse_listing(item)
                        if not listing:
                            continue

                        is_dup = f"muaban:{listing.source_id}" in self.seen_ids

                        if listing.is_vip:
                            vip_count += 1
                            # VIP not-today: skip card, do NOT trigger early-stop
                            if listing.posted_at and not self._is_within_24h(listing.posted_at):
                                continue
                            page_parsed.append(listing)
                            continue

                        # Normal listing
                        page_normal_count += 1
                        if is_dup:
                            page_normal_dedup_hit += 1
                        if listing.posted_at and not self._is_within_24h(listing.posted_at):
                            page_non_today += 1

                        page_parsed.append(listing)

                    all_listings.extend(page_parsed)
                    logger.info(
                        f"[muaban] Page {page_num}: parsed={len(page_parsed)}, "
                        f"normal_dedup={page_normal_dedup_hit}/{page_normal_count}, "
                        f"non_today={page_non_today}, vip={vip_count}"
                    )

                    # Early-stop: first non-today normal listing
                    if page_non_today >= 1:
                        stop_reason = f"non-today normal on page {page_num}"
                        break

                    # Early-stop: normal dedup ratio > threshold
                    if page_normal_count > 0:
                        ratio = page_normal_dedup_hit / page_normal_count
                        if ratio > self.dedup_stop_ratio:
                            stop_reason = (
                                f"normal dedup {page_normal_dedup_hit}/{page_normal_count}"
                                f" > {self.dedup_stop_ratio}"
                            )
                            break

                    page_num += 1
                    await asyncio.sleep(self.request_delay)

                except Exception as e:
                    logger.error(f"[muaban] Error on page {page_num}: {e}")
                    break

        if stop_reason:
            logger.info(f"[muaban] Early-stop: {stop_reason}")

        # Post-process: same-session account count (uses user_id as key)
        from collections import Counter
        id_counts: Counter = Counter(
            l.poster_profile_hash for l in all_listings if l.poster_profile_hash
        )
        for listing in all_listings:
            if listing.poster_profile_hash:
                listing.same_session_account_count = id_counts[listing.poster_profile_hash]

        logger.info(f"[muaban] Stage 1 done: {len(all_listings)} listings")

        # ── Stage 2: Batch detail enrichment ──────────────────────────────
        if all_listings:
            await self._enrich_details_batch(all_listings)

        return all_listings

    # ─── Stage 2: Detail enrichment ────────────────────────────────────────

    async def _enrich_details_batch(self, listings: list[RawListing]) -> None:
        """Concurrently fetch detail pages for contact_name + phone (free, no auth)."""
        sem = asyncio.Semaphore(self.detail_concurrency)

        async def enrich_one(lst: RawListing) -> None:
            async with sem:
                await self._enrich_detail(lst)
                await asyncio.sleep(0.8)

        logger.info(
            f"[muaban] Stage 2: enriching {len(listings)} detail pages "
            f"(sem={self.detail_concurrency})..."
        )
        await asyncio.gather(*[enrich_one(l) for l in listings], return_exceptions=True)

        phones_ok = sum(1 for l in listings if l.phone)
        names_ok = sum(1 for l in listings if l.contact_name)
        logger.info(f"[muaban] Stage 2 done: {phones_ok} phones, {names_ok} names")

    async def _enrich_detail(self, listing: RawListing) -> None:
        """
        Fetch detail page via curl_cffi Firefox133.
        Extracts: contact_name, phone (data-phone in body HTML), full description.
        No auth required — phone embedded in SSR HTML.
        """
        if not listing.source_url:
            return
        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession() as session:
                resp = await session.get(
                    listing.source_url,
                    impersonate="firefox133",
                    timeout=15,
                    headers=_CURL_HEADERS,
                )
            if resp.status_code != 200:
                logger.debug(f"[muaban] detail {listing.source_id}: HTTP {resp.status_code}")
                return

            html = resp.text
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                html,
                re.DOTALL,
            )
            if not match:
                return

            classified = (
                json.loads(match.group(1))
                .get("props", {})
                .get("pageProps", {})
                .get("classified", {})
            )

            # contact_name
            if not listing.contact_name:
                listing.contact_name = classified.get("contact_name") or None

            # Phone from data-phone attribute in body HTML (free, no auth)
            if not listing.phone:
                body_html = classified.get("body", "")
                phones_found = re.findall(r'data-phone=["\'](\d+)["\']', body_html)
                if phones_found:
                    clean = self._clean_phone(phones_found[0])
                    if clean:
                        listing.phone = clean

            # Full description — upgrade from summary if body is longer
            body_html = classified.get("body", "")
            if body_html:
                plain = _HTML_TAG_RE.sub(" ", body_html).strip()
                plain = re.sub(r"\s{2,}", " ", plain)
                if len(plain) > len(listing.description or ""):
                    listing.description = plain

        except Exception as e:
            logger.debug(f"[muaban] _enrich_detail error {listing.source_id}: {e}")

    # ─── Parsing ───────────────────────────────────────────────────────────

    def _parse_listing(self, item: dict[str, Any]) -> RawListing | None:
        try:
            source_id = str(item.get("id", ""))
            if not source_id:
                return None

            title = item.get("title", "")
            description = item.get("summary", "")  # Short preview; upgraded in stage 2

            # District from locations_display (structured, reliable)
            # Format: [{name: "Phường X"}, {name: "Quận Y"}, {name: "TP.HCM"}]
            locations = item.get("locations_display", [])
            if len(locations) >= 2:
                district = locations[-2].get("name", "")
            else:
                loc_str = item.get("location", "")
                parts = [p.strip() for p in loc_str.split(",")]
                district = ""
                for p in parts:
                    if any(k in p for k in ["Quận", "Huyện", "Thủ Đức"]):
                        district = p
                        break
                if not district:
                    district = parts[-2] if len(parts) >= 2 and ("TP" in parts[-1] or "Hồ Chí Minh" in parts[-1]) else (parts[-1] if parts else loc_str)

            address = item.get("location", "")
            price_vnd = item.get("price")
            price_text = item.get("price_display", "")

            # Area from attributes (only "value" key, no "name")
            area_m2 = None
            for attr in item.get("attributes", []):
                val = attr.get("value", "")
                if "m²" in val or "m2" in val.lower():
                    try:
                        area_m2 = float(
                            val.replace("m²", "").replace("m2", "").strip().replace(",", ".")
                        )
                        break
                    except (ValueError, TypeError):
                        pass

            # Phone: list page always masked — filled in stage 2
            phone = ""
            phone_disp = item.get("phone_display", "")
            if phone_disp and "*" not in phone_disp:
                phone = self._clean_phone(phone_disp)

            service_ids = set(item.get("service_ids", []))
            is_vip = bool(service_ids & _VIP_SERVICE_IDS)

            # Poster: list page has user_id only; contact_name + total_listings filled in stage 2
            user_id = str(item.get("user_id", ""))

            # Timestamp: use publish_at (full ISO8601) not publish_display (date only)
            posted_at: datetime | None = None
            raw_ts = item.get("publish_at")
            if raw_ts:
                try:
                    posted_at = datetime.fromisoformat(raw_ts)
                except ValueError:
                    pass
            if posted_at is None:
                posted_at = self._parse_relative_time(item.get("publish_display", ""))

            images = item.get("covers", [])

            return RawListing(
                source="muaban",
                source_id=source_id,
                source_url=urljoin(BASE_URL, item.get("url", "")),
                title=title,
                description=description,
                address=address,
                district=district,
                city="HCMC",
                area_m2=area_m2,
                price_vnd_monthly=price_vnd,
                price_text=price_text,
                phone=phone,
                contact_name=None,          # filled by _enrich_detail (stage 2)
                poster_total_listings=None,  # not available in list/detail page API
                images=images,
                posted_at=posted_at,
                account_type=None,           # is_company unreliable (audit 22/04) → neutral
                poster_profile_hash=user_id, # user_id as session-dedup key
                is_vip=is_vip,
                avatar_url=None,             # not in API; signal guarded in signals.py
            )
        except Exception as e:
            logger.error(f"[muaban] _parse_listing error {item.get('id')}: {e}")
            return None

    def parse_listing(self, raw: Any) -> RawListing | None:
        return self._parse_listing(raw)

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _page_url(self, page_num: int) -> str:
        if page_num == 1:
            return self.start_url
        connector = "&" if "?" in self.start_url else "?"
        return f"{self.start_url}{connector}cp={page_num}"

    def _parse_relative_time(self, text: str) -> datetime | None:
        now_vn = datetime.now(_VN_TZ)
        t = (text or "").lower().strip()
        if not t:
            return None
        try:
            m = re.search(r"(\d+)", t)
            n = int(m.group(1)) if m else 0
            if "phút trước" in t:
                return (now_vn - timedelta(minutes=n)).astimezone(timezone.utc)
            if "giờ trước" in t:
                return (now_vn - timedelta(hours=n)).astimezone(timezone.utc)
            if "hôm nay" in t or "vừa đăng" in t:
                return now_vn.astimezone(timezone.utc)
            if "hôm qua" in t:
                return (now_vn - timedelta(days=1)).astimezone(timezone.utc)
            if "/" in t:
                from dateutil import parser as dp
                return dp.parse(t, dayfirst=True).replace(tzinfo=_VN_TZ).astimezone(timezone.utc)
        except Exception:
            pass
        return None

    def _is_within_24h(self, posted_at: datetime) -> bool:
        if posted_at is None:
            return False
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - posted_at <= timedelta(hours=24)

    def _clean_phone(self, phone: str) -> str:
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("84") and len(digits) == 11:
            digits = "0" + digits[2:]
        return digits if len(digits) == 10 else ""
