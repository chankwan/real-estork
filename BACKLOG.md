# Backlog

Tasks chưa làm — sắp xếp theo trạng thái. Item nào unblock thì kéo xuống commit thẳng.

---

## ⏳ Chờ input

_(không có item chờ)_

---

## 🐞 Bug đã biết, chưa fix

### ~~Signal `account_new_or_few_posts` crash khi `poster_total_listings=None`~~ ✅ Fixed session 23 (2026-08-28)
- **Operator thấy gì**: không thấy gì — classifier catch exception, signal chỉ âm thầm không fire. Log ERROR `'<=' not supported between instances of 'NoneType' and 'int'`.
- **Root cause thật**: comment trong `SignalContext.from_listing` hứa "fall back to DB stats, **then 999**" nhưng bước 999 chưa bao giờ được cài — `stats.get("poster_total_listings")` trả None (khoá này chưa bao giờ tồn tại trong phone_stats) → None lọt vào ctx.
- **Fix**: cài nốt bước 999 (chưa biết = coi như nhiều tin = không thưởng điểm) + chốt chặn None tại chỗ trong signal. 7 test mới.
- **Đính chính mức độ**: BACKLOG cũ ghi "4 lần/2 tuần" — con số đó từ log đã bị xoay vòng xoá. Trong toàn bộ log còn giữ: **0 lần**. Đo trang danh sách nhatot 27/08: **60/60 tin có `live_ads`** → trường hợp thiếu số hiếm hơn ghi nhận cũ nhiều.
- **Cũng đã xác minh** (27/08): trang chi tiết nhatot **không có** `live_ads` trong dữ liệu nhúng (chỉ `sold_ads`); con số "N tin đăng" trên UI do JS gọi API khác vẽ ra. Tin hết hạn → UI hiện "-- tin đăng", không có số để đọc. → **KHÔNG xây bước đọc trang chi tiết cho nhatot** như đã làm với batdongsan guru: trang danh sách đã phủ ~100% và trang chi tiết còn ít dữ liệu hơn.

### ~~Tin "khách đi tìm thuê" lọt vào alert trên portal~~ ❌ Không tồn tại — đã bác bỏ bằng dữ liệu (session 23)
- Giả thuyết từ session 22 (2 tin `134100167`, `134225481`) **sai**. Đọc kỹ: `134100167` là tin chủ nhà cho thuê, tiêu đề chỉ nhồi keyword SEO ("TÌM MẶT BẰNG…") còn nội dung là "nhà đang trống, vào ở ngay… #chothuenha"; `134225481` là tin kêu gọi góp vốn, không phải khách thuê.
- Quét lưới rộng 1.200 tin portal: 22 tin dính từ khoá, đọc tay **0 tin là người đi tìm thuê thật**. Hợp lý — portal là sàn đăng tin cho thuê, người cần thuê dùng ô tìm kiếm chứ không đăng tin (khác Facebook group).
- Nếu đã làm theo giả thuyết này: gắn nhãn sai ~22 tin chủ nhà, gắn đúng 0 tin.


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

### ~~Bot chạy 2 process → `bot-stop` để lại orphan~~ ✅ Fixed 2026-08-20
- `bot-stop.bat`: `taskkill /F` → `taskkill /F /T` (kill cả cây: parent + child giữ lock + cây browser của cycle batdongsan), rồi quét thêm bằng PowerShell các `pythonw.exe` còn khớp `cli.main` từ lần start/stop trước.
- Dùng PowerShell cho phần quét thay vì `wmic`/`for /f` — CommandLine chứa dấu phẩy nên parse CSV sai.
- **Verify**: chạy thật → `[OK] Bot (PID 8872) da dung.` + `[OK] Khong con process mo coi.`; kiểm tra độc lập sau đó: 0 process còn lại, lock đã xoá.
- **Chưa rõ (giữ lại)**: vì sao `cli.main start` đẻ process con — chưa trace ra nguồn. Lock vẫn đảm bảo chỉ 1 scheduler chạy nên không sai kết quả.

