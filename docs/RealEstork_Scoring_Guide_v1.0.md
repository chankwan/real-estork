# RealEstork — Hướng dẫn cơ chế lọc & chấm điểm
**Phiên bản:** v1.0 — 2026-04-22
**Mục đích:** Giải thích cách hệ thống thu thập tin & chấm điểm chính chủ/môi giới để vợ có thể feedback tối ưu công thức.

---

## Tổng quan cách hoạt động

Hệ thống chạy tự động 24/7, quét 3 sàn bất động sản mỗi 20–30 phút. Mỗi tin đăng được:

1. **Thu thập** — Đọc thông tin từ trang web
2. **Lọc trùng** — Bỏ qua tin đã xử lý lần trước
3. **Chấm điểm** — Tính điểm 0–100 dựa trên các dấu hiệu nhận biết
4. **Alert** — Gửi Telegram nếu điểm đủ cao & đúng khu vực & đăng trong 24h

---

## Điểm chấm — Cách đọc kết quả

| Nhãn | Điểm | Ý nghĩa |
|------|------|---------|
| 🟢 **Chính chủ** | ≥ 65 | Dấu hiệu mạnh là chủ nhà thật |
| 🟡 **Cần xác minh** | 40–64 | Chưa đủ dấu hiệu, nên gọi kiểm tra |
| 🔴 **Môi giới** | < 40 | Nhiều dấu hiệu là trung gian |

**Điểm khởi đầu: 50** (trung tính — chưa biết là ai).
Mỗi dấu hiệu phát hiện được sẽ cộng hoặc trừ điểm vào đây.

---

## Bộ lọc trước khi alert vợ

Dù điểm cao, tin vẫn **không được gửi** nếu:
- Đăng quá 24 giờ trước
- Giá dưới 15 triệu/tháng
- Quận không nằm trong danh sách 16 quận trung tâm (Q1–Q11, Bình Thạnh, Phú Nhuận, Tân Bình, Thủ Đức, Gò Vấp)
- Điểm dưới 55

> **Muốn thay đổi điều kiện lọc?** Ví dụ: chỉ nhận mặt tiền, nâng/hạ giá sàn, thêm/bớt quận → báo trực tiếp.

---

## Sàn 1 — Nhatot.com (chotot.com)

### Cách lấy tin
- **URL đang quét:** Cho thuê BĐS TPHCM, giá từ 15 triệu, chỉ tài khoản cá nhân (lọc sẵn từ phía Nhatot — `f=p`)
- **Cách đọc:** Đọc dữ liệu nhúng trong trang web (không cần đăng nhập), mỗi trang 20 tin
- **Số điện thoại:** Không lấy được (tài khoản Chotot bị khóa do quét quá nhiều). Tin hiển thị "🔒 SĐT ẩn — mở app nhatot"
- **Chu kỳ:** Mỗi 20 phút

### Thông tin thu thập được mỗi tin
| Thông tin | Có không? | Ghi chú |
|-----------|-----------|---------|
| Tiêu đề, mô tả | ✅ | Đầy đủ |
| Địa chỉ, quận | ✅ | |
| Giá, diện tích | ✅ | |
| Ảnh | ✅ | |
| Tên người đăng | ✅ | |
| **Loại tài khoản** | ✅ | Nhatot phân loại sẵn: Cá nhân / Doanh nghiệp |
| **Số tin đang đăng** | ✅ | Lấy từ profile người đăng (`seller_info.live_ads`) |
| Số điện thoại | ❌ | Tạm mất — tài khoản Chotot bị khóa |
| Năm gia nhập | ❌ | Không có trên Nhatot |

### Bảng điểm Nhatot

