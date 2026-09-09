# RealEstork — Project Notes for Claude

## What This Project Does
Autonomous real estate scraper for HCMC commercial rentals (văn phòng / mặt bằng kinh doanh).
Scrapes → deduplicates → classifies (chính chủ vs môi giới) → sends Telegram alerts.
Runs as background service. User only reviews daily digest.

## Architecture
```
spiders/          → fetch raw listings per site
pipeline/dedup    → fingerprint-based dedup
pipeline/classifier → YAML-driven rule scoring (0-100) + optional AI signal
pipeline/signals  → signal check functions (must match scoring.yaml keys)
orchestrator/     → APScheduler, coordinates full pipeline
notifications/    → Telegram bot
db/client.py      → Supabase wrapper
config/           → all tuneable config (no redeploy needed)
```

## Active Spiders
| Spider | URL Category | Phone Method |
|--------|-------------|--------------|
| nhatot | thue-bat-dong-san HCMC, price>=15M, f=p (cá nhân/personal only) | RSA-3072 PKCS1v15 + Bearer token API |
| alonhadat | cho-thue-nha-mat-tien/ho-chi-minh | Detail page tel: link scrape |
| batdongsan | cho-thue-nha-mat-pho-tp-hcm | ❌ Not solved yet |

## Alert Routing
- Telegram Admin chat: `TELEGRAM_ADMIN_CHAT_ID`
- Telegram Group chat: `TELEGRAM_GROUP_CHAT_ID`
- Zalo: disabled (commented out, để test Telegram)

## Classification Logic
- Base score: 50
- Thresholds: chinh_chu >= 65, can_xac_minh >= 40, moi_gioi < 40
- Alert to wife: score >= 55, listing age <= 48h, district in whitelist
- All signals in `config/scoring.yaml`, functions in `pipeline/signals.py`

## District Whitelist (alert filter)
16 quận trung tâm HCMC: Quận 1–11, Bình Thạnh, Phú Nhuận, Tân Bình, Thủ Đức, Gò Vấp
Configured in `config/scoring.yaml` → `alert_filters.wife_allowed_districts`
Implemented in `pipeline/classifier.py` → `should_alert_wife()` with `_normalize_district()`

## Known Issues / TODO
- [x] Phone signals tắt vĩnh viễn — Chotot account bị ban 2026-04-22, đã xóa phone scraping khỏi nhatot spider
- [x] `account_new_or_few_posts` fixed — nhatot spider giờ extract `seller_info.live_ads` → `poster_total_listings`
- [ ] batdongsan phone reveal not implemented
- [ ] Scoring weights not yet tuned with real feedback data

## Nhatot Phone Reveal
- **DISABLED** — Chotot account bị ban (2026-04-22). Phone scraping đã xóa khỏi spider.
- Spider chỉ dùng `__NEXT_DATA__` từ SSR page, không cần token hay login.
- Nếu muốn khôi phục: tạo account mới + implement lại RSA+Bearer flow.

## Key Config Files
- `config/scoring.yaml` — scoring weights, thresholds, district whitelist, alert filters
- `config/spiders.yaml` — enable/disable spiders, URLs, page limits
- `config/ai.yaml` — AI provider/model selection
- `config/schedule.yaml` — cron schedules
- `.env` — secrets (tokens, API keys, chat IDs)

## Running
```bash
python -m cli.main start              # full orchestrator
python -m cli.main spider run nhatot  # test single spider
python -m cli.main classify <id>      # debug scoring for a listing
```

## Changelog
### 2026-09-08 (session 24) — Muaban 0 alert suốt 252 cycle + chuẩn hoá scoring bỏ phụ thuộc SĐT
- **Trigger**: user báo group muaban không nhận được tin nào từ lâu, không rõ do tin không đạt hay do nền tảng đổi.
- **Đo trước khi kết luận** (8 ngày log + toàn bộ DB): muaban 252 cycle, 1028 tin mới, **0 alert**. Đối chiếu: nhatot 487 tin → 222 alert, batdongsan 3488 → 62, facebook 38 → 6.
- **Root cause #1 — signal chấm điểm bằng dữ liệu KHÔNG TỒN TẠI** (chặn 100% alert):
  - `muaban_multi_active_listings` (-40) đọc `poster_total_listings`, nhưng muaban.net **không công bố số tin đăng của người bán ở bất kỳ đâu** — verify live: không có trong `__NEXT_DATA__` trang list, không có ở trang chi tiết, 3 dạng URL trang cá nhân (`/thanh-vien/{uid}`, `/nguoi-ban/{uid}`, `/user/{uid}`) đều 404, không có API.
  - Thiếu số → `SignalContext.from_listing` thay bằng **999** ("coi như nhiều tin") → signal phạt fire cho **100% tin muaban**, trừ thẳng 40 điểm. Log 8 ngày: 74/74 tin lọt tới bước chấm điểm đều mang `muaban_multi_active_listings:-40`; phân bố điểm 0/5/15/20/40 — **trần thực tế 40 < ngưỡng gửi 50**, toán học không cho phép tin nào qua.
  - Fallback 999 vốn an toàn với nhatot (signal cộng không fire) nhưng với muaban lại **kích hoạt signal trừ** — cùng một dòng code, hai nguồn, hai kết cục ngược nhau.
  - Đây là lần thứ 2 dính lỗi "thiếu dữ liệu bị hiểu thành kết luận" (lần 1: session 22, batdongsan fetch hỏng → tin môi giới lọt alert).
