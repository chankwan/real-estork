"""
RealEstork — Facebook Groups spider (DRAIN model).

Spider này KHÔNG kéo web. Userscript Tampermonkey (chạy trên Chrome profile
riêng, login via FB) POST post từ 9 group đóng về ingest.fb_receiver (localhost).
Mỗi nhịp lịch, spider rút hàng đợi, parse text tự do (SĐT / quận / giá / diện
tích / tầng) thành RawListing chuẩn → pipeline dedup → classify → telegram.

Post FB là text tự do nên parse là "best-effort": thiếu quận/giá thì để trống,
classifier vẫn xử lý (tín hiệu SĐT-trùng-môi-giới cross-platform vẫn hoạt động).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from ingest.fb_receiver import drain
from spiders.base import BaseSpider, RawListing


# Quận đặt tên — match dạng có dấu lẫn không dấu. Đặt cụm cụ thể trước.
_NAMED_DISTRICTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"th[ủu]\s*đ[ứu]c", re.I), "Thủ Đức"),
    (re.compile(r"b[ìi]nh\s*th[ạa]nh", re.I), "Bình Thạnh"),
    (re.compile(r"ph[úu]\s*nhu[ậa]n", re.I), "Phú Nhuận"),
    (re.compile(r"t[âa]n\s*b[ìi]nh", re.I), "Tân Bình"),
    (re.compile(r"t[âa]n\s*ph[úu]", re.I), "Tân Phú"),
    (re.compile(r"b[ìi]nh\s*t[âa]n", re.I), "Bình Tân"),
    (re.compile(r"g[òo]\s*v[ấa]p", re.I), "Gò Vấp"),
    (re.compile(r"b[ìi]nh\s*ch[áa]nh", re.I), "Bình Chánh"),
    (re.compile(r"nh[àa]\s*b[èe]", re.I), "Nhà Bè"),
    (re.compile(r"h[óo]c\s*m[ôo]n", re.I), "Hóc Môn"),
    (re.compile(r"c[ủu]\s*chi", re.I), "Củ Chi"),
]
# "Quận 1".."Quận 12" / "Q1" / "Q.3" / "quan 7"
_QUAN_NUM = re.compile(r"\b(?:qu[ậa]n|q)\s*\.?\s*(1[0-2]|[1-9])\b", re.I)

# SĐT VN trong text tự do: +84/0 + cụm số có thể chèn space/dot/dash
_PHONE_CANDIDATE = re.compile(r"(?:\+?84|0)[\d.\-\s]{8,13}\d")

# Giá: số + đơn vị (triệu/tr/củ → triệu, tỷ/tỉ/ty → tỷ)
_PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(t[ỷỉy]|tri[ệe]u|tr|c[ủu])\b", re.I)
_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*2|(\d+(?:[.,]\d+)?)\s*m²", re.I)
# Kích thước "ngang × dài" → diện tích = tích 2 cạnh. VD "8.3m x 21m", "20x19m",
# "4 x 11m", "3mx9m". FB hay ghi kiểu này thay vì "N m2".
_DIM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m?\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*m", re.I)
# Nhãn UI FB dính cuối text sau khi userscript expand (See less / Thu gọn) hoặc cụt (See more).
_UI_TAIL_RE = re.compile(r"\s*[….]*\s*(See less|See more|Thu g[ọo]n|Xem thêm)\s*$", re.I)

_FLOOR_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"t[ầa]ng\s*tr[ệe]t|tr[ệe]t", re.I), 1),
    (re.compile(r"l[ầa]u\s*1\b|l[ầa]u\s*m[ộo]t", re.I), 2),
    (re.compile(r"l[ầa]u\s*2\b", re.I), 3),
    (re.compile(r"l[ầa]u\s*3\b", re.I), 4),
    (re.compile(r"t[ầa]ng\s*2\b", re.I), 2),
    (re.compile(r"t[ầa]ng\s*3\b", re.I), 3),
]


# Trục 1 — Ý ĐỊNH (§10.2, §10.5). Dùng để routing 2 topic, KHÔNG dính score.
# Ưu tiên OFFER: "cho thuê" / owner tìm khách → chủ nhà (kể cả có chữ "cần").
_OFFER_KW = [
    "cho thuê", "cho thue", "chính chủ cho thuê", "cần cho thuê",
    "cho thuê nhà", "cho thuê mặt bằng", "cho thuê phòng", "cho thuê căn",
    "cho thuê kho", "cho thuê xưởng", "mặt bằng cho thuê",
    # Chủ nhà tìm khách = vẫn là OFFER (đang có nhà để cho thuê)
    "khách thuê", "tìm khách", "cần khách", "tìm người thuê",
]
_SEEK_KW = [
    "cần thuê", "can thue", "cần tìm thuê", "tìm thuê", "cần thuê nhà",
    "cần thuê mặt bằng", "cần thuê phòng", "cần tìm nhà", "cần tìm mặt bằng",
    "cần tìm phòng", "cần tìm chỗ", "cần mặt bằng", "cần 1 mặt bằng",
    "đang cần thuê", "muốn thuê",
]


def detect_fb_intent(text: str) -> str:
    """Phân loại ý định post FB → 'offer' (chủ) / 'seek' (khách) / 'unknown'.
    Luật ưu tiên (§10.5.2): có tín hiệu OFFER → offer (dù có 'cần').
    Chỉ SEEK khi có seek-kw mà KHÔNG có offer-kw. Còn lại 'unknown' (không route)."""
    t = (text or "").lower()
    if any(k in t for k in _OFFER_KW):
        return "offer"
    if any(k in t for k in _SEEK_KW):
        return "seek"
    return "unknown"


class FacebookGroupsSpider(BaseSpider):
    name = "facebook_groups"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.groups = config.get("groups", [])

    async def fetch_listings(self) -> list[RawListing]:
        raw_posts = drain()
        if not raw_posts:
            return []

        listings: list[RawListing] = []
        for rp in raw_posts:
            try:
                parsed = self.parse_listing(rp)
            except Exception as e:
                logger.warning(f"[facebook_groups] parse error: {type(e).__name__}: {e}")
                parsed = None
            if parsed is not None:
                listings.append(parsed)

        # Post-process: đếm số tin cùng poster trong batch (broker đăng nhiều mặt bằng).
        counts: dict[str, int] = {}
        for lst in listings:
            key = lst.poster_account_id or (lst.contact_name or "").strip().lower()
            if key:
                counts[key] = counts.get(key, 0) + 1
        for lst in listings:
            key = lst.poster_account_id or (lst.contact_name or "").strip().lower()
            if key:
                lst.same_session_account_count = counts[key]

        logger.info(
            f"[facebook_groups] drained {len(raw_posts)} posts → {len(listings)} listings"
        )
        return listings

    def parse_listing(self, raw: Any) -> RawListing | None:
        if not isinstance(raw, dict):
            return None
        text = _UI_TAIL_RE.sub("", (raw.get("text") or "").strip()).strip()
        permalink = (raw.get("permalink") or raw.get("url") or "").strip()
        group_id = str(raw.get("group_id") or "").strip()

        post_id = str(raw.get("post_id") or raw.get("id") or "").strip()
        if not post_id:
            basis = permalink or text
            if not basis:
                return None
            post_id = "fb_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]
        if not text and not permalink:
            return None

        author_id = raw.get("author_id")
        title = text.split("\n", 1)[0][:120] if text else (raw.get("group_name") or "FB post")

        return RawListing(
            source="facebook_groups",
            source_id=post_id,
            source_url=permalink or (f"https://www.facebook.com/groups/{group_id}" if group_id else ""),
            title=title,
            description=text,
            address="",  # FB không có address chuẩn — để classifier dựa district + text
            district=self._extract_district(text),
            area_m2=self._parse_area(text),
            floor_level=self._extract_floor(text),
            price_vnd_monthly=self._parse_price(text),
            price_text="",
            phone=self._extract_phone(text),
            contact_name=(raw.get("author_name") or None),
            poster_account_id=(str(author_id) if author_id else None),
            images=list(raw.get("images") or []),
            posted_at=self._parse_created(raw.get("created_time")),
        )

    # ── text parsers (best-effort) ─────────────────────────────────────────

    def _extract_phone(self, text: str) -> str:
        # Lazy import: pipeline.dedup imports spiders.base → tránh circular import
        # khi spiders package được load qua pipeline.dedup.
        from pipeline.dedup import normalize_phone

        for m in _PHONE_CANDIDATE.finditer(text):
            norm = normalize_phone(m.group(0))
            if norm:
                return norm
        return ""

    def _extract_district(self, text: str) -> str:
        for pattern, name in _NAMED_DISTRICTS:
            if pattern.search(text):
                return name
        m = _QUAN_NUM.search(text)
        if m:
            return f"Quận {m.group(1)}"
        return ""

    def _parse_price(self, text: str) -> int | None:
        m = _PRICE_RE.search(text)
        if not m:
            return None
        num = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        if unit.startswith("t") and unit not in ("tr",) and "ri" not in unit:
            # tỷ / tỉ / ty
            return int(num * 1_000_000_000)
        # tr / triệu / củ
        return int(num * 1_000_000)

    def _parse_area(self, text: str) -> float | None:
        # Ưu tiên diện tích ghi thẳng "N m2" / "N m²"
        m = _AREA_RE.search(text)
        if m:
            val = m.group(1) or m.group(2)
            try:
                return float(val.replace(",", "."))
            except (ValueError, AttributeError):
                pass
        # Fallback: kích thước ngang×dài → diện tích = tích. Guard cạnh hợp lý để
        # tránh bắt nhầm ("1 x 2 phòng"...).
        m = _DIM_RE.search(text)
        if m:
            try:
                w = float(m.group(1).replace(",", "."))
                length = float(m.group(2).replace(",", "."))
                if 1 <= w <= 100 and 1 <= length <= 200:
                    return round(w * length, 1)
            except (ValueError, AttributeError):
                pass
        return None

    def _extract_floor(self, text: str) -> int | None:
        for pattern, floor in _FLOOR_PATTERNS:
            if pattern.search(text):
                return floor
        return None

    def _parse_created(self, raw_ts: Any) -> datetime | None:
        """Accept epoch seconds (FB utime) hoặc ISO string. None nếu không có/parse fail."""
        if raw_ts is None or raw_ts == "":
            return None
        # Epoch seconds
        if isinstance(raw_ts, (int, float)) or (isinstance(raw_ts, str) and raw_ts.isdigit()):
            try:
                return datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                return None
        # ISO string
        try:
            dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
