# Backlog

Tasks chưa làm — sắp xếp theo trạng thái. Item nào unblock thì kéo xuống commit thẳng.

---

## ⏳ Chờ input

_(không có item chờ)_

---

## 🐞 Bug đã biết, chưa fix

### Signal `account_new_or_few_posts` crash khi `poster_total_listings=None`
- **Operator thấy gì**: không thấy gì — classifier catch exception, signal chỉ âm thầm không fire. Log ERROR `'<=' not supported between instances of 'NoneType' and 'int'`.
- **Chi tiết (session 22)**: `pipeline/signals.py` `check_account_new_or_few_posts` so sánh `ctx.poster_total_listings <= 2` — sau session 22 giá trị có thể là None (SignalContext fallback `stats.get(...)` trả None khi phone_stats không có key). Chỉ cấu hình cho nhatot.
- **Mức độ**: thấp — bị catch, không crash bot; nhưng signal +15 của nhatot có thể im lặng không fire.


### Pre-existing test failure: `test_known_broker_phone_crushes_score`
- File: `tests/test_pipeline.py`
- Triệu chứng: signal `is_known_broker` không fire khi phone_stats có `is_known_broker=True`. Score=68 thay vì <40 như expected.
- Phát hiện: session 14 khi chạy full test suite. Pre-existing trước commit 077337f.
- Mức độ: thấp — chỉ ảnh hưởng test, không ảnh hưởng production logic (vì known_broker phone list hiện rất nhỏ).

### ~~Bot bị silent crash khi browser context die~~ ✅ Fixed session 16 (2026-05-26)
- Xem `orchestrator/agent.py` → `start()` — `clean_exit` flag + `_atexit_cleanup` + `except Exception` crash handler.

### ~~Bot không tự dậy sau reboot nếu chưa login Windows (auto-start dùng `-AtLogon`)~~ ✅ RESOLVED (2026-07-22)
- **Cách giải quyết thực tế**: KHÔNG đổi trigger sang -AtStartup. Thay vào đó user đã bật **Windows auto sign-in** (verify: registry `AutoAdminLogon=1`, DefaultUserName="Chankwan PC 2") + **BIOS auto power-on sau mất điện**. Chuỗi giờ: có điện lại → máy tự bật → tự đăng nhập → 2 task -AtLogon tự chạy (bot + Chrome capture). Nội dung cũ giữ dưới đây làm bối cảnh sự cố 37h.
- **Operator thấy gì**: Bot "im" rất lâu sau khi máy tự tắt/reset — không alert, không scrape — dù self-healing lock vẫn OK khi cuối cùng dậy lại.
- **Sự cố thật (24–26/06/2026)**: Máy mất điện/reset cứng ~23:55 ngày 24/06 (bot log cắt giữa dòng; Windows Event 6008 "unexpected shutdown" + Event 41 Kernel-Power "rebooted without cleanly shutting down"). Máy tắt hẳn **~37 giờ** (không event log nào 24/06 23:55 → 26/06 12:39), boot lại 26/06 12:39 → bot mới auto-start 12:40. **KHÔNG phải lỗi code** — code chạy đúng tới lúc mất điện, và self-healing lock phục hồi sạch khi dậy.
- **Nguyên nhân gốc của 37h downtime**: Task Scheduler "RealEstork Bot" dùng trigger **`-AtLogon`** → chỉ chạy khi có người **đăng nhập** Windows. Máy reboot lúc logout → bot nằm chờ tới lần login kế.
- **Giải pháp đề xuất**: Đổi trigger sang **`-AtStartup`** (chạy headless ngay khi máy boot, không cần login) — cần chạy task dưới account đã lưu credential + "Run whether user is logged on or not". Cân nhắc: pythonw headless đã có (`bot-start-headless.bat`), chỉ cần đổi trigger + đảm bảo `.env`/profile path absolute (không phụ thuộc user session).
- **Phụ (tùy chọn)**: thêm UPS nhỏ cho PC2 để chịu được chớp điện ngắn; hoặc Telegram heartbeat "bot còn sống mỗi N giờ" để phát hiện downtime sớm thay vì chờ vợ báo.
- **Mức độ**: trung bình — không mất dữ liệu (dedup cache + DB còn nguyên), nhưng mất coverage tin mới suốt thời gian down.

### Bot chạy 2 process (parent+child) → `bot-stop` để lại orphan → tích luỹ nhiều instance
- **Operator thấy gì**: Sau vài lần start/stop, Task Manager có nhiều `pythonw` cli.main cùng chạy → scraping trùng, có thể bị site chặn (muaban HTTP 403).
- **Chi tiết (session 2026-07-07)**: 1 lần `pythonw -m cli.main start` đẻ ra 2 process — parent + child; **child giữ lock + chạy scheduler**, parent không schedule (lock chặn). `bot-stop.bat` đọc PID trong lock (child) rồi `taskkill /F` **không có `/T`** → chỉ kill child, **parent orphan**. Lần start kế đẻ thêm cặp mới → tích luỹ.
- **Chưa rõ**: vì sao `cli.main start` đẻ child (grep `cli/main.py` không thấy subprocess/fork ở lệnh start — chỉ ở `stop`). Cần trace nguồn gốc process con.
- **Giải pháp đề xuất**: (a) `bot-stop` dùng `taskkill /F /T /PID <lock_pid>` (kill cả cây); hoặc kill mọi `pythonw` match `cli.main` trước khi start. (b) Tìm & loại nguồn spawn child nếu không cố ý.
- **Mức độ**: trung bình — không sai kết quả (lock đảm bảo 1 scheduler) nhưng gây process rác + nghi ngờ rate-limit.

