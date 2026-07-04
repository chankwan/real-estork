# Backlog

Tasks chưa làm — sắp xếp theo trạng thái. Item nào unblock thì kéo xuống commit thẳng.

---

## ⏳ Chờ input

_(không có item chờ)_

---

## 🐞 Bug đã biết, chưa fix

### Pre-existing test failure: `test_known_broker_phone_crushes_score`
- File: `tests/test_pipeline.py`
- Triệu chứng: signal `is_known_broker` không fire khi phone_stats có `is_known_broker=True`. Score=68 thay vì <40 như expected.
- Phát hiện: session 14 khi chạy full test suite. Pre-existing trước commit 077337f.
- Mức độ: thấp — chỉ ảnh hưởng test, không ảnh hưởng production logic (vì known_broker phone list hiện rất nhỏ).

### ~~Bot bị silent crash khi browser context die~~ ✅ Fixed session 16 (2026-05-26)
- Xem `orchestrator/agent.py` → `start()` — `clean_exit` flag + `_atexit_cleanup` + `except Exception` crash handler.

### Bot không tự dậy sau reboot nếu chưa login Windows (auto-start dùng `-AtLogon`)
- **Operator thấy gì**: Bot "im" rất lâu sau khi máy tự tắt/reset — không alert, không scrape — dù self-healing lock vẫn OK khi cuối cùng dậy lại.
- **Sự cố thật (24–26/06/2026)**: Máy mất điện/reset cứng ~23:55 ngày 24/06 (bot log cắt giữa dòng; Windows Event 6008 "unexpected shutdown" + Event 41 Kernel-Power "rebooted without cleanly shutting down"). Máy tắt hẳn **~37 giờ** (không event log nào 24/06 23:55 → 26/06 12:39), boot lại 26/06 12:39 → bot mới auto-start 12:40. **KHÔNG phải lỗi code** — code chạy đúng tới lúc mất điện, và self-healing lock phục hồi sạch khi dậy.
- **Nguyên nhân gốc của 37h downtime**: Task Scheduler "RealEstork Bot" dùng trigger **`-AtLogon`** → chỉ chạy khi có người **đăng nhập** Windows. Máy reboot lúc logout → bot nằm chờ tới lần login kế.
- **Giải pháp đề xuất**: Đổi trigger sang **`-AtStartup`** (chạy headless ngay khi máy boot, không cần login) — cần chạy task dưới account đã lưu credential + "Run whether user is logged on or not". Cân nhắc: pythonw headless đã có (`bot-start-headless.bat`), chỉ cần đổi trigger + đảm bảo `.env`/profile path absolute (không phụ thuộc user session).
- **Phụ (tùy chọn)**: thêm UPS nhỏ cho PC2 để chịu được chớp điện ngắn; hoặc Telegram heartbeat "bot còn sống mỗi N giờ" để phát hiện downtime sớm thay vì chờ vợ báo.
- **Mức độ**: trung bình — không mất dữ liệu (dedup cache + DB còn nguyên), nhưng mất coverage tin mới suốt thời gian down.
