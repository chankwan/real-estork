"""
RealEstork — Alonhadat Spider
Module 1 (M1) — HTTP mode, ít anti-bot

URL: https://alonhadat.com.vn/cho-thue-mat-bang/tp-ho-chi-minh.html
Type: HTTP scraping đơn giản với Scrapling Fetcher
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from loguru import logger

from spiders.base import BaseSpider, RawListing

BASE_URL = "https://alonhadat.com.vn"


class AlonhadatSpider(BaseSpider):
    """
    Spider for alonhadat.com.vn — HTTP scraping, minimal anti-bot.
    Uses Scrapling Fetcher (HTTP mode).
    """

    name = "alonhadat"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.start_url = config.get(
            "url",
            "https://alonhadat.com.vn/cho-thue-mat-bang/tp-ho-chi-minh.html",
        )

    async def fetch_listings(self) -> list[RawListing]:
        """Fetch listings using Scrapling Fetcher."""
        try:
            from scrapling import Fetcher
        except ImportError:
            logger.error("[alonhadat] scrapling not installed. Run: pip install scrapling")
            return []

        all_listings: list[RawListing] = []
        fetcher = Fetcher()
        loop = asyncio.get_running_loop()

        for page_num in range(1, self.max_pages + 1):
            url = self._page_url(page_num)
            logger.info(f"[alonhadat] Fetching page {page_num}: {url}")

            try:
                page = await loop.run_in_executor(None, lambda u=url: fetcher.get(u))

                if page is None:
                    logger.warning(f"[alonhadat] No response page {page_num}")
                    break

                # Extract listing cards
                cards = page.css(".property-item")
                if not cards:
                    logger.info(f"[alonhadat] No cards found page {page_num}")
                    break

                logger.info(f"[alonhadat] Found {len(cards)} cards on page {page_num}")

                for card in cards:
                    listing = self.parse_listing(card)
                    if listing is not None:
                        all_listings.append(listing)

                await asyncio.sleep(self.request_delay)

            except Exception as e:
                logger.error(f"[alonhadat] Error fetching page {page_num}: {e}")
                break

        # Fetch phone numbers from detail pages (phone not on list page)
        if all_listings:
            logger.info(f"[alonhadat] Fetching phones from {len(all_listings)} detail pages...")
            semaphore = asyncio.Semaphore(5)
            phone_tasks = [
                self._fetch_detail_phone(l.source_url, fetcher, loop, semaphore)
                for l in all_listings
            ]
            phones = await asyncio.gather(*phone_tasks)
            found = 0
            for listing, phone in zip(all_listings, phones):
                if phone:
                    listing.phone = phone
                    found += 1
            logger.info(f"[alonhadat] Phones found: {found}/{len(all_listings)}")

        logger.info(f"[alonhadat] Total listings: {len(all_listings)}")
        return all_listings

    async def _fetch_detail_phone(
        self,
        url: str,
        fetcher: Any,
        loop: Any,
        semaphore: asyncio.Semaphore,
    ) -> str:
        """Fetch phone number from a listing detail page via tel: link."""
        async with semaphore:
            try:
                page = await loop.run_in_executor(None, lambda: fetcher.get(url))
                if not page:
                    return ""
                tel_els = page.css('a[href^="tel:"]')
                if tel_els:
                    href = tel_els[0].attrib.get("href", "")
                    raw = href.replace("tel:", "")
                    return self._clean_phone(raw)
            except Exception as e:
                logger.debug(f"[alonhadat] phone fetch error {url}: {e}")
            return ""

    def parse_listing(self, card: Any) -> RawListing | None:
        """Parse an HTML card element into RawListing."""
        try:
            def _css(selector: str) -> Any:
                els = card.css(selector)
                return els[0] if els else None

            # Title + URL
            link_el = _css("a.link")
            if not link_el:
                return None
            title_el = _css(".property-title")
            title = title_el.text.strip() if title_el else ""
            if not title:
                return None

            href = link_el.attrib.get("href", "")
            source_url = urljoin(BASE_URL, href)
            source_id = self._extract_id(source_url)

            # Description
            desc_el = _css(".brief")
            description = desc_el.text.strip() if desc_el else ""
            # Remove "Xem chi tiết" suffix noise
            description = description.replace("<< Xem chi tiết >>", "").strip()

            # Price — <span itemprop="price" content="100000000">100 triệu / tháng</span>
            price_span = _css('[itemprop="price"]')
            price_text = price_span.text.strip() if price_span else ""
            price_vnd = None
            if price_span:
                content = price_span.attrib.get("content", "")
                if content:
                    try:
                        price_vnd = int(content)
                    except ValueError:
                        price_vnd = self._parse_price(price_text)
                else:
                    price_vnd = self._parse_price(price_text)

            # Area — from street-width or parse description
            area_m2 = None
            area_m2 = self._parse_area(description)

            # Address — text is in child spans, not directly on the element
            addr_el = _css(".property-address")
            address_raw = ""
            if addr_el:
                # Find the span with the longest text (contains full address)
                spans = addr_el.css("span")
                if spans:
                    address_raw = max((s.text or "" for s in spans), key=len).strip()
                if not address_raw:
                    address_raw = addr_el.text.strip()
            district_raw = self._extract_district(address_raw)

            # Floor level
            floors_el = _css(".floors")
            floors_text = floors_el.text.strip() if floors_el else ""
            floor_level = self._extract_floor(title, description)
            if floor_level is None and floors_text:
                m = re.search(r"(\d+)", floors_text)
                if m:
                    floor_level = int(m.group(1))

            # Phone
            phone_el = _css(".phone")
            phone = ""
            if phone_el:
                phone = phone_el.attrib.get("data-phone", "") or phone_el.text or ""
                phone = self._clean_phone(phone)

            # Contact name
            name_el = _css(".fullname")
            contact_name = name_el.text.strip() if name_el else None

            # Image
            images: list[str] = []
            img_el = _css(".thumbnail img")
            if img_el:
                src = img_el.attrib.get("src", "") or img_el.attrib.get("data-src", "")
                if src:
                    images.append(urljoin(BASE_URL, src))

            # Posted time
            date_el = _css(".created-date")
            posted_at = self._parse_date(date_el.text.strip() if date_el else "")

            return RawListing(
                source="alonhadat",
                source_id=source_id,
                source_url=source_url,
                title=title,
                description=description,
                address=address_raw,
                district=district_raw,
                area_m2=area_m2,
                floor_level=floor_level,
                price_vnd_monthly=price_vnd,
                price_text=price_text,
                phone=phone,
                contact_name=contact_name,
                images=images,
                posted_at=posted_at,
            )

        except Exception as e:
            logger.error(f"[alonhadat] parse_listing error: {e}")
            return None

    def _extract_district(self, address: str) -> str:
        """Extract district from address string."""
        match = re.search(r"Qu[aậ]n\s+[\w\s]+|Q\.\s*\d+|Q\d+|Huyện\s+\w+", address)
        return match.group(0).strip() if match else address.split(",")[-1].strip()

    def _page_url(self, page_num: int) -> str:
        """Generate URL for page N."""
        if page_num == 1:
            return self.start_url
        return f"https://alonhadat.com.vn/cho-thue-nha-dat/trang-{page_num}"

    def _extract_id(self, url: str) -> str:
        """Extract listing ID from URL."""
        # e.g. /cho-thue-mat-bang/12345-abc.html → 12345
        match = re.search(r"/(\d+)-", url)
        return match.group(1) if match else url.split("/")[-1]

    def _parse_price(self, text: str) -> int | None:
        """Parse price text to VND monthly int."""
        if not text:
            return None
        text_lower = text.lower().replace(",", ".").replace(" ", "")
        # Extract number
        match = re.search(r"(\d+(?:\.\d+)?)", text_lower)
        if not match:
            return None
        num = float(match.group(1))
        if "tỷ" in text_lower or "ty" in text_lower:
            return int(num * 1_000_000_000)
        elif "triệu" in text_lower or "tr" in text_lower:
            return int(num * 1_000_000)
        elif "nghìn" in text_lower or "k" in text_lower:
            return int(num * 1_000)
        return int(num)

    def _parse_area(self, text: str) -> float | None:
        """Parse area text to m2 float."""
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text.lower())
        if match:
            return float(match.group(1).replace(",", "."))
        return None

    def _extract_floor(self, title: str, description: str) -> int | None:
        """Extract floor level from text."""
        text = f"{title} {description}".lower()
        patterns = [
            (r"tầng\s*trệt|trệt", 1),
            (r"tầng\s*1\b|tầng\s*một", 1),
            (r"lầu\s*1\b|lầu\s*một", 2),
            (r"lầu\s*2\b", 3),
            (r"lầu\s*3\b", 4),
            (r"tầng\s*2\b", 2),
            (r"tầng\s*3\b", 3),
        ]
        for pattern, floor in patterns:
            if re.search(pattern, text):
                return floor
        return None

    def _clean_phone(self, phone: str) -> str:
        """Normalize phone number."""
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("84") and len(digits) == 11:
            digits = "0" + digits[2:]
        return digits if len(digits) >= 9 else ""

    def _parse_date(self, text: str) -> datetime | None:
        """Parse Vietnamese date string."""
        if not text:
            return None
        try:
            # Format: "06/04/2026" or "6/4/2026"
            from dateutil import parser as dateparser
            return dateparser.parse(text, dayfirst=True).replace(tzinfo=timezone.utc)
        except Exception:
            return None
