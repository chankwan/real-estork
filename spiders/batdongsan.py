"""
RealEstork — Batdongsan Spider (v4 — VIP-aware early-stop)
Module 1 (M1) — StealthyFetcher (Cloudflare bypass) + detail enrichment

v4: Parse cả VIP lẫn tin thường. Chỉ break early-stop khi gặp tin THƯỜNG
  not-today. VIP not-today bị bỏ qua (continue) — không trigger break.
  Pro-agent badge vẫn hard-skip bất kể VIP hay thường.

  List page:    Parse all cards (VIP + thường). Skip `has_pro_agent`.
                VIP + not-today → continue (skip card, no break).
                Normal + not-today → page_non_today++ → early-stop break.
                Dedup hit-rate > 70% → early-stop break.
  Detail page:  Fetch song song (sem=detail_concurrency) cho mọi listing.
                Extract: contact_name, description, poster_total_listings,
                guru profile hash.
  Guru profile: Orchestrator gọi enrich_from_profile() cho listings trong
                score window [30, 75].

Note: Phone extraction từ BDS đã bỏ — BDS không embed SĐT trong HTML và
      DecryptPhone API cần auth session phức tạp. Classification dựa vào
      poster_total_listings, contact_name, description text signals.

Key selectors:
  LIST:
    - Card listing      : .js__card-listing (all tiers)
    - VIP markers       : class substring 're__vip-silver/gold/diamond' → is_vip=True
    - Normal tier       : class substring 're__vip-normal'
    - Pro-agent badge   : class substring 're__pro-agent' OR text 'chuyên nghiệp' → hard-skip
    - Description       : .re__card-description.js__card-description (plain snippet)
    - Location          : .re__card-location span (second span, skip bullet dot)
    - Time              : .re__card-published-info-published-at (relative text)

  DETAIL:
    - Contact name      : .re__contact-name (fallback: .re__agent-name)
    - Description       : .re__section.re__pr-description .re__section-body,
                         OR .re__detail-content
    - Profile link      : a[href*="guru.batdongsan.com.vn/pa/"]
    - Active listings   : text 'Tin đăng đang có X' từ sidebar contact card

  GURU PROFILE:
    - Active listings   : text 'Tin đăng đang có' → sibling <p> → integer
    - Join year (rel.)  : text 'Tham gia Batdongsan.com.vn' → sibling <p> → 'N năm'
                          Absolute year = current_year - N

"""

from __future__ import annotations

import asyncio
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

from loguru import logger

from spiders.base import BaseSpider, RawListing

BASE_URL = "https://batdongsan.com.vn"
GURU_BASE = "https://guru.batdongsan.com.vn"
DECRYPT_PHONE_API = (
    "https://batdongsan.com.vn"
    "/microservice-architecture-router/Product/ProductDetail/DecryptPhone"
)

# VIP tier class substrings. Captured as metadata (is_vip=True), NOT skipped.
_VIP_TIER_MARKERS = ("re__vip-silver", "re__vip-gold", "re__vip-diamond")

_URL_PROPERTY_TYPE: dict[str, str] = {
    "cho-thue-nha-mat-pho":                  "nha_mat_pho",
    "cho-thue-shophouse-nha-pho-thuong-mai":  "shophouse",
    "cho-thue-kho-nha-xuong-dat":            "kho_nha_xuong",
    "cho-thue-nha-rieng":                    "nha_rieng",
    "cho-thue-nha-biet-thu-lien-ke":         "biet_thu_lien_ke",
}

# Pro-agent: card có class re__pro-agent → confirmed broker, lưu DB, không alert.
# Chỉ check class (không check text) để tránh false positive khi chủ nhà ghi
# "không qua môi giới chuyên nghiệp" trong mô tả.
_PRO_AGENT_MARKERS = ("re__pro-agent",)

# UTC+7 (Asia/Ho_Chi_Minh) — all BDS relative timestamps interpreted in this TZ
_VN_TZ = timezone(timedelta(hours=7))