- **Root cause #2 — nhãn gói tin trả phí bị đảo**: đối chiếu `service_display` trên trang chi tiết: `128 = "Tin thường"` (miễn phí), `2 = "VIP 2"`. Code ghi `_VIP_SERVICE_IDS = {16,8,4,128}` → xếp tin thường (đa số) vào nhóm trả phí và bỏ sót VIP 2 → `page_normal_count = 0` mỗi trang → **cả hai điều kiện dừng sớm không bao giờ fire** → mỗi vòng cày 50 trang × 3 danh mục = 1040 tin, ~10,6 phút/cycle (chu kỳ đặt 20 phút).
- **Root cause #3 — mất sạch SĐT (không phải do logout)**: muaban dựng **Cloudflare Turnstile ở nút "Hiện số"** từ 21/08. Verify bằng browser thật: click nút → 3 request nạp Turnstile, **không** có màn hình/redirect đăng nhập; `data-phone` trong nội dung tin đã bị gỡ, chỉ còn `phone_enc` + `phone_display` che sao; endpoint cũ `/api/v1/classifieds/{id}/phone` trả **404** (không phải 401/403). Bot **chưa từng đăng nhập muaban** (`.muaban_cookies.json` không tồn tại) mà vẫn lấy được số tới 21/08 → không có phiên nào để mất. DB xác nhận cliff: 04→08 tỉ lệ 4-8%, số cuối cùng 21/08, sau đó 0/1559.
- **Quyết định user**: bỏ hẳn việc đi lấy SĐT ("vợ vẫn mở link xem số khi thấy tin ưng"), chuẩn hoá scoring, chỉ loại các signal **phải đi lấy** SĐT.
- **Fix A — nguyên tắc "không biết thì không chấm"** (`pipeline/signals.py`): bỏ fallback 999, `poster_total_listings` giữ `None` = chưa biết. Thêm `poster_count_known()` (loại cả `None` lẫn sentinel `-1` của batdongsan); mọi signal họ hàng guard qua nó.
- **Fix B — gộp 5 signal rời thành 1 thang chung**: `bds_owner_single_listing`/`bds_owner_few_active_listings`/`bds_broker_multi_active_listings`/`muaban_*`/`account_new_or_few_posts` → `poster_single_listing` (=1) / `poster_few_listings` (2-5) / `poster_many_listings` (>5). Mốc **không chồng nhau**; trọng số vẫn per-source. BDS giữ nguyên hành vi: single nâng 10 → **25** để bù việc bỏ stack (cũ: few +15 ∪ single +10 = 25). muaban không khai thang này (không có nguồn dữ liệu) → im hoàn toàn.
- **Fix C — bỏ signal dựa SĐT ở 3 sàn rao vặt**: `trangtrang_spam_penalty` → weight 0 ở default + muaban. Đo 18 ngày: nhatot 0/800 tin có SĐT, batdongsan 0/3510, muaban 0/1559 → signal không còn cơ hội fire. **Facebook giữ nguyên** nhóm signal SĐT (`phone_known_broker` -100, `phone_multi_platform` -40, `phone_multi_listing_same_platform` -40) vì người đăng tự gõ số vào bài: **82,4% tin FB có SĐT**, không tốn công đi lấy.
- **Fix D — đồng bộ ngưỡng gửi**: `wife_min_score` 55 cho cả 3 sàn (nhatot 55 giữ, batdongsan 52→55, muaban 50→55). **Facebook giữ 40** — đo phân bố 18 ngày cho thấy nâng FB lên 55 sẽ cắt **97%** tin (82,5% → 2,6%): gần như toàn bộ tin FB nằm đúng mốc 50 vì bài trong group thường không parse được quận/giá/tuổi tin, nên không signal nào fire. FB cố ý để 40 = "chỉ chặn đứa lộ rõ là môi giới". 3 sàn còn lại dời ngưỡng gần như không đổi kết quả (batdongsan 10,6% → 10,6%).
- **Fix E — nhãn tin trả phí** (`spiders/muaban.py`): `_VIP_SERVICE_IDS` = {16, 8, 4, **2**} (bỏ 128). Kèm bảng đối chiếu `service_display` trong comment.
- **Fix F — gỡ code đi lấy SĐT muaban**: xoá `enrich_listing()` (cookie-based, endpoint 404) + nhánh `data-phone` trong `_enrich_detail`. Stage 2 giữ nguyên vì vẫn lấy được `contact_name` + mô tả đầy đủ (nguồn cho nhóm signal nội dung).
- **Fix G — dedup cache chỉ nhớ 1000 tin sau mỗi lần restart** (phát hiện khi kiểm tra rủi ro flood trước lúc restart): `get_recent_listings(limit=1000)` — nhưng đo ra Supabase/PostgREST **chặn cứng 1000 dòng/lần gọi** bất kể `.limit()` (limit=1000/5000/10000 đều trả đúng 1000). 1000 tin ~ hơn 1 ngày (facebook chiếm phần lớn) → tin cũ của các sàn dễ bị coi là mới. Nguy hiểm hơn bình thường ở session này vì toàn bộ ~8000 tin muaban trong DB **chưa từng được alert** nên lớp "đã alert thì thôi" (`status.startswith("alerted")`) không bảo vệ. Fix: phân trang bằng `.range()` trong `get_recent_listings`, seed nâng lên 12000 (~2 tuần, 9,1s startup). Đo trước khi restart: chưa fix → 117 tin sẽ gửi ngay cycle đầu; sau fix → 3 tin.
- **Fix H — district dạng ghép của muaban**: muaban đổi sang `"TP. Thủ Đức - Quận Thủ Đức"` (225/4000 tin gần nhất) → `_normalize_district` trả nguyên chuỗi `"thu duc - quan thu duc"` → **loại oan toàn bộ tin Thủ Đức**. Fix: tách theo `" - "`, lấy vế mang tên đơn vị hành chính (`Quận`/`Q.`/`Huyện`/`H.`), không có thì lấy vế cuối. Huyện ngoại ô (Hóc Môn/Bình Chánh/Nhà Bè) vẫn bị loại đúng chủ ý.
- **Verify sau restart** (2026-09-09 00:10): dedup seed **1000 → 12000** source ID; muaban cycle **629s → 34,9s** (nhanh ~18×) nhờ early-stop hoạt động trở lại — 3/3 URL dừng ở trang 1-2 thay vì cày 50 trang; 97/97 test pass.
- **Bài học ghi lại**: giá trị mặc định cho dữ liệu thiếu **không trung tính** — nó an toàn hay tai hoạ tuỳ signal đọc nó là signal cộng hay signal trừ. Và khi một signal fire ở 100% tin của một nguồn, đó là dấu hiệu nó đang đọc thứ không tồn tại chứ không phải nguồn đó toàn môi giới (cùng kiểu lỗi với `account_type_personal` fire 100% ở session 23).
- **Cảnh báo cho session sau**: bảng `listings` **không lưu** `poster_total_listings` và `same_session_account_count` → không thể replay/backtest scoring từ DB, mọi tin đọc lại đều rơi vào cảnh "không biết gì". Muốn đo thay đổi scoring phải chạy spider thật.

### 2026-08-19 (session 22) — Audit tin môi giới lọt alert + Cloudflare chặn BDS + chuông đói tin
- **Trigger**: Vợ/user báo 5 tin batdongsan là môi giới (profile 101-709 tin đăng) nhưng bot alert "Likely Chính Chủ" score 76-100.
- **Root cause audit (3 lỗ, cùng gốc "thiếu dữ liệu = được coi là chính chủ")**:
  1. Fetch detail hỏng (Cloudflare) → `poster_total_listings=-1` → lọt qua veto (>5) + không signal nào fire + được thưởng `description_too_short`/`photo_count_low` từ trang rỗng → 76 điểm.
  2. Detail đọc được nhưng nút "Xem thêm N tin khác" (JS render) không kịp → fallback mặc định **1** → `bds_owner_few +15` + `bds_owner_single +10` = +25 điểm cho dữ liệu KHÔNG có → 86-100 điểm. Regex chính `"Tin đăng đang có"` chưa bao giờ match trên trang detail (chuỗi đó chỉ có ở trang guru).
  3. `enrich_from_profile` (trang guru) là code chết — orchestrator gọi `_process_listing` không truyền spider.
- **Sự cố thứ 2 phát hiện trong lúc audit**: BDS nâng Cloudflare lên cả trang list + detail theo lộ trình 11/08 (thăm dò, ~10 marker/ngày) → 17-18/08 (chặn hẳn, 359 marker/ngày). 63 cycle liên tiếp fetch 0 tin **không ai được báo** — bot coi "0 tin" là bình thường. Nguyên nhân kỹ thuật: mỗi trang mở 1 browser mới → fingerprint mới → cf_clearance vô dụng, và fetch thường không biết giải challenge.
- **Fix A+C (chặn lỗ classify)**:
  - `spiders/batdongsan.py`: bỏ fallback mặc định 1 → `None` = chưa biết.
  - `orchestrator/agent.py`: helper `_bds_poster_count_unknown` (None hoặc <0) → tin bị **hoãn** (`chua_xac_minh_nguoi_ban`), vào `_bds_pending`, thử đọc lại tối đa `_BDS_MAX_VERIFY_ATTEMPTS=3` lượt; hết lượt → lưu DB `status=unverified_poster` score 0, KHÔNG alert.
