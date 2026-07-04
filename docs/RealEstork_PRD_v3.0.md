# RealEstork — PRD v3.0

## Nền tảng OSINT Bất động sản Cho thuê Mặt bằng HCMC

**Codename:** RealEstork
**Version:** 3.0 (kế thừa v2.3)
**Date gốc:** 06/04/2026 | **Cập nhật v3.0:** 08/07/2026
**Author:** Chankwan
**Primary language:** Python 3.12+ (bot) + JavaScript userscript (Facebook capture)
**Host:** CHANKWAN-WIN2 (Ryzen 7 5700G / GTX 1660 SUPER 6GB / Win11)

> **v3.0 có gì mới so với v2.3:** thêm **nền tảng thứ 5 — Facebook Groups** (mô hình PUSH, hoàn toàn khác 3 portal PULL), cập nhật kiến trúc, và các thay đổi session 13-19. Tài liệu viết theo 2 tầng: **kỹ thuật** (để agent/engineer khác rebuild được) + **"business view"** (để đọc nhanh, hiểu ý nghĩa vận hành).

> **Trạng thái tài liệu v3.0 (viết theo chunk, duyệt từng phần):**
> - ✅ **Chunk 1:** Section Facebook Groups (rebuild-grade) + Kiến trúc PUSH + Chống ban/via.
> - ✅ **Chunk 2 (file này):** Phân loại v3 (Chủ/Khách/Môi giới) + 2 topic Telegram — **spec thiết kế, chưa build**.
> - ✅ **Chunk 4:** DB schema đầy đủ (từ `db/schema.sql`) + thiết kế bảng `fb_posters`.
> - ✅ **Chunk 3:** Cập nhật 4 portal về hiện tại (session 13-19: multi-URL, crash detection, RLS incident).
>
> → **PRD v3.0 chunk 1-4 đã xong.** Còn lại (không gấp): merge các phần business/OSINT/scoring 4-portal còn kế thừa nguyên từ v2.3 vào file này.
> - ♻️ Các phần business/đối thủ/revenue/OSINT/scoring 4 portal: **kế thừa nguyên `docs/RealEstork_PRD_v2.3.md`** cho tới khi merge vào các chunk sau.

---

## MỤC LỤC (v3.0 — full)

*(Đánh dấu: ✅ viết trong v3.0 | ♻️ còn ở v2.3 chờ merge)*

1. ♻️ Tổng quan & Bối cảnh
2. ♻️ Phân tích Đối thủ
3. ♻️ Hai hướng Kinh doanh
4. ♻️ Revenue Tiềm năng
5. ✅ **Kiến trúc Hệ thống v3 — PULL (portal) + PUSH (Facebook)**
6. ♻️ Tech Stack
7. ♻️ Module 1: Scraper Engine — Portal (nhatot / batdongsan / muaban / alonhadat) · ✅ **cập nhật ss13-19 → §7b**
8. ✅ **Module 1b: Nền tảng #5 — FACEBOOK GROUPS (PUSH model)**  ← trọng tâm Chunk 1
9. ♻️ Module 2: Dedup & Classification (portal)
10. ✅ **Module 2b: Phân loại v3 — Chủ / Khách / Môi giới** (spec — Chunk 2)
11. ♻️ Module 3: OSINT
12. ✅ **Module 4: Alert — Telegram topics theo nguồn** (cập nhật FB)
13. ♻️ Module 5: Auth & Token
14. ♻️ Module 6: Orchestrator (+ FB cycle, + receiver startup)
15. ✅ **Module 7: DB Schema đầy đủ + `fb_posters`** (Chunk 4)
16. ✅ **Chống ban & Quản lý via Facebook**
17. ♻️ Vận hành & Config

---

# 5. KIẾN TRÚC HỆ THỐNG v3 — PULL + PUSH

RealEstork v3 có **2 mô hình thu thập song song**, khác nhau về bản chất:

```
┌─────────────────────────── CHANKWAN-WIN2 (On-premise) ───────────────────────────┐
│                                                                                    │
│  MÔ HÌNH PULL (bot tự đi lấy)          MÔ HÌNH PUSH (dữ liệu tự đẩy về)             │
│  ─────────────────────────            ──────────────────────────────              │
│  Portal: nhatot, batdongsan,          Facebook Groups (đóng):                      │
│  muaban, alonhadat                     [Chrome profile riêng, login via FB]         │
│    │  APScheduler mỗi 5–20 phút          │  userscript Tampermonkey đọc THỤ ĐỘNG    │
│    │  bot fetch web (browser/HTTP)        │  màn hình → POST localhost              │
│    ▼                                      ▼                                         │
│  Spider → RawListing                    ingest/fb_receiver.py (HTTP queue)          │
│                    \                      │  facebook_groups_cycle drain mỗi 3'     │
│                     \                     ▼                                         │
│                      └──────►  PIPELINE CHUNG  ◄────────┘                           │
│                         Dedup → Classify → OSINT → DB(Supabase) → Telegram          │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Vì sao 2 mô hình:** portal cho phép bot tự fetch (dù có Cloudflare/anti-bot vẫn vượt được bằng browser giả lập). **Facebook group ĐÓNG thì không** — nằm sau tường đăng nhập, không API công khai, và Meta 2026 bắt automation cực gắt. Nên FB đảo chiều: **một browser thật của người thật đọc màn hình rồi đẩy về bot** — bot không bao giờ tự đụng vào FB. Chi tiết ở Mục 8.

**Điểm gộp chung:** cả 2 mô hình cho ra cùng `RawListing` (`spiders/base.py`) → đi vào **cùng pipeline** dedup/classify/telegram. Nhờ đó FB tái dùng toàn bộ hạ tầng sẵn có, và tín hiệu **SĐT-trùng-môi-giới cross-platform** hoạt động xuyên nguồn.

---

# 8. MODULE 1b — NỀN TẢNG #5: FACEBOOK GROUPS (PUSH)

> **Business view:** Nhiều tin chính chủ cho thuê mặt bằng **chỉ xuất hiện trong các group Facebook đóng**, không lên portal. Đây là nguồn tin chất lượng cao nhưng khó nhất. Giải pháp: một tài khoản FB thật (via) mở group trong trình duyệt, một script đọc thụ động các bài đăng rồi gửi về bot — giống như "một nhân viên ngồi lướt group cả ngày và copy tin về", nhưng tự động.

## 8.1 Vì sao Facebook + vì sao chọn PASSIVE

**Ràng buộc thực tế (2026):**
- Group đóng nằm sau **login-wall** — không có API công khai, không đường "no-login".
- **Apify và các dịch vụ managed chỉ crawl được group PUBLIC** (~$2.6/1k post) — không dùng được cho group đóng.
- Meta 2026 chống automation rất gắt: AI chấm hành vi, đội chống scraping 100+ người, chấm điểm IP (datacenter = zero-trust), phát hiện account-linkage.

**Bốn mục tiêu mâu thuẫn:** ổn định + rẻ + zero-bảo-trì + zero-thủ-công — **không thể đạt cùng lúc** cho group đóng. Một đòn bẩy phải nhường.

**Quyết định — Passive capture:** một browser thật (via đã login) **đọc thụ động** chính màn hình FB rồi đẩy về bot.
- **Nhường:** tự vá script khi FB đổi giao diện (thưa) + 1 PC always-on mở tab FB.
- **Được:** ban risk thấp nhất (session thật + IP nhà + tần suất thấp = via sống lâu), gần như free (~0–50k/tháng tiền via), không bơm traffic tự động → FB chỉ thấy "một người đang lướt group".

## 8.2 Kiến trúc PUSH (khác 3 portal PULL)

```
[PC always-on] Chrome — PROFILE RIÊNG "RealEstork Bot" (tách profile cá nhân)
   login sẵn 1 via FB (là member các group đóng)
      └─ Tampermonkey userscript "RealEstork FB Group Capture":
           • tự cuộn feed, đọc bài đang hiện
           • bóc: text, người đăng (uid), permalink, thời gian, ảnh
           • chống trùng tại chỗ (localStorage)
           • POST http://127.0.0.1:8787/ingest  (token X-Ingest-Token)
                    │  (chỉ trong máy — không ra internet)
                    ▼
[Bot] ingest/fb_receiver.py — ThreadingHTTPServer, nhận JSON → hàng đợi (queue.Queue)
                    │
                    │  orchestrator: facebook_groups_cycle mỗi 3 phút
                    ▼
   spiders/facebook_groups.py (DRAIN): rút hàng đợi → parse text → RawListing[]
                    ▼
        Dedup → Classify → (OSINT) → DB → Telegram (topic FB)
```

**Thành phần mới trong repo (không có ở 4 portal):**
| Thư mục/file | Vai trò |
|---|---|
| `extension/realestork-fb-capture.user.js` | Userscript Tampermonkey — lớp capture (chạy trong browser) |
| `ingest/fb_receiver.py` | Cổng HTTP localhost nhận post + hàng đợi (stdlib, zero-dep) |
| `spiders/facebook_groups.py` | "Spider" kiểu **drain** — không kéo web, rút hàng đợi |
| `tools/fb_capture_test.py` | Harness test độc lập (nhận → parse → gửi admin chat) |
| `tools/tg_get_topic_id.py` | Lấy `message_thread_id` của topic Telegram |

## 8.3 Cổng nhận `ingest/fb_receiver.py` (rebuild-grade)

- **`ThreadingHTTPServer`** (stdlib, không thêm dependency), chạy trong 1 **daemon thread**, bind **`127.0.0.1:8787`** (chỉ tiến trình cùng máy POST được = anti-abuse lớp 1).
- Endpoint **`POST /ingest`**: header **`X-Ingest-Token`** phải khớp (lớp 2). Body JSON `{"posts": [ {...}, ... ]}`. Trả `{"received": N, "pending": M}`.
- Có **CORS** (`Access-Control-Allow-Origin: *` + preflight `OPTIONS`) vì userscript chạy trên origin `facebook.com`.
- `GET /health` → `{"ok": true, "pending": M}`.
- Hàng đợi = **`queue.Queue`** (thread-safe). API module: `start_receiver(host, port, token)`, `drain(max_items=None)`, `pending_count()`.
- Khởi động: `orchestrator/agent.py` → `start()` gọi `start_receiver(...)` **chỉ khi** spider `facebook_groups` được load (enabled), đọc host/port/token từ config spider + env `FB_INGEST_TOKEN`.

## 8.4 Cơ chế userscript — DOM contract FB 2026 (phần quan trọng nhất để rebuild)

> FB đổi DOM liên tục — đây chính là "đòn bẩy bảo trì" đã chấp nhận. Cách chẩn đoán khi vỡ: dán **probe** vào Console (F12) để soi cấu trúc thật, rồi chỉnh selector. Dưới đây là contract **đã xác minh thực tế** (session 07/2026).

**Định vị post:**
| Thứ | Selector / cách lấy (đã verify) |
|---|---|
| Container 1 post | **`div[role="feed"] > div`** — KHÔNG còn `div[role="article"]` (chỉ khớp 2 widget, sai). Lọc post thật = phần tử có `a[href*="/user/"]`. |
| Text bài | **`[data-ad-rendering-role="story_message"]`** (fallback: khối `div[dir="auto"]` dài nhất). Strip đuôi "See more"/"Xem thêm". |
| Người đăng (uid) | `a[href*="/user/"]` → regex `/user/(\d+)/`. Tên: `aria-label`/heading (best-effort, hay rỗng). |
| Thời gian | anchor có text dạng "20m"/"5 giờ" → parse relative → epoch (best-effort). |
| Ảnh | `img[src]` chứa `fbcdn`/`scontent`. |

**Moi post-id + dựng permalink chi tiết** (thử theo thứ tự, cái nào có trước lấy):
1. `/(?:posts|permalink)/(pfbid\w+|\d+)` — link post trực tiếp (hiếm trong feed mới).
2. `[?&](?:multi_permalinks|story_fbid)=(pfbid\w+|\d+)`.
3. **`[?&]set=(gm|pcb)\.(\d+)`** trên **link ẢNH** — ⭐ đây là chìa khoá cho feed mới. **CẢ `gm.` LẪN `pcb.` đều là group post id** → dựng `https://www.facebook.com/groups/<gid>/posts/<id>/` **mở đúng bài gốc** (đã xác minh thực tế; ban đầu tưởng pcb là album — SAI).
4. `/commerce/listing/(\d+)` → tin Marketplace share vào group → link `/commerce/listing/<id>/`.
- **Không moi được** (bài chưa load ảnh thành link, hoặc bài text thuần) → **fallback** link trang người đăng trong group `/groups/<gid>/user/<uid>/` (vẫn tới poster + thấy các tin khác của họ = vetting). **Nội dung post đã nhúng thẳng trong Telegram (📝)** nên không mất thông tin.