class BatdongsanSpider(BaseSpider):
    """Spider for batdongsan.com.vn — unified pipeline (VIP + thường), detail enrichment."""

    name = "batdongsan"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        _default_url = "https://batdongsan.com.vn/cho-thue-nha-mat-pho-tp-ho-chi-minh?cIds=577,52,576,53"
        urls_cfg = config.get("urls", None)
        if urls_cfg:
            self.start_urls: list[str] = [u.strip() for u in urls_cfg if u.strip()]
        else:
            self.start_urls = [config.get("url", _default_url)]
        # Keep start_url pointing to first URL (used by _page_url default)
        self.start_url = self.start_urls[0]
        self.detail_concurrency: int = int(config.get("detail_concurrency", 4))
        self.dedup_stop_ratio: float = float(config.get("dedup_stop_ratio", 0.7))
        # Hold reference to StealthyFetcher.fetch — lazily imported in fetch_listings
        self._fetch_impl: Any = None

    # ────────────────────────── ORCHESTRATION ──────────────────────────

    async def fetch_listings(self) -> list[RawListing]:
        try:
            from scrapling import StealthyFetcher
        except ImportError:
            logger.error(
                "[batdongsan] scrapling chưa cài. "
                "Chạy: pip install scrapling camoufox && python -m camoufox fetch"
            )
            return []

        self._fetch_impl = StealthyFetcher.fetch
        loop = asyncio.get_running_loop()

        all_listings: list[RawListing] = []
        pro_agent_listings: list[RawListing] = []

        for start_url in self.start_urls:
            listings, pro_agents = await self._fetch_pages_from(start_url, loop)
            all_listings.extend(listings)
            pro_agent_listings.extend(pro_agents)
            if len(self.start_urls) > 1:
                await asyncio.sleep(self.request_delay)

        # ── Detail enrichment (parallel across all URLs) ───────────────
        logger.info(f"[batdongsan] Enriching {len(all_listings)} details (concurrency={self.detail_concurrency})")
        sem = asyncio.Semaphore(self.detail_concurrency)

        async def _enrich(l: RawListing) -> None:
            async with sem:
                try:
                    import random
                    await asyncio.sleep(random.uniform(1.0, 3.0))
                    await self._enrich_from_detail(l, loop)
                except Exception as e:
                    logger.warning(f"[batdongsan] detail enrich failed for {l.source_id}: {e}")

        await asyncio.gather(*(_enrich(l) for l in all_listings))

        # ── Post-process: same-session count ──────────────────────────
        name_counts: Counter = Counter(l.contact_name for l in all_listings if l.contact_name)
        for listing in all_listings:
            listing.same_session_account_count = (
                name_counts[listing.contact_name] if listing.contact_name else 1
            )
        multi = sum(1 for c in name_counts.values() if c > 1)
        if multi:
            logger.info(f"[batdongsan] {multi} accounts posted >1 listing this session")

        logger.info(
            f"[batdongsan] Total: {len(all_listings)} listings, "
            f"{len(pro_agent_listings)} pro-agent (confirmed broker)"
        )
        self._pro_agent_listings = pro_agent_listings
        return all_listings

    async def _fetch_pages_from(
        self, start_url: str, loop: asyncio.AbstractEventLoop
    ) -> tuple[list[RawListing], list[RawListing]]:
        """Crawl list pages for a single start_url. Returns (normal_listings, pro_agent_listings)."""
        from urllib.parse import urlparse
        url_path = urlparse(start_url).path
        property_type = next(
            (ptype for slug, ptype in _URL_PROPERTY_TYPE.items() if slug in url_path), ""
        )

        listings: list[RawListing] = []
        pro_agent_listings: list[RawListing] = []
        vip_count = 0
        pro_agent_count = 0
        stop_reason = ""
        page_num = 1
        while page_num <= self.max_pages:
            url = self._page_url(start_url, page_num)
            logger.info(f"[batdongsan] Fetching page {page_num}: {url}")

            try:
                page = await self._stealth_fetch(url, loop)
            except Exception as e:
                logger.error(f"[batdongsan] Error page {page_num}: {e}")
                break

            if page is None:
                logger.warning(f"[batdongsan] No response page {page_num}")
                break

            html = page.html_content or ""
            if "Checking your browser" in html or "Just a moment" in html:
                logger.warning("[batdongsan] Cloudflare challenge không bypass được")
                break

            # Target full-web cards (tin thường vs compact VIP)
            cards = page.css(".js__card-listing") or []
            if not cards:
                logger.warning(
                    f"[batdongsan] Không tìm thấy card page {page_num} "
                    "— selector có thể đã thay đổi"
                )
                logger.debug(f"[batdongsan] HTML snippet: {html[:500]}")
                break

            page_parsed: list[RawListing] = []
            page_non_today = 0
            page_normal_count = 0
            page_normal_dedup_hit = 0
            for card in cards:
                parsed, skip = self._parse_list_card(card)
                if skip == "pro_agent":
                    pro_agent_count += 1
                    if parsed is not None:
                        pro_agent_listings.append(parsed)
                    continue
                if parsed is None:
                    continue

                # Dedup check
                is_dup = f"batdongsan:{parsed.source_id}" in self.seen_ids

                # VIP: chỉ lấy khi đăng hôm nay + chưa thấy trước đó
                if parsed.is_vip:
                    if parsed.posted_at is None or not self._is_posted_today(parsed.posted_at):
                        vip_count += 1
                        continue  # VIP không phải hôm nay → skip, không trigger early-stop
                    if is_dup:
                        vip_count += 1
                        continue  # VIP đã biết → skip
                    vip_count += 1
                    page_parsed.append(parsed)
                    continue

                # Tin thường: 
                page_normal_count += 1
                if is_dup:
                    page_normal_dedup_hit += 1

                if parsed.posted_at is not None and not self._is_posted_today(parsed.posted_at):
                    page_non_today += 1
                page_parsed.append(parsed)

            logger.info(
                f"[batdongsan] Page {page_num}: parsed={len(page_parsed)}, "
                f"normal_dedup_hit={page_normal_dedup_hit}/{page_normal_count}, "
                f"non_today={page_non_today} "
                f"(VIP_parsed={vip_count}, pro-agent_skip={pro_agent_count} cumulative)"
            )

            if property_type:
                for l in page_parsed:
                    l.property_type = property_type
            listings.extend(page_parsed)

            # ── Early-stop evaluation ───────────────────────────────
            if page_non_today >= 1:
                stop_reason = f"non-today card detected on page {page_num}"
                break

            # Chỉ breakout dựa trên dedup hit-rate của TIN THƯỜNG. VIP bỏ qua.
            if page_normal_count > 0:
                hit_rate = page_normal_dedup_hit / page_normal_count
                if hit_rate > self.dedup_stop_ratio:
                    stop_reason = (
                        f"normal dedup hit-rate {page_normal_dedup_hit}/{page_normal_count} "
                        f">{self.dedup_stop_ratio:.0%} on page {page_num}"
                    )
                    break

            page_num += 1
            await asyncio.sleep(self.request_delay)

        if stop_reason:
            logger.info(f"[batdongsan] Early-stop ({start_url}): {stop_reason}")

        # Drop any leaked non-today cards (defensive)
        before = len(listings)
        listings = [l for l in listings if l.posted_at is None or self._is_posted_today(l.posted_at)]
        if len(listings) < before:
            logger.info(f"[batdongsan] Filtered {before - len(listings)} non-today listings")

        logger.info(
            f"[batdongsan] {start_url}: {len(listings)} listings, "
            f"{len(pro_agent_listings)} pro-agent, VIP={vip_count}"
        )
        return listings, pro_agent_listings

    # ────────────────────────── LIST CARD PARSING ──────────────────────────

    def _parse_list_card(self, card: Any) -> tuple[RawListing | None, str]:
        """
        Parse list card. Returns (listing, skip_reason).
        v4: Parse VIP cards (tag is_vip=True). Skip pro-agent cards.
        """
        try:
            card_cls = card.attrib.get("class", "")

            # Detect VIP tier — parsed bình thường, early-stop logic ở fetch_listings
            is_vip = any(m in card_cls for m in _VIP_TIER_MARKERS)

            # Pro-agent badge: class-based only (không check text — false positive)
            card_html = card.html_content or ""
            has_pro_agent = any(m in card_cls for m in _PRO_AGENT_MARKERS)

            def _css(sel: str) -> Any:
                els = card.css(sel)
                return els[0] if els else None

            source_id = card.attrib.get("prid", "")
            link_el = _css("a.js__product-link-for-product-id")
            if not link_el:
                return None, ""
            title_el = _css(".js__card-title")
            title = (title_el.text.strip() if title_el else "") or link_el.attrib.get("title", "")
            if not title or not source_id:
                return None, ""

            href = link_el.attrib.get("href", "")
            source_url = urljoin(BASE_URL, href) if href else ""

            # Pro-agent: return minimal listing for DB save — no detail fetch, no alert
            if has_pro_agent:
                date_el = _css(".re__card-published-info-published-at")
                date_text = date_el.get_all_text(strip=True) if date_el else ""
                return RawListing(
                    source="batdongsan",
                    source_id=source_id,
                    source_url=source_url,
                    title=title,
                    description="",
                    address="",
                    district="",
                    posted_at=self._parse_relative_time(date_text),
                    has_pro_agent_badge=True,
                    is_vip=is_vip,
                ), "pro_agent"

            price_el = _css(".re__card-config-price")
            price_text = price_el.text.strip() if price_el else ""
            price_vnd = self._parse_price(price_text)

            area_el = _css(".re__card-config-area")
            area_m2 = self._parse_area(area_el.text.strip() if area_el else "")

            loc_el = _css(".re__card-location")
            address_raw = ""
            if loc_el:
                for span in loc_el.css("span"):
                    cls = span.attrib.get("class", "")
                    if "re__card-config-dot" in cls:
                        continue
                    t = span.text.strip()
                    if t:
                        address_raw = t
                        break
            district_raw = self._extract_district(address_raw)

            # Description snippet (may not exist on all cards)
            desc_el = _css(".re__card-description")
            description = desc_el.text.strip() if desc_el else ""

            floor_level = self._extract_floor(title, description)

            images: list[str] = []
            img_el = _css(".pr-img")
            if img_el:
                src = img_el.attrib.get("src", "") or img_el.attrib.get("data-src", "")
                if src:
                    images.append(src)

            date_el = _css(".re__card-published-info-published-at")
            # Time element may be wrapped — get recursive text so nested "Đăng hôm nay" surfaces.
            date_text = date_el.get_all_text(strip=True) if date_el else ""
            posted_at = self._parse_relative_time(date_text)

            listing = RawListing(
                source="batdongsan",
                source_id=source_id,
                source_url=source_url,
                title=title,
                description=description,  # will be replaced by detail-page description
                address=address_raw,
                district=district_raw,
                area_m2=area_m2,
                floor_level=floor_level,
                price_vnd_monthly=price_vnd,
                price_text=price_text,
                phone="",
                contact_name=None,
                images=images,
                posted_at=posted_at,
                has_pro_agent_badge=has_pro_agent,
                is_vip=is_vip,
            )
            return listing, ""

        except Exception as e:
            logger.error(f"[batdongsan] _parse_list_card error: {e}")
            return None, ""

    # Backward-compat: keep parse_listing() for any callers expecting the old API.
    def parse_listing(self, card: Any) -> RawListing | None:
        listing, _ = self._parse_list_card(card)
        return listing

    # ────────────────────────── DETAIL ENRICHMENT ──────────────────────────

    async def _enrich_from_detail(self, listing: RawListing, loop: Any) -> None:
        """Fetch detail page → extract contact, description, active count, profile hash."""
        if not listing.source_url:
            return
        # Retry logic for Cloudflare
        max_retries = 2
        for attempt in range(max_retries):
            page = await self._stealth_fetch(listing.source_url, loop, wait=5000 if attempt > 0 else 3000)
            if page is None:
                continue
            html = page.html_content or ""
            if "Checking your browser" in html or "Just a moment" in html:
                logger.warning(f"[batdongsan] Cloudflare on detail {listing.source_id} (attempt {attempt+1})")
                await asyncio.sleep(2)
                continue
            break
        else:
            # All retries failed
            logger.error(f"[batdongsan] Detail enrichment failed for {listing.source_id} due to Cloudflare")
            listing.poster_total_listings = -1 # Sentinel for "failed to enrich"
            return

        # Phone: BDS không embed số điện thoại trong HTML — chỉ có encrypted `raw`
        # attribute dùng để gọi DecryptPhone API (đã bỏ). listing.phone luôn rỗng.

        # Contact name
        for sel in (".re__contact-name", ".re__agent-name", ".js__contact-name"):
            els = page.css(sel)
            if els:
                t = els[0].text.strip() if els[0].text else ""
                if t:
                    listing.contact_name = t
                    break

        # Full description
        desc_text = ""
        for sel in (
            ".re__section.re__pr-description .re__section-body",
            ".re__detail-content",
            ".re__pr-description .re__section-body",
        ):
            els = page.css(sel)
            if els:
                desc_text = els[0].get_all_text(separator="\n", strip=True)
                if desc_text:
                    break
        if desc_text:
            listing.description = desc_text
            import hashlib
            listing.content_hash = hashlib.sha256(
                f"{listing.title}|{listing.description[:100]}".encode()
            ).hexdigest()

        # Profile hash from guru link (kept for reference, no longer fetched)
        m_guru = re.search(
            r'href="[^"]*guru\.batdongsan\.com\.vn/pa/([^"?#]+)',
            html,
        )
        if m_guru:
            listing.poster_profile_hash = m_guru.group(1)

        # Active listing count — try sidebar "Tin đăng đang có X" first (reliable,
        # rendered in static HTML contact card). Fall back to "Xem thêm X tin khác"
        # button (JS-rendered, may be absent). Default 1 = only this listing.
        m_active = re.search(r'Tin\s+đăng\s+đang\s+có[^0-9]*(\d+)', html, re.IGNORECASE)
        if m_active:
            listing.poster_total_listings = int(m_active.group(1))
        else:
            m_more = re.search(r'Xem thêm\s+(\d+)\s+tin khác', html, re.IGNORECASE)
            listing.poster_total_listings = int(m_more.group(1)) + 1 if m_more else 1

    # ────────────────────────── GURU PROFILE (lazy) ──────────────────────────

    async def enrich_from_profile(self, listing: RawListing) -> bool:
        """
        Called by orchestrator for listings in the classifier uncertainty window.
        Fetches guru profile page → populates poster_total_listings +
        poster_join_year. Returns True iff parse succeeded.
        """
        if not listing.poster_profile_hash:
            return False
        if self._fetch_impl is None:
            try:
                from scrapling import StealthyFetcher
                self._fetch_impl = StealthyFetcher.fetch
            except ImportError:
                return False

        url = f"{GURU_BASE}/pa/{listing.poster_profile_hash}"
        loop = asyncio.get_running_loop()
        try:
            page = await self._stealth_fetch(url, loop)
        except Exception as e:
            logger.warning(f"[batdongsan] profile fetch error {listing.poster_profile_hash}: {e}")
            return False
        if page is None:
            return False
        html = page.html_content or ""
        if "Checking your browser" in html or "Just a moment" in html:
            logger.warning(f"[batdongsan] Cloudflare on profile {listing.poster_profile_hash}")
            return False

        # "Tin đăng đang có" → integer in sibling <p>
        m_active = re.search(
            r'Tin\s*đăng[^<]*đang\s*có[^<]*</span>\s*</p>\s*<p[^>]*>\s*(\d+)\s*</p>',
            html,
            flags=re.IGNORECASE,
        )
        if m_active:
            listing.poster_total_listings = int(m_active.group(1))

        # "Tham gia Batdongsan.com.vn" → "N năm" → absolute year
        m_join = re.search(
            r'Tham\s*gia[^<]*Batdongsan[^<]*</span>\s*</p>\s*<p[^>]*>\s*(\d+)\s*n[aă]m',
            html,
            flags=re.IGNORECASE,
        )
        if m_join:
            years_ago = int(m_join.group(1))
            listing.poster_join_year = datetime.now(_VN_TZ).year - years_ago

        return bool(m_active or m_join)

    # ────────────────────────── HELPERS ──────────────────────────

    async def _stealth_fetch(self, url: str, loop: Any, wait: int = 3000) -> Any:
        # wait: đủ để BDS render static HTML (contact_name, poster_total_listings).
        # network_idle=True giúp bot trông giống người thật hơn, tránh bị Cloudflare bắt.
        kwargs: dict = dict(wait=wait, timeout=60000, network_idle=True)
        fn = self._fetch_impl
        return await loop.run_in_executor(None, lambda: fn(url, **kwargs))

    def _page_url(self, start_url: str, page_num: int) -> str:
        if "?" in start_url:
            base, query = start_url.split("?", 1)
        else:
            base, query = start_url, ""
        base_url = f"{base}/p{page_num}" if page_num > 1 else base
        return f"{base_url}?{query}" if query else base_url

    def _parse_price(self, text: str) -> int | None:
        if not text:
            return None
        t = text.lower().replace(",", ".").replace("\xa0", "").replace(" ", "")
        match = re.search(r"(\d+(?:\.\d+)?)", t)
        if not match:
            return None
        num = float(match.group(1))
        if "tỷ" in t:
            return int(num * 1_000_000_000)
        if "triệu" in t or "tr" in t:
            return int(num * 1_000_000)
        if "nghìn" in t:
            return int(num * 1_000)
        return int(num)

    def _parse_area(self, text: str) -> float | None:
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text.lower())
        if match:
            return float(match.group(1).replace(",", "."))
        return None

    def _extract_district(self, address: str) -> str:
        match = re.search(r"Qu[aậ]n\s+\w+|Q\.\s*\d+|Q\d+", address)
        return match.group(0) if match else address.split(",")[-1].strip()

    def _extract_floor(self, title: str, description: str) -> int | None:
        text = f"{title} {description}".lower()
        patterns = [
            (r"tầng\s*trệt|trệt|tầng\s*1\b", 1),
            (r"lầu\s*1\b", 2),
            (r"lầu\s*2\b|tầng\s*3\b", 3),
            (r"lầu\s*3\b|tầng\s*4\b", 4),
            (r"tầng\s*2\b", 2),
        ]
        for pattern, floor in patterns:
            if re.search(pattern, text):
                return floor
        return None

    def _parse_relative_time(self, text: str) -> datetime | None:
        """
        Parse BDS relative time text into absolute datetime (UTC).
        Handles: 'Đăng hôm nay', 'Đăng hôm qua', 'Đăng N phút/giờ/ngày trước',
        and 'DD/MM/YYYY' fallback.
        Unparseable → None (early-stop treats None as "not today").
        """
        now_vn = datetime.now(_VN_TZ)
        t = (text or "").lower().strip()
        if not t:
            return None
        try:
            if "hôm nay" in t:
                today_noon = now_vn.replace(hour=12, minute=0, second=0, microsecond=0)
                return today_noon.astimezone(timezone.utc)
            if "hôm qua" in t:
                yday = (now_vn - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
                return yday.astimezone(timezone.utc)
            if "phút" in t:
                m = re.search(r"(\d+)", t)
                if m:
                    return (now_vn - timedelta(minutes=int(m.group(1)))).astimezone(timezone.utc)
            if "giờ" in t:
                m = re.search(r"(\d+)", t)
                if m:
                    return (now_vn - timedelta(hours=int(m.group(1)))).astimezone(timezone.utc)
            if "ngày" in t:
                m = re.search(r"(\d+)", t)
                if m:
                    return (now_vn - timedelta(days=int(m.group(1)))).astimezone(timezone.utc)
            if "/" in t:
                from dateutil import parser as dp
                return dp.parse(t, dayfirst=True).replace(tzinfo=_VN_TZ).astimezone(timezone.utc)
        except Exception:
            pass
        return None

    def _is_posted_today(self, posted_at: datetime) -> bool:
        """True iff posted_at falls on the current date in Asia/Ho_Chi_Minh TZ."""
        if posted_at is None:
            return False
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        return posted_at.astimezone(_VN_TZ).date() == datetime.now(_VN_TZ).date()

    def _clean_phone(self, phone: str) -> str:
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("84") and len(digits) == 11:
            digits = "0" + digits[2:]
        return digits if len(digits) == 10 else ""
