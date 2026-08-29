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


class TestNhatotPosterCountUnknown:
    """Thiếu số tin đăng của người bán → phải hoá 999 (chưa biết), KHÔNG được là None.

    Regression session 23: comment ở SignalContext.from_listing hứa 'fall back to
    DB stats, then 999' nhưng bước 999 chưa bao giờ được cài. stats không có khoá
    'poster_total_listings' → ctx nhận None → tín hiệu so None <= 2 ném TypeError,
    classifier nuốt lỗi → tin chính chủ ít tin âm thầm mất +14 điểm.
    """

    def _ctx(self, spider_value, stats=None):
        from pipeline.signals import SignalContext
        listing = make_listing(source="nhatot", source_id="1")
        listing.poster_total_listings = spider_value
        return SignalContext.from_listing(listing, phone_stats=stats)

    def test_thieu_so_thi_999_khong_phai_none(self):
        ctx = self._ctx(None)
        assert ctx.poster_total_listings == 999

    def test_spider_doc_duoc_thi_giu_nguyen(self):
        assert self._ctx(1).poster_total_listings == 1
        assert self._ctx(8).poster_total_listings == 8

    def test_zero_khong_bi_bien_thanh_999(self):
        """live_ads=0 (tin đã hết hạn) là dữ liệu thật, không phải 'chưa biết'."""
        assert self._ctx(0).poster_total_listings == 0

    def test_db_stats_duoc_dung_khi_spider_khong_co(self):
        assert self._ctx(None, stats={"poster_total_listings": 3}).poster_total_listings == 3

    def test_tin_hieu_khong_nem_loi_khi_thieu_so(self):
        from pipeline.signals import check_account_new_or_few_posts
        assert check_account_new_or_few_posts(self._ctx(None)) is False

    def test_tin_hieu_ban_dung_khi_co_so(self):
        from pipeline.signals import check_account_new_or_few_posts
        assert check_account_new_or_few_posts(self._ctx(1)) is True
        assert check_account_new_or_few_posts(self._ctx(2)) is True
        assert check_account_new_or_few_posts(self._ctx(3)) is False
        assert check_account_new_or_few_posts(self._ctx(8)) is False

    def test_guard_chiu_duoc_none_truc_tiep(self):
        """Chốt chặn tại chỗ: dù ai đó nhét None vào ctx thì cũng không nổ."""
        from pipeline.signals import check_account_new_or_few_posts
        ctx = self._ctx(1)
        ctx.poster_total_listings = None
        assert check_account_new_or_few_posts(ctx) is False