- **Fix fetch (session + solve_cloudflare)** — `spiders/batdongsan.py`:
  - `fetch_listings` chuyển từ "1 browser/trang qua StealthyFetcher + executor" sang **1 `AsyncStealthySession`/cycle** với `solve_cloudflare=True`, `max_pages=detail_concurrency` (tab pool), `timeout=180s`. Giải challenge 1 lần (~2-3 phút) → mọi trang sau đi bằng cf_clearance (~7-12s/trang). Verify live 2026-08-19 (lúc BDS đang chặn thật): 2 list page + 3 detail đều 200, đọc số tin đăng 3/3 — trong đó "Ms Thư" active=712 (đúng môi giới trong audit) → giờ bị veto ngay.
  - Tin hoãn được orchestrator nạp vào `spider.pending_retry` TRƯỚC `spider.run()` → enrich lại trong CÙNG session (không tốn lượt solve riêng).
- **Fix bổ sung cùng ngày — đọc trang guru khi trang chi tiết thiếu số** (user phản hồi tin `pr46216077` bị hoãn oan):
  - **Phát hiện**: trang chi tiết để trống ô "số tin đăng" trong CẢ HAI trường hợp — chủ nhà đúng 1 tin (không có nút "Xem thêm N tin khác" vì không có tin nào khác) VÀ môi giới nhiều tin nhưng nút chưa render. Không thể phân biệt từ trang chi tiết. Fallback cũ (mặc định 1) sai với môi giới; fix A (coi là chưa biết) hoãn oan chính chủ.
  - **Lời giải**: bật lại `enrich_from_profile()` (code chết từ session 5) làm **pass 3** — tin nào thiếu số nhưng có link guru → đọc trang profile, nơi ghi rõ con số kể cả khi bằng 1. Chạy trong cùng session (không tốn lượt giải Cloudflare), ~7-8s/tin, chỉ áp cho tin thiếu số nên vài tin/cycle.
  - Bỏ tham chiếu `self._fetch_impl` (không còn tồn tại sau khi chuyển sang session) — đây là lý do method này sẽ crash nếu được gọi.
  - **Verify live**: chủ 1 tin (Nguyệt, pr46216077) → guru đọc ra `1` + tham gia 2025 → giờ được +25 chính chủ thay vì bị hoãn; môi giới (Newland Sg) → `101` → veto ngay. Tin không có link guru → giữ nguyên "chưa biết". Health counter `guru_ok`/`guru_fail` để theo dõi.
- **Chuông đói tin + health (option B+D)**:
  - Spider đếm `cycle_health` (list ok/cf/no-cards, detail ok/cf/unreadable) tại đúng các điểm phát hiện lỗi.
  - Orchestrator: `_check_bds_starvation` — `_BDS_STARVE_CYCLES=6` cycle liên tiếp không đọc được trang list nào (~2h) → Telegram admin 1 lần/đợt kèm chẩn đoán (CF cao = nâng chặn / mất-card = đổi UI), báo khi hồi phục. Cùng pattern heartbeat FB.
  - Daily digest 8h sáng thêm section "🕷 Batdongsan 24h": số cycle, cycle trắng, health line — bắt xu hướng siết dần kiểu 11→14/08.
- **Verify**: 10 unit test mới (regression replay đúng 5 tin bị lọt với giá trị active từ log production) + 5 kịch bản flow (stage→run→resolve, requeue khi cycle chết, chuông kêu đúng ngưỡng 6 + hồi phục, dưới ngưỡng im lặng, day-health tích luỹ) — tất cả PASS. Suite 41/42 pass (1 fail pre-existing session 14: `test_known_broker_phone_crushes_score`). Live test spider thật 2 lần đối đầu CF đang chặn → đều qua.
- **Trade-off đã báo user**: ~68% tin BDS trước đây thuộc diện "chưa biết số tin đăng" sẽ bị hoãn/không alert → alert BDS giảm rõ, đa số là tin đáng lẽ không nên gửi; chủ thật bị trễ tối đa ~40 phút. Cuộc rượt đuổi Cloudflare chưa kết thúc — chuông đói tin là lưới an toàn khi BDS nâng chặn tiếp.
- **Backlog mới ghi nhận**: signal `account_new_or_few_posts` crash khi `poster_total_listings=None` (lộ qua test, chỉ ảnh hưởng nhatot, bị catch bởi classifier). Hàng chờ duyệt tay qua Telegram (đề xuất 4 của user) — lùi tới khi đo được tỉ lệ bỏ-cuộc thật sau fix fetch.
### 2026-08-04 (session 21) — Fix session 20: retry loop bỏ sót lỗi mạng khác wording (message-match → type-match)
- **Trigger**: PC2 cúp điện thật lần 2 (2026-08-03 tối) → bot khởi động lại báo lỗi, KHÔNG tự phục hồi — đúng loại sự cố session 20 tưởng đã fix.
- **Root cause**: fix session 20 nhận diện "lỗi mạng" bằng cách match chuỗi message (`"getaddrinfo failed"`, `"connecterror"`...) — chỉ khớp đúng wording của sự cố lần 1 (`httpx.ConnectError: [Errno 11001] getaddrinfo failed`). Sự cố lần 2 là **loại lỗi mạng khác** (`httpx.ConnectTimeout: [WinError 10060] A connection attempt failed...`) — message hoàn toàn khác, không chứa marker nào → bị phân loại nhầm thành "lỗi config thật" → fail nhanh + thoát thay vì retry. Bug tái diễn y hệt session 20, chỉ khác wording lỗi gốc.
- **Bài học**: match theo **message string** của lỗi mạng là **không đáng tin** — message phụ thuộc OS/locale/loại lỗi cụ thể (DNS fail vs connection timeout vs connection refused đều ra message khác nhau). Cần match theo **exception type**.
- **Fix** (`orchestrator/agent.py`): thêm `import httpx`; đổi điều kiện `is_network` từ thuần string-match sang `isinstance(e, httpx.TransportError) or <string markers as fallback>`. `httpx.TransportError` là lớp cha chung của MỌI lỗi tầng kết nối (`ConnectError`, `ConnectTimeout`, `ReadTimeout`, `PoolTimeout`, `NetworkError`...) bất kể message cụ thể — verify qua `issubclass()`: cả `ConnectTimeout` và `ConnectError` đều `True`, còn `HTTPStatusError` (lỗi RLS — connect thành công, server từ chối) là `False`, nên vẫn phân biệt đúng "không có mạng" khác với "có mạng nhưng bị từ chối".
- **Verify**: test logic replay đúng 2 message lỗi thật từ log 2 sự cố (`getaddrinfo failed` VÀ `WinError 10060`) → cả 2 giờ đều retry đúng cho tới khi hết lỗi; giả lập `HTTPStatusError` kiểu RLS → vẫn fail ngay, 0 retry (không đổi hành vi cho lỗi config thật). Restart bot thật (mạng đang OK) → qua smoke-test ngay, scheduler lên bình thường, không regression.