### `.bat` in ra `'M' is not recognized as an internal or external command`
- **Operator thấy gì**: Chạy `bot-stop.bat` / `bot-start-headless.bat` thấy 2 dòng lỗi `'M' is not recognized` ở đầu output (bot vẫn chạy/dừng đúng).
- **Nguyên nhân (giả thuyết)**: 1 dòng trong `.bat` bị cmd diễn giải sai (có thể liên quan chuỗi bắt đầu bằng "M" — path/echo không escape). Cosmetic, chưa ảnh hưởng chức năng.
- **Mức độ**: thấp — chỉ gây nhiễu output.

---

## 🔧 Vận hành (chưa chỉnh)

### ~~Hàng chờ duyệt tay: gửi Telegram tin BDS "bỏ cuộc"~~ ✅ XONG (2026-08-19)
- Cuối mỗi cycle batdongsan, tin nào bot thử 3 lần vẫn không đọc được số tin đăng của người bán → gộp 1 tin nhắn "🔍 CẦN DUYỆT TAY" (tiêu đề + giá + quận + link). Vượt 10 tin/cycle → gửi cảnh báo hệ thống kèm chẩn đoán thay vì liệt kê (chống flood).
- **Đích đến**: mặc định chat admin. Muốn vào topic riêng trong group → tạo topic, lấy ID, set `TELEGRAM_BDS_REVIEW_TOPIC_ID` trong `.env` (dùng `tools/tg_get_topic_id.py`).

### Siết tiếp trọng số nhatot (B/C/D) — CHỜ dữ liệu phản hồi (session 23)
- **Bối cảnh**: vợ báo ngập tin rác. Đo 774 tin nhatot: `account_type_personal` fire **100%** tin (vì URL đã lọc `?f=p`) → 42% tin chạm trần 100 điểm. Đã tắt signal đó (bước A) — trần điểm biến mất, trung vị 100 → 75.
- **Còn lại, mô phỏng trên 398 tin thật trong log** (công thức verify khớp 189/189 tin dưới trần):
  | Phương án | Tin ≥55 điểm | Trung vị |
  |---|---|---|
  | Sau bước A (đang chạy) | 84% | 75 |
  | B — bỏ `posted_outside_business_hours` (+8, fire 78%) | 71% | 67 |
  | C — B + hạ `account_new_or_few_posts` 14→8 (fire 82%) | 66% | 61 |
  | D — C + hạ `listing_very_fresh` 10→5 | 61% | 56 |
- **Vì sao CHƯA làm B/C/D**: đọc tay 8 tin bị loại ở phương án C thấy có tin trông như thật ("mặt bằng nguyên căn Lê Đức Thọ", "nhà nguyên căn mặt tiền Quận 5"). Không có ground truth thì cắt sâu hơn là đoán mò.
- **Điều kiện để làm**: đợi ~1 tuần dữ liệu từ nút 👍/👎 (bật session 23), rồi chọn ngưỡng bằng bằng chứng.
- **Cũng cần xem lại khi có dữ liệu**: `posted_outside_business_hours` fire 78% và `account_new_or_few_posts` fire 82% — signal fire ở tỉ lệ quá cao thì giá trị phân biệt thấp, giống hệt bệnh của signal vừa tắt.

