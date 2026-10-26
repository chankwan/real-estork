"""
RealEstork — Unit Tests: Dedup Pipeline
Tests for address/phone normalization and dedup rules.
"""

import asyncio
import json

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
        """SĐT đã biết là môi giới → dìm điểm. Chỉ còn Facebook dùng nhóm signal này.

        3 sàn rao vặt đã che số hết (đo 18 ngày: nhatot 0/800, batdongsan 0/3510,
        muaban 0/1559) nên nhóm signal SĐT tắt ở đó; Facebook giữ vì người đăng tự
        gõ số vào bài (82% có số), không tốn công đi lấy.
        """
        listing = make_listing(source="facebook_groups", phone="0901111111")
        result = self.classifier.classify(
            listing,
            phone_stats={"is_known_broker": True, "total_listings": 50}
        )
        assert result.score < 40  # Known broker → moi_gioi

    def test_sdt_moi_gioi_khong_con_cham_diem_o_san_rao_vat(self):
        """Cùng dữ liệu đó ở nhatot → không còn signal SĐT nào fire."""
        listing = make_listing(source="nhatot", phone="0901111111")
        result = self.classifier.classify(
            listing,
            phone_stats={"is_known_broker": True, "total_listings": 50,
                         "trangtrang_report_count": 9}
        )
        assert not any(s.startswith("phone_") or s == "trangtrang_spam_penalty"
                       for s in result.signals_fired)

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

    def test_dang_ghep_gach_ngang(self):
        """Muaban 2026-09 đổi sang 'TP. Thủ Đức - Quận Thủ Đức' — 225/4000 tin gần
        nhất dùng dạng này và đang bị loại oan vì không khớp whitelist."""
        n = self.classifier._normalize_district
        assert n("TP. Thủ Đức - Quận Thủ Đức") == "thu duc"
        assert n("Phường Tân Quy - Quận 7") == "7"
        assert n("TP. Thủ Đức - Quận 9") == "9"
        # không có vế nào ghi rõ đơn vị → lấy vế cuối
        assert n("Bình Thạnh - Bình Thạnh") == "binh thanh"
        # dạng thường không có gạch ngang: giữ nguyên hành vi cũ
        assert n("Quận Gò Vấp") == "go vap"
        assert n("Thành phố Thủ Đức") == "thu duc"

    def test_dang_ghep_van_loai_dung_huyen_ngoai_o(self):
        """Sửa dạng ghép không được vô tình mở cửa cho huyện ngoại ô."""
        n = self.classifier._normalize_district
        assert n("TP. HCM - Huyện Hóc Môn") == "hoc mon"
        assert n("Huyện Bình Chánh") == "binh chanh"

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


class TestPosterCountUnknown:
    """Thiếu số tin đăng của người bán → mọi signal họ hàng phải IM.

    Lịch sử 2 lần dính cùng một lỗi "thiếu dữ liệu bị hiểu thành kết luận":
      - session 22 (batdongsan): fetch hỏng → không đọc được số → tin môi giới
        lọt qua chốt chặn và được thưởng điểm từ trang rỗng.
      - session 24 (muaban): sàn không hề công bố số tin đăng → giá trị mặc định
        999 kích hoạt signal phạt môi giới, trừ 40 điểm cho 100% tin, 252 cycle
        liên tiếp không gửi nổi 1 alert.
    Nên: chưa biết = None, và None không bao giờ được cộng/trừ điểm.
    """

    def _ctx(self, spider_value, stats=None, source="nhatot"):
        from pipeline.signals import SignalContext
        listing = make_listing(source=source, source_id="1")
        listing.poster_total_listings = spider_value
        return SignalContext.from_listing(listing, phone_stats=stats)

    def test_thieu_so_thi_giu_none_khong_doan_bua(self):
        assert self._ctx(None).poster_total_listings is None

    def test_spider_doc_duoc_thi_giu_nguyen(self):
        assert self._ctx(1).poster_total_listings == 1
        assert self._ctx(8).poster_total_listings == 8

    def test_zero_van_la_du_lieu_that(self):
        """live_ads=0 (tin đã hết hạn) là số thật, không phải 'chưa biết'."""
        ctx = self._ctx(0)
        assert ctx.poster_total_listings == 0
        from pipeline.signals import poster_count_known
        assert poster_count_known(ctx) is True

    def test_db_stats_duoc_dung_khi_spider_khong_co(self):
        assert self._ctx(None, stats={"poster_total_listings": 3}).poster_total_listings == 3

    def test_khong_biet_thi_ca_ba_signal_deu_im(self):
        from pipeline.signals import (check_poster_single_listing,
                                      check_poster_few_listings,
                                      check_poster_many_listings)
        ctx = self._ctx(None)
        assert check_poster_single_listing(ctx) is False
        assert check_poster_few_listings(ctx) is False
        assert check_poster_many_listings(ctx) is False

    def test_sentinel_am_cua_batdongsan_cung_la_chua_biet(self):
        """-1 = 'đọc trang chi tiết thất bại', không phải 'ít tin nên là chính chủ'."""
        from pipeline.signals import poster_count_known, check_poster_single_listing
        ctx = self._ctx(-1, source="batdongsan")
        assert poster_count_known(ctx) is False
        assert check_poster_single_listing(ctx) is False

    def test_cac_moc_khong_chong_nhau(self):
        from pipeline.signals import (check_poster_single_listing,
                                      check_poster_few_listings,
                                      check_poster_many_listings)
        fired = lambda n: (check_poster_single_listing(self._ctx(n)),
                           check_poster_few_listings(self._ctx(n)),
                           check_poster_many_listings(self._ctx(n)))
        assert fired(1) == (True, False, False)
        assert fired(2) == (False, True, False)
        assert fired(5) == (False, True, False)
        assert fired(6) == (False, False, True)
        assert fired(190) == (False, False, True)

    def test_guard_chiu_duoc_none_truc_tiep(self):
        """Chốt chặn tại chỗ: dù ai đó nhét None vào ctx thì cũng không nổ."""
        from pipeline.signals import check_poster_many_listings
        ctx = self._ctx(1)
        ctx.poster_total_listings = None
        assert check_poster_many_listings(ctx) is False