### 2026-07-28 (session 20) — Bot không tự dậy sau mất điện: retry vô hạn khi DNS/mạng chưa sẵn sàng
- **Trigger**: PC2 cúp điện thật (không phải test) → có điện lại nhưng bot KHÔNG tự chạy lại, dù Task Scheduler `-AtLogon` đã bắn đúng lúc login. Vợ/user không nhận được Telegram báo gì — phát hiện qua kiểm tra tay.
- **Root cause**: lúc Windows auto-logon xong và task `-AtLogon` bắn, network adapter/DNS **chưa kịp sẵn sàng** (router/ISP còn đang reconnect sau mất điện) → `db.health_check_write()` fail với `ConnectError: [Errno 11001] getaddrinfo failed`. Startup smoke-test (session 15) đúng chức năng — phát hiện lỗi, thoát sạch (`sys.exit(1)`, `clean_exit=True`) thay vì chạy hỏng. Nhưng KHÔNG có ai retry sau đó — task chỉ bắn 1 lần/logon. Càng trớ trêu: Telegram alert báo lỗi cũng cần mạng để gửi → gửi cũng fail cùng lý do → im lặng hoàn toàn.
- **Thử fix bằng Task Scheduler `RestartCount`/`RestartInterval`** (tính năng "restart on failure" có sẵn của Windows) — **verify thực nghiệm cho thấy KHÔNG hoạt động**: tạo task test (`-Once` trigger, action luôn exit 1, action tự ghi timestamp ra file mỗi lần thực sự chạy) → sau 5 phút với `RestartCount=3`/`RestartInterval=1min`, file chỉ có **đúng 1 dòng** — Task Scheduler không hề retry dù settings áp dụng thành công (`Get-ScheduledTask` xác nhận giá trị đã set). Kết luận: **không dựa vào Task Scheduler retry được** (ít nhất với kiểu trigger đã test); setting vẫn giữ lại trên task thật (`RestartCount=20`/`RestartInterval=3min`) làm lưới an toàn phụ vì vô hại, nhưng KHÔNG phải cơ chế chính.
- **Fix thật** (`orchestrator/agent.py` → `start()`): đổi khối DB smoke-test từ "thử 1 lần, fail thì thoát" thành **vòng lặp retry vô hạn mỗi 30s** cho lỗi thuộc nhóm mạng (`getaddrinfo failed`, `ConnectError`, `ConnectTimeout`, "network is unreachable", v.v. — match theo `err_msg.lower()`). Lỗi KHÔNG thuộc nhóm mạng (RLS, sai `SUPABASE_SERVICE_KEY`...) vẫn fail nhanh + alert Telegram như cũ, vì retry không giúp được lỗi config thật.
- **Vì sao retry vô hạn (không giới hạn số lần)**: đã xác nhận Task Scheduler không tự relaunch task khi fail → smoke-test là **lưới an toàn duy nhất**. Giới hạn số lần retry sẽ tái tạo lại đúng bug này (bot chết hẳn nếu mất điện dài hơn ngưỡng). Trade-off chấp nhận: nếu lỗi mạng kéo dài, bot "treo" ở bước smoke-test vô thời hạn — nhưng đây là trạng thái **im lặng, vô hại, tự phục hồi** (không phải crash), ngay khi mạng có lại nó tự qua bước này và gửi Telegram "Started" bình thường.
- **Verify**: (1) test logic cô lập (mock `health_check_write` raise `ConnectionError("getaddrinfo failed")` 3 lần rồi pass) → retry đúng 3 lần, mỗi lần sleep 30s, rồi thành công; lỗi RLS giả lập → raise ngay, 0 retry, 0 sleep — cả 2 case + bộ marker network đều PASS. (2) Restart bot thật (network đang OK) → log `✅ DB smoke test passed` ngay lập tức, scheduler lên bình thường, không rơi vào nhánh retry — xác nhận không có regression ở happy path.
- **Sự cố phụ trong lúc debug** (tự gây ra, đã khắc phục): dùng `taskkill /T` trên 1 cmd.exe tưởng là orphan hóa ra lại là cha của chính bot đang chạy khỏe → giết nhầm cả cây process. Phát hiện ngay qua check lock file, khởi động lại bot thành công trong vài phút, không mất dữ liệu.

### 2026-05-29 (session 19) — Hotfix session 18: thêm f=p vào URL 2 (broker listing rò qua)
- **Trigger**: Vợ gửi tin `nhatot/132673950` (Kho xưởng Q12, 78M, account "Trần Quyết Chiến", profile Nhatot ghi "Môi giới"). Bot alert score 100 chinh_chu lúc 17:03 hôm nay.
- **Root cause**: Trong session 18, em decision URL 2 (`thue-van-phong-mat-bang-kinh-doanh-tp-ho-chi-minh`) **không thêm `?f=p`** với reasoning "spider's signal `account_type_business:-25` sẽ tự loại tin môi giới". **Reasoning sai**.
- **Investigation**:
  - Tin 132673950 có API field `type=u` (Nhatot trả là Cá nhân) → spider fire `account_type_personal:+25` → score 100.
  - Nhưng profile thực tế của user này Nhatot đánh badge "Môi giới" (profile-level label, không phản ánh trong API `type` field).
  - Test: fetch URL 2 với `?f=p` → tin **KHÔNG xuất hiện** trong page 1-3. Fetch không `?f=p` → tin xuất hiện page 2 vị trí 9.
  - Kết luận: **Nhatot's `f=p` filter strict hơn raw `type=u`** — check thêm 1 lớp profile-level "broker label" (auto-flag bởi Nhatot ML hoặc manual). Account "Trần Quyết Chiến" bị flag dù `type=u`.
- **Fix** (`config/spiders.yaml`): thêm `?price=15000000-%2A&f=p` vào URL 2:
  - URL 1 (giữ nguyên): `thue-bat-dong-san-tp-ho-chi-minh?price=15000000-%2A&f=p`
  - URL 2 (cập nhật): `thue-van-phong-mat-bang-kinh-doanh-tp-ho-chi-minh?price=15000000-%2A&f=p`
- **Cost của fix**: URL 2 sẽ return ít listings hơn (chỉ "verified personal" theo Nhatot), nhưng:
  - URL 1 vẫn catch tin chính chủ thuộc category khác (nhà mặt phố, kho, etc.)
  - Min_pages_before_early_stop=5 vẫn đảm bảo coverage page sâu
  - Trade-off: false negative (miss vài tin chính chủ) tốt hơn false positive (alert môi giới như case này)
- **Learning** (cho session sau): KHÔNG bao giờ tin `type=u` raw API là chính chủ thực. Nhatot's `f=p` URL filter là source-of-truth, không phải signal `account_type_personal` trong spider. Khi thêm URL Nhatot, mặc định luôn dùng `?f=p`.
- **Verify**: bot restart 18:25:40 PID 6132, smoke test pass, config mới load. Future cycles Nhatot URL 2 sẽ không trả tin này. Tin 132673950 đã trong dedup cache → không re-process.