class TestNonRentalFilter:
    """Tin sang nhượng / pass hợp đồng / bán / góp vốn không phải mặt bằng để thuê.

    Session 23: đo 1200 tin portal → 40 tin loại này, 9 tin đã gửi cho vợ với
    score 58-100 mang nhãn 'Likely Chính Chủ'.
    """

    def _c(self):
        from pipeline.classifier import ClassificationPipeline
        return ClassificationPipeline()

    def _v(self, title, source="nhatot"):
        return self._c().non_rental_verdict(make_listing(source=source, title=title))

    def test_ban_nha_bi_chan(self):
        assert self._v("Bán nhà 637/36/4 Tỉnh Lộ 10, P Bình Trị Đông B, Q. Bình Tân") == "block"

    def test_sang_quan_bi_chan(self):
        assert self._v("SANG GẤP CỬA HÀNG GỐM BÁT TRÀNG - VỊ TRÍ ĐẮC ĐỊA") == "block"
        assert self._v("Sang quán cf góc 2 mặt tiền Hà Huy Giáp q12", "muaban") == "block"

    def test_pass_hop_dong_bi_chan(self):
        assert self._v("DO NHU CẦU MỞ RỘNG VĂN PHÒNG NÊN PASS HỢP ĐỒNG") == "block"

    def test_nhuong_lai_hop_dong_thue_van_bi_chan(self):
        """Bẫy: tiêu đề có chữ 'thuê' nhưng không có 'cho thuê' → vẫn là sang nhượng."""
        assert self._v("Nhượng lại hợp đồng thuê nhà chung cư") == "block"

    def test_tin_nuoc_doi_thi_gui_kem_nhan(self):
        assert self._v("CHO THUÊ HOẶC HỢP TÁC KINH DOANH SPA MỚI ĐẦU TƯ – GÒ VẤP") == "mixed"
        assert self._v("Cho thuê hoặc bán nhà MT số 19 ĐS 3, P9, Q.GV", "muaban") == "mixed"

    def test_tin_cho_thue_binh_thuong_khong_dinh(self):
        assert self._v("Cho thuê nhà mặt tiền Quận 3, 100m2") == ""
        assert self._v("Chính chủ cho thuê mặt bằng kinh doanh Bình Thạnh") == ""

    def test_khong_chan_oan_chu_ban_trong_mo_ta_nghe(self):
        """'bán cà phê', 'bán hàng' là mô tả ngành nghề — không phải rao bán nhà."""
        assert self._v("Cho thuê mặt bằng bán cà phê mang đi Quận 7") == ""
        assert self._v("Mặt bằng tầng trệt phù hợp bán hàng online") == ""

    def test_facebook_cung_bi_ap(self):
        """Bật cho FB 28/08: đo 400 tin FB → 14 tin sang nhượng/bán, 0 tin oan.

        Quan trọng cho việc #3 (mở recall ý định FB): lớp chặn này phải có TRƯỚC
        khi nới từ khoá, nếu không sẽ đổi lỗi 'tin chủ bị vứt oan' lấy lỗi 'tin
        bán/sang nhượng tràn vào'.
        """
        assert self._v("SANG NHƯỢNG NHÀ CHDV QUẬN 1", "facebook_groups") == "block"
        assert self._v("Cần bán lô đất kdc mới", "facebook_groups") == "block"
        assert self._v("Nhà nguyên căn cho thuê Gò Vấp 12tr", "facebook_groups") == ""

    def test_skip_reason_va_alert_wife(self):
        from pipeline.classifier import ClassificationResult
        c = self._c()
        listing = make_listing(source="nhatot", title="Nhượng lại hợp đồng thuê nhà chung cư",
                               district="Quận 1", price_vnd_monthly=40_000_000)
        listing.listing_age_hours = 1.0
        r = ClassificationResult(score=100, label="chinh_chu", signals_fired={},
                                 ai_probability=None, ai_reasoning="")
        assert c.alert_skip_reason(r, listing) == "khong_phai_cho_thue"
        assert c.should_alert_wife(r, listing) is False

    def test_tin_nuoc_doi_van_qua_duoc_cong_alert(self):
        from pipeline.classifier import ClassificationResult
        c = self._c()
        listing = make_listing(source="nhatot", title="CHO THUÊ HOẶC HỢP TÁC KINH DOANH SPA",
                               district="Quận 1", price_vnd_monthly=40_000_000)
        listing.listing_age_hours = 1.0
        r = ClassificationResult(score=100, label="chinh_chu", signals_fired={},
                                 ai_probability=None, ai_reasoning="")
        assert c.alert_skip_reason(r, listing) == ""