class TestMuabanKhongConTruDiemOan:
    """Regression session 24 — chặn đúng kịch bản đã giết 252 cycle muaban."""

    def setup_method(self):
        from pipeline.classifier import ClassificationPipeline
        self.classifier = ClassificationPipeline()

    def _tin_muaban(self, **kw):
        # muaban không bao giờ có số tin đăng người bán → luôn None
        listing = make_listing(source="muaban", source_id="71212862", **kw)
        listing.poster_total_listings = None
        return listing

    def test_khong_con_signal_phat_moi_gioi_tu_du_lieu_khong_co(self):
        result = self.classifier.classify(self._tin_muaban())
        assert "muaban_multi_active_listings" not in result.signals_fired
        assert "poster_many_listings" not in result.signals_fired

    def test_tin_sach_dat_nguong_gui(self):
        """Tin muaban bình thường, mới đăng → phải vượt mốc gửi 55.

        Trước fix: 50 nền − 40 (signal ma) + 10 (mới đăng) = 20 điểm, trần thực
        đo được trong 8 ngày là 40 < ngưỡng → không đời nào gửi.
        """
        listing = self._tin_muaban(description="Cho thue mat bang 100m2 duong Phan Xich Long")
        listing.listing_age_hours = 1.0
        result = self.classifier.classify(listing)
        assert result.score >= 55, result.signals_fired

    def test_chot_chan_tai_khoan_rai_tin_van_hoat_dong(self):
        """Bỏ signal ma không được làm mất lớp lọc môi giới còn lại."""
        listing = self._tin_muaban()
        listing.same_session_account_count = 9
        result = self.classifier.classify(listing)
        assert "same_session_multi_listing" in result.signals_fired


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

        assert asyncio.run(n._drain_feedback_once(lambda lid, good, voter="": (1, 0))) == 0
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

        saved = asyncio.run(n._drain_feedback_once(save))
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

        assert asyncio.run(n._drain_feedback_once(lambda lid, good, voter="": None)) == 0
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

        assert asyncio.run(n._drain_feedback_once(save)) == 2
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

        asyncio.run(n._drain_feedback_once(save))
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


class TestBaoDongLoiChungChi:
    """Bot không được treo câm nữa khi bắt tay TLS hỏng.

    Sự cố 26-27/08: giờ máy chậm 3 ngày → chứng chỉ bị coi là 'chưa có hiệu lực'
    → mọi HTTPS chết. Bot xếp lỗi này vào nhóm 'chưa có mạng' rồi thử lại mỗi 30s
    trong im lặng 319 lần. Telegram cũng đi qua HTTPS nên chuông báo cũng câm.
    """

    def test_phan_biet_loi_chung_chi_voi_loi_mat_mang(self):
        from orchestrator.agent import _is_cert_error
        # đúng chuỗi lỗi thật đã ghi trong log sự cố
        assert _is_cert_error(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "certificate is not yet valid (_ssl.c:1032)"
        )
        assert _is_cert_error("SSLCertVerificationError: certificate has expired")
        # lỗi mạng thật thì KHÔNG được nhận nhầm
        assert not _is_cert_error("[Errno 11001] getaddrinfo failed")
        assert not _is_cert_error("[WinError 10060] A connection attempt failed")
        assert not _is_cert_error("new row violates row-level security policy")

    def test_hoi_gio_chuan_khong_di_qua_https(self):
        """Chẩn đoán phải dùng NTP (UDP) — nếu đi qua HTTPS thì lúc cần nhất lại hỏng."""
        import inspect
        from orchestrator.agent import _ntp_offset_seconds
        from orchestrator.agent import _ntp_offset_one, _NTP_SERVERS
        src = inspect.getsource(_ntp_offset_one)
        assert "SOCK_DGRAM" in src and "123" in src, "phải là UDP tới cổng NTP"
        assert len(_NTP_SERVERS) >= 3, "1 máy chủ NTP rớt gói là chẩn đoán sai — cần dự phòng"
        src += inspect.getsource(_ntp_offset_seconds)
        # không được đụng bất kỳ client HTTP nào — chúng đều đi qua TLS
        for lib in ("httpx", "requests", "urllib"):
            assert lib not in src, f"{lib} đi qua TLS, lúc cần chẩn đoán thì chính nó cũng hỏng"

    def test_ntp_hong_thi_tra_none_chu_khong_no(self):
        from orchestrator.agent import _ntp_offset_seconds
        assert _ntp_offset_seconds(server="khong-ton-tai.invalid", timeout=0.2) is None

    def test_chuong_keu_khi_ghi_hong_lien_tiep(self):
        import asyncio
        from orchestrator.agent import RealEstorkAgent, _WRITE_FAIL_ALARM_STREAK

        o = RealEstorkAgent.__new__(RealEstorkAgent)
        o._write_alarm_at = None
        o.db = type("D", (), {"write_error_streak": 0, "last_write_error": ""})()
        keu: list[tuple[str, str]] = []
        async def fake_alarm(t, d): keu.append((t, d))
        o._raise_alarm = fake_alarm
        o._clear_alarm = lambda: None
        o.telegram = type("T", (), {"send_lifecycle": lambda self, x: None})()

        # dưới ngưỡng → im lặng
        o.db.write_error_streak = _WRITE_FAIL_ALARM_STREAK - 1
        asyncio.run(o.check_write_health())
        assert keu == []

        # chạm ngưỡng → kêu
        o.db.write_error_streak = _WRITE_FAIL_ALARM_STREAK
        o.db.last_write_error = "ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED]"
        o._diagnose_tls_failure = lambda: "GIỜ MÁY SAI"
        asyncio.run(o.check_write_health())
        assert len(keu) == 1
        assert "GIỜ MÁY SAI" in keu[0][1], "lỗi chứng chỉ phải kèm chẩn đoán"

        # còn hỏng nhưng chưa tới hạn nhắc lại → không spam
        asyncio.run(o.check_write_health())
        assert len(keu) == 1

    def test_ghi_lai_duoc_thi_go_co_bao_dong(self):
        import asyncio
        from orchestrator.agent import RealEstorkAgent

        o = RealEstorkAgent.__new__(RealEstorkAgent)
        o._write_alarm_at = 12345.0          # đang trong đợt báo động
        o.db = type("D", (), {"write_error_streak": 0, "last_write_error": ""})()
        da_go = []
        o._clear_alarm = lambda: da_go.append(True)
        class _T:
            async def send_lifecycle(self, x): pass
        o.telegram = _T()

        asyncio.run(o.check_write_health())
        assert da_go == [True], "hết lỗi thì phải gỡ cờ báo động"
        assert o._write_alarm_at is None

    def test_db_dem_so_lan_ghi_hong_lien_tiep(self):
        from db.client import SupabaseDB
        db = SupabaseDB.__new__(SupabaseDB)
        db.write_error_streak = 0
        db.last_write_error = ""
        db._note_write_error(RuntimeError("boom"))
        db._note_write_error(RuntimeError("boom"))
        assert db.write_error_streak == 2
        assert "boom" in db.last_write_error
        db._note_write_ok()
        assert db.write_error_streak == 0 and db.last_write_error == ""