**Chờ-ảnh-render (pending) — vì sao cần:** `set=gm/pcb` nằm trong **link ảnh**, mà FB **load ảnh lười** (text hiện trước, ảnh thành link sau vài giây). Nếu chụp quá sớm → chưa có id → fallback. Cơ chế: post nào chưa có link thật → đưa vào `pending` map, **quét lại tối đa ~3 nhịp** (`MAX_WAIT_TICKS`) cho ảnh render; có id thì gửi link đúng bài, quá lâu mới chịu fallback. `dedupKey = hash(uid + text[:120])` ổn định (không phụ thuộc link) dùng cho seen/inflight/pending.

**Chống trùng + độ bền POST:** `seen` (localStorage) chỉ set **SAU khi POST trả 200** → receiver off/lỗi mạng thì post được giữ lại thử lại (không "nuốt" mất). `inflight` chặn gửi trùng trong lúc chờ.

**Xoay vòng group (rotation):** hiện **time-based** — ở mỗi group `dwellMs` ngẫu nhiên 90–150s rồi `location.href` sang group kế; badge hiện **đếm ngược** `chuyển sau Xs`. **Tự loại URL trùng** trong danh sách groups (bug thực tế: 2 URL giống nhau → `findIndex` trả index đầu → kẹt vòng lặp không qua group khác). Cuộn mỗi `captureEveryMs` = 6s.
> ⏳ **Kế hoạch (Bước 3.1):** thay time-based bằng **scan-until-seen** (gặp N bài đã-gửi liên tiếp thì chuyển group, giống early-stop batdongsan) + ép **sort chronological** (bài mới ở trên). Chưa implement.

**Badge chẩn đoán** (góc màn hình): `g<pos>/<N> · feed <số bài trên DOM> · chờ <pending> · sent <đã gửi> · chuyển sau <Xs>`.

## 8.5 Drain spider `spiders/facebook_groups.py`

- Kế thừa `BaseSpider` nhưng **`fetch_listings()` = rút hàng đợi** (`drain()`) thay vì kéo web.
- Mỗi post JSON → `parse_listing()` → `RawListing`: `source="facebook_groups"`, `source_id=post_id`, `source_url=permalink`, `description=text`, `contact_name`, `poster_account_id=uid`, `posted_at`, `images`.
- **Parse text tự do (best-effort, regex):** SĐT (VN mobile, chuẩn hoá qua `normalize_phone`), quận (list quận HCMC có dấu/không dấu + "Quận N"), giá (triệu/tr/tỷ), diện tích (m2/m²), tầng (trệt/lầu/tầng). Thiếu thì để trống — classifier vẫn xử lý.
- Post-process `same_session_account_count`: đếm số post cùng poster trong 1 batch (tín hiệu môi giới spam).

## 8.6 Định tuyến & hiển thị Telegram (nguồn FB)

- **Topic riêng, env-based:** `notifications`/orchestrator map `source → message_thread_id`. FB đọc từ env **`TELEGRAM_FB_TOPIC_ID`** (vd 3612); không set → rơi vào topic General. (nhatot=10, muaban=11, batdongsan=5 hardcode; số to như 3612 là do topic tạo muộn — thread_id = message_id lúc tạo topic.)
- **Nhúng thẳng text post (📝)** vào tin nhắn (`description[:600]`) — vì link group không preview được như link portal. Bỏ dòng 📍 địa chỉ khi trống (FB không có địa chỉ chuẩn).
- Nhánh hiển thị SĐT riêng cho FB: `"📋 SĐT trong nội dung post — mở link"`. Nhãn link: `"👤 Xem người đăng + các tin khác"`.

## 8.7 Config & vận hành FB

```yaml
# config/spiders.yaml
- name: facebook_groups
  enabled: true            # go-live: bật → receiver chạy khi bot start
  type: push               # PUSH model (không pull web)
  ingest_host: "127.0.0.1"
  ingest_port: 8787
  ingest_token: "..."      # khớp token trong userscript; hoặc override bằng env FB_INGEST_TOKEN
  groups: [ ... URL group đóng ... ]   # userscript xoay vòng qua đây
```
```yaml
# config/schedule.yaml
facebook_groups_cycle:
  interval_minutes: 3      # drain hàng đợi mỗi 3 phút (rẻ; no-op khi rỗng)
  function: run_facebook_groups_cycle
  enabled: true
```
- Env bắt buộc: **`FB_INGEST_TOKEN`** (khớp userscript), **`TELEGRAM_FB_TOPIC_ID`** (topic FB).
- Orchestrator: `run_facebook_groups_cycle()` seed `seen_ids` → `spider.run()` (drain) → dedup → `_process_listing` từng tin. Empty queue → return sớm (không log spam).

