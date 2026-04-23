# RealEstork — PRD v2.1 (Updated)

## Nền tảng OSINT Bất động sản Cho thuê Mặt bằng HCMC

**Codename:** RealEstork
**Version:** 2.2 (Updated 20/04/2026)
**Date gốc:** 06/04/2026 | **Cập nhật lần cuối:** 20/04/2026
**Author:** Chankwan
**Implementation:** Antigravity (Flash & Claude Sonnet) + Claude Code (Terminal)
**Primary language:** Python 3.12+
**Host:** CHANKWAN-WIN2 (Ryzen 7 5700G / GTX 1660 SUPER 6GB / Win11)

---

## MỤC LỤC

1. Tổng quan & Bối cảnh
2. Phân tích Đối thủ Cạnh tranh
3. Hai hướng Kinh doanh Song song
4. Đánh giá Revenue Tiềm năng
5. Kiến trúc Hệ thống
6. Tech Stack
7. Module 1: Scraper Engine
8. Module 2: Dedup & Classification Pipeline
9. Module 3: OSINT Phone Lookup
10. Module 4: Alert / Notification System
11. Module 5: Auth & Token Management
12. Module 6: Agentic Orchestrator
13. Module 7: Database Schema (Supabase)
14. Cấu hình & Vận hành
15. Implementation Roadmap
16. Success Metrics
17. Risks & Mitigations

---

## 1. TỔNG QUAN & BỐI CẢNH

### 1.1 Vấn đề

Vợ là Sale Admin tại công ty môi giới BĐS thương mại cho thuê ở TP.HCM. Thu nhập hiện tại: ~20 triệu VNĐ/tháng.

Quy trình kiếm tiền hiện tại:

1. **PHÁT HIỆN** — Dò thủ công trang 1 các web rao vặt (batdongsan.com.vn, nhatot.com) để tìm mặt bằng nhà phố mới đăng cho thuê.
2. **XÁC MINH** — Phân biệt chính chủ vs môi giới bằng kinh nghiệm.
3. **LIÊN HỆ** — Gọi chủ nhà xác nhận thông tin, hỏi hoa hồng.
4. **ĐĂNG KÝ** — Post lên database công ty, ghi nhận quyền sở hữu lead.
5. **THU TIỀN** — Sale chốt → chủ nhà trả 0.5–2 tháng tiền thuê hoa hồng → vợ nhận 5–10%.

**Bottleneck chính:** Bước 1 & 2 — refresh thủ công liên tục + phân biệt chính chủ/môi giới tốn nhiều thời gian.

### 1.2 Hai hướng kinh doanh song song

**HƯỚNG 1 — Sale Admin Accelerator:** Tool nội bộ hỗ trợ vợ phát hiện nhà chính chủ mới nhanh nhất. Notification: Telegram group.

**HƯỚNG 2 — Sàn Aggregate:** Platform tổng hợp lọc tin chính chủ, bán subscription. Infrastructure từ Hướng 1 được thừa kế.

### 1.3 Thị trường HCMC

Giá thuê mặt bằng bán lẻ trung tâm HCMC tăng 8–10%/năm. CBD đạt VND 4.5 triệu/m²/tháng. Khu vực Quận 1–11, Bình Thạnh, Phú Nhuận, Tân Bình là khu vực target chính của RealEstork.

---

## 2. PHÂN TÍCH ĐỐI THỦ CẠNH TRANH

### 2.1 Bản đồ thị trường

**CATEGORY A — Listing Platforms (nguồn data, KHÔNG phải đối thủ):**
- Batdongsan.com.vn: #1 VN, PropertyGuru Group
- Nhatot.com (Chợ Tốt): Carousell
- Alonhadat.com.vn, Homedy.com, Muaban.net

**CATEGORY B — Aggregator / Lọc chính chủ (ĐỐI THỦ TRỰC TIẾP):**
- SànChínhChủ: ~300 sites, ~80-90% accuracy, rule-based, không có real-time alert
- GNha.vn: focus pháp lý
- Guland.vn: map-based