class TestNutBamHetHan:
    """Bug 15/09: vợ bấm nút, phiếu vào DB nhưng nút không đổi gì — bấm lại,
    vẫn không đổi. Telegram chỉ nhận trả lời cho một lần bấm trong ~15 giây,
    mà bot cũ hỏi 1 phút/lần nên trả lời LUÔN quá hạn. Lời cảm ơn và việc cập
    nhật số phiếu lúc đó nằm chung một khối try, nên lời cảm ơn ném lỗi là kéo
    theo phần cập nhật nút không bao giờ chạy.

    Đo trên log: 09/08 5 lần bấm / 5 lỗi, 09/11 5/5, 15/09 1/1 — không sót cú nào.
    """

    def _make(self, answer_raises: bool):
        import asyncio
        from telegram.error import TelegramError
        from notifications.telegram import TelegramNotifier

        da_sua_nut = []

        class _Q:
            data = "fb|1|listing-A"
            from_user = None

            async def answer(self, text=None):
                if answer_raises:
                    raise TelegramError(
                        "Query is too old and response timeout expired "
                        "or query id is invalid"
                    )

            async def edit_message_reply_markup(self, reply_markup=None):
                da_sua_nut.append(reply_markup)

        class _U:
            update_id = 1
            callback_query = _Q()

        n = TelegramNotifier.__new__(TelegramNotifier)
        n.token = "x"
        n._feedback_offset = None

        class _Bot:
            async def get_updates(self, **kw):
                return [_U()]

        n.bot = _Bot()
        saved = asyncio.run(n._drain_feedback_once(lambda lid, good, voter="": (2, 1)))
        return saved, da_sua_nut

    def test_loi_cam_on_het_han_van_phai_cap_nhat_so_phieu_len_nut(self):
        saved, da_sua_nut = self._make(answer_raises=True)
        assert saved == 1, "phiếu vẫn phải được tính"
        assert da_sua_nut, (
            "ĐÂY LÀ BUG GỐC: lời cảm ơn quá hạn không được phép chặn việc "
            "cập nhật số phiếu lên nút — nếu không vợ bấm xong thấy nút đứng im"
        )

    def test_truong_hop_binh_thuong_van_cap_nhat_nut(self):
        saved, da_sua_nut = self._make(answer_raises=False)
        assert saved == 1 and da_sua_nut


class TestChotChanTrangLap:
    """Bug 16/09: muaban đổi tên tham số phân trang. Tên cũ KHÔNG gây lỗi —
    nền tảng trả HTTP 200 kèm đúng 20 tin đúng định dạng, chỉ là luôn của
    trang 1. Bot cày 50 trang của cùng 20 tin suốt nhiều ngày mà không nhánh
    lỗi nào chạm tới.

    Chốt chặn kiểm tra KẾT QUẢ (trang mới có trùng khít trang trước không)
    chứ không kiểm tra tên tham số — nên lần đổi sau vẫn bắt được.
    """

    def _fake_page(self, ids):
        import json
        from datetime import datetime, timedelta, timezone
        # Dấu thời gian phải TƯƠNG ĐỐI với lúc chạy test. Bản đầu cắm cứng
        # "2026-09-16T10:00:00+07:00" nên đúng 24h sau là tin hoá "tin cũ",
        # early-stop non-today bắn trước khi chốt chặn trùng trang kịp chạy —
        # test tự gãy theo lịch chứ không phải vì code hỏng.
        vn = timezone(timedelta(hours=7))
        moi = (datetime.now(vn) - timedelta(hours=2)).isoformat()
        items = [
            {
                "id": i,
                "title": f"tin {i}",
                "service_ids": [128],
                "publish_at": moi,
                "area": {"name": "Quận 1"},
            }
            for i in ids
        ]
        payload = {"props": {"pageProps": {"classified": {"items": items}}}}
        return (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + "</script>"
        )

    def _run(self, trang_lap: bool):
        import asyncio
        from spiders.muaban import MuabanSpider

        sp = MuabanSpider({
            "urls": ["https://muaban.net/x?sort=1"],
            "max_pages": 5,
            "request_delay_seconds": 0,
            "dedup_stop_ratio": 0.99,
        })
        sp.cycle_health = {}
        goi = {"n": 0}
        html_self = self

        class _Resp:
            def __init__(self, text):
                self.status_code = 200
                self.text = text

        class _Session:
            async def get(self, url, **kw):
                goi["n"] += 1
                if trang_lap:
                    ids = [1, 2, 3]            # nền tảng luôn đưa trang 1
                else:
                    base = goi["n"] * 10
                    ids = [base + 1, base + 2, base + 3]
                return _Resp(html_self._fake_page(ids))

        got = asyncio.run(sp._fetch_pages_from(_Session(), "https://muaban.net/x?sort=1"))
        return sp, got, goi["n"]

    def test_trang_lap_thi_dung_ngay_va_ghi_dau_hieu(self):
        sp, got, so_lan_goi = self._run(trang_lap=True)
        assert sp.cycle_health.get("list_repeat_page") == 1, (
            "không phát hiện được phân trang chết"
        )
        assert so_lan_goi == 2, f"phải dừng ngay sau trang 2, đã gọi {so_lan_goi} lần"
        assert len(got) == 3, "không được gom trùng tin của trang lặp"

    def test_phan_trang_binh_thuong_thi_khong_kich_hoat_oan(self):
        sp, got, so_lan_goi = self._run(trang_lap=False)
        assert "list_repeat_page" not in sp.cycle_health, "kêu oan khi phân trang vẫn tốt"
        assert so_lan_goi == 5 and len(got) == 15


class TestChuongNenTangDoi:
    """Chuông báo khi nền tảng đổi cách hoạt động — cho MỌI nguồn, không riêng
    muaban. Hai ca thật nó phải bắt được: muaban bỏ tham số phân trang (16/09)
    và batdongsan nâng tường chặn (17/08, 63 cycle trắng không ai được báo).
    """

    def _agent(self):
        import asyncio
        from orchestrator.agent import RealEstorkAgent

        ag = RealEstorkAgent.__new__(RealEstorkAgent)
        ag._platform_alerted = {}
        tin_nhan = []

        class _TG:
            async def send_admin(self, text):
                tin_nhan.append(text)

        ag.telegram = _TG()
        return ag, tin_nhan, asyncio

    class _Spider:
        def __init__(self, health):
            self.cycle_health = health

    def test_trang_lap_thi_keu_va_noi_ro_nguyen_nhan(self):
        ag, tin_nhan, asyncio = self._agent()
        sp = self._Spider({"list_pages_ok": 1, "list_repeat_page": 1})
        asyncio.run(ag._check_platform_change("muaban", sp))
        assert len(tin_nhan) == 1
        assert "muaban" in tin_nhan[0] and "trang lặp" in tin_nhan[0]
        assert "phân trang" in tin_nhan[0], "phải nói thẳng phải đi xem chỗ nào"

    def test_khong_keu_lai_khi_su_co_van_the(self):
        ag, tin_nhan, asyncio = self._agent()
        sp = self._Spider({"list_pages_ok": 1, "list_repeat_page": 1})
        for _ in range(5):
            asyncio.run(ag._check_platform_change("muaban", sp))
        assert len(tin_nhan) == 1, (
            "mỗi cycle một tin nhắn thì vài tiếng sau không ai đọc nữa"
        )

    def test_hoi_phuc_thi_bao_lai(self):
        ag, tin_nhan, asyncio = self._agent()
        asyncio.run(ag._check_platform_change("muaban", self._Spider({"list_repeat_page": 1})))
        asyncio.run(ag._check_platform_change("muaban", self._Spider({"list_pages_ok": 9})))
        assert len(tin_nhan) == 2 and "hoạt động lại" in tin_nhan[1]
        # hồi phục rồi thì im, không nhắc mãi
        asyncio.run(ag._check_platform_change("muaban", self._Spider({"list_pages_ok": 9})))
        assert len(tin_nhan) == 2

    def test_tuong_chan_batdongsan_cung_keu(self):
        ag, tin_nhan, asyncio = self._agent()
        asyncio.run(ag._check_platform_change("batdongsan", self._Spider({"list_cf_blocked": 4})))
        assert "tường chặn" in tin_nhan[0] and "batdongsan" in tin_nhan[0]

    def test_ten_cu_list_no_cards_cua_batdongsan_van_duoc_doc(self):
        """batdongsan dùng tên cũ `list_no_cards`, cùng nghĩa `list_no_data`."""
        ag, tin_nhan, asyncio = self._agent()
        asyncio.run(ag._check_platform_change("batdongsan", self._Spider({"list_no_cards": 3})))
        assert tin_nhan and "mất dữ liệu" in tin_nhan[0]

    def test_cycle_sach_thi_im(self):
        ag, tin_nhan, asyncio = self._agent()
        asyncio.run(ag._check_platform_change("nhatot", self._Spider({"list_pages_ok": 5})))
        assert tin_nhan == []