## 8.8 Bảng "cách lấy tin" (Facebook Groups)

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Cơ chế | **PUSH** — userscript đọc thụ động → POST localhost | Không bot tự vào FB |
| Đăng nhập | Via FB thật, login 1 lần trong profile riêng | Không auto-login |
| Chu kỳ | Userscript: xoay group liên tục; Bot: drain mỗi 3' | 1 vòng group ~time-based |
| Text/mô tả | ✅ (có thể cụt nếu "See more") | story_message |
| Người đăng + uid | ✅ | link /user/ |
| Link bài chi tiết | ✅ **khi** ảnh lộ set=gm/pcb; else link người đăng | fallback vẫn dùng được |
| SĐT | ⚠️ parse từ text (best-effort) | có thể mất nếu ở cuối bài bị cụt |
| Quận/Giá/Diện tích | ⚠️ parse từ text tự do | thiếu → để trống |
| Số tin của người đăng (cross) | ⏳ Bước 3.3 (DB tích luỹ uid) | tín hiệu môi giới |

## 8.9 Giới hạn & Gotchas (rebuild-grade)

- **FB đổi DOM = đòn bẩy bảo trì.** Khi capture về 0: dùng probe Console soi `div[role="feed"] > div`, `story_message`, link `set=`… rồi chỉnh selector/regex trong userscript. Không cần restart bot (sửa userscript = phía browser).
- **`set=gm` VÀ `set=pcb` đều là post-id** → `/posts/<id>/` mở đúng bài. (Đừng bỏ pcb — sai lầm từng mắc.)
- **Userscript KHÔNG tạo được "trusted event".** Hover/click giả lập bằng script không làm FB lộ permalink (FB chỉ nghe chuột thật). Nên vài bài text-thuần không-ảnh sẽ không có link chi tiết — chấp nhận (text đã nhúng). Playwright làm được (chuột CDP là trusted) nhưng tái nhập rủi ro bot-detection → chỉ là phương án cuối.
- **Text "See more" có thể cụt** → mất phần cuối (đôi khi là SĐT). Không auto-bấm "See more" để giữ passive. (Bug đang mở, xử lý ở chunk phân loại.)
- **Text tự do** → parse quận/giá/SĐT là best-effort, sẽ có tin thiếu field → scoring cần nới cho FB (Chunk 2).

---

# 12. MODULE 4 (cập nhật) — Alert Telegram theo TOPIC nguồn

v3 định tuyến mỗi nguồn vào **topic riêng** trong group Telegram bằng `message_thread_id`:

| Nguồn | Topic (thread_id) | Nguồn cấu hình |
|---|---|---|
| batdongsan | 5 | hardcode |
| nhatot | 10 | hardcode |
| muaban | 11 | hardcode |
| facebook_groups | env `TELEGRAM_FB_TOPIC_ID` (vd 3612) | env (self-serve) |
| *(kế hoạch)* FBG Chủ / FBG Khách | ⏳ Chunk 2 | env |

Lấy `thread_id`: tạo topic → gửi 1 lệnh dạng `/id` vào topic (bot chỉ nhận command do Privacy Mode) → chạy `tools/tg_get_topic_id.py` → set vào `.env`. Áp dụng khi **restart bot**.

---

# 16. CHỐNG BAN & QUẢN LÝ VIA FACEBOOK

> **Business view:** Via (tài khoản FB mua ngoài, ~50k VNĐ) là "công nhân" đọc group. Coi như **tiêu hao** — cách giữ nó sống lâu nhất chính là cơ chế passive: nó chỉ lướt như người thật.

**Nguyên tắc giữ via sống lâu:**
- **Profile Chrome RIÊNG "RealEstork Bot"** — tách hoàn toàn profile cá nhân (cookies/fingerprint không trộn → FB khó liên kết account & vạ lây ban; tab always-on không phá phiên làm việc; đổi via chỉ cần xoá profile).
- **Login 1 lần, để yên.** Bot không đụng mật khẩu/login. FB thỉnh thoảng đăng xuất/đòi xác minh → login lại tay (việc thủ công duy nhất, thưa).
- **IP nhà** (residential) — tin cậy hơn hẳn IP datacenter của tool thuê ngoài. Không cần proxy.
- **Tần suất thấp, giống người** — cuộn chậm, xoay vòng, không cào sâu liên tục.
- **Warm-up trước khi cào:** via mới → 1–2 tuần dùng như người thật (đọc, like lai rai, join group giãn ra) **rồi** mới bật userscript. Bật capture ngay trên via mới = cờ đỏ.
- **Dự phòng:** giữ 2–3 via đã warm; via chết → swap, không gián đoạn.

**Việc thủ công thực tế:** mua + warm via (1 lần) + login lại khi bị đăng xuất (thưa). Hằng ngày = 0 thao tác.

---

# 10. MODULE 2b — PHÂN LOẠI v3: CHỦ / KHÁCH / MÔI GIỚI

> **Trạng thái: THIẾT KẾ — CHƯA IMPLEMENT.** Sẽ build ở **Bước 3.2** (tín hiệu in-session) + **Bước 3.3** (DB tích luỹ uid). Hiện tại FB dùng scoring **default** (owner-vs-broker, `config/scoring.yaml`) → chưa có "khách thuê", chưa tách 2 topic. Section này là **spec dẫn đường** cho code.

> **Business view:** Trên group FB có 3 kiểu người: **chủ nhà** (đăng cho thuê — lead để vợ giành), **khách thuê** (đăng cần thuê — khách tiềm năng để match), và **môi giới** (nhiễu, cần loại). Nguy hiểm: môi giới **giả danh** — đóng vai khách để moi số chủ, đóng vai chủ để moi số khách. Nên không tin lời khai; phải nhìn hành vi (spam nhiều group, SĐT trùng môi giới).

## 10.1 Mô hình 2 trục (môi giới đè lên tất cả)