### 2.2 Lợi thế cạnh tranh

1. **REAL-TIME ALERT** — Không ai có. Push-based thay vì pull-based.
2. **AI + LEARNING LOOP** — SànChínhChủ rule-based từ 2015. RealEstork có AI signal + feedback loop.
3. **FOCUS NICHE** — Mặt bằng cho thuê HCMC. Classifier chính xác hơn.

---

## 3. HAI HƯỚNG KINH DOANH SONG SONG

### 3.1 Hướng 1: Sale Admin Accelerator (ĐANG VẬN HÀNH)

Mục tiêu: Alert real-time qua **Telegram group** khi phát hiện mặt bằng chính chủ mới.

Output Telegram hiện tại:
```
🏠 Likely Chính Chủ (Score: 88)

📍 P. Bến Thành (Quận 1 cũ)
💰 120 triệu/tháng | 128m²
📞 0906763286

🔗 Xem ảnh & chi tiết (batdongsan)

📊 OSINT:
• Google: 0 results

Ref: batdongsan-45545460
```

### 3.2 Hướng 2: Sàn Aggregate (Phase 2)

Chưa triển khai. Infrastructure của Hướng 1 sẽ được tái sử dụng.

---

## 4. ĐÁNH GIÁ REVENUE TIỀM NĂNG

*(Không thay đổi so với thiết kế gốc — xem PRD gốc v2.1 để biết projection)*

---

## 5. KIẾN TRÚC HỆ THỐNG

### 5.1 Nguyên tắc

- Self-hosted trên CHANKWAN-WIN1
- Plugin-based scraper: thêm site = thêm 1 file + 1 YAML entry
- Config-driven scoring: chỉnh weights bằng edit YAML, không cần redeploy
- Rule-based classification là nền tảng chính, AI là signal bổ sung

### 5.2 High-level Architecture (Trạng thái thực tế)

```
CHANKWAN-WIN2 (On-premise)
├── Agentic Orchestrator (APScheduler AsyncIOScheduler)
│   ├── scrape_cycle — mỗi 5 phút (nhatot)
│   ├── batdongsan_cycle — mỗi 20 phút (riêng biệt)
│   ├── daily_digest — 8:00 sáng
│   └── _browser_lock — mutex đảm bảo 1 browser tại 1 thời điểm
│
├── Scraper Engine
│   ├── nhatot (ACTIVE) — API mode, phone reveal via RSA+Bearer
│   ├── batdongsan (ACTIVE) — StealthyFetcher, 2-stage fetch
│   ├── alonhadat (DISABLED) — tạm tắt
│   ├── homedy, muaban, cafeland (DISABLED) — Phase 2
│   └── facebook_groups, zalo_web (DISABLED) — Phase 2+
│
├── Auth Management
│   ├── nhatot — Bearer token, auto-refresh via Playwright profile
│   └── batdongsan — Cookie-based, UMS refresh → headless auto-refresh
│
├── Pipeline
│   ├── Dedup (fingerprint hash)
│   ├── Classifier — per-source YAML (scoring.yaml / scoring_batdongsan.yaml)
│   └── OSINT — Google phone lookup
│
├── Notification
│   └── Telegram Bot (group + admin)
│
└── Supabase (PostgreSQL)
    ├── listings, phones, broker_phones
    ├── classification_feedback
    └── spider_runs (monitoring)
```

### 5.3 Luồng xử lý song song

```
Startup  → scrape_cycle chạy ngay (nhatot)
           batdongsan_cycle chờ 20 phút

_browser_lock (asyncio.Lock):
  Khi BDS đang chạy → nhatot đợi BDS xong rồi mới chạy
  Tránh crash do 2 camoufox instance đồng thời
```

---

## 6. TECH STACK (Thực tế triển khai)