#### Dấu hiệu Chính chủ (cộng điểm)
| Dấu hiệu | Điểm | Giải thích | Feedback? |
|----------|------|-----------|-----------|
| **Nhatot xác nhận tài khoản Cá nhân** | +25 | Platform tự phân loại, rất đáng tin | |
| **Account mới hoặc ít tin** (≤ 2 tin đang đăng) | +14 | Chủ nhà thường chỉ có 1-2 mặt bằng | |
| **Viết không dấu / nhiều lỗi chính tả** | +15 | Chủ nhà gõ nhanh trên điện thoại, không copy-paste | |
| **Đăng ngoài giờ hành chính** (trước 8h, sau 18h, hoặc cuối tuần) | +8 | Chủ nhà đăng sau giờ làm việc | |
| **Mô tả dùng ngôn ngữ chính chủ** | +5 | "nhà tôi", "chủ nhà cho thuê", "không qua trung gian"… | ⬅ Nên tăng? |
| **Ít ảnh** (≤ 5 ảnh) | +5 | Chủ nhà chụp nhanh, không pro | |
| **Mô tả rất ngắn** (< 50 ký tự) | +5 | Chủ nhà ghi qua loa | |
| **Tin rất mới** (< 2 giờ) | +10 | Ưu tiên cao nhất | |
| **Tin trong ngày** (2–24 giờ) | +5 | | |
| **Tầng trệt / tầng 1** | +8 | Mặt bằng kinh doanh tốt nhất | |
| **Không rõ tầng** | +3 | Chủ nhà thường lười ghi | |
| AI phân tích text | 0–30 | Phụ thuộc setup (hiện chưa hoạt động) | |

#### Dấu hiệu Môi giới (trừ điểm)
| Dấu hiệu | Điểm | Giải thích | Feedback? |
|----------|------|-----------|-----------|
| **Nhatot xác nhận tài khoản Doanh nghiệp** | -25 | Platform tự phân loại | |
| **Lịch sử đăng ≥ 20 tin** | -30 | Rõ ràng môi giới chuyên nghiệp | |
| **Tên tài khoản chứa từ môi giới** | -20 | "BĐS Quỳnh Hương", "Địa ốc ABC", "Công ty XYZ"… | ⬅ Bổ sung tên? |
| **Cùng 1 account đăng > 2 tin trong 1 lần quét** | -20 | Broker thường đăng hàng loạt | |
| **Mô tả dùng ngôn ngữ marketing thổi phồng** | -20 | "siêu phẩm", "vị trí vàng", "không thể bỏ lỡ"… | ⬅ Bổ sung từ? |
| **Nhắc đến hoa hồng** | -15 | "hoa hồng 1 tháng", "commission"… | |
| **Nhiều emoji** (≥ 5 cái) | -15 | Format marketing của môi giới | |
| **Nhiều ảnh** (≥ 8 ảnh) | -10 | Chụp chuyên nghiệp | |
| **Ngôn ngữ môi giới** | -10 | "hotline:", "zalo:", "chuyên BĐS"… | |
| **Tin đăng lại** (> 7 ngày tuổi) | -15 | Môi giới tái đăng | |
| **Lầu 3 trở lên** | -5 | Ít nhu cầu | |
| **Mô tả quá dài** (> 500 ký tự) | -5 | Copy-paste marketing | |

---

## Sàn 2 — Batdongsan.com.vn

### Cách lấy tin
- **URL đang quét:** Cho thuê nhà mặt phố TPHCM, lọc theo loại hình: Kho, Nhà xưởng, Đất thương mại, Shophouse
- **Cách đọc:** Dùng trình duyệt ẩn danh (bypass Cloudflare), đọc trang danh sách + vào từng trang chi tiết
- **Số điện thoại:** Không lấy được (quá phức tạp, tạm bỏ qua)
- **Chu kỳ:** Mỗi 20 phút

### Đặc điểm xử lý BĐS
- **Tin VIP (quảng cáo trả tiền):** Chỉ lấy nếu đăng hôm nay + chưa thấy trước đó. VIP cũ → bỏ qua nhanh, không mất thời gian
- **Tin môi giới chuyên nghiệp (có badge):** Bỏ qua, lưu vào database nhãn "Confirmed Broker" để thống kê
- **Dừng quét sớm:** Gặp tin thường không phải hôm nay → dừng trang đó, không quét thêm