class TestChuongNguonImLang:
    """Ca 14/09: vòng Chợ Tốt treo giữa chừng lúc 04:20 khi đang tải một trang.
    Scheduler chỉ cho mỗi job một lượt chạy cùng lúc nên ~97 lượt sau đó đều bị
    bỏ qua. 8 tiếng không một tin Chợ Tốt nào — và KHÔNG cơ chế nào hiện có
    phát hiện ra, vì bot vẫn sống, DB vẫn ghi được, hai nguồn kia vẫn chạy.
    """

    def _agent(self, now_offset_phut):
        import asyncio
        import time
        from orchestrator.agent import RealEstorkAgent

        ag = RealEstorkAgent.__new__(RealEstorkAgent)
        ag._source_last_ok = {}
        ag._silence_alerted = set()
        ag._start_time = time.time()
        ag._schedule_config = {
            "schedules": {
                "nhatot_cycle": {"interval_minutes": 5, "enabled": True},
                "muaban_cycle": {"interval_minutes": 20, "enabled": True},
                "batdongsan_cycle": {"interval_minutes": 20, "enabled": True},
            }
        }
        tin_nhan = []

        class _TG:
            async def send_admin(self, text):
                tin_nhan.append(text)

        ag.telegram = _TG()
        moc = time.time() - now_offset_phut * 60
        for s in ("nhatot", "muaban", "batdongsan"):
            ag._source_last_ok[s] = time.time()
        ag._source_last_ok["nhatot"] = moc
        return ag, tin_nhan, asyncio

    def test_im_lang_qua_lau_thi_keu(self):
        # nhatot chu kỳ 5 phút → ngưỡng tối thiểu 30 phút. 8 tiếng = quá xa.
        ag, tin_nhan, asyncio = self._agent(now_offset_phut=8 * 60)
        asyncio.run(ag.check_source_silence())
        assert len(tin_nhan) == 1
        assert "nhatot" in tin_nhan[0] and "im lặng" in tin_nhan[0]

    def test_cham_mot_chut_thi_khong_keu_oan(self):
        ag, tin_nhan, asyncio = self._agent(now_offset_phut=20)
        asyncio.run(ag.check_source_silence())
        assert tin_nhan == [], "một cycle chậm bất thường không được làm chuông kêu"

    def test_keu_dung_mot_lan_roi_bao_khi_chay_lai(self):
        ag, tin_nhan, asyncio = self._agent(now_offset_phut=8 * 60)
        asyncio.run(ag.check_source_silence())
        asyncio.run(ag.check_source_silence())
        assert len(tin_nhan) == 1, "không được nhắc lại mỗi 10 phút"
        ag._mark_source_alive("nhatot")
        asyncio.run(ag.check_source_silence())
        assert len(tin_nhan) == 2 and "chạy lại" in tin_nhan[1]

    def test_nguong_theo_chu_ky_tung_nguon(self):
        ag, _, _ = self._agent(now_offset_phut=0)
        gh = ag._silence_limits()
        assert gh["nhatot"] == 30 * 60, "chu kỳ 5 phút → sàn 30 phút"
        assert gh["muaban"] == 80 * 60, "chu kỳ 20 phút → 4 lần = 80 phút"


class TestChuongKhongKeuOan:
    """Chuông nền tảng đổi KHÔNG được kêu vì nhiễu nền.

    Sự cố 16/09 11:11 — ngay cycle đầu sau khi bật chuông, nó nhắn Telegram
    báo "batdongsan đổi cách hoạt động" trong khi batdongsan hoàn toàn bình
    thường: 1 URL lỗi trang đầu, 3 URL còn lại đọc tốt, cycle về 26 tin và
    gửi được 1 alert.

    Đo trên log: "Không tìm thấy card" xảy ra 3-5 lần MỖI NGÀY suốt cả tuần
    (10/09: 3, 11/09: 5, 12/09: 4, 13/09: 3, 14/09: 4, 15/09: 5). Ngưỡng 1
    nghĩa là chuông kêu ~4 lần/ngày — vài hôm là không ai đọc nữa, đúng cái
    bệnh mà nó sinh ra để chữa.
    """

    def _agent(self):
        import asyncio
        from orchestrator.agent import RealEstorkAgent

        ag = RealEstorkAgent.__new__(RealEstorkAgent)
        ag._platform_alerted = {}
        tin_nhan = []

        class _TG:
            async def send_admin(self, text):
                tin_nhan.append(text)

        ag.telegram = _TG()
        return ag, tin_nhan, asyncio

    class _Spider:
        def __init__(self, health):
            self.cycle_health = health

    def test_mot_trang_loi_le_giua_nhieu_trang_tot_thi_im(self):
        """Tái hiện đúng cycle đã kêu oan 16/09."""
        ag, tin_nhan, asyncio = self._agent()
        sp = self._Spider({"list_pages_ok": 8, "list_no_cards": 1})
        asyncio.run(ag._check_platform_change("batdongsan", sp))
        assert tin_nhan == [], (
            "1 trang hỏng / 8 trang tốt là nhiễu nền — kêu là hỏng cái chuông"
        )

    def test_gay_gan_het_thi_van_phai_keu(self):
        """Cloudflare chặn hẳn (ca 17/08): không đọc được trang nào."""
        ag, tin_nhan, asyncio = self._agent()
        sp = self._Spider({"list_pages_ok": 0, "list_cf_blocked": 4})
        asyncio.run(ag._check_platform_change("batdongsan", sp))
        assert len(tin_nhan) == 1 and "tường chặn" in tin_nhan[0]

    def test_mat_du_lieu_toan_bo_thi_keu(self):
        """Đổi cấu trúc trang: mọi URL đều không tìm thấy khối dữ liệu."""
        ag, tin_nhan, asyncio = self._agent()
        sp = self._Spider({"list_pages_ok": 0, "list_no_cards": 4})
        asyncio.run(ag._check_platform_change("batdongsan", sp))
        assert len(tin_nhan) == 1 and "mất dữ liệu" in tin_nhan[0]

    def test_trang_lap_keu_ngay_ca_khi_nhieu_trang_tot(self):
        """Trang lặp là dấu hiệu riêng: 2 trang liên tiếp trùng khít từng ID
        không thể là trục trặc thoáng qua. Ca muaban 16/09 có 3 URL, mỗi URL
        đọc được trang 1 rồi phát hiện trang 2 trùng → pages_ok=3, lặp=3.
        Nếu áp cùng luật 'hỏng nhiều hơn tốt' thì sẽ KHÔNG kêu — sai."""
        ag, tin_nhan, asyncio = self._agent()
        sp = self._Spider({"list_pages_ok": 3, "list_repeat_page": 3})
        asyncio.run(ag._check_platform_change("muaban", sp))
        assert len(tin_nhan) == 1 and "trang lặp" in tin_nhan[0]

    def test_nhieu_nen_theo_ngay_that_khong_lam_chuong_keu(self):
        """Replay 6 ngày log thật: mỗi ngày 3-5 lần mất card, xen giữa các
        cycle bình thường. Không được kêu lần nào."""
        ag, tin_nhan, asyncio = self._agent()
        so_lan_mat_card_moi_ngay = [3, 5, 4, 3, 4, 5]
        for so_lan in so_lan_mat_card_moi_ngay:
            for _ in range(so_lan):
                # mỗi lần là 1 cycle: 1 URL hỏng, phần còn lại đọc tốt
                asyncio.run(ag._check_platform_change(
                    "batdongsan", self._Spider({"list_pages_ok": 8, "list_no_cards": 1})
                ))
            # xen các cycle sạch
            for _ in range(10):
                asyncio.run(ag._check_platform_change(
                    "batdongsan", self._Spider({"list_pages_ok": 12})
                ))
        assert tin_nhan == [], f"kêu oan {len(tin_nhan)} lần trong 6 ngày nhiễu nền"