```
Trục 1 — Ý ĐỊNH (từ text)          Trục 2 — TÍNH THẬT (tín hiệu hành vi/cross)
  "cho thuê..."  → OFFER (chủ)       nick spam nhiều group · SĐT trùng broker
  "cần thuê..."  → SEEK  (khách)     · copy-paste nhiều nơi · tên/từ khoá môi giới

LUẬT KẾT HỢP (trục 2 ĐÈ trục 1):
  Môi giới (trục 2 mạnh)  → BLACKLIST, không gửi
  else OFFER + thật       → topic  FBG Chủ
  else SEEK  + thật       → topic  FBG Khách
```

## 10.2 Trục 1 — Ý định (intent), từ text

| Ý định | Từ khoá (khởi điểm, mở rộng dần) |
|---|---|
| **OFFER** (chủ nhà) | "cho thuê", "cần cho thuê", "chính chủ cho thuê", "nhà cho thuê", có địa chỉ + giá + diện tích |
| **SEEK** (khách thuê) | "cần thuê", "cần tìm", "tìm thuê", "ai có … cho em/mình thuê", nêu ngân sách/nhu cầu ("tầm X triệu", "cần mặt bằng khu…") |
| Không rõ | → `can_xac_minh` (không gửi cho tới khi rõ) |

## 10.3 Trục 2 — Phát hiện môi giới

> **Thuật ngữ:** "marketplace" = 3 sàn portal (nhatot / batdongsan / muaban), phân biệt với "Facebook".

### 10.3.1 Cửa sổ đo — IN-SESSION vs TÍCH LUỸ (DB)

Quan trọng: các tín hiệu đếm được đo trên **2 cửa sổ khác nhau**, đừng lẫn:

| Cửa sổ | Định nghĩa | Bắt được | Bước |
|---|---|---|---|
| **IN-SESSION** | Trong 1 lần drain / 1 vòng quét hiện tại | Broker **đang spam NGAY** (đăng dồn dập) | 3.2 (in-memory) |
| **TÍCH LUỸ (DB)** | Hồ sơ uid trong bảng `fb_posters`, cộng dồn **qua nhiều ngày / nhiều group** | Broker **rải tin theo thời gian** (mỗi ngày vài group) | 3.3 (persistent) |

### 10.3.2 Bảng tín hiệu môi giới + cửa sổ đo

| # | Tín hiệu | Ngưỡng khởi điểm | Cửa sổ | Nguồn |
|---|---|---|---|---|
| 1 | uid xuất hiện ở nhiều **group riêng biệt** | **≥ 5 group** | **TÍCH LUỸ (DB)** — trong 1 session hiếm khi đủ 5 | `fb_posters.groups_seen` (3.3) |
| 2a | uid đăng nhiều post **ngay bây giờ** | **≥ 6 post** | IN-SESSION (3.2) | đếm uid trong batch drain |
| 2b | uid đăng nhiều post **tổng cộng** | ngưỡng riêng | TÍCH LUỸ (DB) | `fb_posters.post_count` (3.3) |
| 3 | **SĐT trùng môi giới marketplace** | xem 10.3.3 | ngay (dùng DB sàn sẵn có) | `phones` + `broker_phones` (3.2) |
| 4 | Cùng 1 text đăng nhiều group (copy-paste) | hash text trùng ≥ 2-3 group | IN-SESSION + TÍCH LUỸ | text-hash (3.2/3.3) |
| 5 | Tên/từ khoá môi giới trong tên hoặc text | — | ngay | `account_name_broker_keywords` (3.2) |

→ **Tín hiệu #1 (group-count) thực chất là feature 3.3 (DB)**, không phải in-session. Ngưỡng #1/#2 chọn **lỏng** (≥5 group / ≥6 post) để ít oan cho chủ có 2-3 mặt bằng. Tune sau bằng data thật.

### 10.3.3 Cross-marketplace check (qua SĐT) — mạnh nhất, chạy ngay

Nối Facebook với DB 3 sàn marketplace **qua số điện thoại**:
1. Spider FB parse SĐT từ text post.
2. Tra SĐT trong `phones` (tích luỹ từ nhatot/batdongsan/muaban) + `broker_phones`.
3. Nếu SĐT **(a)** đã trong `broker_phones` (môi giới đã biết) **HOẶC (b)** xuất hiện ở **nhiều listing marketplace** (phone_count cao, nhiều platform) → post FB đó = **môi giới**.

- **Tái dùng pipeline sẵn có** (`phone_stats`, `is_known_broker`, `phone_count_all_platforms`) — chạy ngay ở 3.2, không cần code mới ngoài việc đảm bảo SĐT parse được.
- **Giới hạn:** chỉ chạy khi post FB **có SĐT trong text**. Không SĐT → tín hiệu này im.
- **Bonus (enhancement):** SĐT môi giới phát hiện trên FB **feed ngược** vào `broker_phones` → 3 sàn cùng hưởng (chống môi giới xuyên nền tảng).

## 10.4 Alert filter cho FB — NỚI (khác portal)

FB text thưa → parse quận/tuổi tin/giá hay trượt. **Không hard-reject** như portal:

| Điều kiện | Portal | **FB (nới)** |
|---|---|---|
| Thiếu quận | reject "ngoài quận" | **vẫn gửi** (ghi chú "quận: ?") |
| Parse được quận nhưng ngoài whitelist | reject | **reject** (giữ) |
| Thiếu tuổi tin (không parse được giờ đăng) | reject nếu >48h | **vẫn gửi** (không biết = không loại) |
| Là môi giới (trục 2) | — | **chặn** (blacklist) |

→ Nguyên tắc: **chỉ chặn khi CHẮC CHẮN loại bỏ** (là môi giới, hoặc quận parse được mà ngoài vùng). Nghi ngờ/thiếu data → vẫn gửi. Đổi lại nhiều alert hơn, nhưng không bỏ sót tin FB (log thật cho thấy filter chặt làm mất hầu hết tin FB).

## 10.5 Phát hiện Khách thuê — cơ chế