### 2026-05-28 (session 18) — Nhatot multi-URL + min-pages floor + fix district "Thành phố Thủ Đức"
- **Trigger**: Vợ gửi URL tin `nhatot/132648841` (Cho thuê tòa nhà mặt phố Thủ Đức, 110M, chính chủ, score 75) — bot đã crawl + classify đúng lúc 12:26 hôm nay nhưng KHÔNG alert. Investigation chỉ ra 2 vấn đề riêng biệt nằm chồng nhau.
- **Root cause #1 (real blocker cho tin này)** — district normalizer reject "Thành phố Thủ Đức":
  - Nhatot trả `area_name = "Thành phố Thủ Đức"` (TP Thủ Đức là đơn vị hành chính đặc biệt sáp nhập từ Q2+Q9+Thủ Đức cũ năm 2021).
  - `_normalize_district` trong `pipeline/classifier.py` không strip prefix "Thành phố" / "TP" / "TP." → `"thanh pho thu duc"` không match `"thu duc"` trong whitelist → reject `ngoai_quan`.
  - Fix: thêm `thanh\s*pho|tp\.?` vào regex strip prefix. Verify: 7/7 test pass (gồm 3 test case mới `test_thanh_pho_prefix`).
- **Root cause #2 (broader coverage issue)** — bot có thể miss tin ở page sâu:
  - Initial hypothesis: tin 132648841 ở page 5 của `?f=p` filter. Bot's `dedup_stop_ratio: 0.7` early-stop fire ở page 1 → bot không reach page 5.
  - Verify thực tế: tin được bot bắt được hôm nay (sau 2 ngày downtime, page 1 ít dedup hit). Nhưng trong steady-state operation, dedup hit rate cao → vẫn miss tin ở page 5+.
  - Fix preventive (giống pattern muaban session 17):
    - Multi-URL config: `url:` (single) → `urls:` (list 2 entries). URL 1 giữ nguyên `?f=p` filter (chính chủ), URL 2 thêm `thue-van-phong-mat-bang-kinh-doanh-tp-ho-chi-minh` (category-specific, sort chronological hơn).
    - `min_pages_before_early_stop: 5` config mới — bắt buộc crawl ít nhất 5 page/URL trước khi early-stop được phép fire. Pages 1-4 luôn được crawl bất kể dedup ratio.
- **Refactor** (`spiders/nhatot.py`):
  - `__init__`: đọc `urls` list trước, fallback `url` single.
  - `_page_url(start_url, page_num)`: parameterized signature thay vì `self.start_url`.
  - `fetch_listings`: outer loop cho mỗi URL → gọi `_fetch_pages_from(start_url, loop)`. Stage 2 post-process (same-session count) global cross-URL.
  - `_fetch_pages_from`: inner crawl logic với check `if page_num < min_pages: skip early-stop` rồi `continue`. Log slug-prefixed: `[nhatot:thue-bat-dong-san-tp-ho-chi-minh] Page 1: ...`.
- **Pattern source**: 100% copy từ `spiders/muaban.py` session 17. 3 spider giờ đã chuẩn hoá multi-URL pattern (batdongsan, muaban, nhatot).
- **Verify**:
  - Multi-URL: bot post-restart log `[nhatot:thue-bat-dong-san-tp-ho-chi-minh] Done: 188 listings` rồi tiếp `[nhatot:thue-van-phong-mat-bang-kinh-doanh-tp-ho-chi-minh] Fetching page 1`. ✅
  - Min_pages floor: log `Page 1: dedup 10/18 (early-stop disabled until page 5)` ở pages 1-4. ✅
  - District fix: DB rehydrate tin 132648841 → `district='Thành phố Thủ Đức' → normalized='thu duc' → in whitelist: True`. Score 75, label chinh_chu, price 110M, age 0.05h, tất cả pass alert filters. ✅
  - Tin này specifically sẽ không re-alert vì đã trong dedup cache, nhưng tin TP Thủ Đức tương lai sẽ alert.
- **Tests**: +1 test (`test_thanh_pho_prefix`) trong `TestDistrictNormalization` — 3 case (Thành phố/TP/TP.) + 1 regression case (Thành phố Hà Nội không match TP). 7/7 pass.

### 2026-05-26 (session 17) — Mở rộng muaban: 1 URL → 3 URL (nhà cho thuê + văn phòng/MBKD + nhà xưởng/kho/đất)
- **Trigger**: Vợ gửi 3 link muaban có tin chính chủ mà bot bỏ sót (BACKLOG item "Mở rộng muaban URL category"). Cụ thể: bot chỉ crawl `cho-thue-van-phong-mat-bang-ho-chi-minh`, miss 2 category `cho-thue-nha-ho-chi-minh` và `cho-thue-nha-xuong-kho-dat-ho-chi-minh`.
- **Root cause**: KHÔNG phải bug parsing/dedup. Là gap **phạm vi config** — `config/spiders.yaml:54` hardcode `url:` (single string), spider load `self.start_url` rồi loop pages. 2 category còn lại không bao giờ được fetch.
- **Refactor** (`spiders/muaban.py`):
  - `__init__`: đọc `urls` (list) trước, fallback `url` (string) cho backward-compat.
  - `_page_url(start_url, page_num)`: signature đổi để nhận URL làm tham số (thay vì `self.start_url`).
  - `fetch_listings`: split thành outer loop (cho mỗi `start_url` trong `self.start_urls` → gọi `_fetch_pages_from`) + Stage 2 detail enrichment global + post-process `same_session_account_count` global.
  - `_fetch_pages_from(session, start_url)`: helper mới chứa toàn bộ inner crawl logic (paginate, parse, VIP filter, early-stop). Log lines giờ kèm slug để dễ debug: `[muaban:cho-thue-nha-ho-chi-minh] Fetching page 1: ...`.
- **Pattern source**: 100% copy từ `spiders/batdongsan.py` (lines 93-102 init, 127-132 outer loop, 166-292 helper, 546-552 `_page_url`). Đã chuẩn hoá multi-URL pattern across 2 spiders.
- **State management — giữ global, không tách per-URL** (decision rationale):
  - `self.seen_ids` global → cùng listing xuất hiện ở 2 category chỉ classify 1 lần. Tránh re-alert + tiết kiệm Stage 2 detail fetch.
  - `same_session_account_count` aggregate cross-category → 1 user post ở cả "nhà cho thuê" + "nhà xưởng" → fire signal multi-listing broker đúng (đây là behavior mong muốn, ko phải bug).
- **Config thay đổi** (`config/spiders.yaml`): `url:` → `urls:` list 3 entries. Tất cả query params `?sort=1&price=15000000-100000000` (sort=1 mandatory cho early-stop; price filter parity với behavior cũ).
- **Verify**: `bot spider run muaban --dry-run` standalone → expect 3 dòng `[muaban:slug] Fetching page 1` (1 cho mỗi URL), `Stage 1 done: N listings từ 3 URL(s)`, dedup cross-category hoạt động. Sau đó restart bot → monitor 1 muaban cycle thật → expect ít nhất 1 alert từ category mới nếu có chính chủ score ≥ 50 trong 30-60 phút.