### `.bat` in ra `'M' is not recognized as an internal or external command`
- **Operator thấy gì**: Chạy `bot-stop.bat` / `bot-start-headless.bat` thấy 2 dòng lỗi `'M' is not recognized` ở đầu output (bot vẫn chạy/dừng đúng).
- **Nguyên nhân (giả thuyết)**: 1 dòng trong `.bat` bị cmd diễn giải sai (có thể liên quan chuỗi bắt đầu bằng "M" — path/echo không escape). Cosmetic, chưa ảnh hưởng chức năng.
- **Mức độ**: thấp — chỉ gây nhiễu output.

---

## 🔧 Vận hành (chưa chỉnh)

### ~~Hàng chờ duyệt tay: gửi Telegram tin BDS "bỏ cuộc"~~ ✅ XONG (2026-08-19)
- Cuối mỗi cycle batdongsan, tin nào bot thử 3 lần vẫn không đọc được số tin đăng của người bán → gộp 1 tin nhắn "🔍 CẦN DUYỆT TAY" (tiêu đề + giá + quận + link). Vượt 10 tin/cycle → gửi cảnh báo hệ thống kèm chẩn đoán thay vì liệt kê (chống flood).
- **Đích đến**: mặc định chat admin. Muốn vào topic riêng trong group → tạo topic, lấy ID, set `TELEGRAM_BDS_REVIEW_TOPIC_ID` trong `.env` (dùng `tools/tg_get_topic_id.py`).

## 🚀 Cải tiến Facebook Groups

### `detect_fb_intent` recall thấp — nhiều tin Chủ rớt về `unknown` → không gửi
- **Operator thấy gì**: Nhiều tin cho thuê chính chủ trên FB KHÔNG tới Telegram vì bị gắn `intent=unknown → không route`.
- **Nguyên nhân**: bộ từ khoá offer/seek trong `spiders/facebook_groups.py:detect_fb_intent` hẹp — tin không có "cho thuê"/"cần thuê" rõ ràng đều rớt unknown, bất kể filter giá (session 2026-07-07 thấy hầu hết FB post = unknown).
- **Đề xuất**: mở rộng từ khoá offer (vd "cho thuê", "cần cho thuê", "còn trống", giá + diện tích + địa chỉ = tín hiệu offer ngầm), cân nhắc heuristic "có SĐT + giá + địa chỉ" → coi là offer.
- **Mức độ**: cao — đây là nút thắt recall thật, filter giá hôm nay vô nghĩa nếu tin không lọt qua bước intent.

### ~~Bật lại tin Khách (seek)~~ ✅ Đã bật lại (2026-07-07, commit 3678fdf)
- Tin Khách nhận MỌI giá. Filter ≥20M chuyển sang `fb_offer_min_price_vnd` (offer-only) — chỉ áp cho tin Chủ.

### Userscript re-send tin đã seen (0-new drains) — lãng phí quét
- **Triệu chứng**: log `received N, 0 new sau dedup` — userscript gửi lại tin đã có trong DB do `seen` (localStorage trình duyệt) lệch với dedup DB của bot (localStorage bị FB làm đầy/xoá, hoặc reset khi reload).
- **Mức độ**: thấp — không sai kết quả (DB dedup chặn), chỉ tốn thời gian quét vào tin cũ thay vì tìm tin mới.

### Roadmap phân loại FB (từ plan, chưa làm)
- **B — Detector "sang nhượng CHDV"**: lọc noise tin sang nhượng cơ sở (business transfer) — không phải cho thuê, hay parse nhầm giá.
- **C — Feed SĐT môi giới FB → `broker_phones`**: đóng vòng cross-marketplace (§10.3.3) — SĐT môi giới bắt trên FB dùng để chặn ở portal và ngược lại.
- **D — Ghi verdict + post_count vào `fb_posters`**: bắt spammer đăng nhiều trong **1 group** (vd "Ngọc Thư" 13 post) — hiện signal chỉ bắt cross-group (`group_count>=5`).
- **E — Learning loop feedback vợ cho FB**: nối phản hồi vợ (đúng/sai chính chủ) vào điều chỉnh score FB.

### Bước 5 — Runbook warm via + go-live
- Quy trình nuôi via FB (warm account), giữ 2-3 via dự phòng, checklist go-live. (Task #5 trong list, pending.)

---

## 🧹 Dọn dẹp
- ~~File rác `cd` (0-byte) ở root repo~~ ✅ Đã xoá (2026-08-19).