### Bộ não AI đang chết — bật lại thế nào cho an toàn (session 23)
- **Operator thấy gì**: không thấy gì. Bot chạy bình thường, chấm điểm bình thường, nhưng **thuần luật** — tín hiệu AI không tham gia. Log đầy `[ai] zero-token call failed: All connection attempts failed` (481 lần chỉ trong ~4 giờ ngày 27/08).
- **Nguyên nhân**: cấu hình AI trỏ về cổng `localhost:3001` trên PC2 — không có gì chạy ở đó. Proxy thật sống trên **PC1: `http://chankwan-pc1:8317/v1`** (verify 27/08: gọi thành công, có `gemini-3.7-flash-high`). Model cũ trong cấu hình là `gemini-web/gemini-pro`, không còn tồn tại trên proxy mới.
- **Vì sao KHÔNG chỉ đổi địa chỉ là xong**:
  - Tín hiệu AI có trọng số **±30 điểm** — nặng nhất hệ thống (so với `account_type_personal` +25, `detail_has_pro_agent_badge` -40). Công thức: `30 × (xác suất − 0.5) × 2`.
  - Ngưỡng gửi cho vợ là 55, ngưỡng nhãn chính chủ 65 (nhatot) / 60 (batdongsan). Một tin chính chủ bị model chấm 0.2 là tụt 18 điểm → rơi khỏi ngưỡng gửi.
  - AI chết trả về 0.5 → cộng 0 → tín hiệu biến mất êm. Nên bật lại = **thả một biến ±30 vào hệ thống đang cân bằng sát ngưỡng**, bằng model chưa từng chạy trên dữ liệu này.
- **Chỉ ảnh hưởng 2/4 nguồn**: `nhatot` + `batdongsan` có khai báo `ai_classification`. `muaban` + `facebook_groups` KHÔNG có trong bộ luật riêng → kết quả AI bị vứt. Nhưng bot vẫn **gọi AI cho cả 4 nguồn** rồi bỏ đi 2 → lãng phí mỗi cycle. Sửa luôn khi làm việc này.
- **Thứ tự làm (đo trước, bật sau)**:
  1. **Dựng bộ đối chứng** — chưa có dữ liệu đúng/sai nên chưa thể biết AI giúp hay hại. Lấy ~100 tin nhatot/batdongsan trong DB, ưu tiên tin đã có phản hồi của vợ.
  2. Cho model chấm, đặt cạnh điểm luật hiện tại. Ba con số cần: bao nhiêu tin đang gửi sẽ **rớt** khỏi ngưỡng, bao nhiêu tin đang chặn sẽ **lọt vào**, và danh sách tin lệch nhiều nhất để đọc tay xem AI hay luật đúng.
  3. Có số rồi mới quyết bật/không, và quyết trọng số ±30 có còn hợp lý không.
- **Model đề xuất** (user không giới hạn, stack = Gemini sub + local 24GB VRAM):
  | Vai | Model | Ghi chú |
  |---|---|---|
  | Runtime (chấm từng tin) | **`qwen3:14b`** | Tiếng Việt tốt nhất trong tầm 24GB. Q8 ~15GB. Mặc định đề xuất |
  | Runtime, cần nhanh hơn | `qwen3:30b-a3b` | MoE, kích hoạt ~3B/lượt → nhanh gần 3B, chất lượng gần 30B. Q4 ~17-18GB |
  | Runtime, cần mạnh hơn | `qwen3:32b` Q4 (~19-20GB) | Sát trần VRAM, chỉ chọn nếu đo thấy 14B thua rõ |
  | Thầy dạy (tuần/lần) | `gemini-3.7-flash-high` qua sub | Tổng hợp quy luật từ hàng nghìn tin, khác việc phân loại lẻ |
  - Gemma 3 27B là phương án so sánh nếu đã có sẵn. Nếu tồn tại bản Qwen mới hơn 3.x thì lấy bản mới nhất **cùng cỡ 14B**, logic chọn không đổi.
  - **Ưu tiên local cho runtime**: sự cố 27/08 cho thấy mọi thứ qua mạng là điểm chết (cổng AI chết 481 lần không ai biết; certificate hỏng làm bot câm 16,5h). Local không quota, không TLS, không Cloudflare.
- **Mức độ**: trung bình — không phải bug, là cơ hội chưa khai thác. Không gấp, nhưng làm đúng thứ tự thì rẻ.

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