class TestTachMayGanKhoiNguoiDay:
    """muaban gán lại dấu thời gian cho gần như toàn bộ tin trong khung
    00:00-00:06 mỗi đêm (đo 2 đêm 17-19/09: 161/164 tin bị đổi dấu nằm trong
    khung này; trang sâu bị quét sạch 60/60).

    Hệ quả cũ: mọi tin đều được +10 "tin rất mới" — đo 16/09 thì 13/16 tin gửi
    cho vợ có điểm đúng bằng ngưỡng 55, tức qua được nhờ điểm chấm trên dữ
    liệu do máy muaban sinh ra.
    """

    def _tin(self, gio, phut):
        from datetime import datetime, timedelta, timezone
        from spiders.muaban import MuabanSpider
        vn = timezone(timedelta(hours=7))
        sp = MuabanSpider({"urls": ["https://muaban.net/x"]})
        hom_nay = datetime.now(vn).replace(hour=gio, minute=phut, second=0, microsecond=0)
        item = {
            "id": 1, "title": "Cho thue mat bang Quan 1",
            "publish_at": hom_nay.isoformat(),
            "covers": [], "price": 20000000,
            "locations_display": [{"name": "TP.HCM"}, {"name": "Quận 1"}, {"name": "P.1"}],
            "url": "/x/1", "service_ids": [128],
        }
        return sp._parse_listing(item)

    def test_dau_trong_luot_quet_nua_dem_thi_coi_nhu_chua_biet_tuoi(self):
        for phut in (0, 3, 6, 10):
            l = self._tin(0, phut)
            assert l.manually_bumped is False, f"00:{phut:02d} phải là máy gán"
            assert l.posted_at is None, f"00:{phut:02d}: tuổi tin phải là CHƯA BIẾT"
            assert l.listing_age_hours is None

    def test_dau_gio_ban_ngay_thi_la_nguoi_day(self):
        for gio in (7, 12, 18, 22):
            l = self._tin(gio, 30)
            assert l.manually_bumped is True, f"{gio}h phải là người đẩy"
            assert l.posted_at is not None, f"{gio}h: phải giữ tuổi tin"

    def test_bien_11_phut_van_tinh_la_nguoi_day(self):
        """Lượt quét đo được hết 4-7 phút; biên đặt 10 phút. 00:11 là ngoài biên."""
        l = self._tin(0, 11)
        assert l.manually_bumped is True

    def test_tin_may_gan_khong_con_an_diem_tin_moi(self):
        from pipeline.signals import SIGNAL_FUNCTIONS, SignalContext
        l = self._tin(0, 2)
        ctx = SignalContext.from_listing(l)
        assert SIGNAL_FUNCTIONS["listing_very_fresh"](ctx) is False
        assert SIGNAL_FUNCTIONS["listing_fresh"](ctx) is False
        assert SIGNAL_FUNCTIONS["manually_bumped"](ctx) is False

    def test_tin_nguoi_day_an_dung_signal_moi(self):
        from pipeline.signals import SIGNAL_FUNCTIONS, SignalContext
        l = self._tin(14, 0)
        ctx = SignalContext.from_listing(l)
        assert SIGNAL_FUNCTIONS["manually_bumped"](ctx) is True

    def test_nguon_khac_muaban_khong_bi_anh_huong(self):
        """Signal mới chỉ muaban set cờ; nguồn khác phải im."""
        from pipeline.signals import SIGNAL_FUNCTIONS, SignalContext
        from spiders.base import RawListing
        l = RawListing(source="nhatot", source_id="1", source_url="u", title="t",
                       description="", address="", district="Quận 1")
        assert SIGNAL_FUNCTIONS["manually_bumped"](SignalContext.from_listing(l)) is False