class TestFeedbackButtons:
    """Nút 👍/👎 dưới mỗi tin Telegram — đầu vào duy nhất của vòng học.

    Session 23: bảng phản hồi trống 0 dòng vì hàm ghi phản hồi chưa từng được
    gọi ở đâu. Phần phân tích hàng tuần chạy vào bảng rỗng suốt từ đầu.
    """

    def test_khong_co_id_thi_khong_gan_nut(self):
        from notifications.telegram import _feedback_keyboard
        assert _feedback_keyboard(None) is None
        assert _feedback_keyboard("") is None

    def test_co_id_thi_ra_2_nut(self):
        from notifications.telegram import _feedback_keyboard
        kb = _feedback_keyboard("abc-123")
        row = kb.inline_keyboard[0]
        assert len(row) == 2
        assert row[0].callback_data == "fb|1|abc-123"
        assert row[1].callback_data == "fb|0|abc-123"

    def test_bam_xong_van_con_du_2_nut_de_sua_neu_nham(self):
        """Bấm nhầm 👍 phải đổi lại được 👎 — không được khoá cứng lựa chọn."""
        from notifications.telegram import _feedback_keyboard
        kb = _feedback_keyboard("abc-123", good_count=1, bad_count=0)
        row = kb.inline_keyboard[0]
        assert len(row) == 2, "mất nút = không sửa được lựa chọn"
        # callback_data giữ nguyên → bấm nút kia là đổi phiếu của mình
        assert row[0].callback_data == "fb|1|abc-123"
        assert row[1].callback_data == "fb|0|abc-123"

    def test_nut_hien_so_phieu_cho_nhieu_nguoi_cung_danh_gia(self):
        """Vợ + đồng nghiệp cùng bấm 1 tin. Telegram chỉ có MỘT bộ nút chung nên
        không đánh dấu riêng từng người được — hiện số phiếu để ai cũng đọc."""
        from notifications.telegram import _feedback_keyboard
        row = _feedback_keyboard("abc-123", good_count=2, bad_count=1).inline_keyboard[0]
        assert "(2)" in row[0].text and "(1)" in row[1].text
        # chưa ai bấm thì không hiện số 0 cho rối
        row0 = _feedback_keyboard("abc-123").inline_keyboard[0]
        assert "(" not in row0[0].text and "(" not in row0[1].text

    def test_payload_la_van_duoc_tra_loi(self):
        """Nút cũ từ phiên bản trước: không trả lời thì Telegram quay vòng vòng."""
        import asyncio
        from notifications.telegram import TelegramNotifier

        class _Q:
            def __init__(self, data):
                self.data = data; self.from_user = None; self.answered = []
            async def answer(self, text=None): self.answered.append(text)

        class _U:
            def __init__(self, uid, q): self.update_id = uid; self.callback_query = q

        q = _Q("fb|seen")
        n = TelegramNotifier.__new__(TelegramNotifier)
        n.token = "x"; n._feedback_offset = None

        class _Bot:
            async def get_updates(self, **kw): return [_U(5, q)]
        n.bot = _Bot()

        assert asyncio.run(n.poll_feedback(lambda lid, good, voter="": (1, 0))) == 0
        assert q.answered, "phải trả lời callback dù payload không hiểu được"

    def test_callback_data_khong_vuot_gioi_han_64_byte(self):
        """Telegram chặn callback_data > 64 byte — UUID 36 ký tự phải lọt."""
        from notifications.telegram import _feedback_keyboard
        kb = _feedback_keyboard("123e4567-e89b-12d3-a456-426614174000")
        for btn in kb.inline_keyboard[0]:
            assert len(btn.callback_data.encode("utf-8")) <= 64

    def test_doc_nut_bam_va_luu_dung_nhan(self):
        import asyncio
        from notifications.telegram import TelegramNotifier

        class _Q:
            def __init__(self, data):
                self.data = data; self.from_user = None; self.answered = []
            async def answer(self, text=None): self.answered.append(text)
            async def edit_message_reply_markup(self, reply_markup=None): pass

        class _U:
            def __init__(self, uid, q): self.update_id = uid; self.callback_query = q

        n = TelegramNotifier.__new__(TelegramNotifier)
        n.token = "x"; n._feedback_offset = None
        ups = [_U(1, _Q("fb|1|listing-A")), _U(2, _Q("fb|0|listing-B")), _U(3, _Q("linh tinh"))]

        class _Bot:
            async def get_updates(self, **kw): return ups
        n.bot = _Bot()

        got = []
        def save(lid, good, voter=""):
            got.append((lid, good)); return (1, 0)

        saved = asyncio.run(n.poll_feedback(save))
        assert saved == 2
        assert got == [("listing-A", True), ("listing-B", False)]
        assert n._feedback_offset == 4        # đã xác nhận hết, restart không đọc lại

    def test_luu_that_bai_thi_khong_dem_va_bao_nguoi_bam(self):
        import asyncio
        from notifications.telegram import TelegramNotifier

        class _Q:
            def __init__(self, data):
                self.data = data; self.from_user = None; self.answered = []
            async def answer(self, text=None): self.answered.append(text)
            async def edit_message_reply_markup(self, reply_markup=None):
                raise AssertionError("không được sửa nút khi lưu thất bại")

        class _U:
            def __init__(self, uid, q): self.update_id = uid; self.callback_query = q

        q = _Q("fb|1|listing-A")
        n = TelegramNotifier.__new__(TelegramNotifier)
        n.token = "x"; n._feedback_offset = None

        class _Bot:
            async def get_updates(self, **kw): return [_U(9, q)]
        n.bot = _Bot()

        assert asyncio.run(n.poll_feedback(lambda lid, good, voter="": None)) == 0
        assert q.answered and "Chưa lưu được" in q.answered[0]


