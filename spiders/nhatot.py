"""
RealEstork — Nhatot Spider (nhatot.com)
Module 1 (M1) — StealthyFetcher mode

URL: https://www.nhatot.com/thue-van-phong-mat-bang-kinh-doanh-tp-ho-chi-minh
Type: StealthyFetcher (bypass Cloudflare via Camoufox)

Data source: __NEXT_DATA__ JSON embedded in SSR page
Category: cg=1030 (Văn phòng / Mặt bằng kinh doanh - cho thuê)
Region: region_v2=13000 (TP. Hồ Chí Minh)
Pagination: ?page=N
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from spiders.base import BaseSpider, RawListing

BASE_URL = "https://www.nhatot.com"
LISTING_URL_TPL = "https://www.nhatot.com/thue-bat-dong-san-tp-ho-chi-minh/{list_id}.htm"


class NhatotSpider(BaseSpider):
    """
    Spider for nhatot.com — uses StealthyFetcher to bypass Cloudflare.
    Scrapes __NEXT_DATA__ JSON for commercial rental listings (cg=1030).
    """

    name = "nhatot"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.start_url = config.get(
            "url",
            "https://www.nhatot.com/thue-van-phong-mat-bang-kinh-doanh-tp-ho-chi-minh",
        )

    async def fetch_listings(self) -> list[RawListing]:
        """Fetch listings using StealthyFetcher + __NEXT_DATA__ extraction."""
        try:
            from scrapling import StealthyFetcher
        except ImportError as e:
            logger.error(
                f"[nhatot] StealthyFetcher import failed ({type(e).__name__}: {e}). "
                "Fix: pip install -r requirements.txt && "
                "venv/Scripts/scrapling.exe install"
            )
            return []

        all_listings: list[RawListing] = []
        loop = asyncio.get_running_loop()
        age_stop_hours: float = self.config.get("age_stop_hours", 24)
        dedup_stop_ratio: float = self.config.get("dedup_stop_ratio", 0.7)

        for page_num in range(1, self.max_pages + 1):
            url = self._page_url(page_num)
            logger.info(f"[nhatot] Fetching page {page_num}: {url}")

            try:
                page = await loop.run_in_executor(
                    None,
                    lambda u=url: StealthyFetcher.fetch(
                        u,
                        wait=6000,
                        timeout=60000,
                    ),
                )

                if page is None:
                    logger.warning(f"[nhatot] No response on page {page_num}")
                    break

                html = page.html_content or ""

                if "Just a moment" in html or "Checking your browser" in html:
                    logger.warning("[nhatot] Cloudflare challenge not bypassed!")
                    break

                # Extract __NEXT_DATA__
                import json as _json
                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    html,
                    re.DOTALL,
                )
                if not match:
                    logger.warning(f"[nhatot] No __NEXT_DATA__ on page {page_num}")
                    logger.debug(f"[nhatot] HTML snippet: {html[:300]}")
                    break

                data = _json.loads(match.group(1))
                adlisting = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("initialState", {})
                    .get("adlisting", {})
                )
                ads = adlisting.get("data", {}).get("ads", [])

                if not ads:
                    logger.info(f"[nhatot] No ads on page {page_num}")
                    break

                logger.info(f"[nhatot] Found {len(ads)} ads on page {page_num}")

                page_listings: list[RawListing] = []
                for ad in ads:
                    listing = self.parse_listing(ad)
                    if listing is not None:
                        page_listings.append(listing)

                all_listings.extend(page_listings)

                # Early-stop 1: dedup ratio — chỉ tính tin thường (không tính VIP/sticky)
                # VIP luôn nằm đầu trang dù cũ → làm phình ratio giả tạo nếu tính vào
                normal_listings = [l for l in page_listings if not l.is_vip]
                if self.seen_ids and normal_listings:
                    seen_count = sum(
                        1 for l in normal_listings
                        if f"nhatot:{l.source_id}" in self.seen_ids
                    )
                    ratio = seen_count / len(normal_listings)
                    if ratio >= dedup_stop_ratio:
                        logger.info(
                            f"[nhatot] Dedup early-stop page {page_num}: "
                            f"{seen_count}/{len(normal_listings)} normal seen ({ratio:.0%})"
                        )
                        break

                # Early-stop 2: age — stop when non-VIP ads on this page go stale
                ages = [
                    l.listing_age_hours for l in page_listings
                    if not l.is_vip and l.listing_age_hours is not None
                ]
                if ages:
                    oldest = max(ages)
                    if oldest > age_stop_hours:
                        logger.info(
                            f"[nhatot] Age early-stop page {page_num}: "
                            f"oldest non-VIP = {oldest:.1f}h > {age_stop_hours}h"
                        )
                        break

                await asyncio.sleep(self.request_delay)

            except Exception as e:
                logger.error(f"[nhatot] Error page {page_num}: {e}")
                break

        # Post-process: count listings per account
        # Primary key: poster_account_id (stable numeric ID from platform)
        # Fallback: contact_name (for spiders that don't extract account_id)
        from collections import Counter
        id_counts: Counter = Counter(
            l.poster_account_id for l in all_listings if l.poster_account_id
        )
        name_counts: Counter = Counter(
            l.contact_name for l in all_listings if l.contact_name and not l.poster_account_id
        )
        for listing in all_listings:
            if listing.poster_account_id:
                listing.same_session_account_count = id_counts[listing.poster_account_id]
            elif listing.contact_name:
                listing.same_session_account_count = name_counts[listing.contact_name]
        multi_posters = sum(1 for c in id_counts.values() if c > 1)
        if multi_posters:
            logger.info(f"[nhatot] {multi_posters} accounts posted >1 listing this session")

        logger.info(f"[nhatot] Total listings: {len(all_listings)}")
        return all_listings

    def parse_listing(self, raw: dict[str, Any]) -> RawListing | None:
        """Parse a single nhatot ad dict into RawListing."""
        try:
            source_id = str(raw.get("list_id", raw.get("ad_id", "")))
            if not source_id:
                return None

            source_url = LISTING_URL_TPL.format(list_id=source_id)

            title = raw.get("subject", "") or ""
            description = raw.get("body", "") or ""

            # Skip sale & non-rental listings
            title_lower = title.lower()
            _skip_kw = [
                # Sale listings
                "bán nhà", "cần bán", "nhà bán", "bán đất", "bán căn hộ",
                "bán shophouse", "chính chủ bán", "bán gấp", "muốn bán", "bán xưởng",
                # Business transfer — not pure rental
                "sang nhượng", "sang quán", "sang tiệm", "sang mặt bằng",
                "sang kiot", "sang sạp", "sang vựa", "sang shop", "thanh lý kiot",
            ]
            if any(kw in title_lower for kw in _skip_kw):
                return None

            # Location
            area_name = raw.get("area_name", "") or ""
            ward_name = raw.get("ward_name", "") or ""
            address_raw = raw.get("address", "") or ""
            address = ", ".join(filter(None, [address_raw, ward_name, area_name, "TP. Hồ Chí Minh"]))

            # Price
            price_vnd = raw.get("price", None)
            price_text = raw.get("price_string", "") or ""
            if price_vnd and isinstance(price_vnd, (int, float)):
                price_vnd = int(price_vnd)
            else:
                price_vnd = None

            # Area
            area_m2 = raw.get("area", raw.get("size", None))
            if area_m2:
                try:
                    area_m2 = float(area_m2)
                except (ValueError, TypeError):
                    area_m2 = None

            # Floor level
            floor_level = self._extract_floor(title, description, raw)

            # Phone — hidden on listing pages, not in __NEXT_DATA__
            phone = self._extract_phone(raw)

            # Contact name + account ID
            contact_name = raw.get("account_name", None) or raw.get("full_name", None)
            account_id = raw.get("account_id", None)
            poster_account_id = str(account_id) if account_id else None

            # Seller info — broker proxy signals
            seller_info = raw.get("seller_info", {}) or {}
            poster_total_listings = seller_info.get("live_ads", None)
            poster_sold_listings = seller_info.get("sold_ads", None)
            # type: "u"=user/personal (chính chủ), "s"=store/business (môi giới)
            account_type = raw.get("type", None)

            # Property characteristics
            is_main_street = raw.get("is_main_street", None)  # True=mặt tiền, False=hẻm, None=unknown
            is_vip = bool(raw.get("is_sticky", False))         # Paid sticky ad = VIP tier

            # Images
            images: list[str] = []
            img = raw.get("image", None)
            if img:
                images.append(img)
            for extra_img in raw.get("images", []):
                if isinstance(extra_img, str) and extra_img not in images:
                    images.append(extra_img)
                elif isinstance(extra_img, dict):
                    src = extra_img.get("url", extra_img.get("src", ""))
                    if src and src not in images:
                        images.append(src)

            # Posted time — web uses relative "date" string, API uses list_time ms
            posted_at = None
            list_time = raw.get("list_time", None)
            if list_time:
                try:
                    posted_at = datetime.fromtimestamp(list_time / 1000, tz=timezone.utc)
                except (ValueError, TypeError, OSError):
                    pass

            if posted_at is None:
                date_str = raw.get("date", "") or ""
                posted_at = self._parse_relative_time(date_str)

            return RawListing(
                source="nhatot",
                source_id=source_id,
                source_url=source_url,
                title=title,
                description=description,
                address=address,
                district=area_name,
                city="HCMC",
                area_m2=area_m2,
                floor_level=floor_level,
                price_vnd_monthly=price_vnd,
                price_text=price_text,
                phone=phone,
                contact_name=contact_name,
                poster_account_id=poster_account_id,
                images=images,
                posted_at=posted_at,
                poster_total_listings=poster_total_listings,
                poster_sold_listings=poster_sold_listings,
                account_type=account_type,
                is_main_street=is_main_street,
                is_vip=is_vip,
            )

        except Exception as e:
            logger.error(f"[nhatot] parse_listing error: {e} | id={raw.get('list_id')}")
            return None

    def _page_url(self, page_num: int) -> str:
        if page_num == 1:
            return self.start_url
        from urllib.parse import urlparse, urlencode, parse_qs
        parsed = urlparse(self.start_url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params["page"] = [str(page_num)]
        query = urlencode({k: v[0] for k, v in params.items()})
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query}"

    def _extract_phone(self, raw: dict[str, Any]) -> str:
        """Extract phone from listing data."""
        phone = raw.get("phone", "") or raw.get("contact_phone", "") or ""
        if phone:
            return self._clean_phone(phone)
        contact_info = raw.get("contact_info", {}) or {}
        if isinstance(contact_info, dict):
            phone = contact_info.get("phone", "") or ""
            if phone:
                return self._clean_phone(phone)
        return ""

    def _clean_phone(self, phone: str) -> str:
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("84") and len(digits) == 11:
            digits = "0" + digits[2:]
        if digits.startswith("0084") and len(digits) == 13:
            digits = "0" + digits[4:]
        return digits if len(digits) == 10 else phone

    def _extract_floor(
        self, title: str, description: str, raw: dict[str, Any]
    ) -> int | None:
        floor_raw = raw.get("floor", None) or raw.get("tang", None)
        if floor_raw is not None:
            try:
                return int(floor_raw)
            except (ValueError, TypeError):
                pass

        text = f"{title} {description}".lower()
        patterns = [
            (r"tầng\s*trệt", 1),
            (r"tầng\s*1\b", 1),
            (r"tầng\s*2\b", 2),
            (r"tầng\s*3\b", 3),
            (r"tầng\s*4\b", 4),
            (r"tầng\s*5\b", 5),
            (r"lầu\s*1\b", 2),
            (r"lầu\s*2\b", 3),
            (r"lầu\s*3\b", 4),
            (r"trệt", 1),
            (r"ground floor", 1),
        ]
        for pattern, floor in patterns:
            if re.search(pattern, text):
                return floor
        return None

    def _parse_relative_time(self, text: str) -> datetime | None:
        """Parse Vietnamese relative time: '5 phút trước', '2 giờ trước', '3 ngày trước'."""
        now = datetime.now(timezone.utc)
        text = text.lower().strip()
        try:
            if "giây" in text:
                m = re.search(r"(\d+)", text)
                if m:
                    return now - timedelta(seconds=int(m.group(1)))
            elif "phút" in text:
                m = re.search(r"(\d+)", text)
                if m:
                    return now - timedelta(minutes=int(m.group(1)))
            elif "giờ" in text:
                m = re.search(r"(\d+)", text)
                if m:
                    return now - timedelta(hours=int(m.group(1)))
            elif "ngày" in text:
                m = re.search(r"(\d+)", text)
                if m:
                    return now - timedelta(days=int(m.group(1)))
            elif "/" in text:
                from dateutil import parser as dp
                return dp.parse(text, dayfirst=True).replace(tzinfo=timezone.utc)
        except Exception:
            pass
        return None