### 2026-05-26 (session 16) — Fix silent crash: lock preserved on unhandled exception
- **Trigger**: BACKLOG bug "bot silent crash khi browser context die" — atexit luôn dọn lock kể cả khi crash → next start không detect được crash.
- **Root cause**: `atexit.register(lambda: lock_file.unlink(...))` unconditional — chạy bất kể process thoát bình thường hay crash.
- **Fix** (`orchestrator/agent.py` → `start()`):
  - `clean_exit = False` flag, chỉ set `True` trên 2 con đường graceful: (1) `except (KeyboardInterrupt, SystemExit, asyncio.CancelledError)` và (2) smoke test abort trước `sys.exit(1)`.
  - `_atexit_cleanup()` thay lambda: chỉ `unlink` lock nếu `clean_exit is True`. Crash path → lock giữ lại → next start detect qua PID-not-alive.
  - Thêm `except Exception` cho crash path trong main loop: log error + gửi Telegram `💥 CRASHED` với traceback truncated + uptime + hint "lock giữ lại" + `scheduler.shutdown(wait=False)` + `raise`.
  - Thêm `asyncio.CancelledError` vào graceful stop handler (Python 3.8+: CancelledError là BaseException, không bị `except Exception` bắt — nếu event loop bị cancel externally thì không bị nhầm là crash).
- **Coverage matrix**:
  - `Ctrl+C` / `bot-stop` → `clean_exit=True` → lock dọn → Telegram "stopped" ✅
  - Smoke test fail → `clean_exit=True` → lock dọn → Telegram "KHỞI ĐỘNG THẤT BẠI" ✅
  - Unhandled exception trong main loop → `clean_exit=False` → lock giữ → Telegram "CRASHED" → next start detect ✅
  - Kill -9 / OOM / power loss → atexit không chạy → lock giữ → next start detect (đã có từ session 14) ✅
  - **Gap còn lại**: exception trong APScheduler job không propagate lên main loop (APScheduler tự catch) → main loop vẫn `while True` → bot không crash nhưng spider chết lặng. Separate bug, chưa scope.
- **Verify**: `bot-stop` → lock deleted ✅ (confirmed). Bot restart → smoke test pass → scheduler started ✅.

### 2026-05-25 (session 15) — Supabase project transfer → RLS chặn 21h + bot doctor key prefix check
- **Trigger**: User chuyển project Supabase sang organization khác tối 24/05. Bot "đứng" từ 21h 24/05 đến ~17h 25/05 (~20h downtime im lặng).
- **Symptom đánh lừa**: bot KHÔNG đứng theo nghĩa thông thường — PID alive, log file vẫn ghi mỗi cycle scrape/dedup/classify, `bot doctor` PID check báo healthy. Nhưng 853 RLS errors cumulative, 0 alert Telegram, 0 DB writes trong gần 24h.
- **Root cause**: Supabase đã release format key mới (`sb_secret_*` = service role, `sb_publishable_*` = anon) thay cho JWT cũ (`eyJ...`). Khi transfer sang org khác, Supabase re-issue keys; user copy nhầm `sb_publishable_*` vào `SUPABASE_SERVICE_KEY`. Publishable key pass authentication nhưng bị RLS chặn mọi insert (`code 42501: new row violates row-level security policy`).
- **Fix**: chỉ update `.env` (no code change). Replace `sb_publishable_*` → `sb_secret_*`. Restart bot (`bot-stop.bat` + `bot-start-headless.bat`).
- **Verify** (tail log post-restart): 853 RLS errors cumulative → **0 errors** sau restart. Dedup cache local còn nguyên → cycle đầu sau restart dồn 128 listings backlog, ra **52 alerts Telegram trong 30 phút** rồi giãn lại bình thường.
- **Prevention** (`cli/main.py` → `doctor`): thêm check prefix `SUPABASE_SERVICE_KEY` ngay sau bước verify key tồn tại:
  - `sb_publishable_*` / `sb_anon_*` → HARD FAIL với hướng dẫn copy-paste vào Supabase Dashboard.
  - `sb_secret_*` / `eyJ...` (JWT cũ) → PASS.
  - Format khác → WARN (chưa biết, đừng hard fail).
  - Verify: negative test với `SUPABASE_SERVICE_KEY=sb_publishable_TEST` → `bot doctor` fail rõ ràng tại check này, KHÔNG đợi tới step "Supabase reachable" mới ra lỗi mơ hồ.
- **Defense-in-depth: startup write smoke test** (`db/client.py` → `health_check_write()`, gọi từ `orchestrator/agent.py` → `start()` sau lock setup, trước `setup_scheduler()`):
  - Insert 1 sentinel row vào `spider_logs` (`spider_name="__health_check__"`). KHÔNG swallow exception — caller xử lý.
  - Orchestrator catch → nếu lỗi chứa `row-level security` / `42501` thì hint key prefix; lỗi khác thì hint URL/key. Telegram alert `🚨 KHỞI ĐỘNG THẤT BẠI` với hint cụ thể + `sys.exit(1)`. atexit dọn lock (không phải crash → next start không trigger detection).
  - Tại sao không SELECT-only: incident 2026-05-25 cho thấy publishable key có thể SELECT qua RLS permissive (seed_from_db chạy OK) nhưng INSERT bị chặn → SELECT check không catch được. Smoke test bắt buộc dùng write op.
  - Tại sao không dedicated health_check table: tránh schema migration. `spider_logs` đã bắt buộc service-role, accumulate sentinel rows trivial (~1 row/restart).
  - Verify: bot restart → log `✅ DB smoke test passed (write OK)` ngay sau `Ready`, trước `Scheduler started`. Negative path không test live (sẽ spam Telegram thật) — trust theo bot doctor negative test đã chạy ở cùng session.

### 2026-05-22 (session 14) — Self-healing lock + headless auto-start + Telegram lifecycle + district fix
- **Trigger**: Bot bị block ko khởi động được vì zombie lock file (PID 15048 đã chết nhưng `.orchestrator.lock` còn). User yêu cầu: loại root cause + làm friendly + standardize naming + auto-start sau reboot + Telegram báo lifecycle.
- **Self-healing lock** (`orchestrator/agent.py`):
  - Helper `_pid_alive(pid)` dùng `os.kill(pid, 0)` (stdlib, cross-platform, ko cần psutil).
  - Logic: lock tồn tại → check PID alive → alive thì exit, ko alive thì dọn lock + đánh dấu `crash_detected_pid` → start bình thường → gửi Telegram crash notify.
  - `atexit.register` dọn lock khi graceful exit. Crash để lock lại → next start tự phát hiện.
- **Headless + auto-start** (`bot-start-headless.bat` + Task Scheduler):
  - `pythonw.exe -X utf8 -m cli.main start --source manual-headless` chạy ko cửa sổ.
  - Task Scheduler "RealEstork Bot" — trigger `-AtLogon`, action chạy `bot-start-headless.bat`, source `auto-headless`. Tự khởi động khi đăng nhập Windows.
  - Guard `sys.stderr is not None` trong `cli/main.py` (pythonw có stderr/stdout = None → loguru `add(sys.stderr)` crash).
