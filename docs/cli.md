# RealEstork CLI — Hướng dẫn Vận hành

Tất cả các lệnh được thực thi thông qua module `cli.main`. 
Cấu trúc lệnh: `python -m cli.main [command] [options]`

---

## 1. Vận hành chính

### `start`
**Lệnh:** `python -m cli.main start`
- **Mô tả:** Khởi động hệ thống Orchestrator toàn diện.
- **Use case:** Chạy bot ở chế độ tự động 24/7. Bot sẽ tự động lập lịch crawl, xử lý và bắn alert Telegram.
- **Option:** `--dry-run` (Chạy thử pipeline nhưng không gửi thông báo thật).

### `digest`
**Lệnh:** `python -m cli.main digest`
- **Mô tả:** Gửi báo cáo tổng kết (Daily Digest) ngay lập tức.
- **Use case:** Muốn xem thống kê hoạt động của hệ thống trong ngày mà không cần đợi đến 8:00 sáng.

---

## 2. Quản lý Spider (Crawl)

### `spider list`
**Lệnh:** `python -m cli.main spider list`
- **Mô tả:** Liệt kê danh sách các spider hiện có và trạng thái (Enable/Disable).
- **Use case:** Kiểm tra xem các spider (nhatot, batdongsan, alonhadat) đã được cấu hình đúng chưa.

### `spider run <name>`
**Lệnh:** `python -m cli.main spider run [nhatot|batdongsan]`
- **Mô tả:** Chạy thủ công một spider cụ thể.
- **Use case:** Kiểm tra xem spider có đang bị chặn (blocked) bởi website không, hoặc muốn lấy dữ liệu mới ngay lập tức cho một site nhất định.
- **Option:** `--dry-run` (Chỉ in kết quả ra màn hình, không lưu vào database).

---

## 3. Cấu hình & Auth (Quan trọng)

### `setup-nhatot`
**Lệnh:** `python -m cli.main setup-nhatot`
- **Mô tả:** Mở trình duyệt để đăng nhập Chợ Tốt và lấy Access Token.
- **Use case:** Chạy lần đầu tiên hoặc khi token Chợ Tốt hết hạn mà hệ thống không thể tự refresh tự động.

### `setup-batdongsan`
**Lệnh:** `python -m cli.main setup-batdongsan`
- **Mô tả:** Mở trình duyệt để đăng nhập Batdongsan.com.vn và lưu Cookies.
- **Use case:** Chạy lần đầu tiên để đảm bảo tính năng **Decrypt Phone** (lấy SĐT) hoạt động ổn định.

---

## 4. Phân tích & Phản hồi

### `classify <listing_id>`
**Lệnh:** `python -m cli.main classify [ID_TIN_DANG]`
- **Mô tả:** Hiển thị chi tiết bảng điểm (score breakdown) của một tin đăng.
- **Use case:** Kiểm tra tại sao một tin đăng lại được chấm điểm cao (Chính chủ) hoặc thấp (Môi giới). Giúp tinh chỉnh lại các trọng số (weight) trong file `scoring.yaml`.

### `mark <ref> <status>`
**Lệnh:** `python -m cli.main mark [source-id] [called|owner|broker|archived]`
- **Mô tả:** Đánh dấu trạng thái thực tế của một tin đăng sau khi đã kiểm tra.
- **Use case:** Ghi lại phản hồi (feedback) để hệ thống tính toán độ chính xác (Accuracy). 
- *Ví dụ:* `python -m cli.main mark batdongsan-12345 owner`

---

## 5. Quản lý AI

### `ai status`
**Lệnh:** `python -m cli.main ai status`
- **Mô tả:** Kiểm tra model AI đang được sử dụng và cấu hình hiện tại.
- **Use case:** Xác nhận hệ thống đang dùng model nào (Ollama local hay Gemini web).

### `ai models`
**Lệnh:** `python -m cli.main ai models`
- **Mô tả:** Liệt kê danh sách các model AI được hỗ trợ (Local, Web Chat, Pay-per-token).
- **Use case:** Xem các lựa chọn thay thế để chuyển đổi model khi cần.

---

## Ghi chú Vận hành
- Luôn kiểm tra file log tại `logs/orchestrator.log` để theo dõi chi tiết quá trình chạy ngầm.
- Nếu thấy số điện thoại không hiển thị, hãy chạy lại các lệnh `setup-*` để cập nhật quyền truy cập.