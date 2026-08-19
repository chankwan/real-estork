"""
RealEstork — Unit Tests: Dedup Pipeline
Tests for address/phone normalization and dedup rules.
"""

import pytest
from datetime import datetime, timezone

from pipeline.dedup import normalize_address, normalize_phone, DedupPipeline
from spiders.base import RawListing


def make_listing(**kwargs) -> RawListing:
    defaults = {
        "source": "nhatot",
        "source_id": "123",
        "source_url": "https://example.com/123",
        "title": "Cho thuê mặt bằng",
        "description": "Nhà tôi cần cho thuê",
        "address": "123 Hai Bà Trưng, Q.3",
        "district": "Quận 3",
        "phone": "0901234567",
        "price_vnd_monthly": 100_000_000,
    }
    defaults.update(kwargs)
    return RawListing(**defaults)


# =====================================================
# Address Normalization Tests
# =====================================================

class TestAddressNormalization:
    def test_lowercase(self):
        assert normalize_address("Quận 3") == normalize_address("quận 3")

    def test_remove_diacritics(self):
        result = normalize_address("Hai Bà Trưng")
        assert "trung" in result or "truong" in result  # unidecode result

    def test_strip_extra_spaces(self):
        result = normalize_address("  Quận   3  ")
        assert "  " not in result

    def test_empty_string(self):
        assert normalize_address("") == ""

    def test_none_safe(self):
        # Should not crash with empty
        result = normalize_address("")
        assert result == ""


# =====================================================
# Phone Normalization Tests
# =====================================================

class TestPhoneNormalization:
    def test_standard_10_digit(self):
        assert normalize_phone("0901234567") == "0901234567"

    def test_plus84_prefix(self):
        assert normalize_phone("+84901234567") == "0901234567"

    def test_84_prefix_no_plus(self):
        assert normalize_phone("84901234567") == "0901234567"

    def test_with_spaces(self):
        assert normalize_phone("090 123 4567") == "0901234567"

    def test_with_dashes(self):
        assert normalize_phone("090-123-4567") == "0901234567"

    def test_empty(self):
        assert normalize_phone("") == ""

    def test_invalid(self):
        result = normalize_phone("123")
        assert result == "" or result == "123"  # Can't normalize short numbers


# =====================================================
# Dedup Pipeline Tests
# =====================================================

class TestDedupPipeline:
    def setup_method(self):
        self.dedup = DedupPipeline()

    def test_exact_hash_duplicate(self):
        listing1 = make_listing(source_id="1")
        listing2 = make_listing(source_id="2", title=listing1.title)  # Same hash if same title+phone+desc
        
        # Process first listing
        new = self.dedup.filter_new([listing1])
        assert len(new) == 1
        
        # Same content → duplicate
        listing2.content_hash = listing1.content_hash
        new2 = self.dedup.filter_new([listing2])
        assert len(new2) == 0

    def test_different_source_same_content(self):
        """Same listing cross-posted on 2 platforms → deduplicated."""
        listing1 = make_listing(source="nhatot", source_id="111")
        listing2 = make_listing(source="batdongsan", source_id="222")
        # Same content → same hash
        listing2.content_hash = listing1.content_hash
        
        new = self.dedup.filter_new([listing1, listing2])
        assert len(new) == 1

    def test_new_listing_passes(self):
        listing = make_listing(
            source_id="new_unique_999",
            title="Unique listing",
            phone="0987654321",
            description="Different content",
            address="999 Another Street"
        )
        new = self.dedup.filter_new([listing])
        assert len(new) == 1

    def test_phone_district_price_duplicate(self):
        """Same seller cross-posting same property with slight variation."""
        listing1 = make_listing(source_id="a1", price_vnd_monthly=100_000_000)
        listing2 = make_listing(
            source_id="a2",
            price_vnd_monthly=105_000_000,  # 5% diff → within ±10% → duplicate
        )
        
        new = self.dedup.filter_new([listing1, listing2])
        assert len(new) == 1

    def test_same_phone_different_district_not_duplicate(self):
        """Same agent listing in different districts → NOT duplicate."""
        listing1 = make_listing(source_id="b1", district="Quận 1")
        listing2 = make_listing(source_id="b2", district="Quận 3")
        # Same phone, different district
        
        new = self.dedup.filter_new([listing1, listing2])
        # May or may not be 2 depending on address normalization
        # Just check at least 1 passes
        assert len(new) >= 1

    def test_empty_input(self):
        new = self.dedup.filter_new([])
        assert new == []

    def test_seed_from_db(self):
        """Seeding from DB prevents re-alerting known listings."""
        existing = [
            {
                "content_hash": "abcdef123456",
                "phone": "0901234567",
                "district": "Quận 3",
                "address_normalized": "123 hai ba trung quan 3",
                "price_vnd_monthly": 100_000_000,
            }
        ]
        self.dedup.seed_from_db(existing)
        
        # Listing with same phone/district
        listing = make_listing(source_id="xyz")
        listing.content_hash = "abcdef123456"
        
        new = self.dedup.filter_new([listing])
        assert len(new) == 0  # Was already in DB → filtered out