```
Layer                  | Tool                         | Ghi chú
-----------------------+------------------------------+----------------------------------
Scraping engine        | Scrapling (StealthyFetcher)  | Camoufox browser, Cloudflare bypass
Phone decrypt (nhatot) | RSA-3072 PKCS1v15            | Encrypt list_id → Bearer token API
Phone decrypt (BDS)    | curl_cffi Firefox133 TLS     | Cookie-based DecryptPhone endpoint
Browser automation     | Playwright (Chromium)        | Auth setup + headless auto-refresh
Database               | Supabase                     | PostgreSQL, free tier
AI Gateway             | zero-token (gemini-web)      | Gemini Pro qua browser session
Scheduling             | APScheduler AsyncIOScheduler | 2 jobs song song, asyncio-safe
Notification           | Telegram Bot API             | Group + Admin channel
Logging                | loguru                       | logs/orchestrator.log (rotation 1d)
```

---

## 7. MODULE 1: SCRAPER ENGINE

### 7.1 Spider: Nhatot (ACTIVE)

**Loại:** API mode (không dùng browser)
**URL:** `https://www.nhatot.com/thue-bat-dong-san-tp-ho-chi-minh?price=15000000-%2A&f=p`
**Filter:** Giá ≥ 15 triệu, `f=p` = cá nhân/personal only (không broker/doanh nghiệp)
**Interval:** Chạy trong scrape_cycle mỗi 5 phút
**Pages:** 3 trang, 20 tin/trang → tối đa 60 tin/cycle

**Phone reveal:**
- API: `GET https://gateway.chotot.com/v1/private/ad-listing/phone?e={encrypted}`
- Encryption: RSA-3072 PKCS1v15, encrypt `list_id` bằng nhatot production public key
- Auth: `Authorization: Bearer {NHATOT_ACCESS_TOKEN}` (~24h TTL)
- Auto-refresh: khi token expire → Playwright headless → capture Bearer từ Network → lưu `.env`

### 7.2 Spider: Batdongsan (ACTIVE)

**Loại:** StealthyFetcher (camoufox browser, bypass Cloudflare)
**URL:** `https://batdongsan.com.vn/cho-thue-nha-mat-pho-tp-ho-chi-minh?cIds=577,52,576,53`
**Categories:** Kho (577), Nhà xưởng (52), Đất (576), Shophouse (53) + Nhà mặt phố
**Interval:** Cycle riêng mỗi 20 phút
**Pages:** Tối đa 80 trang (safety cap) — dừng sớm khi điều kiện đạt

**Pipeline 2-stage:**

**Stage 1 — Trang danh sách:**
- Bỏ qua tin VIP (bạc/vàng/kim cương): class `re__vip-silver`, `re__vip-gold`, `re__vip-diamond`
- Bỏ qua tin có badge "Môi giới chuyên nghiệp" trên card: class `re__pro-agent`
- Chỉ lấy tin hiển thị "hôm nay" (kể cả tin cũ được pump)
- **Early-stop:** dừng khi gặp tin đầu tiên "hôm qua" HOẶC >70% tin đã dedup (dedup_stop_ratio=0.7)

**Stage 2 — Trang chi tiết (từng listing):**
- Fetch song song với semaphore=4 (detail_concurrency)
- Lấy: SĐT (raw attr + uid + prid), tên người đăng, mô tả đầy đủ
- **Lấy số tin đang rao:** regex `"Tin đăng đang có X"` từ sidebar contact card
  - Nếu không có → fallback: `"Xem thêm X tin khác"` + 1
  - Nếu không có cả hai → mặc định = 1 (chỉ có bài này)
- **Decrypt phone:** chỉ decrypt cho listing có active ≤ 5 (broker rõ ràng không cần)

**Phone decrypt (Batdongsan):**
- API: `POST /microservice-architecture-router/Product/ProductDetail/DecryptPhone`
- Auth: Cookie-based + `Authorization: Bearer {accessToken}` header
- AccessToken JWT TTL: ~1 giờ → auto-refresh qua UMS endpoint
- UMS refresh fail (session ~5h server-side) → headless Playwright dùng profile đã lưu
- Profile: `.batdongsan_browser_profile/` (Chromium persistent context)
- Rate limit: 2s delay giữa các request, dừng ngay khi 429