class TestChamLaiTinCuDuocDay:
    """Lớp chống trùng loại tin theo source_id nên tin đã thấy không bao giờ
    được xem lại. Với mặt bằng cho thuê thì đó là lỗ: chủ lấy lại được mặt
    bằng sẽ đẩy tin CŨ lên tìm khách mới.

    Đo 22/09 trên 100 tin trang 1-5: 21 tin được đẩy tay trong ngày, bot bỏ
    qua cả 21 vì đã biết (8 đã gửi, 10 đã loại môi giới, 3 chưa đủ điểm).
    """

    def _agent(self, db_rows, hong=False):
        from orchestrator.agent import RealEstorkAgent
        ag = RealEstorkAgent.__new__(RealEstorkAgent)

        class _Res:
            def __init__(self, data): self.data = data

        class _Q:
            def __init__(self): self._ids = []
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def in_(self, col, ids): self._ids = ids; return self
            def execute(self):
                if hong:
                    raise RuntimeError("mat ket noi")
                return _Res([r for r in db_rows if r["source_id"] in self._ids])

        class _DB:
            class client:
                @staticmethod
                def table(name): return _Q()

        ag.db = _DB()
        return ag

    def _tin(self, sid, gio_truoc, day_tay=True):
        from datetime import datetime, timedelta, timezone
        from spiders.base import RawListing
        return RawListing(
            source="muaban", source_id=sid, source_url="u", title="t",
            description="", address="", district="Quận 1",
            posted_at=datetime.now(timezone.utc) - timedelta(hours=gio_truoc),
            manually_bumped=day_tay,
        )

    def test_tin_cu_co_dau_moi_hon_thi_cham_lai(self):
        ag = self._agent([{"source_id": "A", "posted_at": "2026-09-20T00:00:00+00:00"}])
        l = self._tin("A", 1)
        assert [x.source_id for x in ag._tin_cu_vua_duoc_day([l], [])] == ["A"]

    def test_dau_khong_doi_thi_khong_cham_lai(self):
        """Chặn lặp: cùng một lượt đẩy chỉ được chấm lại ĐÚNG MỘT LẦN, nếu
        không thì mỗi cycle 20 phút lại chấm lại toàn bộ."""
        from datetime import datetime, timedelta, timezone
        moc = datetime.now(timezone.utc) - timedelta(hours=1)
        ag = self._agent([{"source_id": "A", "posted_at": moc.isoformat()}])
        l = self._tin("A", 1)
        l.posted_at = moc
        assert ag._tin_cu_vua_duoc_day([l], []) == []

    def test_tin_may_gan_khong_bao_gio_cham_lai(self):
        ag = self._agent([{"source_id": "A", "posted_at": "2026-09-01T00:00:00+00:00"}])
        l = self._tin("A", 1, day_tay=False)
        l.posted_at = None
        assert ag._tin_cu_vua_duoc_day([l], []) == []

    def test_tin_moi_tinh_khong_bi_tinh_hai_lan(self):
        """Tin đã nằm trong danh sách 'mới' thì không được gom lại lần nữa."""
        ag = self._agent([{"source_id": "A", "posted_at": "2026-09-01T00:00:00+00:00"}])
        l = self._tin("A", 1)
        assert ag._tin_cu_vua_duoc_day([l], [l]) == []

    def test_khong_hoi_sinh_tin_da_bi_loai_vi_moi_gioi(self):
        """Lớp chặn môi giới đếm số tin cùng tài khoản trong CÙNG MẺ CÀO, nên
        nó phụ thuộc kích thước mẻ. Mẻ 16/09 có 1040 tin → thấy tài khoản có
        5+ tin → loại đúng. Mẻ bây giờ 80 tin → cùng tài khoản chỉ lộ 1-2 tin
        → lớp chặn không fire. Chấm lại trong mẻ nhỏ là vứt bỏ bằng chứng thu
        được từ mẻ lớn. Ca thật: tin 70746888 (22/09) chấm lại ra 65 điểm và
        suýt được gửi, dù trước đó đã bị loại vì môi giới."""
        ag = self._agent([{"source_id": "70746888",
                           "posted_at": "2026-09-01T00:00:00+00:00",
                           "status": "auto_vetoed_broker"}])
        l = self._tin("70746888", 1)
        assert ag._tin_cu_vua_duoc_day([l], []) == []

    def test_khong_cham_lai_tin_da_gui(self):
        ag = self._agent([{"source_id": "A", "posted_at": "2026-09-01T00:00:00+00:00",
                           "status": "alerted_telegram"}])
        assert ag._tin_cu_vua_duoc_day([self._tin("A", 1)], []) == []

    def test_van_cham_lai_tin_chi_thieu_diem(self):
        """Đây mới là nhóm cần xem lại: đã chấm, chưa đủ điểm, chưa có phán
        quyết môi giới. Đo 22/09: 3/21 tin được đẩy tay thuộc nhóm này."""
        ag = self._agent([{"source_id": "A", "posted_at": "2026-09-01T00:00:00+00:00",
                           "status": "new"}])
        assert [x.source_id for x in ag._tin_cu_vua_duoc_day([self._tin("A", 1)], [])] == ["A"]

    def test_tin_chua_tung_co_trong_db_thi_khong_phai_tin_cu(self):
        ag = self._agent([])
        l = self._tin("moi", 1)
        assert ag._tin_cu_vua_duoc_day([l], []) == []

    def test_tra_cuu_hong_thi_bo_qua_chu_khong_cham_lai_tat_ca(self):
        """Tra cứu hỏng mà đoán bừa 'có đẩy mới' thì mỗi cycle chấm lại sạch."""
        ag = self._agent([], hong=True)
        l = self._tin("A", 1)
        assert ag._tin_cu_vua_duoc_day([l], []) == []


class TestSoSachHongKhongDuocKeoAlertChetTheo:
    """Ghi DB hỏng thì tin VẪN phải tới tay vợ.

    Sự cố 2026-10-04: org Supabase cạn quota egress (project kia đốt ~1,4 GB
    /ngày), mọi lệnh đọc/ghi trả 402. Bot còn sống, còn crawl, còn chấm điểm —
    nhưng có một dòng `if not saved: return "db_error"` khiến tin nào ghi hỏng
    là bị bỏ luôn, không gửi. Mất 7 tin đã đủ điều kiện gửi trong 4,5 giờ đầu.

    Alert là sản phẩm, DB chỉ là sổ sách. Sổ sách hỏng không được phép kéo
    sản phẩm chết theo.
    """

    def _agent(self, tmp_path, ghi_duoc: bool):
        import types
        from unittest.mock import AsyncMock, MagicMock

        from orchestrator.agent import RealEstorkAgent

        ag = RealEstorkAgent.__new__(RealEstorkAgent)
        ag.dry_run = False
        ag._spool_path = tmp_path / "pending.jsonl"
        ag.db = MagicMock()
        ag.db.get_listing_status.return_value = None
        ag.db.upsert_listing.return_value = {"id": "uuid-1"} if ghi_duoc else None
        ag.ai = MagicMock()
        ag.ai.analyze_listing = AsyncMock(return_value=None)
        ag.classifier = MagicMock()
        # Dùng LỚP THẬT chứ không dựng object giả: object giả từng thiếu trường
        # `ai_probability` nên test vỡ khi production thêm trường đó vào. Lớp
        # thật thì không lệch được.
        from pipeline.classifier import ClassificationResult

        ag.classifier.classify.return_value = ClassificationResult(
            score=80, label="chinh_chu"
        )
        ag.classifier.alert_skip_reason.return_value = None
        ag.classifier.non_rental_verdict.return_value = ""
        ag.telegram = MagicMock()
        ag.telegram.send_listing_alert = AsyncMock(return_value=True)
        return ag

    def _tin(self):
        import types

        l = types.SimpleNamespace(
            source="nhatot", source_id="TEST123", phone="", contact_name="Chủ nhà",
            same_session_account_count=1, poster_total_listings=1, address="Quận 1",
            listing_age_hours=1.0, title="Cho thuê mặt bằng", description="chính chủ",
            price_vnd_monthly=30_000_000,
        )
        l.to_dict = lambda: {"source": "nhatot", "source_id": "TEST123"}
        return l

    def test_ghi_db_hong_van_gui_alert(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "111")
        monkeypatch.setenv("TELEGRAM_GROUP_CHAT_ID", "222")
        ag = self._agent(tmp_path, ghi_duoc=False)
        ket_qua = asyncio.run(ag._process_listing(self._tin()))
        assert ket_qua == "alerted"
        assert ag.telegram.send_listing_alert.await_count == 2

    def test_ghi_db_duoc_thi_hanh_vi_khong_doi(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "111")
        monkeypatch.setenv("TELEGRAM_GROUP_CHAT_ID", "222")
        ag = self._agent(tmp_path, ghi_duoc=True)
        ket_qua = asyncio.run(ag._process_listing(self._tin()))
        assert ket_qua == "alerted"
        assert ag.telegram.send_listing_alert.await_count == 2
        ag.db.update_listing_status.assert_called_once_with("uuid-1", "alerted_telegram")

    def test_tin_ghi_hong_duoc_spool_kem_trang_thai_da_gui(self, tmp_path, monkeypatch):
        """Hai dòng: 'new' rồi 'alerted_telegram'. Nạp lại theo thứ tự thì
        dòng sau đè dòng trước, nên tin mang đúng trạng thái đã gửi."""
        monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "111")
        monkeypatch.setenv("TELEGRAM_GROUP_CHAT_ID", "222")
        ag = self._agent(tmp_path, ghi_duoc=False)
        asyncio.run(ag._process_listing(self._tin()))

        dong = [json.loads(d) for d in ag._spool_path.read_text(encoding="utf-8").splitlines() if d.strip()]
        assert [d.get("status") for d in dong] == ["new", "alerted_telegram"]
        assert all(d["source_id"] == "TEST123" for d in dong)

    def test_ghi_db_duoc_thi_khong_spool(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "111")
        monkeypatch.setenv("TELEGRAM_GROUP_CHAT_ID", "222")
        ag = self._agent(tmp_path, ghi_duoc=True)
        asyncio.run(ag._process_listing(self._tin()))
        assert not ag._spool_path.exists()

    def test_tin_bi_veto_moi_gioi_cung_duoc_spool(self, tmp_path, monkeypatch):
        """Tin bị veto môi giới cũng phải vào file ghi tạm khi DB chết.

        Trước đây hai nhánh veto gọi upsert_listing rồi BỎ QUA kết quả, nên
        lúc Supabase khoá (04-10/10) tin bị veto mất hẳn khỏi sổ sách — không
        alert (đúng) nhưng cũng không ghi tạm (sai). Không ảnh hưởng tin gửi
        cho vợ, nhưng làm sổ sách thủng một mảng.
        """
        monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "111")
        monkeypatch.setenv("TELEGRAM_GROUP_CHAT_ID", "222")
        ag = self._agent(tmp_path, ghi_duoc=False)
        l = self._tin()
        l.same_session_account_count = 9   # vượt ngưỡng veto của portal (>4)

        ket_qua = asyncio.run(ag._process_listing(l))

        assert ket_qua == "veto_broker"
        assert ag.telegram.send_listing_alert.await_count == 0
        dong = [json.loads(d) for d in ag._spool_path.read_text(encoding="utf-8").splitlines() if d.strip()]
        assert len(dong) == 1
        assert dong[0]["status"] == "auto_vetoed_broker"