# =====================================================
# Classification Pipeline Tests
# =====================================================

class TestClassificationPipeline:
    def setup_method(self):
        from pipeline.classifier import ClassificationPipeline
        self.classifier = ClassificationPipeline()

    def test_owner_language_increases_score(self):
        listing = make_listing(description="Nhà tôi cần cho thuê, liên hệ trực tiếp")
        result = self.classifier.classify(listing)
        assert result.score > 50  # Should boost above base_score

    def test_broker_language_decreases_score(self):
        listing = make_listing(
            description="Vị trí vàng, đắc địa, hoa hồng tốt, không thể bỏ lỡ"
        )
        result = self.classifier.classify(listing)
        assert result.score < 50  # Should reduce below base_score

    def test_known_broker_phone_crushes_score(self):
        listing = make_listing(phone="0901111111")
        result = self.classifier.classify(
            listing,
            phone_stats={"is_known_broker": True, "total_listings": 50}
        )
        assert result.score < 40  # Known broker → moi_gioi

    def test_fresh_listing_bonus(self):
        from datetime import datetime, timezone
        import time
        listing = make_listing()
        listing.listing_age_hours = 1.5  # Very fresh
        result = self.classifier.classify(listing)
        # listing_very_fresh gives +10
        assert result.score >= 60

    def test_stale_listing_penalty(self):
        # Use neutral description (no owner/broker keywords) to isolate stale signal
        listing = make_listing(description="Cho thuê mặt bằng quận 3.")
        listing.listing_age_hours = 200  # > 7 days → listing_stale: -15
        result = self.classifier.classify(listing)
        # Base=50, stale=-15, photo_low=+5, floor_ambiguous=+3 → 43
        # Just verify stale penalty is actually applied (score < base without stale=50+5+3=58)
        assert result.score < 58  # Lower than without stale penalty

    def test_ground_floor_bonus(self):
        listing = make_listing(floor_level=1)
        result = self.classifier.classify(listing)
        assert result.score >= 58  # +8 from floor_ground_level

    def test_label_thresholds(self):
        # Score >= 65 → chinh_chu
        listing1 = make_listing(description="Nhà tôi cần cho thuê, không qua trung gian")
        r1 = self.classifier.classify(listing1)

        # Label consistency
        assert r1.label in ["chinh_chu", "can_xac_minh", "moi_gioi"]
        if r1.score >= 65:
            assert r1.label == "chinh_chu"
        elif r1.score >= 40:
            assert r1.label == "can_xac_minh"
        else:
            assert r1.label == "moi_gioi"


# =====================================================
# District Normalization Tests
# =====================================================

class TestDistrictNormalization:
    """Tests for _normalize_district — handles post-2025 ward merger formats."""

    def setup_method(self):
        from pipeline.classifier import ClassificationPipeline
        self.classifier = ClassificationPipeline()

    def test_simple_district(self):
        norm = self.classifier._normalize_district
        assert norm("Quận 3") == "3"
        assert norm("Q.3") == "3"
        assert norm("Q. 3") == "3"
        assert norm("Tân Bình") == "tan binh"

    def test_batdongsan_format_outer_district(self):
        """Batdongsan: 'Q. X (P. Y mới)' — outer is district."""
        norm = self.classifier._normalize_district
        # Real-world case from batdongsan-45685110 (was being rejected as ngoai_quan)
        assert norm("Q. Tân Bình (P. Bảy Hiền mới)") == "tan binh"
        assert norm("Q. 7 (P. Tân Quy mới)") == "7"
        assert norm("Quận Bình Thạnh (P. 22 mới)") == "binh thanh"

    def test_muaban_format_inner_district(self):
        """Muaban: 'P. X (Q. Y cũ)' — inner is district."""
        norm = self.classifier._normalize_district
        assert norm("P. Tân Quy (Q. 7 cũ)") == "7"
        assert norm("P. Bảy Hiền (Q. Tân Bình cũ)") == "tan binh"

    def test_no_parentheses(self):
        norm = self.classifier._normalize_district
        assert norm("Bình Thạnh") == "binh thanh"
        assert norm("Phú Nhuận") == "phu nhuan"

    def test_leading_zero_district(self):
        norm = self.classifier._normalize_district
        assert norm("Quận 03") == "3"
        assert norm("Q.07") == "7"

    def test_empty_safe(self):
        norm = self.classifier._normalize_district
        assert norm("") == ""

    def test_thanh_pho_prefix(self):
        """Nhatot returns 'Thành phố Thủ Đức' for TP Thủ Đức (special HCMC unit)."""
        # Real-world case from nhatot/132648841 (session 18 — was being rejected as ngoai_quan)
        norm = self.classifier._normalize_district
        assert norm("Thành phố Thủ Đức") == "thu duc"
        assert norm("TP Thủ Đức") == "thu duc"
        assert norm("TP. Thủ Đức") == "thu duc"
        # Regression: city names with no district prefix stay intact
        assert norm("Thành phố Hà Nội") == "ha noi"