### 7.3 Config file: `config/spiders.yaml`

```yaml
spiders:
  - name: nhatot
    enabled: true
    type: stealthy
    url: https://www.nhatot.com/thue-bat-dong-san-tp-ho-chi-minh?price=20000000-%2A&f=p
    interval_minutes: 20   # display only — thực tế do scrape_cycle quyết định
    max_pages: 3

  - name: batdongsan
    enabled: true
    type: stealthy
    url: https://batdongsan.com.vn/cho-thue-nha-mat-pho-tp-ho-chi-minh?cIds=577,52,576,53
    interval_minutes: 20
    max_pages: 80
    request_delay_seconds: 5
    detail_concurrency: 4
    dedup_stop_ratio: 0.7

  - name: alonhadat
    enabled: false   # Tạm tắt
    ...
```

---

## 8. MODULE 2: DEDUP & CLASSIFICATION PIPELINE

### 8.1 Deduplication

- Fingerprint: `SHA256(source + source_id)` + content hash `SHA256(title|phone|description[:100])`
- In-memory set seeded từ DB khi startup
- `batdongsan` spider nhận `seen_ids` từ orchestrator trước khi chạy → early-stop dedup per-page

### 8.2 Classification — Rule-based Scoring

**Nguyên lý:** Điểm cơ sở 50, cộng/trừ theo từng signal. Phân loại theo threshold.

**Per-source config:**
- `config/scoring.yaml` — default (nhatot, alonhadat)
- `config/scoring_batdongsan.yaml` — riêng cho batdongsan (threshold nới hơn)

**Thresholds:**

| Label | Nhatot | Batdongsan |
|---|---|---|
| `chinh_chu` | score ≥ 65 | score ≥ 60 |
| `can_xac_minh` | score ≥ 40 | score ≥ 38 |
| `moi_gioi` | score < 40 | score < 38 |

*(BDS threshold nới vì thiếu 3 signal nhatot-only: `phone_hidden_owner`, `account_type_personal/business`)*

**Điều kiện alert Telegram:**
- Score ≥ 55
- Quận nằm trong whitelist 16 quận trung tâm HCMC
- Tuổi tin ≤ 24 giờ

### 8.3 Signals chính

**Signals chung (nhatot + batdongsan):**

| Signal | Weight | Điều kiện |
|---|---|---|
| `listing_very_fresh` | +10 | Đăng ≤ 2 giờ |
| `listing_fresh` | +5 | Đăng 2–24 giờ |
| `listing_stale` | -15 | Đăng > 7 ngày |
| `text_owner_language` | +5 | Dùng "chính chủ", "nhà tôi"... |
| `text_marketing_superlatives` | -10 | Dùng từ marketing: "đẳng cấp", "siêu vị trí"... |
| `account_name_broker_keywords` | -20 | Tên có: "BĐS", "môi giới", "công ty", "TNHH"... |
| `same_session_multi_listing` | -20 | Cùng tên/SĐT đăng > 2 tin trong 1 batch |
| `description_many_emojis` | -15 | > 5 emoji trong mô tả |
| `photo_count_low` | +5 | ≤ 5 ảnh |
| `floor_ground` | +10 | Tầng trệt |
| `posted_outside_business_hours` | +5 | Đăng ngoài 8h–18h hoặc cuối tuần |

**Signals nhatot-only:**

| Signal | Weight | Điều kiện |
|---|---|---|
| `account_type_personal` | +25 | `type="u"` (cá nhân) |
| `account_type_business` | -25 | `type="s"` (doanh nghiệp) |
| `account_new_or_few_posts` | +15 | Tổng tin đang rao ≤ 2 |
| `phone_hidden_owner` | +10 | Seller tự ẩn SĐT (không phải token expire) |