Khách thuê thường **KHÔNG có** giá/diện tích/tầng/SĐT cụ thể (họ mô tả nhu cầu). Nên **không áp** bộ scoring chủ nhà (floor/price/area/photo). Phát hiện = **phân loại ý định từ text**:

1. **Keyword intent:**
   - SEEK (khách): "cần thuê", "cần tìm", "tìm thuê", "ai có … cho em/mình thuê", ngân sách ("tầm/khoảng X triệu", "ngân sách…").
   - OFFER (chủ): "cho thuê", "cần cho thuê", "chính chủ cho thuê".
2. **Luật ưu tiên (chống nhầm):** có "cho thuê" → **OFFER** (dù có chữ "cần"). Chỉ "cần thuê / cần tìm" mà **KHÔNG** có "cho thuê" → **SEEK**.
3. **Gợi ý cấu trúc:** khách hay KHÔNG có địa chỉ cụ thể + ảnh mặt bằng, thường nêu **nhu cầu/ngân sách**. Chủ có địa chỉ + giá + ảnh của 1 mặt bằng cụ thể.
4. **Mơ hồ** (không rõ offer/seek) → `can_xac_minh`, không route.
5. **AI signal phụ giúp:** cho LLM đọc text → phân offer/seek khi rule không chắc.

- Best-effort, sẽ sai vài ca → tune bằng feedback vợ.
- **Lưu ý:** môi giới cũng đăng seek ("cần tìm mặt bằng cho khách") — nhưng **trục 2 (10.3) bắt được và đè lên** → vào blacklist, không lọt vào FBG Khách.
- **Giá trị cho vợ:** khách thuê = khách tiềm năng để **match** với listing chủ nhà đang có (khu X, ngân sách Y).

## 10.6 Routing → 2 topic Telegram mới

| Kết quả | Đích |
|---|---|
| Môi giới | **Blacklist** — không gửi (lưu DB nhãn broker) |
| Chủ nhà (offer + thật + qua filter) | Topic **FBG Chủ** — env `TELEGRAM_FB_CHU_TOPIC_ID` |
| Khách thuê (seek + thật) | Topic **FBG Khách** — env `TELEGRAM_FB_KHACH_TOPIC_ID` |

*(Thay cho `TELEGRAM_FB_TOPIC_ID` đơn hiện tại. Cách lấy thread_id: xem Mục 12.)*

## 10.7 Tích hợp vào classifier (implementation notes cho Bước 3.2)

- Thêm `"facebook_groups"` vào `PER_SOURCE_CONFIGS` (`pipeline/classifier.py`) + tạo **`config/scoring_facebook_groups.yaml`** (chỉ tín hiệu text khả dụng + ngưỡng nới).
- Thêm signal mới vào `pipeline/signals.py` đúng contract `check_<name>(ctx) -> bool|float`: `fb_intent_offer`, `fb_intent_seek`, `fb_broker_multi_group`, `fb_text_duplicate`. Map vào `SIGNAL_FUNCTIONS`.
- **Đếm cross-group in-session (3.2):** orchestrator gom uid qua toàn bộ batch drained (nhiều group trong 1 vòng) → set `same_session_account_count` mở rộng thành "số group riêng biệt của uid".
- **Định tuyến:** trong `run_facebook_groups_cycle`/`_process_listing`, sau classify: nếu broker → skip gửi (lưu DB); else theo intent chọn topic Chủ/Khách.
- **Fix kèm:** bug **text/SĐT cụt** (userscript đọc `story_message` thiếu dòng cuối) — xử lý ở đây vì liên quan cách đọc text (probe tìm element chứa full text, hoặc gộp block).

## 10.8 Nâng cấp DB (Bước 3.3 — preview)

Bảng mới **`fb_posters`** (key = uid): `groups_seen[]`, `post_count`, `phones[]`, `classification`, `first_seen`/`last_seen`. Tích luỹ **vĩnh viễn, cross-session**: thêm group mới sau này → cùng uid cộng dồn hồ sơ cũ → điểm môi giới mạnh dần. (Chi tiết ở Chunk 4 — DB schema.)

---

# 15. MODULE 7 — DATABASE SCHEMA (Supabase / PostgreSQL)

> Nguồn chính xác: **`db/schema.sql`** (header ghi v2.1 — chưa cập nhật cho FB) + `db/client.py` (wrapper). FB **dùng chung bảng `listings`** (`source="facebook_groups"`), không cần bảng listing riêng. Bảng **mới `fb_posters`** (thiết kế dưới) phục vụ tích luỹ hồ sơ poster cho phân loại môi giới (Bước 3.3).

## 15.1 Tổng quan các bảng

| Bảng | Vai trò | Trạng thái |
|---|---|---|
| **listings** | Tin đăng mọi nguồn (4 sàn + Facebook) — bảng lõi | Active |
| **phones** | Tần suất SĐT + cache OSINT (nối cross-marketplace) | Active |
| **broker_phones** | DB SĐT môi giới đã biết (seed từ vợ + auto-detect) | Active |
| **classification_feedback** | Learning loop (nhãn thật vợ /mark) | Active |
| **spider_logs** | Log mỗi lần chạy spider + health-check sentinel | Active |
| **alert_subscribers** | Hướng 2 (bán subscription) | Phase 2 |
| **company_listings** | Trích DB công ty (Phase 2, đã ẩn SĐT vì privacy) | Phase 2 |
| 🆕 **fb_posters** | Hồ sơ poster FB theo uid (group/post count tích luỹ) | **Thiết kế — Bước 3.3** |

## 15.2 Bảng `listings` (lõi)