- **Symmetric naming + stop**: `bot-start.bat` (visible) / `bot-start-headless.bat` / `bot-stop.bat` (đọc PID từ lock + `taskkill /F` + dọn lock). Khớp với `bot doctor` pattern. CLI `bot stop` cũng có.
- **Telegram lifecycle** (`notifications/telegram.py` → `send_lifecycle()`): gửi vào admin chat + group General topic (ko `message_thread_id`). 3 sự kiện:
  - 🟢 Started — mode label (manual-visible/manual-headless/auto-headless) + PID + time.
  - 🔴 Stopped — uptime + PID. Trigger: Ctrl+C, `bot stop`, atexit.
  - ⚠️ Crash detected — gửi ở lần start kế tiếp sau crash, kèm PID cũ đã chết.
- **Fix `_normalize_district`** (`pipeline/classifier.py`): batdongsan-45685110 (Tân Bình, score=66) bị reject "ngoài quận". 3 bug:
  1. Format batdongsan `"Q. Tân Bình (P. Bảy Hiền mới)"` — outer là district, code cũ chỉ extract inner.
  2. Regex `p\.?` ăn chữ "p" trong "phu nhuan" → "hu nhuan". Sửa: tách prefix dạng short (q/p/h) bắt buộc có `.` hoặc space.
  3. Suffix "cũ/mới" sau ward merger 2025 ko bị strip → `"7 cu"` ko match whitelist.
- **Tests**: +6 test trong `TestDistrictNormalization` (tests/test_pipeline.py) — batdongsan format, muaban format, no parens, leading zeros, Phú Nhuận edge, empty. Pass 6/6.
- **Docs**: `README.md` rewrite (bảng lệnh + lifecycle + Task Scheduler), `docs/cli.md` rewrite (bot prefix throughout + lifecycle table), `BACKLOG.md` mới (track muaban URL expansion + 2 known bugs).
- **Known bug** (chưa fix, đã ghi BACKLOG): bot silent crash khi browser context die — atexit vẫn chạy → dọn lock → crash detection miss.

### 2026-04-28 (session 13) — District whitelist 19 quận + per-district price override
- **Trigger**: 2 tin score=100 chinh_chu (`nhatot/132087311` Tân Phú nhà đất, `nhatot/132087583` Bình Tân mặt bằng kinh doanh) bị reject "ngoài quận" hôm 28/04. Cả 2 đều là tin chính chủ thật, miss alert.
- **Fix YAML** cả 3 source (`config/scoring.yaml` + `scoring_batdongsan.yaml` + `scoring_muaban.yaml`):
  - Whitelist 16 → 19 quận: thêm Q12, Tân Phú, Bình Tân. Loại 5 huyện ngoại ô (Bình Chánh, Củ Chi, Hóc Môn, Nhà Bè, Cần Giờ).
  - Thêm `district_price_overrides` block: Q12/Tân Phú/Bình Tân chỉ alert tin >= 40M (filter tin nhỏ ở vùng xa).
- **Fix code** (`pipeline/classifier.py`): thêm helper `_min_price_for_district(filters, district)` — resolve override qua `_normalize_district` matching. Update `should_alert_wife()` + `alert_skip_reason()` dùng helper thay vì đọc `wife_min_price_vnd` trực tiếp.
- **Verify**: 7/7 unit test pass (Tân Phú 18M=gia_thap, Bình Tân 50M=pass, Quận 1 18M=pass, Bình Chánh 30M=ngoai_quan, etc.)
- **Doc**: PRD §8.2 update bảng "Điều kiện alert" + thêm bảng `district_price_overrides`. Session 13 entry trong PRD changelog.

### 2026-04-28 (session 12) — Per-source scoring muaban
- **Root cause**: 18 cycles × ~50 listings/ngày → **0 alert Telegram**. Trần điểm thực tế muaban = 50 (base) + 10 (very_fresh) − 10 (listing_is_vip) = 50 < `wife_min_score: 55` default. `account_type_personal:+25` chỉ fire cho nhatot.
- **Fix `config/scoring_muaban.yaml`** (per-source config đã có sẵn, `PER_SOURCE_CONFIGS = ("batdongsan", "muaban")` ở `pipeline/classifier.py:21`):
  - Thêm `alert_filters` block (wife_min_score: 50, wife_max_listing_age_hours: 24, wife_min_price_vnd: 15M, 16 quận trung tâm)
  - Hạ thresholds: chinh_chu 65→60, can_xac_minh 40→38
  - Bỏ `listing_is_vip` (mọi muaban đều VIP, signal không discriminate)
  - Giảm `same_session_multi_listing` -20 → -15 (muaban có chủ 2-3 mặt bằng phổ biến)
- **Doc**: Scoring Guide v1.0 → v1.1 với note v12. PRD v2.3 thêm session 11+12.
- **Verify**: `[classifier] Loaded muaban: 14 signals. Thresholds: chinh_chu>=60, can_xac_minh>=38` ở orchestrator startup. Alert vợ sẽ ra 1-2 cycle tiếp theo.

### 2026-04-25 (session 11) — Self-serve setup (PC1→PC2 reproducible)
- **Root cause**: scrapling 0.4+ tách engine deps; `requirements.txt` pin `>=0.2.9` quá lỏng → fresh PC pull về thiếu `patchright`/`msgspec`/`protego` → spider chết với log misleading "scrapling not installed".
- **Fix install**: `pip install patchright msgspec protego` (qua `scrapling[fetchers]`).
- **`requirements-lock.txt`** (107 packages, exact versions). `setup-full.bat` (one-click setup). `bot doctor` command (`cli/main.py`) — pre-flight 25 checks tiếng Việt với fix copy-paste-ready.
- **Spider error message bộc lộ root cause**: `except ImportError as e:` + log `{type(e).__name__}: {e}` thay vì câu chung chung.

### 2026-04-22 (session 9) — Remove nhatot phone scraping (account banned)
- **Chotot account bị ban**: `_NHATOT_RSA_PUBLIC_KEY`, `PHONE_API`, `_fetch_phone`, `_encrypt_list_id` xóa khỏi `spiders/nhatot.py`
- **Orchestrator**: Xóa `_check_nhatot_token()` + `NhatotAuthClient` import. Spider nhatot giờ chỉ đọc `__NEXT_DATA__`, không cần token.
- **Log spam fix**: 60 WARNING/cycle → 0 (phone loop không còn tồn tại)

### 2026-04-20 (session 8) — Rollback Batdongsan speed strategy
- **Rollback to skip VIP** (`spiders/batdongsan.py`):
  - Quay lại chiến lược skip `re__vip-silver/gold/diamond` + `re__pro-agent` ngay tại list page.
  - Mục tiêu: Tối ưu tốc độ, giảm số lượng detail page fetch không cần thiết.
  - Phù hợp với PRD v2.2.
- **Phone extraction removal**: Xác nhận đã gỡ bỏ logic lấy SĐT BDS (quá phức tạp/chậm) để tập trung vào content signals.