**Signals batdongsan-only:**

| Signal | Weight | Điều kiện |
|---|---|---|
| `bds_owner_single_listing` | +10 | Tin đang rao = 1 |
| `bds_owner_few_active_listings` | +15 | 2 ≤ tin đang rao ≤ 5 |
| `bds_broker_multi_active_listings` | -30 | Tin đang rao > 5 (chỉ fire khi đã có count thực) |
| `poster_join_year_veteran` | -10 | Tham gia ≥ 3 năm |
| `detail_has_pro_agent_badge` | -40 | Badge "Môi giới chuyên nghiệp" đã xác nhận |

**Lưu ý quan trọng:** `bds_broker_multi_active_listings` chỉ fire khi `poster_total_listings < 999` (guard chống false positive khi chưa có dữ liệu thực).

### 8.4 Broker Veto (Hard rules, trước scoring)

1. **Session veto:** Cùng contact_name/SĐT đăng > 4 tin trong 1 cycle → veto, score=0
2. **Active listing veto:** `poster_total_listings > 5` → veto ngay, không cần scoring

### 8.5 AI Signal

- Provider hiện tại: `zero-token` (Gemini Web qua browser session)
- Prompt: phân tích mô tả listing → `is_owner_probability` (0.0–1.0)
- Weight: AI signal = 1 trong ~25 signals, weight khoảng 10–15%
- Fallback: nếu AI fail → scoring chỉ dùng rule-based

---

## 9. MODULE 3: OSINT PHONE LOOKUP

**Mục tiêu:** Cung cấp thêm thông tin về chủ nhà cho vợ trước khi gọi.

**Hiện tại triển khai:**
- Google search: tìm SĐT trong dấu ngoặc kép → đếm kết quả
- Kết quả hiển thị trong Telegram: `Google: X results`

**Kế hoạch (Phase 2):**
- Truecaller lookup
- Cross-platform frequency (SĐT xuất hiện bao nhiêu lần trên nhiều platform)
- Known broker DB match

---

## 10. MODULE 4: ALERT / NOTIFICATION SYSTEM

### 10.1 Telegram (Đang vận hành)

**Channels:**
- `TELEGRAM_GROUP_CHAT_ID` — Group vợ nhận alert listing
- `TELEGRAM_ADMIN_CHAT_ID` — Admin nhận cảnh báo hệ thống

**Điều kiện alert listing:**
```python
score >= 55
AND listing_age_hours <= 24  # Tin không quá 24h
AND district in whitelist_16_quan
```

**Whitelist 16 quận:**
Quận 1–11, Bình Thạnh, Phú Nhuận, Tân Bình, Thủ Đức, Gò Vấp

**Format tin nhắn:**
```
🏠 {emoji} {label} (Score: {score})

📍 {district}
💰 {price} | {area}m²
📞 {phone}  ← SĐT thực nếu reveal được
             ← "🔒 SĐT ẩn — mở app BĐS" nếu không lấy được

🔗 Xem ảnh & chi tiết ({source})

📊 OSINT:
• Google: {N} results

Ref: {source}-{source_id}
[preview card từ BDS/Nhatot]
```

**Alert hệ thống (Admin):**
- Nhatot token expire → nhắc refresh (tự động refresh sau)
- BDS session expire → nhắc chạy `setup-batdongsan` (headless tự thử trước)
- Daily digest lúc 8:00 sáng

### 10.2 Zalo (Disabled)

Đã code nhưng tắt — focus Telegram trước khi MVP ổn định.

---

## 11. MODULE 5: AUTH & TOKEN MANAGEMENT

### 11.1 Nhatot

**Cơ chế:** Bearer token (~24h TTL)

**Setup lần đầu:**
```bash
python -m cli.main setup-nhatot
# Mở Chrome visible → login Google → bot capture Bearer token → lưu .env
```