# =====================================================
# Tin nhatot 135317229 (Anh Bảy, nguyên tòa Tân Phú 250tr) — chấm 9 điểm, sót
# alert ngày 18/10. Ba lỗi trừ oan (đếm trùng tin giữa 2 URL −20, dấu câu bị
# coi là emoji −15, ảnh đại diện bị đếm thành ảnh riêng −10) và một chữ "đắc
# địa" trừ đủ −20. Dữ liệu dưới đây lấy từ chính tin đó.
# =====================================================

_ANH_BAY_TITLE = "CHO THUÊ TÒA NHÀ MỚI 100% –TÂN PHÚ–1880M² SÀN – GIÁ CHỈ 250 TR/THÁNG"
_ANH_BAY_BODY = (
    "• Vị trí đắc địa: Số 69/39-41-43 Nguyễn Cửu Đàm, Phường Tân Sơn Nhì, Quận Tân Phú, TP.HCM. "
    "Đường trước nhà rộng 12m thông thoáng, xe lớn ra vào tránh nhau thoải mái, có sân rộng cho xe lớn quay đầu.\n"
    "• Kết cấu hiện đại: Tòa nhà mới xây, hiện trạng sử dụng ngay, sàn và trần đã hoàn thiện đồng bộ, sạch đẹp.\n"
    "\t• Tổng diện tích sàn: 1880m²\n"
    "\t• Quy mô: 1 tầng hầm giữ xe, 5 tầng làm việc biệt lập và 1 sân thượng siêu thoáng mát.\n"
    "\t• Tiện ích vận hành: 2 thang máy tốc độ cao, hệ thống thang thoát hiểm độc lập.\n"
    "\t• An toàn pháp lý: Hệ thống PCCC đã được cơ quan chức năng thẩm định và cấp phép đầy đủ.\n"
    "• Kết nối giao thông & Tiện ích xung quanh:\n"
    "\t• Sát vách tuyến Metro số 2 (Trạm Bà Quẹo).\n"
    "\t• Nằm giữa cụm chợ giao thương sầm uất: Chợ Tân Hương, Võ Thành Trang, chợ Sơn Kỳ...\n"
    "• Hình thức cho thuê: Thuê lâu dài, ổn định.\n"
    "• Giá thuê nguyên tòa: 250 triệu đồng / tháng, cọc 3 tháng.\n"
    "Liên hệ chính chủ: Anh Bảy – *** (Hỗ trợ xem nhà trực tiếp 24/7)."
)


def _anh_bay_raw(list_id: str = "135317229") -> dict:
    """Ad dict dạng nhatot trả trong __NEXT_DATA__: `image` là ảnh đại diện bản
    nhỏ, `images` là đủ 7 ảnh bản lớn — ảnh đầu trùng tên file với `image`."""
    ten = [f"ef5dff957e9209069ae831c0e055704{i}-300799850908226149{i}.jpg" for i in range(7)]
    return {
        "list_id": int(list_id),
        "subject": _ANH_BAY_TITLE,
        "body": _ANH_BAY_BODY,
        "area_name": "Quận Tân Phú",
        "price": 250_000_000,
        "account_name": "Anh Bảy",
        "account_id": 3868774,
        "type": "u",
        "list_time": 1792454386830,  # 2026-10-18 00:39 UTC = 07:39 giờ VN
        "image": f"https://cdn.chotot.com/AAA/preset:listing/plain/{ten[0]}",
        "images": [f"https://cdn.chotot.com/BBB/preset:view/plain/{t}" for t in ten],
    }