### Thông tin thu thập được mỗi tin
| Thông tin | Có không? | Ghi chú |
|-----------|-----------|---------|
| Tiêu đề, địa chỉ, giá, diện tích | ✅ | Từ trang danh sách |
| **Mô tả đầy đủ** | ✅ | Từ trang chi tiết |
| **Tên người đăng** | ✅ | Từ trang chi tiết |
| **Số tin đang đăng** | ✅ | Sidebar trang chi tiết: "Tin đăng đang có X" |
| **Link trang cá nhân** | Một phần | Không phải ai cũng có (guru.batdongsan.com.vn) |
| **Năm gia nhập** | Một phần | Chỉ có khi tìm thấy trang cá nhân |
| Số điện thoại | ❌ | Tạm bỏ |

### Bảng điểm BĐS
*BĐS dùng ngưỡng nới lỏng hơn (chính chủ ≥ 60 thay vì 65) vì thiếu một số tín hiệu so với Nhatot.*

#### Dấu hiệu Chính chủ (cộng điểm)
| Dấu hiệu | Điểm | Giải thích | Feedback? |
|----------|------|-----------|-----------|
| **Chỉ có 1 tin đang đăng** | +10 (+15 stack) | Người bình thường hiếm khi có nhiều | |
| **Có 1–5 tin đăng** | +15 | Chủ có vài BĐS — vẫn chấp nhận được | ⬅ Ngưỡng phù hợp? |
| **Mô tả dùng ngôn ngữ chính chủ** | +5 | Tương tự Nhatot | |
| **Viết không dấu** | +10 | Chủ nhà gõ nhanh | |
| **Đăng ngoài giờ hành chính** | +5 | | |
| **Tin rất mới** (< 2h) | +10 | | |
| **Tin trong ngày** (2–24h) | +5 | | |
| **Tầng trệt** | +8 | | |
| **Không rõ tầng** | +3 | | |
| **Mô tả ngắn** | +5 | | |

#### Dấu hiệu Môi giới (trừ điểm)
| Dấu hiệu | Điểm | Giải thích | Feedback? |
|----------|------|-----------|-----------|
| **Có > 5 tin đăng** | -30 | Broker chuyên nghiệp | ⬅ Ngưỡng 5 có đúng không? |
| **Tên tài khoản chứa từ môi giới** | -25 | Mạnh hơn Nhatot vì BĐS có nhiều "Quỳnh Hương BĐS" | |
| **Cùng 1 người đăng > 2 tin/lần quét** | -30 | | |
| **Gia nhập ≥ 3 năm** (nếu có trang cá nhân) | -10 | Dấu hiệu phụ — broker lâu năm | ⬅ Có phù hợp không? |
| **Mô tả marketing thổi phồng** | -20 | | |
| **Nhắc hoa hồng** | -15 | | |
| **Ngôn ngữ môi giới** | -10 | | |
| **Nhiều emoji** | -15 | | |
| **Nhiều ảnh** (≥ 8) | -3 | Giảm nhẹ vì BĐS lớn hay có nhiều ảnh | |
| **Mô tả quá dài** | -5 | | |

---

## Sàn 3 — Muaban.net

### Cách lấy tin
- **URL đang quét:** Cho thuê văn phòng/mặt bằng TPHCM, giá 15–100 triệu, sắp xếp mới nhất
- **Cách đọc:** Dùng kỹ thuật giả lập Firefox (nhẹ hơn BĐS, không cần trình duyệt thật)
- **Số điện thoại:** ✅ **Lấy được miễn phí** — Muaban nhúng số điện thoại trong trang chi tiết, không cần đăng nhập
- **Chu kỳ:** Mỗi 30 phút

### Thông tin thu thập được mỗi tin
| Thông tin | Có không? | Ghi chú |
|-----------|-----------|---------|
| Tiêu đề, địa chỉ, giá, diện tích | ✅ | |
| **Số điện thoại** | ✅ | Từ trang chi tiết, miễn phí |
| **Tên người đăng** | ✅ | Từ trang chi tiết |
| Mô tả đầy đủ | ✅ | |
| **Avatar (ảnh đại diện)** | ✅ | Dùng để phát hiện tài khoản mới |
| Số tin đang đăng | ❌ | API trả về lỗi, chưa lấy được |
| Loại tài khoản | ❌ | Không đáng tin trên Muaban |

