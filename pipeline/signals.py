"""
RealEstork — Signal Check Functions
Module 2 (M2) — Classification Pipeline

Each function corresponds to a signal in config/scoring.yaml.
Functions receive a SignalContext and return bool or float.

To add a new signal:
1. Add entry in config/scoring.yaml
2. Add function here with matching name
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SignalContext:
    """All data available to signal checkers."""
    # From RawListing
    title: str
    description: str
    phone: str
    floor_level: int | None
    listing_age_hours: float | None
    images: list[str]
    posted_at: Any  # datetime | None
    price_vnd_monthly: int | None

    # From phone frequency analysis (from DB)
    phone_count_all_platforms: int = 0        # Total listings with this phone
    phone_count_max_single_platform: int = 0  # Max on any single platform
    phone_platform_count: int = 0             # How many distinct platforms

    # From broker DB
    phone_is_known_broker: bool = False

    # Phone hidden by seller (not token expire)
    phone_hidden: bool = False                 # True = seller chủ động ẩn SĐT trên nhatot

    # From poster info (if available from platform)
    poster_total_listings: int = 999          # Assume high (unknown) by default
    poster_sold_listings: int = 0             # Historical total posted (0=unknown)
    account_type: str | None = None           # "u"=personal, "s"=business, None=unknown
    contact_name: str = ""                    # Seller display name (for broker keyword check)
    same_session_account_count: int = 1       # How many listings same account posted in this crawl batch

    # Batdongsan-specific (only populated after detail/guru-profile enrichment)
    poster_profile_hash: str | None = None    # Presence → profile fetched (strict guard for BDS signals)
    poster_join_year: int | None = None       # Absolute year the poster joined the platform
    has_pro_agent_badge: bool = False         # Detail/list page carries "Môi giới chuyên nghiệp" badge
    is_vip: bool = False
    avatar_url: str | None = None
    is_main_street: bool | None = None      # True=mặt tiền, False=hẻm, None=unknown

    # Phone spam reputation (from trangtrang DB cache)
    trangtrang_report_count: int = 0        # Number of spam reports on trangtrang.com (0 = unknown/clean)

    # AI result (optional, filled async)
    ai_owner_probability: float | None = None

    # Computed helpers
    description_lower: str = ""
    title_lower: str = ""
    posted_hour: int = 12    # Default to noon if unknown
    is_weekend: bool = False

    def __post_init__(self) -> None:
        self.description_lower = (self.description or "").lower()
        self.title_lower = (self.title or "").lower()
        if self.posted_at:
            try:
                self.posted_hour = self.posted_at.hour
                self.is_weekend = self.posted_at.weekday() >= 5
            except AttributeError:
                pass

    @classmethod
    def from_listing(
        cls,
        listing: Any,  # RawListing
        phone_stats: dict[str, Any] | None = None,
    ) -> "SignalContext":
        """Build SignalContext from a RawListing + optional phone stats."""
        stats = phone_stats or {}
        return cls(
            title=listing.title or "",
            description=listing.description or "",
            phone=listing.phone or "",
            floor_level=listing.floor_level,
            listing_age_hours=listing.listing_age_hours,
            images=listing.images or [],
            posted_at=listing.posted_at,
            price_vnd_monthly=listing.price_vnd_monthly,
            phone_count_all_platforms=stats.get("total_listings", 0),
            phone_count_max_single_platform=stats.get("max_single_platform", 0),
            phone_platform_count=stats.get("platform_count", 0),
            phone_is_known_broker=stats.get("is_known_broker", False),
            # Prefer value extracted directly by spider (e.g. seller_info.live_ads from nhatot)
            # Fall back to DB stats, then 999 (unknown = assume high = signal won't fire)
            poster_total_listings=(
                listing.poster_total_listings
                if getattr(listing, "poster_total_listings", None) is not None
                else stats.get("poster_total_listings")
            ),
            poster_sold_listings=getattr(listing, "poster_sold_listings", None) or 0,
            account_type=getattr(listing, "account_type", None),
            contact_name=getattr(listing, "contact_name", None) or "",
            same_session_account_count=getattr(listing, "same_session_account_count", 1),
            phone_hidden=getattr(listing, "phone_hidden", False),
            poster_profile_hash=getattr(listing, "poster_profile_hash", None),
            poster_join_year=getattr(listing, "poster_join_year", None),
            has_pro_agent_badge=getattr(listing, "has_pro_agent_badge", False),
            is_vip=getattr(listing, "is_vip", False),
            avatar_url=getattr(listing, "avatar_url", None),
            is_main_street=getattr(listing, "is_main_street", None),
            trangtrang_report_count=stats.get("trangtrang_report_count", 0),
        )


# ============================================================
# SIGNAL CHECK FUNCTIONS
# Each returns bool (for binary signals) or float (0.0-1.0)
# Named to match scoring.yaml signal keys
# ============================================================

def check_phone_single_listing(ctx: SignalContext) -> bool:
    return ctx.phone_count_all_platforms == 1

def check_phone_few_listings(ctx: SignalContext) -> bool:
    return 2 <= ctx.phone_count_all_platforms <= 4

def check_phone_multi_listing_same_platform(ctx: SignalContext) -> bool:
    return ctx.phone_count_max_single_platform >= 5

def check_phone_multi_platform(ctx: SignalContext) -> bool:
    return ctx.phone_platform_count >= 3

def check_phone_known_broker(ctx: SignalContext) -> bool:
    return ctx.phone_is_known_broker

def check_text_owner_language(ctx: SignalContext) -> bool:
    keywords = [
        "nhà tôi", "chính chủ cần cho thuê", "liên hệ trực tiếp",
        "chủ nhà cho thuê", "tôi cần cho thuê", "nhà chính chủ",
        "cho thuê trực tiếp", "không qua trung gian",
    ]
    return any(kw in ctx.description_lower for kw in keywords)

def check_text_marketing_superlatives(ctx: SignalContext) -> bool:
    keywords = [
        "đắc địa", "siêu hot", "sinh lợi cao", "vị trí vàng",
        "không thể bỏ lỡ", "cơ hội hiếm có", "giá tốt nhất",
        "mặt bằng đẹp nhất", "vị trí chiến lược", "cơ hội đầu tư",
    ]
    return any(kw in ctx.description_lower for kw in keywords)

def check_text_commission_mention(ctx: SignalContext) -> bool:
    keywords = [
        "hoa hồng", "commission", "phí môi giới", "% cho sale",
        "có hoa hồng", "hỗ trợ hoa hồng",
    ]
    return any(kw in ctx.description_lower for kw in keywords)

def check_text_agent_language(ctx: SignalContext) -> bool:
    keywords = [
        "liên hệ môi giới", "chuyên bds", "chuyên bất động sản",
        "hotline:", "zalo:", "chuyên gia tư vấn",
    ]
    return any(kw in ctx.description_lower for kw in keywords)

def check_photo_count_low(ctx: SignalContext) -> bool:
    return len(ctx.images) <= 5

def check_photo_count_high(ctx: SignalContext) -> bool:
    return len(ctx.images) >= 8

def check_posted_outside_business_hours(ctx: SignalContext) -> bool:
    return ctx.posted_hour < 8 or ctx.posted_hour > 18 or ctx.is_weekend

def check_account_new_or_few_posts(ctx: SignalContext) -> bool:
    return ctx.poster_total_listings <= 2

def check_seller_high_sold_count(ctx: SignalContext) -> bool:
    """Lịch sử đăng >= 20 tin — rõ ràng là môi giới chuyên nghiệp. 0 = không có data → không fire."""
    return ctx.poster_sold_listings >= 20

_BROKER_NAME_KEYWORDS = [
    # Nghề BĐS
    "môi giới", "moi gioi", "bds", "bđs", "bất động sản", "bat dong san",
    "địa ốc", "dia oc", "nhà đất", "nha dat", "kinh doanh bđs",
    # Tổ chức / pháp nhân
    "công ty", "cong ty", "doanh nghiệp", "doanh nghiep", "tnhh", "cổ phần",
    # Tư vấn / chuyên nghiệp
    "tư vấn", "tu van", "chuyên viên", "chuyen vien",
    # Từ tiếng Anh hiếm dùng nhưng vẫn giữ phòng trường hợp sàn lớn
    "realty", "property", "land",
]

def check_account_name_broker_keywords(ctx: SignalContext) -> bool:
    """Tên tài khoản chứa từ khóa môi giới — dấu hiệu rõ ràng."""
    name = ctx.contact_name.lower()
    return any(kw in name for kw in _BROKER_NAME_KEYWORDS)

def check_same_session_multi_listing(ctx: SignalContext) -> bool:
    """Cùng 1 tài khoản đăng >2 tin trong cùng batch crawl — broker pattern. 2 tin có thể chủ có 2 mặt bằng."""
    return ctx.same_session_account_count > 2

_EMOJI_PATTERN = None
def check_description_many_emojis(ctx: SignalContext) -> bool:
    """Nhiều emoji trong tiêu đề + mô tả — dấu hiệu format marketing của môi giới."""
    import re
    global _EMOJI_PATTERN
    if _EMOJI_PATTERN is None:
        _EMOJI_PATTERN = re.compile(
            "[\U0001F300-\U0001F9FF"   # symbols, pictographs, emoticons
            "\U00002702-\U000027B0"    # dingbats
            "\U0000FE00-\U0000FE0F"    # variation selectors
            "\U00003030\U000000A9\U000000AE\U00002000-\U00003300]+",
            flags=re.UNICODE,
        )
    text = ctx.title + " " + ctx.description
    count = len(_EMOJI_PATTERN.findall(text))
    return count >= 5

def check_phone_hidden_owner(ctx: SignalContext) -> bool:
    """
    Seller chủ động ẩn SĐT trên nhatot (non-401 API error).
    Broker cần phone visible để kiếm khách — họ không ẩn.
    Chủ nhà giàu ngại bị làm phiền → ẩn SĐT → strong chính chủ signal.
    Chỉ fire khi phone_hidden=True (phân biệt với token expired = False).
    """
    return ctx.phone_hidden


def check_account_type_personal(ctx: SignalContext) -> bool:
    """Platform xác nhận tài khoản cá nhân (nhatot type=u). None=unknown → không fire."""
    return ctx.account_type == "u"

def check_account_type_business(ctx: SignalContext) -> bool:
    """Platform xác nhận tài khoản doanh nghiệp/shop (nhatot type=s). None=unknown → không fire."""
    return ctx.account_type == "s"

def check_listing_very_fresh(ctx: SignalContext) -> bool:
    return ctx.listing_age_hours is not None and ctx.listing_age_hours <= 2

def check_listing_fresh(ctx: SignalContext) -> bool:
    return ctx.listing_age_hours is not None and 2 < ctx.listing_age_hours <= 24

def check_listing_stale(ctx: SignalContext) -> bool:
    return ctx.listing_age_hours is not None and ctx.listing_age_hours > 168

def check_floor_ground_level(ctx: SignalContext) -> bool:
    return ctx.floor_level == 1

def check_floor_ambiguous(ctx: SignalContext) -> bool:
    return ctx.floor_level is None

def check_floor_upper_level(ctx: SignalContext) -> bool:
    return ctx.floor_level is not None and ctx.floor_level >= 3

# Tập hợp ký tự đặc trưng tiếng Việt (có dấu thanh + chữ cái mở rộng)
_VIET_DIACRITIC_CHARS = frozenset(
    "ăâđêôơư"
    "áàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    "ĂÂĐÊÔƠƯ"
    "ÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ"
)

def check_description_no_diacritics(ctx: SignalContext) -> bool:
    """
    Phát hiện viết không dấu / có typo nhiều — dấu hiệu chủ nhà gõ nhanh trên điện thoại.
    Tiếng Việt chuẩn có ~25-40% ký tự mang dấu đặc trưng.
    Nếu tỉ lệ < 8% → văn bản gần như không dấu → chính chủ signal.
    AI text và môi giới chuyên nghiệp luôn dùng diacritics đầy đủ.
    """
    text = ctx.title + " " + ctx.description
    alpha_chars = [c for c in text if c.isalpha()]
    if len(alpha_chars) < 30:  # Quá ngắn, không đủ dữ liệu
        return False
    viet_count = sum(1 for c in alpha_chars if c in _VIET_DIACRITIC_CHARS)
    ratio = viet_count / len(alpha_chars)
    return ratio < 0.08


def check_description_too_short(ctx: SignalContext) -> bool:
    return len(ctx.description) < 50

def check_description_medium(ctx: SignalContext) -> bool:
    return 50 <= len(ctx.description) <= 300

def check_description_too_long(ctx: SignalContext) -> bool:
    return len(ctx.description) > 500

# ============================================================
# Batdongsan-specific signals
# All require guru profile enrichment (poster_profile_hash set).
# Without enrichment, the default poster_total_listings=999 would
# wrongly fire the broker signal — the guard prevents that.
# ============================================================

def _bds_has_active_count(ctx: SignalContext) -> bool:
    """True khi có số liệu tin đăng thực từ detail page (không phải sentinel/lỗi)."""
    t = ctx.poster_total_listings
    return t is not None and t >= 0 and t < 999

def check_bds_broker_multi_active_listings(ctx: SignalContext) -> bool:
    """Detail page: >5 tin đăng đang có → broker chuyên nghiệp."""
    if not _bds_has_active_count(ctx):
        return False
    return ctx.poster_total_listings > 5

def check_bds_owner_few_active_listings(ctx: SignalContext) -> bool:
    """Detail page: 1-5 tin đăng → chủ có ít BĐS. Stacks với single_listing khi ==1."""
    if not _bds_has_active_count(ctx):
        return False
    return 1 <= ctx.poster_total_listings <= 5

def check_bds_owner_single_listing(ctx: SignalContext) -> bool:
    """Detail page: đúng 1 tin đăng → strongest chính chủ signal."""
    if not _bds_has_active_count(ctx):
        return False
    return ctx.poster_total_listings == 1

def check_poster_join_year_veteran(ctx: SignalContext) -> bool:
    """Tham gia >= 3 năm — signal phụ khi combine với multi-listing (broker lâu năm)."""
    from datetime import datetime
    if ctx.poster_join_year is None:
        return False
    return ctx.poster_join_year <= datetime.now().year - 3

def check_detail_has_pro_agent_badge(ctx: SignalContext) -> bool:
    """Badge 'Môi giới chuyên nghiệp' → hard broker signal."""
    return ctx.has_pro_agent_badge


def check_account_name_is_phone(ctx: SignalContext) -> bool:
    """Tên tài khoản là số điện thoại — thường là chính chủ."""
    import re
    # Remove dots, spaces, dashes
    clean_name = re.sub(r"[\s\.\-]", "", ctx.contact_name)
    return bool(re.match(r"^0\d{9}$", clean_name))


def check_avatar_is_blank(ctx: SignalContext) -> bool:
    """
    Ảnh đại diện là default/placeholder — thường là chủ nhà.
    Chỉ fire khi avatar_url được set nhưng là URL default.
    Khi avatar_url=None (data không có) → False (unknown, không fire).
    """
    if ctx.avatar_url is None:
        return False  # unknown — không có data, không cộng/trừ điểm
    if not ctx.avatar_url:
        return True   # empty string = explicitly blank
    default_markers = ["avatar-default", "no-avatar", "user_default", "default-avatar"]
    return any(m in ctx.avatar_url.lower() for m in default_markers)


def check_listing_is_vip(ctx: SignalContext) -> bool:
    """Tin đăng VIP/có trả phí — mild broker indicator."""
    return ctx.is_vip


def check_muaban_multi_active_listings(ctx: SignalContext) -> bool:
    """Dành riêng cho Muaban: >= 5 bài đăng trên trang cá nhân -> Broker."""
    return ctx.poster_total_listings is not None and ctx.poster_total_listings >= 5


def check_muaban_few_active_listings(ctx: SignalContext) -> bool:
    """Dành riêng cho Muaban: < 5 bài đăng trên trang cá nhân -> Owner candidate."""
    return ctx.poster_total_listings is not None and ctx.poster_total_listings < 5


def check_ai_classification(ctx: SignalContext) -> float:
    """Returns 0.0-1.0 probability. Used as continuous weight multiplier."""
    if ctx.ai_owner_probability is None:
        return 0.5  # Neutral if AI unavailable
    return float(ctx.ai_owner_probability)


def check_trangtrang_spam_penalty(ctx: SignalContext) -> bool:
    """Phone has 5+ spam reports on trangtrang.com — strong spam/broker indicator."""
    return ctx.trangtrang_report_count >= 5

# Map signal names (from YAML) to check functions
SIGNAL_FUNCTIONS: dict[str, Any] = {
    "phone_single_listing": check_phone_single_listing,
    "phone_few_listings": check_phone_few_listings,
    "phone_multi_listing_same_platform": check_phone_multi_listing_same_platform,
    "phone_multi_platform": check_phone_multi_platform,
    "phone_known_broker": check_phone_known_broker,
    "text_owner_language": check_text_owner_language,
    "text_marketing_superlatives": check_text_marketing_superlatives,
    "text_commission_mention": check_text_commission_mention,
    "text_agent_language": check_text_agent_language,
    "photo_count_low": check_photo_count_low,
    "photo_count_high": check_photo_count_high,
    "posted_outside_business_hours": check_posted_outside_business_hours,
    "account_new_or_few_posts": check_account_new_or_few_posts,
    "seller_high_sold_count": check_seller_high_sold_count,
    "account_name_broker_keywords": check_account_name_broker_keywords,
    "same_session_multi_listing": check_same_session_multi_listing,
    "description_many_emojis": check_description_many_emojis,
    "phone_hidden_owner": check_phone_hidden_owner,
    "account_type_personal": check_account_type_personal,
    "account_type_business": check_account_type_business,
    "listing_very_fresh": check_listing_very_fresh,
    "listing_fresh": check_listing_fresh,
    "listing_stale": check_listing_stale,
    "floor_ground_level": check_floor_ground_level,
    "floor_ambiguous": check_floor_ambiguous,
    "floor_upper_level": check_floor_upper_level,
    "description_no_diacritics": check_description_no_diacritics,
    "description_too_short": check_description_too_short,
    "description_medium": check_description_medium,
    "description_too_long": check_description_too_long,
    "bds_broker_multi_active_listings": check_bds_broker_multi_active_listings,
    "bds_owner_few_active_listings": check_bds_owner_few_active_listings,
    "bds_owner_single_listing": check_bds_owner_single_listing,
    "poster_join_year_veteran": check_poster_join_year_veteran,
    "detail_has_pro_agent_badge": check_detail_has_pro_agent_badge,
    "account_name_is_phone": check_account_name_is_phone,
    "avatar_is_blank": check_avatar_is_blank,
    "listing_is_vip": check_listing_is_vip,
    "muaban_multi_active_listings": check_muaban_multi_active_listings,
    "muaban_few_active_listings": check_muaban_few_active_listings,
    "trangtrang_spam_penalty": check_trangtrang_spam_penalty,
    "ai_classification": check_ai_classification,
}