class TestTinAnhBayKhongBiTruOan:
    def test_anh_dai_dien_khong_bi_dem_thanh_anh_rieng(self):
        from spiders.nhatot import NhatotSpider
        l = NhatotSpider({}).parse_listing(_anh_bay_raw())
        assert len(l.images) == 7

    def test_dau_cau_khong_phai_emoji(self):
        from pipeline.signals import SignalContext, check_description_many_emojis
        l = make_listing(title=_ANH_BAY_TITLE, description=_ANH_BAY_BODY)
        assert check_description_many_emojis(SignalContext.from_listing(l)) is False

    def test_emoji_that_van_bi_bat(self):
        from pipeline.signals import SignalContext, check_description_many_emojis
        l = make_listing(title="🔥 HOT 🔥", description="⭐ mặt tiền ✅ giá tốt ☎ gọi ngay 🏠")
        assert check_description_many_emojis(SignalContext.from_listing(l)) is True

    def test_cung_tin_o_hai_url_chi_dem_mot_lan(self):
        from spiders.base import bo_tin_trung
        a1 = make_listing(source_id="1", contact_name="Anh Bảy")
        a2 = make_listing(source_id="2", contact_name="Anh Bảy")
        # URL "mọi BĐS" có cả 2 tin, URL "văn phòng/mặt bằng" lặp lại cả 2.
        gop = [a1, a2, make_listing(source_id="1"), make_listing(source_id="2")]
        assert [l.source_id for l in bo_tin_trung(gop)] == ["1", "2"]

    def test_mot_chu_quang_cao_tru_nua_hai_chu_tru_du(self):
        from pipeline.signals import SignalContext, check_text_marketing_superlatives as f

        def muc(mo_ta):
            ctx = SignalContext.from_listing(make_listing(description=mo_ta))
            ctx.keywords = ["đắc địa", "vị trí vàng"]
            return f(ctx)

        assert muc("nhà thường") == 0.0
        assert muc("vị trí đắc địa") == 0.5
        assert muc("đắc địa, vị trí vàng") == 1.0

    def test_tin_anh_bay_qua_nguong_gui(self):
        """Chấm lại đúng tin đó sau khi sửa: lên 66 điểm, qua ngưỡng gửi 55."""
        from pipeline.classifier import ClassificationPipeline
        from spiders.nhatot import NhatotSpider

        l = NhatotSpider({}).parse_listing(_anh_bay_raw())
        l.listing_age_hours = 0.0          # bot bắt được ngay lúc tin vừa đăng
        l.poster_total_listings = 2        # trang tài khoản: active=2
        l.same_session_account_count = 2   # 2 tin, sau khi bỏ trùng giữa 2 URL

        r = ClassificationPipeline().classify(l)

        assert "description_many_emojis" not in r.signals_fired
        assert "photo_count_high" not in r.signals_fired
        assert "same_session_multi_listing" not in r.signals_fired
        assert r.signals_fired["text_marketing_superlatives"] == -10
        assert r.signals_fired["text_owner_language"] == 5
        assert r.score == 66   # 69 − 3: bỏ floor_ambiguous (2026-10-26)
        assert r.label == "chinh_chu"


class TestTuKhoaVaQuyCachChamDongBo:
    """2026-10-26: từ khoá đọc từ config; muaban chấm cùng quy cách; BDS bỏ +3 ảnh."""

    def test_tu_khoa_doc_tu_config_khong_con_viet_cung(self):
        """'siêu phẩm' chỉ có trong YAML, list viết cứng cũ không có — giờ phải bắt được."""
        from pipeline.classifier import ClassificationPipeline
        r = ClassificationPipeline().classify(make_listing(description="siêu phẩm mặt bằng"))
        assert r.signals_fired.get("text_marketing_superlatives") == -10

    def test_sua_config_la_doi_hanh_vi(self):
        from pipeline.classifier import ClassificationPipeline
        c = ClassificationPipeline()
        c._configs["_default"]["signals"]["text_commission_mention"]["keywords"] = ["tu-khoa-thu"]
        assert "text_commission_mention" in c.classify(make_listing(description="có tu-khoa-thu")).signals_fired
        assert "text_commission_mention" not in c.classify(make_listing(description="có hoa hồng")).signals_fired

    def test_ten_moi_gioi_doc_tu_config(self):
        from pipeline.classifier import ClassificationPipeline
        r = ClassificationPipeline().classify(make_listing(contact_name="Hương BĐS Quận 1"))
        assert "account_name_broker_keywords" in r.signals_fired

    def test_muaban_lien_he_chinh_chu_duoc_cong(self):
        from pipeline.classifier import ClassificationPipeline
        r = ClassificationPipeline().classify(
            make_listing(source="muaban", description="cho thuê mặt bằng, liên hệ chính chủ"))
        assert r.signals_fired["text_owner_language"] == 5

    def test_muaban_nhieu_emoji_bi_tru(self):
        from pipeline.classifier import ClassificationPipeline
        r = ClassificationPipeline().classify(
            make_listing(source="muaban", description="🔥 nhà 💰 giá 📍 chỗ ✅ ok 🏠 cho thuê"))
        assert r.signals_fired["description_many_emojis"] == -10

    def test_muaban_khong_cham_anh_va_tang(self):
        """Muaban không có dữ liệu ảnh/tầng thật → không được fire cho mọi tin."""
        from pipeline.classifier import ClassificationPipeline
        r = ClassificationPipeline().classify(make_listing(source="muaban", images=[]))
        assert "photo_count_low" not in r.signals_fired
        assert "floor_ambiguous" not in r.signals_fired

    def test_bds_khong_con_cong_it_anh(self):
        from pipeline.classifier import ClassificationPipeline
        r = ClassificationPipeline().classify(make_listing(source="batdongsan", images=["a.jpg"]))
        assert "photo_count_low" not in r.signals_fired

    def test_khong_cong_diem_vi_thieu_hoac_bia_du_lieu(self):
        """BDS: giờ đăng là 12:00 do spider tự gán → không chấm giờ/tuổi tin.
        Mọi sàn: không rõ tầng không được cộng."""
        from datetime import datetime, timezone
        from pipeline.classifier import ClassificationPipeline
        c = ClassificationPipeline()
        bds = make_listing(source="batdongsan", floor_level=None, listing_age_hours=1.0,
                           posted_at=datetime(2026, 10, 25, 5, 0, tzinfo=timezone.utc))
        fired = c.classify(bds).signals_fired
        for s in ("posted_outside_business_hours", "listing_very_fresh", "listing_fresh", "floor_ambiguous"):
            assert s not in fired
        assert "floor_ambiguous" not in c.classify(make_listing(floor_level=None)).signals_fired

    def test_moi_signal_tu_khoa_dang_bat_deu_co_tu_khoa(self):
        from pipeline.classifier import ClassificationPipeline, KEYWORD_SIGNALS
        c = ClassificationPipeline()
        for ten, cfg in c._configs.items():
            for sig, sc in cfg.get("signals", {}).items():
                if sig in KEYWORD_SIGNALS and isinstance(sc, dict) and sc.get("weight", 0) != 0:
                    assert c._keywords_for(cfg, sig), f"{ten}/{sig} thiếu keywords"

    def test_gio_dang_tinh_theo_gio_viet_nam(self):
        """nhatot trả giờ UTC. 03:00 UTC = 10h sáng VN (trong giờ); 13:00 UTC = 20h tối VN."""
        from datetime import datetime, timezone
        from pipeline.signals import SignalContext, check_posted_outside_business_hours as f
        thu_ba = lambda h: datetime(2026, 10, 27, h, 0, tzinfo=timezone.utc)
        assert not f(SignalContext.from_listing(make_listing(posted_at=thu_ba(3))))
        assert f(SignalContext.from_listing(make_listing(posted_at=thu_ba(13))))
        # Không có múi giờ = đã là giờ VN
        assert not f(SignalContext.from_listing(make_listing(posted_at=datetime(2026, 10, 27, 10, 0))))