### Bảng điểm Muaban

*Muaban dùng bộ chấm riêng vì thiếu một số tín hiệu, và có thêm tín hiệu đặc thù.*

#### Dấu hiệu Chính chủ (cộng điểm)
| Dấu hiệu | Điểm | Giải thích | Feedback? |
|----------|------|-----------|-----------|
| **Tên tài khoản là số điện thoại** | +20 | Rất đặc trưng của chủ nhà bình thường | ⬅ Chính xác không? |
| **Ảnh đại diện trống** (dùng ảnh mặc định) | +15 | Chủ nhà mới lập tài khoản, chưa upload ảnh | ⬅ Có nhiều false positive? |
| **Ít tin đăng** (< 5 tin) | +20 | | ⬅ Ngưỡng 5 phù hợp? |
| **Viết không dấu** | +15 | | |
| **Đăng ngoài giờ hành chính** | +8 | | |
| **Tin rất mới** (< 2h) | +10 | | |
| **Tầng trệt** | +8 | | |

#### Dấu hiệu Môi giới (trừ điểm)
| Dấu hiệu | Điểm | Giải thích | Feedback? |
|----------|------|-----------|-----------|
| **≥ 5 tin đăng** | -40 | Ngưỡng được duyệt | ⬅ Có quá gắt không? |
| **Tên tài khoản chứa từ môi giới** | -30 | | |
| **Mô tả marketing** | -20 | | |
| **Tin VIP (trả phí đăng nổi bật)** | -10 | Nhẹ — chủ nhà cũng có thể mua VIP | |
| **Nhắc hoa hồng** | -15 | | |
| **Ngôn ngữ môi giới** | -10 | | |
| **Nhiều emoji** | -15 | | |
| **Mô tả quá dài** | -5 | | |
| **Dùng ngôn ngữ "chính chủ"** | -5 | Muaban: môi giới hay giả danh claim này, nên trừ nhẹ | ⬅ Đồng ý không? |

---

## So sánh 3 sàn

| | Nhatot | BĐS | Muaban |
|--|--------|-----|--------|
| **Có số điện thoại** | ❌ | ❌ | ✅ |
| **Phân loại cá nhân/DN tự động** | ✅ | ❌ | ❌ |
| **Biết số tin đang đăng** | ✅ | ✅ | ❌ |
| **Biết năm gia nhập** | ❌ | Một phần | ❌ |
| **Mô tả đầy đủ** | ✅ | ✅ | ✅ |
| **Ngưỡng chính chủ** | 65 | 60 | 65 |
| **Alert vợ từ điểm** | 55 | 52 | 55 |

---

## Câu hỏi gợi ý để feedback

Khi xem tin được alert, hãy nhìn vào điểm số và trả lời:

1. **"Tin này bị lọc oan"** — Thực tế là chính chủ nhưng bị đánh giá là môi giới → dấu hiệu nào bị sai?
2. **"Tin này lọt qua nhưng là môi giới"** → Dấu hiệu nào đang thiếu?
3. **Ngưỡng số tin đăng** — Trên BĐS, hiện tại > 5 tin = môi giới. Thực tế bạn gặp có đúng không? Chủ nhà bình thường tối đa mấy tin?
4. **Muaban: ≥ 5 tin = môi giới** — Ngưỡng này ổn không hay cần điều chỉnh?
5. **Từ khóa marketing** — Trong thực tế bạn thấy môi giới hay dùng những cụm nào mà hệ thống chưa có?
6. **Khu vực** — 16 quận hiện tại có thiếu quận nào hay thừa quận nào không?

---

*Tài liệu này cập nhật theo từng session làm việc. Phiên bản mới nhất luôn ở thư mục `docs/`.*