Cột chính (từ `db/schema.sql`): `id UUID`, **`source`** + **`source_id`** (UNIQUE), `source_url`, `title`, `description`, `address`, `address_normalized`, `district`, `city`, `area_m2`, `floor_level`, `price_vnd_monthly BIGINT`, `price_text`, `phone`, `contact_name`, `images TEXT[]`, `posted_at`, `scraped_at`, `listing_age_hours`, `content_hash` (SHA256 title+phone+desc[:100]).
- **Phân loại:** `classification_score INT` (default 50), `classification_label` (chinh_chu / can_xac_minh / moi_gioi), `ai_result JSONB`, `osint_result JSONB`.
- **Trạng thái (workflow vợ):** `status` (new / alerted / called / confirmed_owner / confirmed_broker / archived / auto_vetoed_broker), `notes`.
- Trigger auto `updated_at`. UNIQUE(source, source_id) = khoá dedup chính.
> **FB dùng bảng này:** `source="facebook_groups"`, `source_id` = post-id (id thật hoặc `fbh_<hash>`), `district`/`price`/`phone` = parse best-effort từ text (có thể NULL).
> ⏳ Bước 3.2 sẽ thêm cột phục vụ 3 loại (vd `intent` offer/seek/broker) — chi tiết khi implement.

## 15.3 `phones` + `broker_phones` (nối cross-marketplace)

**`phones`** (PK = `phone`): `total_listings`, `platforms TEXT[]`, `platform_count`, `max_single_platform`, `first_seen`/`last_seen`, `is_known_broker`, `broker_company`, + cache OSINT (`zalo_name`, `zalo_is_business`, `truecaller_*`, `google_result_count`, `trangtrang_spam`, `notes`). Index GIN trên `platforms`.
**`broker_phones`** (PK = `phone`): `name`, `company`, `source` (manual / confirmed_by_wife / auto_detected), `confidence`.

> **Đây là hạ tầng cho check môi giới cross-marketplace của FB (10.3.3):** SĐT parse từ post FB → tra 2 bảng này → nếu `is_known_broker` hoặc `platform_count`/`total_listings` cao → post FB = môi giới. SĐT môi giới phát hiện trên FB có thể ghi vào `broker_phones` (`source=auto_detected`) → 3 sàn cùng hưởng.

## 15.4 `classification_feedback` (learning loop)

`id`, `listing_id → listings(id)`, `predicted_label`, `predicted_score`, `actual_label`, `feedback_source` (wife_zalo / subscriber_telegram), `signals_at_prediction JSONB` (snapshot signal→điểm), `ai_model_used`. → dùng cho weekly tuning + feedback vợ (câu hỏi ở scoring guide).

## 15.5 `spider_logs`

`spider_name`, `started_at`/`finished_at`, `status` (success/partial/failed), `listings_found`, `new_listings`, `error_message`, `duration_seconds`. Cũng chứa **sentinel row** của `health_check_write()` (`spider_name="__health_check__"`) — smoke test write-path lúc startup (bắt sự cố RLS/key sai, xem Chunk 3).

## 15.6 Phase 2: `alert_subscribers`, `company_listings`

- `alert_subscribers`: `telegram_chat_id`, `district_filter[]`, `min/max_price`, `min_score`, `subscription_tier` (free/basic/premium), `is_active` — Hướng 2 bán tin.
- `company_listings`: mặt bằng từ DB công ty (address/district/area/price/commission/lease_status) — **cố tình KHÔNG lưu SĐT/tên chủ** (privacy), chỉ cross-reference nội bộ.

## 15.7 🆕 `fb_posters` — thiết kế (Bước 3.3)

Hồ sơ poster Facebook theo **uid**, tích luỹ **vĩnh viễn cross-session/cross-group** → nền cho tín hiệu môi giới #1/#2b (10.3):

```sql
CREATE TABLE IF NOT EXISTS fb_posters (
    uid TEXT PRIMARY KEY,              -- Facebook user id (từ /groups/<gid>/user/<uid>)
    display_name TEXT,                 -- tên hiển thị (best-effort)
    groups_seen TEXT[] DEFAULT '{}',   -- các group_id RIÊNG BIỆT uid đã đăng
    group_count INTEGER DEFAULT 0,     -- len(groups_seen) — để query ngưỡng ≥5 nhanh
    post_count INTEGER DEFAULT 0,      -- tổng post đã thấy từ uid (tích luỹ)
    phones TEXT[] DEFAULT '{}',        -- SĐT trích từ các post của uid
    classification TEXT DEFAULT 'unknown', -- chu | khach | moi_gioi | unknown (verdict tích luỹ)
    broker_confidence NUMERIC DEFAULT 0,   -- 0-1, tăng dần theo tín hiệu
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fb_posters_groupcount ON fb_posters(group_count);
CREATE INDEX IF NOT EXISTS idx_fb_posters_class ON fb_posters(classification);
```

**Logic cập nhật (mỗi FB cycle, per post):** upsert theo `uid` → nếu `group_id` chưa có trong `groups_seen` thì thêm + `group_count++`; `post_count++`; thêm SĐT vào `phones`; cập nhật `last_seen`.
**Dùng để chấm:** trước classify post FB, tra `fb_posters[uid]` → nếu `group_count ≥ 5` (hoặc `post_count` tích luỹ cao) → fire tín hiệu môi giới. **Thêm group mới sau này → cùng uid cộng dồn hồ sơ cũ** → điểm môi giới mạnh dần (đúng như anh xác nhận: DB càng chạy càng chính xác).

## 15.8 RLS & Service Key (gotcha vận hành)

- Hiện **service role key bypass RLS** — mọi write dùng `SUPABASE_SERVICE_KEY`. RLS chỉ bật khi làm Web UI (Hướng 2).
- **Sự cố đã gặp (session 15):** copy nhầm `sb_publishable_*` (anon) vào `SUPABASE_SERVICE_KEY` → pass auth nhưng RLS chặn mọi INSERT (`code 42501`) → bot "chạy" nhưng 0 write, 0 alert ~20h. → `bot doctor` giờ check prefix key + `health_check_write()` smoke test lúc startup (chi tiết Chunk 3).

## 15.9 SupabaseDB (`db/client.py`) — method reference