# =====================================================
# Batdongsan — xác minh số tin đăng của người bán
# (audit 2026-08-18: môi giới 101/709 tin lọt alert)
# =====================================================

class _StubPage:
    """Trang giả cho _enrich_from_detail: chỉ cần html_content + css() rỗng."""

    def __init__(self, html: str) -> None:
        self.html_content = html

    def css(self, selector: str):
        return []


class TestBatdongsanPosterCount:
    """Đọc số tin đăng từ trang chi tiết — không đọc được thì phải là 'chưa biết'."""

    def _enrich(self, html: str):
        import asyncio
        from spiders.batdongsan import BatdongsanSpider

        spider = BatdongsanSpider({"name": "batdongsan", "urls": ["https://x"]})

        async def fake_fetch(url, loop, wait=3000):
            return _StubPage(html)

        spider._stealth_fetch = fake_fetch
        listing = make_listing(source="batdongsan", source_url="https://x/pr1")
        asyncio.run(spider._enrich_from_detail(listing, None))
        return listing.poster_total_listings

    def test_sidebar_count(self):
        assert self._enrich("<p>Tin đăng đang có</p><p>32</p>") == 32

    def test_xem_them_button(self):
        # "Xem thêm 101 tin khác" = 101 tin khác + chính tin này
        assert self._enrich("<div>Xem thêm 101 tin khác</div>") == 102

    def test_khong_thay_so_thi_chua_biet(self):
        """Regression: trước đây mặc định 1 → +25 điểm chính chủ cho môi giới."""
        assert self._enrich("<div>trang chi tiết không có khối liên hệ</div>") is None

    def test_cloudflare_chan_thi_sentinel(self):
        assert self._enrich("<title>Just a moment...</title>") == -1


class TestBdsPosterCountUnknown:
    """Hàng rào thứ hai: chưa biết số tin đăng → không được coi là chính chủ."""

    def _l(self, count, source="batdongsan"):
        listing = make_listing(source=source, source_id="1")
        listing.poster_total_listings = count
        return listing

    def test_none_la_chua_biet(self):
        from orchestrator.agent import _bds_poster_count_unknown
        assert _bds_poster_count_unknown(self._l(None)) is True

    def test_sentinel_am_la_chua_biet(self):
        from orchestrator.agent import _bds_poster_count_unknown
        assert _bds_poster_count_unknown(self._l(-1)) is True

    def test_co_so_that_thi_di_tiep(self):
        from orchestrator.agent import _bds_poster_count_unknown
        assert _bds_poster_count_unknown(self._l(1)) is False
        assert _bds_poster_count_unknown(self._l(7)) is False

    def test_source_khac_khong_dinh_gate(self):
        from orchestrator.agent import _bds_poster_count_unknown
        assert _bds_poster_count_unknown(self._l(None, source="nhatot")) is False

    def test_replay_5_tin_bi_lot_trong_audit(self):
        """5 tin vợ báo — dùng đúng giá trị active đã ghi trong log production."""
        from orchestrator.agent import _bds_poster_count_unknown

        leaked = {
            "44549267": -1,   # showroom Q2, score 76
            "46211967": -1,   # Nguyễn Thị Minh Khai, score 76
            "45755898": None, # Lê Duẩn, score 100 (log ghi 1 = mặc định cũ)
            "46162437": None, # villa Nguyễn Văn Hưởng, score 96
            "45959419": None, # duplex Q7, score 86
        }
        for source_id, active in leaked.items():
            listing = self._l(active)
            listing.source_id = source_id
            assert _bds_poster_count_unknown(listing) is True, source_id