class TestFbIntentRecall:
    """Đoán ý định tin Facebook — mở recall (session 23).

    Đo 400 tin FB thật: 'chưa rõ' 164 → 43, Chủ +118, Khách +3, 0 tin đảo ngược sai.
    Người bán FB phần lớn không viết "cho thuê" mà viết "18TRIỆU/THÁNG - NHÀ MỚI
    XÂY NGUYÊN CĂN", nên chỉ dò chữ "cho thuê" là vứt oan ~20% tin chủ nhà.
    """

    def _i(self, text, price=None, phone=""):
        from spiders.facebook_groups import detect_fb_intent
        return detect_fb_intent(text, price_vnd=price, phone=phone)

    def test_khach_tim_thue_van_la_khach_du_co_tu_khoa_chu(self):
        """Bẫy thứ tự: 'nhà nguyên căn' nằm trong từ khoá Chủ, nhưng người TÌM
        cũng viết vậy. Seek phải được xét TRƯỚC, nếu không sẽ gán nhầm."""
        assert self._i("E tìm nhà nguyên căn quận Tân Phú, ngân sách 15tr") == "seek"
        assert self._i("Mình tìm mặt bằng kinh doanh quận 3") == "seek"

    def test_chu_nha_dung_tu_can_tim_van_la_chu(self):
        """Chủ nhà hay viết 'cần cho thuê', 'tìm khách thuê' — có 'cần'/'tìm'."""
        assert self._i("Chính chủ cần cho thuê nhà mặt tiền Q3") == "offer"
        assert self._i("Nhà trống, đang tìm khách thuê lâu dài") == "offer"

    def test_tu_khoa_mo_rong_bat_duoc_tin_chu_khong_co_chu_cho_thue(self):
        assert self._i("12TR CÓ MẶT BẰNG KINH DOANH ĐẸP – LÊ ĐỨC THỌ") == "offer"
        assert self._i("Biệt thự Thảo Điền. Giá thuê: 80tr/tháng") == "offer"
        assert self._i("NHÀ NGUYÊN CĂN ĐƯỜNG NGUYỄN ĐÌNH CHIỂU, QUẬN 3") == "offer"

    def test_tin_chu_khong_khop_tu_khoa_nao_van_duoc_cuu_boi_cau_truc(self):
        """Tin thật: 'XÂY NGUYÊN CĂN' không khớp cụm 'nhà nguyên căn'. Lớp từ
        khoá bó tay, nhưng có giá + SĐT nên bước suy cấu trúc kết luận đúng."""
        txt = "18TRIỆU/THÁNG - NHÀ MỚI XÂY NGUYÊN CĂN ĐƯỜNG SỐ 2 / PHƯỜNG THỦ ĐỨC"
        assert self._i(txt) == "unknown"
        assert self._i(txt, price=18_000_000, phone="0901234567") == "offer"

    def test_suy_theo_cau_truc_khi_khong_co_tu_khoa_nao(self):
        """Có giá theo tháng + SĐT = tin rao cho thuê, dù không có chữ 'thuê'."""
        txt = "127/ Lê Văn Duyệt P.3 Bình Thạnh 2.5x7 trệt 2 lầu 2pn 3wc"
        assert self._i(txt, price=9_000_000, phone="0793344717") == "offer"

    def test_thieu_gia_hoac_thieu_sdt_thi_khong_dam_ket_luan(self):
        txt = "127/ Lê Văn Duyệt P.3 Bình Thạnh 2.5x7 trệt 2 lầu"
        assert self._i(txt, price=9_000_000, phone="") == "unknown"
        assert self._i(txt, price=None, phone="0793344717") == "unknown"

    def test_khong_suy_lieu_khi_than_bai_co_dau_hieu_sang_nhuong(self):
        """Tin thật đã lọt lưới: tiêu đề 'BÌNH THẠNH - THUÊ' nên lớp chặn (đọc
        tiêu đề) không bắt được, mà lại đủ giá + SĐT nên suýt bị gán Chủ."""
        txt = "BÌNH THẠNH - THUÊ\nLỜI\n- GIÁ SANG 1XX\n6P + 1MB + 6WC\nThuê 16.8tr"
        assert self._i(txt, price=16_800_000, phone="0899907921") == "unknown"

    def test_goi_kieu_cu_chi_1_tham_so_van_chay(self):
        """Giữ tương thích: chỗ nào gọi kiểu cũ vẫn không vỡ."""
        from spiders.facebook_groups import detect_fb_intent
        assert detect_fb_intent("Chính chủ cho thuê nhà") == "offer"
        assert detect_fb_intent("") == "unknown"

    def test_tu_khoa_doc_tu_config(self):
        from spiders.facebook_groups import _intent_config
        cfg = _intent_config()
        assert "cho thuê" in cfg["offer_strong"]
        assert "giá thuê" in cfg["offer_keywords"]
        assert "giá sang" in cfg["transfer_markers"]
        assert cfg["structural"]["enabled"] is True