| Method | Việc |
|---|---|
| `upsert_listing` / `upsert_listings_batch` | Ghi tin (conflict trên source+source_id) |
| `get_recent_listings(limit)` | Seed dedup cache lúc startup |
| `get_listing_status` / `update_listing_status` | Đọc/ghi status workflow vợ |
| `update_classification` | Ghi score/label/ai_result/osint_result |
| `get_phone_stats` / `upsert_phone` | Tần suất SĐT (cross-marketplace) |
| `is_known_broker` / `seed_broker_phones` | Check/seed môi giới |
| `get_phone_trangtrang_report_count` | Cache spam trangtrang |
| `save_feedback` / `get_recent_feedback` | Learning loop |
| `log_spider_run` / `health_check_write` | Log + smoke test write-path |
| `get_daily_stats` | Digest 8h sáng |
| `get_active_subscribers` / `upsert_subscriber` | Hướng 2 |
| 🆕 *(3.3)* `upsert_fb_poster` / `get_fb_poster(uid)` | Tích luỹ hồ sơ poster FB |

---

# 7b. CẬP NHẬT PORTAL — SESSION 13-19 (deltas so với v2.3)

> v2.3 mô tả 4 portal ở trạng thái session 12. Dưới đây là các thay đổi **kể từ đó** — đọc kèm Module 1/7 của v2.3. (Nguồn: changelog `CLAUDE.md`.)

## 7b.1 Nhatot — multi-URL + min-pages floor (ss18-19)

- **1 URL → 2 URL**, cả hai đều `?price=15000000-*&f=p`:
  1. `thue-bat-dong-san-tp-ho-chi-minh` (all BĐS, chính chủ)
  2. `thue-van-phong-mat-bang-kinh-doanh-tp-ho-chi-minh` (VP/MBKD)
- **`min_pages_before_early_stop: 5`** — bắt buộc crawl ≥5 page/URL trước khi cho phép early-stop → không bỏ sót tin chính chủ ở page sâu.
- **Bài học (ss19):** `f=p` (URL filter của Nhatot) là source-of-truth cho "chính chủ", **mạnh hơn** signal `account_type=u` (type=u raw vẫn có thể là môi giới bị Nhatot gắn badge profile). → Thêm URL Nhatot phải luôn dùng `?f=p`.
- **Fix district (ss18):** `_normalize_district` strip prefix "Thành phố / TP / TP." → "Thành phố Thủ Đức" match được whitelist.

## 7b.2 Muaban — 1 URL → 3 category (ss17)

Thêm 2 category: `cho-thue-nha-ho-chi-minh` + `cho-thue-nha-xuong-kho-dat-ho-chi-minh` (ngoài `cho-thue-van-phong-mat-bang`). Config `url:` → `urls:` list. State (`seen_ids`, `same_session_account_count`) giữ **global cross-URL** (chủ đăng nhiều category = 1 lần classify + đúng tín hiệu broker). Pattern multi-URL nay chuẩn hoá cho 3 spider (batdongsan/muaban/nhatot).

## 7b.3 District whitelist 19 quận + per-district price override (ss13)

16 → **19 quận** (thêm Q12, Tân Phú, Bình Tân; loại 5 huyện ngoại ô). Thêm `district_price_overrides`: Q12/Tân Phú/Bình Tân chỉ alert tin **≥40M** (filter tin nhỏ vùng xa). *(Đã phản ánh trong bảng scoring v2.3.)*

## 7b.4 Độ bền vận hành (ss14, 16)

- **Self-healing lock (ss14):** `.orchestrator.lock` chứa PID; start check PID còn sống (`os.kill(pid,0)`) → còn sống thì exit, chết thì dọn lock + đánh dấu crash. Hết cảnh "zombie lock chặn khởi động".
- **Crash detection + Telegram lifecycle (ss14,16):** `clean_exit` flag — chỉ dọn lock khi thoát graceful; crash (unhandled exception) giữ lock lại → next start phát hiện. Telegram báo 🟢 Started / 🔴 Stopped / ⚠️ Crash / 💥 Crashed (kèm traceback + uptime).
- **Headless auto-start (ss14):** `pythonw` + Task Scheduler `-AtLogon`. → **Known gap (BACKLOG):** `-AtLogon` chỉ chạy khi có người login → máy reboot lúc logout thì bot nằm chờ (đã gặp thực tế: mất điện 24/06, down ~37h tới khi login). Giải pháp đề xuất: đổi trigger `-AtStartup`.

## 7b.5 Sự cố RLS key format + phòng ngừa (ss15)

- **Sự cố:** Supabase đổi format key (`sb_secret_*` = service, `sb_publishable_*` = anon). Copy nhầm publishable vào `SUPABASE_SERVICE_KEY` → pass auth nhưng RLS chặn INSERT (`42501`) → bot "chạy" (PID sống, log ghi) nhưng **0 write, 0 alert ~20h im lặng**.
- **Phòng ngừa:** (1) `bot doctor` check prefix key (publishable → HARD FAIL). (2) `health_check_write()` — INSERT 1 sentinel vào `spider_logs` lúc startup (trước scheduler); fail → Telegram "KHỞI ĐỘNG THẤT BẠI" + `sys.exit(1)`. **Dùng write op, không SELECT** — vì publishable key SELECT được qua RLS nhưng INSERT bị chặn.

## 7b.6 alonhadat

Trạng thái: **`enabled: false`** (tạm tắt, focus 3 sàn chính + FB). Spider HTTP đơn giản (Scrapling), phone qua detail `tel:` link — sẵn sàng bật lại khi cần.

---

> **PRD v3.0 — Chunk 1-4 hoàn tất** (Facebook rebuild-grade · phân loại v3 spec · DB schema + fb_posters · cập nhật portal ss13-19). Các phần business/đối thủ/revenue/OSINT/bảng-điểm-4-sàn vẫn tra ở **`RealEstork_PRD_v2.3.md`** cho tới khi có nhu cầu merge trọn vào file này.