**Auto-refresh:**
- Spider detect token expire → set flag `token_expired = True`
- Orchestrator `_check_nhatot_token()` phát hiện flag → gọi `NhatotAuthClient._refresh_headless()`
- Playwright headless dùng profile `.nhatot_browser_profile/` → intercept Bearer từ Network
- Lưu vào `.env` → tiếp tục hoạt động
- Nếu headless fail → Telegram admin alert "setup-nhatot cần thiết"

### 11.2 Batdongsan

**Cơ chế:** Cookie-based + AccessToken JWT (1h TTL)

**Files:**
- `.batdongsan_cookies.json` — cookies (~7 ngày)
- `.batdongsan_browser_profile/` — Chromium profile cho headless refresh

**Setup lần đầu:**
```bash
python -m cli.main setup-batdongsan
# Mở Chrome visible → login → lưu cookies + profile
```

**Auto-refresh flow:**
```
AccessToken JWT expire (mỗi ~1h)
  → UMS refresh: POST /user-management-service/api/v1/User/RefreshToken
  → Nếu OK: cookies mới, tiếp tục
  → Nếu isSuccess=false (con.ses.id expire sau ~5h):
      → Headless Playwright dùng .batdongsan_browser_profile/
      → Nếu OK: cookies mới, tiếp tục
      → Nếu fail: Telegram admin alert "setup-batdongsan cần thiết"
```

**Rate limit phone decrypt:**
- Delay 2s giữa các request (~0.5 req/s)
- Dừng ngay (break) khi nhận 429
- Chỉ decrypt listing có active ≤ 5 (broker > 5 bị veto trước, không cần SĐT)

---

## 12. MODULE 6: AGENTIC ORCHESTRATOR

**File:** `orchestrator/agent.py`

### 12.1 Startup sequence

```python
# 1. Init components (DB, spiders, dedup, classifier, AI, Telegram)
# 2. Seed dedup cache từ DB (1000 recent source IDs + hashes)
# 3. Setup APScheduler jobs
# 4. Chạy ngay scrape_cycle (nhatot)
# 5. BDS cycle chờ 20 phút mới chạy lần đầu
# 6. Event loop giữ chạy
```

### 12.2 Scheduling

```yaml
# config/schedule.yaml
schedules:
  scrape_cycle:
    function: run_scrape_cycle
    interval_minutes: 5
    enabled: true

  batdongsan_cycle:
    function: run_batdongsan_cycle
    interval_minutes: 20
    enabled: true

  daily_digest:
    function: daily_digest
    cron: "0 8 * * *"
```

### 12.3 scrape_cycle (mỗi 5 phút)

```
Acquire _browser_lock
→ Fetch nhatot (exclude batdongsan)
→ Check nhatot token + BDS cookies
→ Dedup
→ Per listing: broker_veto → classify → OSINT → DB → alert
→ Release _browser_lock
```

### 12.4 batdongsan_cycle (mỗi 20 phút)

```
Acquire _browser_lock
→ Seed spider.seen_ids từ dedup cache
→ spider.run():
    Stage 1: list pages (skip VIP + pro-agent, early-stop)
    Stage 2: detail pages (parallel sem=4)
    Phone decrypt (non-broker only)
→ Dedup
→ Per listing:
    Broker veto 1: session_count > 4
    Broker veto 2: active_count > 5
    → Classify (1 pass, active count đã có từ stage 2)
    → OSINT (score ≥ 50)
    → DB upsert
    → Alert (score ≥ 55, age ≤ 24h, district OK)
→ Release _browser_lock
```

### 12.5 _process_listing

Hàm core xử lý 1 listing sau dedup:

1. **Broker veto 1** — session_count > 4 → lưu DB status=auto_vetoed_broker, return
2. **Broker veto 2** — active_count > 5 → lưu DB status=auto_vetoed_broker, return
3. **Phone stats** — lấy từ DB (phone frequency, is_known_broker)
4. **AI classification** — async, fail-safe
5. **Classify** — rule-based + AI signal → score + label
6. **OSINT** — nếu score ≥ 50 và có phone
7. **DB upsert** — lưu listing + classification
8. **Alert** — nếu đủ điều kiện → Telegram group