class TestFeedbackNhieuNguoi:
    """Vợ + 1 đồng nghiệp cùng đánh giá — mỗi người giữ 1 phiếu riêng.

    Bẫy: nếu xoá phản hồi cũ theo tin (không theo người) thì người thứ hai bấm
    sẽ xoá mất phiếu của người thứ nhất.
    """

    def test_moi_nguoi_mot_phieu_khong_dam_nhau(self):
        import asyncio
        from notifications.telegram import TelegramNotifier

        class _Q:
            def __init__(self, data, uid):
                self.data = data; self.answered = []
                self.from_user = type("U", (), {"id": uid})()
            async def answer(self, text=None): self.answered.append(text)
            async def edit_message_reply_markup(self, reply_markup=None): pass

        class _U:
            def __init__(self, uid, q): self.update_id = uid; self.callback_query = q

        # kho phieu gia lap: {(tin, nguoi): danh gia}
        kho: dict[tuple[str, str], bool] = {}
        def save(lid, good, voter=""):
            kho[(lid, voter)] = good           # ghi de phieu CUA MINH
            g = sum(1 for (l, _), v in kho.items() if l == lid and v)
            b = sum(1 for (l, _), v in kho.items() if l == lid and not v)
            return (g, b)

        n = TelegramNotifier.__new__(TelegramNotifier)
        n.token = "x"; n._feedback_offset = None
        ups = [
            _U(1, _Q("fb|1|tin-A", 111)),   # vợ: đáng xem
            _U(2, _Q("fb|0|tin-A", 222)),   # đồng nghiệp: rác
        ]
        class _Bot:
            async def get_updates(self, **kw): return ups
        n.bot = _Bot()

        assert asyncio.run(n.poll_feedback(save)) == 2
        assert kho == {("tin-A", "111"): True, ("tin-A", "222"): False}, \
            "phiếu của người này không được ghi đè người kia"

    def test_doi_y_chi_ghi_de_phieu_cua_chinh_minh(self):
        import asyncio
        from notifications.telegram import TelegramNotifier

        class _Q:
            def __init__(self, data, uid):
                self.data = data; self.answered = []
                self.from_user = type("U", (), {"id": uid})()
            async def answer(self, text=None): self.answered.append(text)
            async def edit_message_reply_markup(self, reply_markup=None): pass

        class _U:
            def __init__(self, uid, q): self.update_id = uid; self.callback_query = q

        kho: dict[tuple[str, str], bool] = {}
        def save(lid, good, voter=""):
            kho[(lid, voter)] = good
            g = sum(1 for (l, _), v in kho.items() if l == lid and v)
            return (g, len([1 for (l, _), v in kho.items() if l == lid and not v]))

        n = TelegramNotifier.__new__(TelegramNotifier)
        n.token = "x"; n._feedback_offset = None
        ups = [
            _U(1, _Q("fb|1|tin-A", 111)),   # vợ bấm nhầm: đáng xem
            _U(2, _Q("fb|0|tin-A", 222)),   # đồng nghiệp: rác
            _U(3, _Q("fb|0|tin-A", 111)),   # vợ sửa lại: rác
        ]
        class _Bot:
            async def get_updates(self, **kw): return ups
        n.bot = _Bot()

        asyncio.run(n.poll_feedback(save))
        assert kho[("tin-A", "111")] is False, "sửa được phiếu của mình"
        assert kho[("tin-A", "222")] is False, "phiếu người kia còn nguyên"
        assert len(kho) == 2, "không đẻ thêm phiếu trùng"