### 2026-04-18 (session 5) — Batdongsan redesign: 2-stage fetch + BDS-specific scoring
- **Crawl strategy overhaul** (`spiders/batdongsan.py`):
  - URL: `/cho-thue-nha-mat-pho-tp-ho-chi-minh?cIds=577,52,576,53` (Kho + Nhà xưởng + Đất + Shophouse), `max_pages=30`
  - Stage 1 (list): skip `re__vip-silver/gold/diamond` + `re__pro-agent` cards. Dual early-stop: first non-"hôm nay" card OR >70% dedup hit-rate per page
  - Stage 2 (detail): per-listing fetch → phone raw/prid/uid, contact_name, full description, guru profile hash, pro-agent badge. Async sem=4
  - Stage 3 (lazy): `enrich_from_profile()` extracts "Tin đăng đang có" (active count) + "Tham gia N năm" (→ absolute join year)
  - `_parse_relative_time`: "hôm nay"/"hôm qua"/phút/giờ/ngày với UTC+7 TZ
  - `seen_ids: set[str]` attr seeded by orchestrator from dedup cache
- **Per-source scoring** (`pipeline/classifier.py`):
  - `PER_SOURCE_CONFIGS = ("batdongsan",)` → auto-loads `config/scoring_{source}.yaml`
  - `classify()` picks config via `listing.source`; thresholds + signals source-specific
  - `should_alert_wife/product` merge default + source filters
- **New BDS signals** (`pipeline/signals.py`):
  - `bds_broker_multi_active_listings` (-30): active>5 (ngưỡng user approve)
  - `bds_owner_few_active_listings` (+15): 2≤active≤5
  - `bds_owner_single_listing` (+10): active==1 (stacks với few)
  - `poster_join_year_veteran` (-10): joined ≥3 năm
  - `detail_has_pro_agent_badge` (-40): hard broker
  - All guard on `poster_profile_hash != None` (prevent firing before enrichment)
- **Orchestrator** (`orchestrator/agent.py`):
  - `run_scrape_cycle` now `exclude=["batdongsan"]`
  - New `run_batdongsan_cycle`: seeds `spider.seen_ids` → fetches → dedupes → per-listing classify pass 1 → if score ∈ [30, 75] + profile_hash → `enrich_from_profile` → classify pass 2 → persist + alert
  - `_process_listing` takes optional `enrich_profile_spider` (backward-compat for non-BDS paths)
- **Configs**:
  - `config/schedule.yaml`: thêm `batdongsan_cycle` 20-min (song song với `scrape_cycle` 5-min)
  - `config/spiders.yaml`: URL mới, `max_pages: 30`, `detail_concurrency: 4`, `dedup_stop_ratio: 0.7`
  - `config/scoring_batdongsan.yaml` (NEW): thresholds nới (chinh_chu 60, can_xac_minh 38) do thiếu 3 nhatot-only signals
- **Infrastructure**:
  - `spiders/base.py`: RawListing + `poster_profile_hash`, `poster_join_year`, `has_pro_agent_badge`; BaseSpider + `seen_ids`
  - `spiders/__init__.py`: `fetch_all(only, exclude)` + `get_spider(name)`
  - `pipeline/dedup.py`: `seen_source_ids` property

### 2026-04-15 (session 4)
- Batdongsan phone reveal implemented:
  - Endpoint: POST `/microservice-architecture-router/Product/ProductDetail/DecryptPhone`
  - Auth: Cookie-based (~7 ngày TTL), cần OTP thủ công
  - Payload: `raw` attr từ `span.js__card-phone-btn` + `prid` + `uid`
  - Response: plain text `|0938 612 266`
  - `auth/batdongsan_auth.py`: BatdongsanAuthClient — Playwright Google OAuth + OTP → lưu cookies
  - `spiders/batdongsan.py`: extract `raw`/`prid`/`uid` từ list page → batch DecryptPhone (httpx)
  - `cli/main.py`: `setup-batdongsan` command — visible browser cho Google + OTP
  - `orchestrator/agent.py`: `_check_batdongsan_cookies()` — alert 24h trước khi hết hạn
  - `.env.example`: thêm `BDS_ACCOUNT_PHONE`
  - Không cần vào detail page — tất cả data có trên list page
- Fix trangtrang.com URL: `/dien-thoai/{phone}` → `/{phone}.html` (SSR, không cần DynamicFetcher)
- AI model: switch từ Ollama gemma4 → zero-token gemini-web/gemini-pro

### 2026-04-15 (session 3)
- Auto token refresh via Google OAuth + Playwright browser profile
  - `auth/nhatot_auth.py`: NhatotAuthClient — headless Chrome intercepts Bearer token
  - `cli/main.py`: `setup-nhatot` command — visible browser for first-time Google login
  - `orchestrator/agent.py`: `_check_nhatot_token()` → auto-refresh (không cần manual DevTools)
  - `notifications/telegram.py`: thêm `send_admin()` helper
  - Profile lưu tại `.nhatot_browser_profile/` (gitignored)
  - Token refresh headless ~15-20s; nếu session hết hạn → Telegram nhắc chạy setup-nhatot
- Scoring adjustments (từ feedback session 3):
  - `text_owner_language`: weight +15 → +5 (môi giới giả danh claim này)
  - `text_marketing_superlatives`: mở rộng từ 10 → 24 keywords (phân nhóm rõ)
  - `photo_count_low`: <= 3 → <= 5
  - `same_session_multi_listing`: > 1 → > 2 (chủ 2 mặt bằng không bị phạt)
  - `account_name_broker_keywords`: xóa "agent", thêm "công ty", "doanh nghiệp", "tnhh"


### 2026-04-13 (session 2)
- Đổi nhatot URL sang `thue-bat-dong-san?price=15000000-*&f=p` (vợ share, f=p = cá nhân/personal only)
- Fix `_page_url()` để giữ nguyên query params (f=p, price) khi phân trang
- Tắt tất cả phone-frequency signals (phụ thuộc token 24h TTL không ổn định)
- Thêm `account_type_personal` (+25) và `account_type_business` (-25) signals từ nhatot `type` field
- `account_type=None` (default) → signal không fire → tương thích các site khác
- Thêm `account_type` field vào `RawListing`, extract từ `raw["type"]` trong nhatot spider
- Thêm price filter >= 20M VND (URL + alert_filters + should_alert_wife)
- Thêm signals: `account_name_broker_keywords` (-20), `same_session_multi_listing` (-20), `description_many_emojis` (-15)
- `same_session_account_count`: nhatot spider post-process, đếm số tin cùng account_name trong 1 batch
- Lưu ý: 2.2 (account bio/description) không available trong listing API, bỏ qua

### 2026-04-13 (session 1)
- Implemented nhatot phone reveal via RSA-3072 + Bearer token
- Implemented alonhadat phone reveal via detail page tel: scrape
- Added district whitelist filter (16 central HCMC districts) in `should_alert_wife()`
- Added `_normalize_district()` for fuzzy district matching (handles Q.3, Quận 3, etc.)
- Added nhatot token expiration detection + Telegram alert (throttled once/day)
- Telegram: differentiated phone display per source (🔒 SĐT ẩn for nhatot/batdongsan)