---

## 13. MODULE 7: DATABASE SCHEMA (Supabase)

### Bảng chính

**listings**
```sql
id UUID PRIMARY KEY
source TEXT          -- 'nhatot', 'batdongsan', 'alonhadat'
source_id TEXT       -- ID gốc trên platform
source_url TEXT
title TEXT
description TEXT
price_vnd BIGINT
area_m2 FLOAT
district TEXT
address TEXT
phone TEXT
contact_name TEXT
posted_at TIMESTAMPTZ
scraped_at TIMESTAMPTZ
listing_age_hours FLOAT
classification_score INT
classification_label TEXT  -- 'chinh_chu', 'can_xac_minh', 'moi_gioi'
status TEXT               -- 'new', 'called', 'confirmed_owner', 'confirmed_broker', 'auto_vetoed_broker'
poster_total_listings INT  -- Số tin đang rao của người đăng (lúc scrape)
poster_join_year INT       -- Năm tham gia platform
content_hash TEXT          -- SHA256 dedup
source_content_hash TEXT
```

**phones**
```sql
phone TEXT
source TEXT
listing_count INT
platform_count INT
is_known_broker BOOL
last_seen TIMESTAMPTZ
```

**spider_runs**
```sql
id UUID
spider_name TEXT
status TEXT
listings_found INT
new_listings INT
duration_seconds FLOAT
run_at TIMESTAMPTZ
```

---

## 14. CẤU HÌNH & VẬN HÀNH

### 14.1 Chạy hệ thống

```bash
# Khởi động orchestrator (full pipeline)
python -m cli.main start

# Test spider đơn lẻ
python -m cli.main spider run nhatot
python -m cli.main spider run batdongsan

# Debug classification
python -m cli.main classify <listing_uuid>

# Setup auth lần đầu
python -m cli.main setup-nhatot
python -m cli.main setup-batdongsan

# Gửi digest ngay
python -m cli.main digest
```

### 14.2 Xem logs

```powershell
# Realtime
Get-Content logs\orchestrator.log -Wait -Tail 50

# Tìm kiếm
Select-String -Path logs\orchestrator.log -Pattern "Phones revealed|score=|BROKER VETO" | Select-Object -Last 30
```

### 14.3 Key config files

| File | Mục đích |
|---|---|
| `config/scoring.yaml` | Scoring weights, thresholds, district whitelist (nhatot default) |
| `config/scoring_batdongsan.yaml` | Scoring riêng cho batdongsan |
| `config/spiders.yaml` | Enable/disable spider, URLs, page limits |
| `config/schedule.yaml` | Cron schedules |
| `config/ai.yaml` | AI provider/model selection |
| `.env` | Secrets: tokens, API keys, chat IDs |
| `.batdongsan_cookies.json` | BDS auth cookies |
| `.batdongsan_browser_profile/` | Chromium profile cho BDS headless refresh |

### 14.4 Environment variables (.env)

```bash
# Supabase
SUPABASE_URL=
SUPABASE_KEY=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_GROUP_CHAT_ID=   # Group vợ
TELEGRAM_ADMIN_CHAT_ID=   # Admin alerts

# Nhatot
NHATOT_ACCESS_TOKEN=      # Bearer token, auto-refresh via Playwright

# Batdongsan
BDS_ACCOUNT_PHONE=        # SĐT tài khoản BDS (optional, dùng trong DecryptPhone payload)
```

---

## 15. IMPLEMENTATION ROADMAP

### ✅ Đã hoàn thành (tính đến 19/04/2026)

**Session 1 (13/04):**
- Nhatot phone reveal (RSA-3072 + Bearer token)
- District whitelist filter (16 quận)
- Token expiration detection + Telegram alert