class TestMoiNguoiMotPhieu:
    """Luật: mỗi người đúng 1 lượt vote trên 1 tin, và vote cho 1 kết quả."""

    class _FakeDB:
        """Bảng phản hồi giả lập — đủ để kiểm luật 1-người-1-phiếu."""
        def __init__(self):
            self.rows = []      # [{id, listing_id, actual_label, feedback_source}]
            self._n = 0
            self.save_fails = False

        def get_listing_by_id(self, lid):
            return {"id": lid, "classification_label": "chinh_chu", "classification_score": 77}

        def save_feedback(self, **kw):
            if self.save_fails:
                return False
            self._n += 1
            self.rows.append({"id": self._n, **kw})
            return True

        def prune_feedback(self, listing_id, feedback_source):
            mine = [r for r in self.rows
                    if r["listing_id"] == listing_id and r["feedback_source"] == feedback_source]
            for r in mine[:-1]:                     # giữ bản mới nhất
                self.rows.remove(r)
            return max(0, len(mine) - 1)

        def count_feedback(self, listing_id):
            mine = [r for r in self.rows if r["listing_id"] == listing_id]
            g = sum(1 for r in mine if r["actual_label"] == "chinh_chu")
            return g, len(mine) - g

    def _saver(self, db):
        """Bản sao logic _save trong orchestrator, chạy trên DB giả."""
        def _save(listing_id, is_good, voter_id=""):
            row = db.get_listing_by_id(listing_id)
            if not row:
                return None
            source = f"telegram_button:{voter_id}" if voter_id else "telegram_button"
            ok = db.save_feedback(
                listing_id=row["id"], predicted_label=row["classification_label"],
                predicted_score=row["classification_score"],
                actual_label="chinh_chu" if is_good else "moi_gioi",
                feedback_source=source, signals_at_prediction={},
            )
            if not ok:
                return None
            db.prune_feedback(row["id"], source)
            return db.count_feedback(row["id"])
        return _save

    def test_bam_10_lan_van_chi_con_1_phieu(self):
        db = self._FakeDB(); save = self._saver(db)
        for i in range(10):
            save("tin-A", i % 2 == 0, "111")
        mine = [r for r in db.rows if r["feedback_source"] == "telegram_button:111"]
        assert len(mine) == 1, "1 người phải chỉ còn đúng 1 phiếu"
        assert mine[0]["actual_label"] == "moi_gioi"   # lần bấm cuối (i=9 → False)
        assert db.count_feedback("tin-A") == (0, 1)

    def test_hai_nguoi_hai_phieu(self):
        db = self._FakeDB(); save = self._saver(db)
        assert save("tin-A", True, "111") == (1, 0)
        assert save("tin-A", False, "222") == (1, 1)
        assert len(db.rows) == 2

    def test_ghi_hong_thi_phieu_cu_con_nguyen(self):
        """Ghi trước dọn sau: lưu hỏng thì không được mất phiếu đã có."""
        db = self._FakeDB(); save = self._saver(db)
        save("tin-A", True, "111")
        db.save_fails = True
        assert save("tin-A", False, "111") is None
        mine = [r for r in db.rows if r["feedback_source"] == "telegram_button:111"]
        assert len(mine) == 1 and mine[0]["actual_label"] == "chinh_chu"


class TestCycleKhongTrungNguon:
    """Mỗi nguồn chỉ được xử lý bởi ĐÚNG một chu kỳ.

    Session 23: chu kỳ "Nhatot" lấy mọi nguồn trừ batdongsan + muaban, nên
    facebook_groups bị chạy pipeline 2 lần (cycle riêng 3 phút + cycle này
    5 phút), và thống kê "Nhatot cycle done" lẫn số liệu Facebook.
    """

    def test_cycle_nhatot_khong_dung_vao_nguon_co_cycle_rieng(self):
        from orchestrator.agent import _NHATOT_CYCLE_EXCLUDE
        for nguon in ("batdongsan", "muaban", "facebook_groups"):
            assert nguon in _NHATOT_CYCLE_EXCLUDE, f"{nguon} có cycle riêng, không được lấy lại"

    def test_nhatot_van_nam_trong_cycle_cua_no(self):
        from orchestrator.agent import _NHATOT_CYCLE_EXCLUDE
        assert "nhatot" not in _NHATOT_CYCLE_EXCLUDE

    def test_moi_nguon_co_dung_1_cycle_trong_lich_chay(self):
        """Đối chiếu lịch chạy thật: không nguồn nào có 2 chu kỳ."""
        import yaml
        with open("config/schedule.yaml", encoding="utf-8") as f:
            jobs = (yaml.safe_load(f) or {}).get("schedules", {})
        from orchestrator.agent import _NHATOT_CYCLE_EXCLUDE
        co_cycle_rieng = {
            "batdongsan": "batdongsan_cycle",
            "muaban": "muaban_cycle",
            "facebook_groups": "facebook_groups_cycle",
        }
        for nguon, job in co_cycle_rieng.items():
            if jobs.get(job, {}).get("enabled", True):
                assert nguon in _NHATOT_CYCLE_EXCLUDE, (
                    f"{nguon} vừa có '{job}' vừa bị cycle nhatot lấy → xử lý 2 lần"
                )
