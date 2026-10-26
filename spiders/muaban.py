"""
RealEstork — Muaban Spider (muaban.net)
Module 1 (M1) — curl_cffi Firefox133 (no browser needed)

Cloudflare bypass: curl_cffi Firefox133 TLS impersonation — verified 22/04/2026.
httpx plain → 403. StealthyFetcher (camoufox) → works but overkill.

Crawl strategy (v4 — 08/09/2026):
  Stage 1 — List pages (curl_cffi, 1 shared AsyncSession):
    - Parse __NEXT_DATA__ JSON, 20 items/page
    - Tin trả phí (service_ids ∩ {16,8,4,2}): skip nếu > 24h, keep nếu trong 24h
    - Tin thường (service_id 128): early-stop khi gặp tin đầu tiên không phải hôm nay
    - Dedup ratio early-stop: >70% tin thường đã seen → stop
  Stage 2 — Detail pages (curl_cffi, concurrent sem=3):
    - contact_name (từ classified JSON)
    - Full description (body HTML → plain text)

Không lấy SĐT: muaban dựng Cloudflare Turnstile ở nút "Hiện số" từ 21/08/2026.
Xem ghi chú trong class.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

from loguru import logger

from spiders.base import BaseSpider, RawListing, bo_tin_trung

BASE_URL = "https://muaban.net"
# Gói tin trả phí. Đối chiếu service_display trên trang chi tiết (2026-09-08):
#   16 = "Nổi bật", 8 = "VIP S", 4 = "VIP 1", 2 = "VIP 2", 128 = "Tin thường".
# Trước đây bộ này ghi {16, 8, 4, 128} — tức xếp "Tin thường" (miễn phí, chiếm đa
# số) vào nhóm trả phí và bỏ sót "VIP 2". Hậu quả: tin thường đi vào nhánh VIP nên
# không bao giờ được đếm vào page_normal_count, khiến cả hai điều kiện dừng sớm
# không đủ dữ liệu để kích hoạt → mỗi vòng cày hết 50 trang × 3 danh mục.
_VIP_SERVICE_IDS = {16, 8, 4, 2}
_VN_TZ = timezone(timedelta(hours=7))
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Luot quet nua dem cua muaban chay trong khung 00:00-00:06 gio VN (do 2 dem
# 17-19/09: 161/164 tin bi doi dau nam trong khung nay). Lay bien 10 phut cho
# rong — luot quet co the cham hon khi san dong tin.
_PHUT_CUOI_LUOT_QUET = 10

_CURL_HEADERS = {"Referer": "https://www.google.com/"}


class MuabanSpider(BaseSpider):
    """Spider for muaban.net — curl_cffi Firefox133, no browser required."""

    name = "muaban"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        _default_url = (
            "https://muaban.net/bat-dong-san/cho-thue-van-phong-mat-bang-ho-chi-minh"
            "?sort=1&price=15000000-100000000"
        )
        urls_cfg = config.get("urls", None)
        if urls_cfg:
            self.start_urls: list[str] = [u.strip() for u in urls_cfg if u and u.strip()]
        else:
            self.start_urls = [config.get("url", _default_url)]
        self.start_url = self.start_urls[0]  # giữ cho compat nếu có chỗ khác tham chiếu
        self.dedup_stop_ratio: float = float(config.get("dedup_stop_ratio", 0.7))
        self.detail_concurrency: int = int(config.get("detail_concurrency", 3))
        self.cycle_health: dict[str, int] = {}

    # Phone reveal: BỎ HẲN (2026-09-08).
    # Muaban dựng Cloudflare Turnstile ở nút "Hiện số" từ 21/08 — số cuối cùng lấy
    # được là 21/08, sau đó 0/1559 tin. Số cũ nằm sẵn trong nội dung tin (data-phone)
    # đã bị gỡ, endpoint /api/v1/classifieds/{id}/phone trả 404 (không phải 401/403,
    # nên KHÔNG phải chuyện hết đăng nhập — spider này chưa từng đăng nhập). Lấy lại
    # được thì phải mở trình duyệt thật giải captcha từng tin, quá đắt so với giá trị:
    # vợ vẫn mở link xem số khi thấy tin ưng. Nhóm signal theo SĐT cũng đã tắt.

    # ─── Stage 1: List page crawl ──────────────────────────────────────────

    async def fetch_listings(self) -> list[RawListing]:
        from curl_cffi.requests import AsyncSession

        all_listings: list[RawListing] = []
        self.cycle_health = {}

        async with AsyncSession() as session:
            for idx, start_url in enumerate(self.start_urls):
                url_listings = await self._fetch_pages_from(session, start_url)
                all_listings.extend(url_listings)
                if idx < len(self.start_urls) - 1:
                    await asyncio.sleep(self.request_delay)

        all_listings = bo_tin_trung(all_listings)

        # Post-process: same-session account count (uses user_id as key) — global across URLs.
        from collections import Counter
        id_counts: Counter = Counter(
            l.poster_profile_hash for l in all_listings if l.poster_profile_hash
        )
        for listing in all_listings:
            if listing.poster_profile_hash:
                listing.same_session_account_count = id_counts[listing.poster_profile_hash]

        logger.info(
            f"[muaban] Stage 1 done: {len(all_listings)} listings "
            f"từ {len(self.start_urls)} URL(s)"
        )

        # ── Stage 2: Batch detail enrichment (global across all URLs) ──
        if all_listings:
            await self._enrich_details_batch(all_listings)

        return all_listings

    async def _fetch_pages_from(self, session, start_url: str) -> list[RawListing]:
        """Crawl list pages for a single start_url. Returns listings collected.

        Early-stop logic (non-today, dedup ratio) applies per-URL — non-today on
        URL A does not stop URL B. Dedup state (self.seen_ids) stays global so the
        same listing surfacing in two categories is detected, but doesn't stop the
        crawl of a different category.
        """
        slug = start_url.split("/")[-1].split("?")[0]
        listings: list[RawListing] = []
        page_num = 1
        stop_reason = ""
        prev_page_ids: set[str] | None = None

        while page_num <= self.max_pages:
            url = self._page_url(start_url, page_num)
            logger.info(f"[muaban:{slug}] Fetching page {page_num}: {url}")

            try:
                resp = await session.get(
                    url,
                    impersonate="firefox133",
                    timeout=20,
                    headers=_CURL_HEADERS,
                )

                if resp.status_code != 200:
                    self.bump_health("list_http_error")
                    logger.warning(f"[muaban:{slug}] Page {page_num}: HTTP {resp.status_code}")
                    break

                html = resp.text
                if "Just a moment" in html or "Checking your browser" in html:
                    self.bump_health("list_cf_blocked")
                    logger.warning(f"[muaban:{slug}] Cloudflare challenge on page {page_num}")
                    break

                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    html,
                    re.DOTALL,
                )
                if not match:
                    self.bump_health("list_no_data")
                    logger.warning(f"[muaban:{slug}] No __NEXT_DATA__ on page {page_num}")
                    break

                data = json.loads(match.group(1))
                items = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("classified", {})
                    .get("items", [])
                )

                if not items:
                    logger.info(f"[muaban:{slug}] No listings on page {page_num}")
                    break

                # ── Chốt chặn "phân trang chết" ───────────────────────────
                # Trang mới trả về ĐÚNG tập ID của trang trước = nền tảng đang
                # bỏ qua tham số phân trang và đưa lại trang mặc định. Không
                # kiểm tra tên tham số (muaban đổi lúc nào không báo) mà kiểm
                # tra KẾT QUẢ — nên lần đổi sau vẫn bắt được.
                #
                # Vì sao lỗi này từng im lặng cả tuần: phản hồi vẫn hợp lệ
                # (HTTP 200, 20 tin, đúng định dạng) nên không nhánh lỗi nào
                # chạm tới. Cơ chế dừng sớm thì thấy "trang 2 trùng 100% trang
                # 1" và dừng — trông y như dừng đúng lúc.
                page_ids = {str(it.get("id")) for it in items if it.get("id")}
                if prev_page_ids is not None and page_ids and page_ids == prev_page_ids:
                    self.bump_health("list_repeat_page")
                    stop_reason = (
                        f"trang {page_num} trùng khít trang {page_num - 1} "
                        f"({len(page_ids)} ID y hệt) — phân trang không còn tác dụng"
                    )
                    logger.warning(f"[muaban:{slug}] {stop_reason}")
                    break
                prev_page_ids = page_ids

                self.bump_health("list_pages_ok")

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

                listings.extend(page_parsed)
                logger.info(
                    f"[muaban:{slug}] Page {page_num}: parsed={len(page_parsed)}, "
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
                logger.error(f"[muaban:{slug}] Error on page {page_num}: {e}")
                break

        if stop_reason:
            logger.info(f"[muaban:{slug}] Early-stop: {stop_reason}")
        logger.info(f"[muaban:{slug}] Done: {len(listings)} listings")
        return listings

    # ─── Stage 2: Detail enrichment ────────────────────────────────────────

    async def _enrich_details_batch(self, listings: list[RawListing]) -> None:
        """Concurrently fetch detail pages for contact_name + mô tả đầy đủ."""
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

        names_ok = sum(1 for l in listings if l.contact_name)
        descs_ok = sum(1 for l in listings if (l.description or "").strip())
        logger.info(f"[muaban] Stage 2 done: {names_ok} names, {descs_ok} mô tả")

    async def _enrich_detail(self, listing: RawListing) -> None:
        """
        Fetch detail page via curl_cffi Firefox133.
        Extracts: contact_name + mô tả đầy đủ (nguồn cho nhóm signal nội dung).
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

            images = item.get("covers", [])

            # ── Dấu thời gian: tách "máy gán" khỏi "người đẩy tay" ──────────
            # publish_at KHÔNG phải ngày đăng gốc, mà là lần đẩy gần nhất.
            # Đo 2 đêm liên tiếp (17-19/09), theo dõi cùng 140 tin qua nửa đêm:
            #   161/164 tin bị đổi dấu rơi vào đúng khung 00:00-00:06 giờ VN
            #   → muaban chạy một lượt đẩy hàng loạt lúc giao ngày.
            # Trang sâu bị quét sạch 60/60; trang 1 chỉ 20/60 — phần còn lại ở
            # trang 1 mang dấu giờ ban ngày, tức có người vừa động vào tin.
            #
            # Đã loại khả năng "giờ ban ngày = tính năng tự đẩy của gói trả
            # phí": trong nhóm mang dấu muộn hơn lượt máy, tin trả phí chỉ
            # chiếm 9% (5/56) — còn lại là tin thường miễn phí, tức có người
            # ngồi bấm tay từng tin.
            #
            # Hai kết luận, hai cách xử lý khác nhau:
            #
            # 1. Dấu trong khung máy quét → KHÔNG BIẾT tuổi tin (đặt None).
            #    Không phải vì tin cũ, mà vì con số đó do máy muaban sinh ra,
            #    không nói gì về tin. Trước đây nó được chấm +10 "tin rất mới"
            #    cho MỌI tin: đo 16/09 thì 13/16 tin gửi đi có điểm đúng bằng
            #    ngưỡng 55 — tức chúng qua được chủ yếu nhờ điểm chấm trên dữ
            #    liệu máy sinh. Cùng loại lỗi với session 24.
            #
            # 2. Dấu ngoài khung máy quét → có người vừa đẩy tin. Ghi lại vào
            #    manually_bumped để scoring dùng. Với mặt bằng cho thuê đây là
            #    tín hiệu đáng giá: chủ lấy lại được mặt bằng thì đẩy tin cũ
            #    lên tìm khách mới.
            posted_at: datetime | None = None
            raw_ts = item.get("publish_at")
            if raw_ts:
                try:
                    posted_at = datetime.fromisoformat(raw_ts)
                except ValueError:
                    pass
            if posted_at is None:
                posted_at = self._parse_relative_time(item.get("publish_display", ""))

            manually_bumped = self._la_day_tay(posted_at)
            if not manually_bumped:
                posted_at = None

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
                manually_bumped=manually_bumped,
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

    def _page_url(self, start_url: str, page_num: int) -> str:
        """Dựng link trang thứ page_num.

        Tham số phân trang là `page`. Trước đây là `cp` — muaban đã bỏ tên đó
        (2026-09, không rõ chính xác ngày; sớm nhất quan sát được trong log là
        08/09). Điểm nguy hiểm: tên cũ KHÔNG gây lỗi gì — muaban trả HTTP 200
        kèm đúng 20 tin đúng định dạng, chỉ là luôn luôn của trang 1. Verify
        live 2026-09-15: cp=2/10/50 trả cùng 3 ID đầu (70946042, 70746888,
        71225315) trong khi danh mục khai 3018 tin; page=2 trả tin khác hẳn và
        xin quá số trang thật thì trả rỗng.

        Hậu quả suốt thời gian hỏng: bot chỉ từng nhìn 20 tin trên cùng mỗi
        danh mục — tầng đó gần như toàn tin trả phí (môi giới). Tin thường bắt
        đầu từ trang 2 (16/20) và trang 3 trở đi (20/20).

        Chốt chặn chống tái diễn nằm ở _fetch_pages_from: trang mới trùng khít
        trang trước → dừng + kêu chuông, KHÔNG phụ thuộc tên tham số.
        """
        if page_num == 1:
            return start_url
        connector = "&" if "?" in start_url else "?"
        return f"{start_url}{connector}page={page_num}"

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

    @staticmethod
    def _la_day_tay(posted_at: datetime | None) -> bool:
        """Dấu thời gian này do NGƯỜI đẩy, hay do lượt quét nửa đêm của muaban?

        Đo 2 đêm: lượt quét chạy trong khung 00:00-00:06 giờ VN (đêm 17/09 hết
        4 phút, đêm 18/09 hết 7 phút). Lấy biên 00:00-00:10 cho rộng — lượt
        quét có thể chạy lâu hơn khi sàn đông tin, còn người bấm đúng 6 phút
        đầu ngày thì hiếm.

        Không đọc được dấu nào → False (chưa biết thì không coi là đẩy tay).
        """
        if posted_at is None:
            return False
        t = posted_at.astimezone(_VN_TZ) if posted_at.tzinfo else posted_at.replace(tzinfo=_VN_TZ)
        trong_luot_quet = t.hour == 0 and t.minute <= _PHUT_CUOI_LUOT_QUET
        return not trong_luot_quet

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