**Session 2 (13/04):**
- Nhatot URL: `thue-bat-dong-san?price=20M+&f=p`
- Scoring: `account_type_personal/business`, `account_name_broker_keywords`, `same_session_multi_listing`
- Price filter ≥ 15 triệu

**Session 3 (15/04):**
- Nhatot auto token refresh via Google OAuth + Playwright profile
- Scoring adjustments: `text_owner_language`, `text_marketing_superlatives` (24 keywords), `photo_count_low`

**Session 4 (15/04):**
- Batdongsan phone reveal (Cookie + DecryptPhone API)
- `setup-batdongsan` CLI command
- BDS cookies auto-check + alert 24h trước expire

**Session 5 (18/04):**
- Batdongsan 2-stage fetch (list → detail)
- VIP tier skip, pro-agent skip tại list page
- Early-stop: first non-today card OR dedup > 70%
- Per-source scoring (scoring_batdongsan.yaml)
- New BDS signals: `bds_broker_multi_active_listings`, `bds_owner_few_active_listings`, `bds_owner_single_listing`
- Orchestrator: tách `run_batdongsan_cycle` riêng (20-min)
- `SpiderEngine.fetch_all(only, exclude)`

**Session 6 (19/04):**
- Fix signal bug: guard `poster_total_listings >= 999` chống false positive pass 1
- File logging: `logs/orchestrator.log` (loguru, rotation 1d)
- Extract active count từ detail page sidebar ("Tin đăng đang có X") thay vì guru profile
- Broker veto 2: `active > 5` veto trước scoring — bỏ stage 3 (guru profile fetch)
- Pre-filter phone decrypt: chỉ decrypt listing active ≤ 5
- Authorization Bearer header trong DecryptPhone request
- Delay 2s + break on 429 cho phone decrypt
- BDS headless auto-refresh khi UMS fail
- BDS profile fix: absolute path + flush wait 5s
- Browser lock: `asyncio.Lock` ngăn 2 spider dùng camoufox đồng thời
- Alert age filter: 48h → 24h

### 🔄 Đang theo dõi

- Xác nhận phone reveal BDS ổn định sau fix Authorization header
- Calibrate scoring_batdongsan.yaml sau 1–2 tuần dữ liệu thực

### 📋 Phase 2 (Chưa làm)

- Spider: alonhadat, homedy, muaban
- OSINT: Truecaller, cross-platform phone frequency
- Web UI cho aggregate platform
- Zalo notification
- Feedback loop: `mark` command cập nhật DB → tune weights

---

## 16. SUCCESS METRICS

| Metric | Target | Trạng thái |
|---|---|---|
| Listings/ngày (survived filter) | 10–30 | Đang đo |
| Alert precision (chính chủ thật) | ≥ 80% | Chưa đủ data |
| Phone reveal rate (BDS) | ≥ 50% | ~3/28 (đang fix) |
| BDS cycle duration | ≤ 20 phút | ~15–20 phút |
| Token uptime (nhatot) | ≥ 99% | Auto-refresh OK |
| Session uptime (BDS) | ≥ 95% | Headless refresh mới fix |

---

## 17. RISKS & MITIGATIONS

| Risk | Khả năng | Tác động | Mitigation |
|---|---|---|---|
| BDS/Nhatot block IP | Trung bình | Cao | Delay đủ lớn, 1 request tại 1 thời điểm |
| BDS cookie expire | Cao | Trung bình | Headless auto-refresh; Telegram alert khi fail |
| Nhatot token expire | Trung bình | Trung bình | Auto-refresh via Playwright profile |
| False positive (alert môi giới) | Đang xảy ra | Trung bình | Broker veto cứng + BDS active count từ detail |
| False negative (miss chính chủ) | Đang xảy ra | Trung bình | Tune scoring sau khi có feedback data |
| Rate limit phone decrypt | Cao | Thấp | 2s delay, break on 429, chỉ decrypt non-broker |
| camoufox crash (2 instances) | Đã xảy ra | Cao | `_browser_lock` mutex, sequential execution |
