"""
RealEstork — OSINT Phone Lookup Pipeline
Module 3 (M3)

Priority:
1. Internal DB Check (always, no bypass needed)
2. Google Search (SerpAPI free tier or scrape)
3. Trangtrang.com (HTTP scraping)
4. Zalo Profile (DynamicFetcher + proxy/antidetect)
5. Truecaller (StealthyFetcher + proxy)
6. dangkykinhdoanh.gov.vn (Phase 1.5)

Fallback: If external OSINT fails → system still works with Internal DB alone.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import httpx
from loguru import logger


class OSINTLookup:
    """
    OSINT pipeline for phone numbers.
    Returns dict with all available context for alert messages.
    """

    def __init__(self) -> None:
        self.serpapi_key = os.environ.get("SERPAPI_KEY", "")
        self.proxy_url = os.environ.get("WEBSHARE_PROXY_URL", "")  # Optional

    async def lookup(self, phone: str, db_client: Any = None) -> dict[str, Any]:
        """
        Run all OSINT lookups for a phone number.
        Returns dict with results. Partial results OK — external failures are non-blocking.
        """
        if not phone or len(phone) < 9:
            return {}

        result: dict[str, Any] = {"phone": phone}

        # Step 4: Internal DB Check (PRIORITY — always first, no rate limit)
        if db_client:
            try:
                phone_stats = db_client.get_phone_stats(phone)
                result["internal_listing_count"] = phone_stats.get("total_listings", 0)
                result["internal_platforms"] = phone_stats.get("platforms", [])
                result["is_known_broker"] = phone_stats.get("is_known_broker", False)
                if result["is_known_broker"]:
                    result["broker_company"] = phone_stats.get("broker_company", "")
                logger.debug(f"[osint] Internal DB: {phone} found {result['internal_listing_count']} times")
            except Exception as e:
                logger.warning(f"[osint] Internal DB check failed: {e}")

        # Run external lookups concurrently (with error isolation)
        tasks = [
            self._google_search(phone),
            self._trangtrang_lookup(phone),
        ]
        google_result, trangtrang_result = await asyncio.gather(
            *tasks, return_exceptions=True
        )

        if isinstance(google_result, dict):
            result.update(google_result)
        if isinstance(trangtrang_result, dict):
            result.update(trangtrang_result)

        # Zalo and Truecaller are more aggressive — run sequentially with delay
        # Only if we have time budget (not blocking critical path)
        try:
            zalo_result = await asyncio.wait_for(
                self._zalo_lookup(phone), timeout=10.0
            )
            if isinstance(zalo_result, dict):
                result.update(zalo_result)
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"[osint] Zalo lookup skipped: {e}")

        logger.info(f"[osint] Lookup complete for {phone}: {list(result.keys())}")
        return result

    async def _google_search(self, phone: str) -> dict:
        """
        Google search for phone number.
        Uses SerpAPI free tier (100/month) or direct scrape.
        """
        result = {}
        try:
            if self.serpapi_key:
                # SerpAPI (more reliable, free 100/month)
                params = {
                    "q": f'"{phone}"',
                    "api_key": self.serpapi_key,
                    "num": 10,
                    "gl": "vn",
                    "hl": "vi",
                }
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://serpapi.com/search", params=params
                    )
                    data = resp.json()
                    organic = data.get("organic_results", [])
                    result["google_result_count"] = len(organic)
                    if organic:
                        result["google_top_url"] = organic[0].get("link", "")
                        result["google_snippet"] = organic[0].get("snippet", "")
            else:
                # Fallback: simple HTTP to Google (may get CAPTCHA)
                async with httpx.AsyncClient(
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(
                        f'https://www.google.com/search?q="{phone}"&num=10'
                    )
                    # Count result snippets (rough estimate)
                    count = resp.text.count('"g"') // 5  # Very rough
                    result["google_result_count"] = min(count, 100)

        except Exception as e:
            logger.debug(f"[osint] Google search failed for {phone}: {e}")

        return result

    async def _trangtrang_lookup(self, phone: str) -> dict:
        """
        Check trangtrang.com spam/scam database (SSR — plain HTTP, no JS needed).
        URL pattern: https://trangtrang.com/{phone}.html
        Returns: danger_score (0-10), report_count, categories (list), is_spam (bool|None)
        """
        result = {}
        try:
            url = f"https://trangtrang.com/{phone}.html"
            async with httpx.AsyncClient(
                timeout=10,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "vi-VN,vi;q=0.9",
                    "Referer": "https://trangtrang.com/",
                },
            ) as client:
                resp = await client.get(url, follow_redirects=True)

            if resp.status_code == 404:
                # Phone not in DB — neutral signal (no reports)
                result["trangtrang_found"] = False
                return result

            if resp.status_code != 200:
                logger.debug(f"[osint] trangtrang HTTP {resp.status_code} for {phone}")
                return result

            html = resp.text
            html_lower = html.lower()
            result["trangtrang_found"] = True

            # Danger score: "Điểm: 7.5/10" or "Điểm: 8/10"
            score_match = re.search(r"[Đđ]i[eê]m[:\s]+(\d+(?:[.,]\d+)?)\s*/\s*10", html)
            if score_match:
                result["trangtrang_score"] = float(score_match.group(1).replace(",", "."))

            # Report count: "2 nhận xét" or "15 nhận xét đã duyệt"
            count_match = re.search(r"(\d+)\s*nh[aậ]n\s*x[eé]t", html_lower)
            if count_match:
                result["trangtrang_report_count"] = int(count_match.group(1))

            # Severity label: "Nghiêm trọng", "Nguy hiểm", "Đang theo dõi", "An toàn"
            severity = None
            if "nghiêm trọng" in html_lower or "nghi[eê]m tr[oọ]ng" in html_lower:
                severity = "critical"
            elif "nguy hiểm" in html_lower:
                severity = "dangerous"
            elif "đang theo dõi" in html_lower:
                severity = "monitoring"
            elif "an toàn" in html_lower or "đáng tin" in html_lower:
                severity = "safe"
            if severity:
                result["trangtrang_severity"] = severity

            # Spam categories present in page
            categories = []
            category_map = {
                "lừa đảo": "scam",
                "làm phiền": "harassment",
                "quảng cáo": "ads",
                "môi giới": "broker",
                "bất động sản": "realestate",
                "tín dụng": "loan",
                "bảo hiểm": "insurance",
            }
            for vn_kw, en_tag in category_map.items():
                if vn_kw in html_lower:
                    categories.append(en_tag)
            if categories:
                result["trangtrang_categories"] = categories

            # Composite spam flag
            score = result.get("trangtrang_score", 0)
            is_spam = (
                score >= 5.0
                or severity in ("critical", "dangerous")
                or "scam" in categories
                or result.get("trangtrang_report_count", 0) >= 3
            )
            result["trangtrang_spam"] = is_spam if result.get("trangtrang_score") or result.get("trangtrang_report_count") else None

            logger.debug(
                f"[osint] trangtrang {phone}: score={result.get('trangtrang_score')}, "
                f"reports={result.get('trangtrang_report_count')}, severity={severity}, "
                f"cats={categories}"
            )

        except Exception as e:
            logger.debug(f"[osint] trangtrang lookup failed for {phone}: {e}")

        return result

    async def _zalo_lookup(self, phone: str) -> dict:
        """
        Look up Zalo profile for phone number.
        Uses DynamicFetcher (Scrapling). With proxy if configured.
        Antidetect: max 20 lookups per session, rotate IP.

        Note: This is best-effort. Zalo lookup may be blocked.
        Circuit breaker: fails silently → OSINT still returns other signals.
        """
        result = {}
        try:
            # Try Zalo web API approach first (simpler)
            # POST to Zalo "find friend" endpoint with phone
            # This may require a valid Zalo session cookie
            # For MVP: return empty dict, implement properly in Phase 1.5
            # when antidetect browser (GoLogin/AdsPower) is set up
            logger.debug(f"[osint] Zalo lookup not yet implemented (Phase 1.5)")

            # Placeholder for when implemented:
            # result["zalo_name"] = ...
            # result["zalo_is_business"] = ...
            # result["zalo_avatar_url"] = ...

        except Exception as e:
            logger.debug(f"[osint] Zalo lookup failed: {e}")

        return result

    async def _truecaller_lookup(self, phone: str) -> dict:
        """
        Truecaller lookup — Phase 1.5 with proxy/antidetect.
        Circuit breaker: fails silently.
        """
        return {}  # Implement in Phase 1.5 with proper bypass strategy
