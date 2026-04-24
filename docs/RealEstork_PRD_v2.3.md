# RealEstork — PRD v2.3

## Nền tảng OSINT Bất động sản Cho thuê Mặt bằng HCMC

**Codename:** RealEstork
**Version:** 2.3
**Date gốc:** 06/04/2026 | **Cập nhật lần cuối:** 24/04/2026
**Author:** Chankwan
**Implementation:** Antigravity (Flash & Claude Sonnet) + Claude Code (Terminal)
**Primary language:** Python 3.12+
**Host:** CHANKWAN-WIN2 (Ryzen 7 5700G / GTX 1660 SUPER 6GB / Win11)

> **Về loại tài liệu này:** Đây là PRD (Product Requirements Document) — tài liệu mô tả mục tiêu, thiết kế và trạng thái sản phẩm. Chuẩn liên quan phổ biến: IEEE 830 SRS (formal spec), TRD (Technical Requirements Doc), RFC (engineering decisions), ADR (Architecture Decision Records — decisions log). Với dự án solo như RealEstork, PRD + CLAUDE.md (implementation notes) là standard thực tế đủ dùng.

---

## MỤC LỤC

1. Tổng quan & Bối cảnh
2. Phân tích Đối thủ Cạnh tranh
3. Hai hướng Kinh doanh Song song
4. Đánh giá Revenue Tiềm năng
5. Kiến trúc Hệ thống (Trạng thái hiện tại)
6. Tech Stack
7. Module 1: Scraper Engine — 3 Spider Active
8. Module 2: Dedup & Classification Pipeline
9. Module 3: OSINT Phone Lookup
10. Module 4: Alert / Notification System
11. Module 5: Auth & Token Management
12. Module 6: Agentic Orchestrator
13. Module 7: Database Schema (Supabase)
14. Cấu hình & Vận hành
15. Session Changelog
16. Success Metrics
17. Risks & Mitigations

---

## 1. TỔNG QUAN & BỐI CẢNH

### 1.1 Vấn đề

Vợ là Sale Admin tại công ty môi giới BĐS thương mại cho thuê ở TP.HCM. Thu nhập ~20 triệu VNĐ/tháng.

Quy trình kiếm tiền:
1. **PHÁT HIỆN** — Dò thủ công các web rao vặt để tìm mặt bằng mới.
2. **XÁC MINH** — Phân biệt chính chủ vs môi giới bằng kinh nghiệm.
3. **LIÊN HỆ** — Gọi chủ nhà xác nhận, hỏi hoa hồng.
4. **ĐĂNG KÝ** — Post vào database công ty, ghi nhận quyền sở hữu lead.
5. **THU TIỀN** — Sale chốt → chủ nhà trả 0.5–2 tháng hoa hồng → vợ nhận 5–10%.

**Bottleneck:** Bước 1 & 2 — refresh thủ công + phân biệt chính chủ/môi giới tốn nhiều thời gian.

*Business view: Vợ đang bỏ lỡ cơ hội vì biết tin muộn hơn đồng nghiệp. Mỗi lead đặt vào database công ty trước ai 30 phút là một lợi thế cạnh tranh thực sự.*

### 1.2 Hai hướng kinh doanh song song

**HƯỚNG 1 — Sale Admin Accelerator (ĐANG VẬN HÀNH):** Tool nội bộ alert real-time qua Telegram group khi phát hiện mặt bằng chính chủ mới. Phục vụ riêng vợ.

**HƯỚNG 2 — Sàn Aggregate (Phase 2):** Platform tổng hợp lọc tin chính chủ, bán subscription cho sale admin/môi giới toàn thị trường. Infrastructure Hướng 1 được tái sử dụng.

### 1.3 Thị trường HCMC

Giá thuê mặt bằng bán lẻ trung tâm HCMC tăng 8–10%/năm. CBD đạt VND 4.5 triệu/m²/tháng. Khu vực target: 16 quận trung tâm (Quận 1–11, Bình Thạnh, Phú Nhuận, Tân Bình, Thủ Đức, Gò Vấp).

---

## 2. PHÂN TÍCH ĐỐI THỦ CẠNH TRANH

### 2.1 Bản đồ thị trường

**CATEGORY A — Listing Platforms (nguồn data, KHÔNG phải đối thủ):**
- Batdongsan.com.vn: #1 VN, PropertyGuru Group
- Nhatot.com (Chợ Tốt): Carousell
- Muaban.net: Từ 2006, tỷ lệ chính chủ cao
- Alonhadat.com.vn, Homedy.com

**CATEGORY B — Aggregator lọc chính chủ (ĐỐI THỦ TRỰC TIẾP):**
- SànChínhChủ: ~300 sites, 80–90% accuracy, rule-based, không có real-time alert
- GNha.vn: focus pháp lý
- Guland.vn: map-based

### 2.2 Lợi thế cạnh tranh của RealEstork

| Lợi thế | Giải thích kỹ thuật | Giải thích business |
|---|---|---|
| **Real-time push alert** | APScheduler polling 5–20 phút, Telegram push ngay khi phát hiện | SànChínhChủ chỉ cho user vào xem — RealEstork chủ động gửi đến user |
| **AI + Learning loop** | AI signal (~15% influence) + `classification_feedback` table cho weekly tuning | Càng dùng càng chính xác — SànChínhChủ vẫn là rule-based từ 2015 |
| **Focus niche HCMC** | Classifier được tinh chỉnh cho mặt bằng thương mại HCMC | Hiểu sâu thị trường → ít false positive hơn tool toàn quốc |
| **3 platform song song** | nhatot + batdongsan + muaban cùng chạy | Bao phủ rộng hơn, ít bỏ sót listing |

---

## 3. HAI HƯỚNG KINH DOANH SONG SONG

### 3.1 Hướng 1: Sale Admin Accelerator (ĐANG VẬN HÀNH)

Vợ nhận Telegram message khi có mặt bằng chính chủ mới:

```
🏪 Likely Chính Chủ (Score: 82)
🏪 Nhà mặt phố

📍 Quận 1
💰 120 triệu/tháng | 80m²
📞 0901234567 (Anh Minh)

🔗 Xem ảnh & chi tiết (batdongsan)

📊 OSINT:
• Google: 0 results

#nha_mat_pho #batdongsan | batdongsan-45545460
```

*Business view: Vợ biết ngay — mặt bằng gì, ở đâu, giá bao nhiêu, khả năng chính chủ cao không. Nhấn link, xem ảnh, gọi ngay. Không cần mở thêm tab nào khác.*

### 3.2 Hướng 2: Sàn Aggregate (Phase 2)

Chưa triển khai. Infrastructure Hướng 1 sẽ được tái sử dụng — platform, scoring engine, spider, DB đều dùng chung.

---

## 4. ĐÁNH GIÁ REVENUE TIỀM NĂNG

*(Không thay đổi so với thiết kế gốc — xem PRD v2.1 để biết projection)*

Hướng 1: Tool hiện tại giúp vợ phát hiện listing sớm 2–3 giờ so với thủ công → ước tính tăng 30–50% số căn ghi nhận → +6–10 triệu/tháng.

Hướng 2: 10 paid users × 100k VNĐ/tháng = breakeven. SànChínhChủ chứng minh market có nhu cầu.

---

## 5. KIẾN TRÚC HỆ THỐNG (Trạng thái hiện tại)

### 5.1 Nguyên tắc

- Self-hosted trên CHANKWAN-WIN2
- Plugin-based scraper: thêm site = thêm 1 file + 1 YAML entry
- Config-driven scoring: chỉnh weights bằng edit YAML, không cần redeploy
- Rule-based là nền tảng, AI là signal bổ sung (~15%)

### 5.2 High-level Architecture

```
CHANKWAN-WIN2 (On-premise)
├── Agentic Orchestrator (APScheduler AsyncIOScheduler)
│   ├── scrape_cycle      — mỗi 5 phút (nhatot)
│   ├── muaban_cycle      — mỗi 20 phút (muaban)
│   ├── batdongsan_cycle  — mỗi 20 phút (batdongsan)
│   ├── daily_digest      — 8:00 sáng
│   └── _browser_lock     — mutex: đảm bảo 1 browser (camoufox) tại 1 thời điểm
│
├── Scraper Engine
│   ├── nhatot (ACTIVE)       — __NEXT_DATA__ SSR, không cần token
│   ├── batdongsan (ACTIVE)   — StealthyFetcher, 2-stage, 5 URL categories
│   ├── muaban (ACTIVE)       — curl_cffi Firefox133, 2-stage, FREE phone
│   └── alonhadat (DISABLED)  — tạm tắt
│
├── Pipeline
│   ├── Dedup (fingerprint hash, in-memory set)
│   ├── Classifier — per-source YAML scoring
│   └── OSINT — trangtrang.com spam lookup (cached), Google phone
│
├── Notification
│   └── Telegram Bot (group + admin)
│
└── Supabase (PostgreSQL)
    ├── listings, phones, broker_phones
    ├── classification_feedback
    └── spider_logs (monitoring)
```

*Business view: 3 nguồn tin chạy song song, tự động suốt ngày. Orchestrator là "trưởng team robot" — phối hợp khi nào chạy cái gì, gửi alert gì, báo lỗi gì.*

### 5.3 Luồng xử lý song song

```
_browser_lock (asyncio.Lock):
  Khi BDS hoặc nhatot đang dùng camoufox → cycle khác đợi
  Tránh crash do 2 browser instance đồng thời

3 cycle song song về thời gian nhưng sequential về browser:
  nhatot:     interval 5 phút, nhanh (~1–2 phút)
  muaban:     interval 20 phút, nhanh (~2–3 phút)
  batdongsan: interval 20 phút, chậm hơn (~10–15 phút, có detail fetch)
```

---

## 6. TECH STACK (Thực tế triển khai)

```
Layer                  | Tool                         | Ghi chú
-----------------------+------------------------------+----------------------------------------
Scraping (browser)     | Scrapling StealthyFetcher    | Camoufox, Cloudflare bypass (BDS)
Scraping (HTTP)        | curl_cffi Firefox133 TLS     | Muaban — TLS fingerprint Firefox
Scraping (SSR)         | httpx / __NEXT_DATA__        | Nhatot — parse SSR JSON, no browser
Phone free (muaban)    | data-phone HTML attr         | Không cần auth, extract từ detail page
Scheduling             | APScheduler AsyncIOScheduler | 3 jobs song song, asyncio-safe
Database               | Supabase (PostgreSQL)        | Free tier, JSONB cho flexible data
AI signal              | Ollama gemma4:e4b            | Local GPU inference, switchable
Notification           | Telegram Bot API             | Group + Admin channel
Logging                | loguru                       | logs/orchestrator.log (rotation 1d)
```

**Thay đổi lớn từ v2.2:**
- Nhatot: bỏ RSA-3072 + Bearer token (tài khoản bị ban 22/04/2026). Chuyển sang đọc thuần `__NEXT_DATA__` SSR — đơn giản hơn, ổn định hơn, không cần login.
- Muaban: thêm curl_cffi Firefox133 cho Stage 2 detail fetch — lấy phone miễn phí từ HTML attr `data-phone`.
- BDS phone decrypt: đã ngừng vì quá phức tạp/chậm. Focus vào content signals.

---

## 7. MODULE 1: SCRAPER ENGINE — 3 SPIDER ACTIVE

### 7.1 Spider: Nhatot (ACTIVE)

**Loại:** SSR JSON mode (không dùng browser)
**URL:** `https://www.nhatot.com/thue-bat-dong-san-tp-ho-chi-minh?price=15000000-%2A&f=p`
**Filter:** Giá ≥ 15 triệu, `f=p` = cá nhân/personal only
**Interval:** Chạy trong scrape_cycle mỗi 5 phút
**Pages:** 3 trang, 20 tin/trang

**Cơ chế crawl:**
- Parse `__NEXT_DATA__` JSON từ SSR HTML response — không cần browser, không cần token
- Extract từ JSON: `source_id`, `title`, `description`, `phone`, `district`, `price`, `images`, `account_type`, `posted_at`, `poster_total_listings` (từ `seller_info.live_ads`)
- `account_type`: `"u"` = cá nhân (→ signal +25), `"s"` = doanh nghiệp (→ signal -25)

**Phone:** Có sẵn trong `__NEXT_DATA__` JSON (không cần reveal API). Nếu ẩn → `phone = None`.

**Auth:** Không cần. Nhatot token đã xóa (tài khoản Chotot bị ban 22/04/2026).

*Business view: Nhatot là nguồn đơn giản nhất — cá nhân đăng tin qua app Chợ Tốt, nhiều chủ nhà thật. System phân biệt được "tài khoản cá nhân" vs "tài khoản doanh nghiệp" ngay từ metadata platform.*

### 7.2 Spider: Batdongsan (ACTIVE)

**Loại:** StealthyFetcher (camoufox browser, bypass Cloudflare)
**URLs crawl (5 categories):**

| Slug URL | Loại BĐS | Emoji |
|---|---|---|
| `cho-thue-nha-mat-pho` | Nhà mặt phố | 🏪 |
| `cho-thue-shophouse-nha-pho-thuong-mai` | Shophouse | 🏬 |
| `cho-thue-kho-nha-xuong-dat` | Kho/Nhà xưởng | 🏭 |
| `cho-thue-nha-rieng` | Nhà riêng | 🏠 |
| `cho-thue-nha-biet-thu-lien-ke` | Biệt thự/Liền kề | 🏘️ |

**Interval:** Cycle riêng mỗi 20 phút
**Pages:** Tối đa 80 trang/URL (safety cap) — dừng sớm theo điều kiện

**Pipeline 2-stage:**

**Stage 1 — Trang danh sách:**
- Bỏ qua tin VIP (bạc/vàng/kim cương): class `re__vip-silver/gold/diamond`
- Bỏ qua tin có badge pro-agent trên card: class `re__pro-agent`
- Chỉ lấy tin "hôm nay" — skip tin cũ bị push lên bởi VIP
- **Early-stop 1:** Gặp tin đầu tiên "hôm qua" → dừng trang này
- **Early-stop 2:** >70% tin trong trang đã có trong dedup cache → dừng toàn bộ (dedup_stop_ratio=0.7)
- Extract: `source_id`, `title`, `district`, `price`, `images`, `posted_at`, `property_type`

**Stage 2 — Trang chi tiết (per listing, async sem=4):**
- Fetch song song, tối đa 4 request cùng lúc
- Extract: `contact_name`, `description` đầy đủ
- Đếm số tin đang rao từ sidebar: regex `"Tin đăng đang có X"` → `poster_total_listings`
  - Fallback: `"Xem thêm X tin khác"` + 1
  - Không có → mặc định = 1

**Phone:** Không implement — quá phức tạp (cookie-based DecryptPhone API), ảnh hưởng tốc độ. Focus vào content signals thay thế.

**Visual phân loại trong Telegram:** Mỗi tin BDS hiển thị emoji + tên loại BĐS trên dòng riêng bên dưới classification label.

*Business view: BDS có nhiều loại mặt bằng. Vợ thấy ngay đây là "🏪 Nhà mặt phố" hay "🏭 Kho/Nhà xưởng" — không cần đọc tiêu đề mới hiểu loại tài sản.*

### 7.3 Spider: Muaban (ACTIVE)

**Loại:** 2-stage — Stage 1 REST API, Stage 2 curl_cffi Firefox133
**URL:** `https://muaban.net/bat-dong-san/cho-thue-mat-bang-kinh-doanh-ho-chi-minh`
**Filter:** Giá ≥ 15 triệu, HCMC
**Interval:** Cycle riêng mỗi 20 phút

**Pipeline 2-stage:**

**Stage 1 — REST API (list):**
- API: `https://gateway.muaban.net/api/post/v1/...` — trả JSON summary
- Extract: `source_id`, `title`, `district`, `price`, `images`, `publish_at` (ISO8601)
- **Early-stop:** Gặp listing đầu tiên `publish_at` là "hôm qua" hoặc cũ hơn → dừng
  - *Muaban crawl trong 24h → luôn có fresh data. Break ngay khi thấy "hôm qua".*
- Ưu tiên tin mới nhất: `listing_very_fresh` (+10) cho tin ≤ 2h, `listing_fresh` (+5) cho tin 2–24h

**Stage 2 — Detail page (curl_cffi Firefox133 TLS):**
- Fetch từng listing detail page
- Extract `contact_name` và `phone` từ HTML attr `data-phone` — **miễn phí, không cần auth**
- Extract `description` đầy đủ, `avatar_is_blank` (ảnh đại diện người đăng)
- `poster_total_listings` = số tin đang rao của người đăng
  - Nguồn: sidebar profile — nếu API trả 403 → `None` (không fire signal)

**Auth:** Không cần. Muaban cho phép đọc phone từ HTML public.

**Lưu ý vận hành:** Muaban volume thấp (~5–15 tin mới/ngày cho segment này). Nếu không có tin mới → không alert. Đây là hành vi đúng, không phải lỗi.

*Business view: Muaban nổi tiếng có nhiều chủ nhà thật (chính chủ) hơn. Phone lấy được miễn phí, không cần xin quyền gì. Nhược điểm: ít listing hơn BDS/Nhatot.*

### 7.4 Config file: `config/spiders.yaml`

```yaml
spiders:
  - name: nhatot
    enabled: true
    url: https://www.nhatot.com/thue-bat-dong-san-tp-ho-chi-minh?price=15000000-%2A&f=p
    max_pages: 3

  - name: batdongsan
    enabled: true
    urls:
      - https://batdongsan.com.vn/cho-thue-nha-mat-pho-tp-ho-chi-minh
      - https://batdongsan.com.vn/cho-thue-shophouse-nha-pho-thuong-mai-tp-ho-chi-minh
      - https://batdongsan.com.vn/cho-thue-kho-nha-xuong-dat-tp-ho-chi-minh
      - https://batdongsan.com.vn/cho-thue-nha-rieng-tp-ho-chi-minh
      - https://batdongsan.com.vn/cho-thue-nha-biet-thu-lien-ke-tp-ho-chi-minh
    max_pages: 80
    request_delay_seconds: 5
    detail_concurrency: 4
    dedup_stop_ratio: 0.7

  - name: muaban
    enabled: true
    url: https://muaban.net/bat-dong-san/cho-thue-mat-bang-kinh-doanh-ho-chi-minh
    max_pages: 3
```

---

## 8. MODULE 2: DEDUP & CLASSIFICATION PIPELINE

### 8.1 Deduplication

- **Fingerprint:** `SHA256(source + source_id)` — primary dedup key
- **Content hash:** `SHA256(title|phone|description[:100])` — catch cross-platform duplicate
- **In-memory set** seeded từ DB (1000 recent source IDs) khi startup
- `batdongsan` spider nhận `seen_ids` từ orchestrator trước khi chạy → early-stop per-page

### 8.2 Classification — Rule-based Scoring

**Nguyên lý:**
- Điểm cơ sở: 50
- Mỗi signal cộng/trừ điểm
- Phân loại theo threshold: `chinh_chu` / `can_xac_minh` / `moi_gioi`

**Per-source config:**

| File | Dùng cho |
|---|---|
| `config/scoring.yaml` | Nhatot (default) |
| `config/scoring_batdongsan.yaml` | Batdongsan |
| `config/scoring_muaban.yaml` | Muaban |

**Thresholds:**

| Label | Nhatot | Batdongsan | Muaban |
|---|---|---|---|
| `chinh_chu` | score ≥ 65 | score ≥ 60 | score ≥ 65 |
| `can_xac_minh` | score ≥ 40 | score ≥ 38 | score ≥ 40 |
| `moi_gioi` | score < 40 | score < 38 | score < 40 |

*(BDS threshold nới vì thiếu `account_type_personal/business` signal. Muaban có signal riêng thay thế.)*

**Điều kiện alert Telegram:**
- Score ≥ 55
- Quận trong whitelist 16 quận trung tâm
- Tuổi tin ≤ 24 giờ

*Business view: Điểm 50 là "trung lập". Mỗi tín hiệu tốt (chủ nhà) cộng điểm, mỗi tín hiệu xấu (môi giới) trừ điểm. System alert khi tin đạt ≥55 — tức là đã có nhiều tín hiệu tốt hơn xấu.*

### 8.3 Signals toàn bộ (24/04/2026)

**Signals chung (tất cả platform):**

| Signal | Weight | Điều kiện | Giải thích business |
|---|---|---|---|
| `listing_very_fresh` | +10 | Đăng ≤ 2 giờ | Tin mới nhất — alert ngay cho vợ |
| `listing_fresh` | +5 | 2h < tuổi ≤ 24h | Tin hôm nay — vẫn còn cơ hội |
| `listing_stale` | -15 | Tuổi > 7 ngày | Tin cũ — môi giới đẩy lên lại |
| `text_owner_language` | +5 | "chính chủ", "nhà tôi"... | Ngôn ngữ chủ nhà — nhưng môi giới cũng giả danh nên weight thấp |
| `text_marketing_superlatives` | -20 | "đắc địa", "siêu hot", "vị trí vàng"... | Ngôn ngữ bán hàng chuyên nghiệp = dấu hiệu môi giới |
| `text_commission_mention` | -15 | "hoa hồng", "commission"... | Nói tới hoa hồng = công khai là môi giới |
| `text_agent_language` | -10 | "hotline:", "zalo:", "chuyên BDS"... | Ngôn ngữ chuyên nghiệp của broker |
| `account_name_broker_keywords` | -30 | Tên có "BĐS", "môi giới", "công ty"... | Tên tài khoản tố cáo môi giới |
| `same_session_multi_listing` | -20 | Cùng tài khoản đăng > 2 tin/batch | 1 chủ nhà có thể có 2 mặt bằng, > 2 là môi giới |
| `description_many_emojis` | -15 | > 5 emoji | Format marketing — chủ nhà thật không làm vậy |
| `description_no_diacritics` | +15 | Viết không dấu / tỉ lệ dấu < 8% | Gõ nhanh trên điện thoại = chủ nhà thật |
| `description_too_short` | +5 | Mô tả < 50 ký tự | Viết qua loa = chính chủ lười |
| `description_too_long` | -5 | Mô tả > 500 ký tự | Copy-paste marketing |
| `photo_count_low` | +5 | ≤ 5 ảnh | Chụp nhanh bằng điện thoại = chính chủ |
| `photo_count_high` | -10 | ≥ 8 ảnh | Ảnh chuyên nghiệp = môi giới |
| `posted_outside_business_hours` | +8 | Trước 8h hoặc sau 18h, cuối tuần | Chủ nhà đăng sau giờ làm |
| `floor_ground_level` | +8 | Tầng trệt/tầng 1 | Tầng trệt giá trị nhất, chủ nhà nắm rõ |
| `floor_ambiguous` | +3 | Không ghi tầng | Chính chủ thường không ghi kỹ |
| `floor_upper_level` | -5 | Từ lầu 3 trở lên | Ít nhu cầu, thường văn phòng |
| `trangtrang_spam_penalty` | -25 | SĐT có ≥ 5 báo cáo spam/scam trên trangtrang.com | Cộng đồng đã xác nhận spam |
| `ai_classification` | weight 30 | AI phân tích mô tả → `is_owner_probability` (0–1) × 30 | AI đọc ngữ cảnh mà rules bỏ qua |

**Signals nhatot-only:**

| Signal | Weight | Điều kiện |
|---|---|---|
| `account_type_personal` | +25 | `type="u"` — platform xác nhận cá nhân |
| `account_type_business` | -25 | `type="s"` — platform xác nhận doanh nghiệp |
| `account_new_or_few_posts` | +14 | Tổng tin đang rao ≤ 2 |
| `seller_high_sold_count` | -30 | Lịch sử ≥ 20 tin đã đăng |

**Signals batdongsan-only:**

| Signal | Weight | Điều kiện |
|---|---|---|
| `muaban_multi_active_listings` | -40 | Tin đang rao ≥ 5 → broker rõ ràng |
| `muaban_few_active_listings` | +20 | Tin đang rao < 5 → ứng viên chính chủ |
| `listing_is_vip` | -10 | Tin VIP (BDS trả phí đẩy) |

*(Lưu ý: BDS signal names dùng tiền tố `bds_*` trong code nhưng không liệt kê đầy đủ ở đây — xem `pipeline/signals.py`)*

**Signals muaban-specific (thay thế default khi source=muaban):**

| Signal | Weight | Điều kiện |
|---|---|---|
| `muaban_multi_active_listings` | -40 | Tin đang rao ≥ 5 |
| `muaban_few_active_listings` | +20 | Tin đang rao < 5 |
| `avatar_is_blank` | +15 | Không có ảnh đại diện — chủ nhà thường không setup |
| `account_name_is_phone` | +20 | Tên tài khoản là số điện thoại — owner pattern mạnh |
| `listing_is_vip` | -10 | Tin VIP |
| `text_owner_language` | -5 | Giảm weight vì môi giới trên muaban hay giả danh claim này |
| `trangtrang_spam_penalty` | -30 | Weight cao hơn vì muaban có nhiều spam hơn |

*Business view: Muaban có cách nhận diện broker khác — không có thông tin tài khoản "cá nhân/doanh nghiệp" như Nhatot. Thay vào đó, dựa vào ảnh đại diện, tên tài khoản, và số tin đang rao.*

### 8.4 Broker Veto (Hard rules, chạy trước scoring)

1. **Session veto:** Cùng contact_name/SĐT đăng > 4 tin trong 1 cycle → veto, không classify, lưu `status=auto_vetoed_broker`
2. **Active listing veto (BDS):** `poster_total_listings > 5` → veto ngay

### 8.5 AI Signal

- Provider: `ollama/gemma4:e4b` (local GPU, switchable via `config/ai.yaml`)
- Prompt: phân tích mô tả listing → `is_owner_probability` (0.0–1.0)
- Contribution: weight tối đa 30 điểm (~15% tổng ảnh hưởng)
- Fallback: nếu AI fail → scoring chỉ dùng rule-based

### 8.6 Debug logging

Mỗi listing sau classify được log với format:
```
[orchestrator] muaban/70825513: score=20 label=moi_gioi age=0.3h active=None signals=[text_owner_language:-5 listing_very_fresh:+10 trangtrang_spam_penalty:-30]
```
Fields: `score`, `label`, `age` (listing_age_hours), `active` (poster_total_listings), `signals` (mỗi signal fired kèm weight).

---

## 9. MODULE 3: OSINT PHONE LOOKUP

**Mục tiêu:** Cung cấp thêm context về SĐT trước khi vợ gọi.

**Triển khai hiện tại:**
- **Google search:** tìm SĐT trong dấu ngoặc kép → đếm kết quả → hiển thị "Google: X results" trong Telegram
- **Trangtrang.com:** DB 325k+ reviews — lookup cached trong `listings.osint_result` JSONB. Nếu SĐT có ≥ 5 báo cáo spam → fire `trangtrang_spam_penalty` signal (trừ điểm ngay trong scoring)

**Cơ chế trangtrang (quan trọng):**
- Kết quả OSINT từ lần scrape trước được lưu vào DB (cột `osint_result` JSONB)
- Trước khi classify, orchestrator query DB xem SĐT này đã từng có kết quả trangtrang chưa
- Nếu có → thêm `trangtrang_report_count` vào `phone_stats` → classifier dùng để fire penalty
- *Lần đầu gặp SĐT spam: penalty chưa fire. Lần thứ 2 trở đi: penalty fire. Trade-off chấp nhận được.*

**Phase 2:**
- Truecaller lookup
- Cross-platform phone frequency
- Known broker DB match

---

## 10. MODULE 4: ALERT / NOTIFICATION SYSTEM

### 10.1 Telegram

**Channels:**
- `TELEGRAM_GROUP_CHAT_ID` — Group vợ nhận alert listing
- `TELEGRAM_ADMIN_CHAT_ID` — Admin nhận cảnh báo hệ thống

**Điều kiện alert listing:**
```
score >= 55
AND listing_age_hours <= 24
AND district in whitelist_16_quan
```

**Format tin nhắn (khi có property_type — BDS):**
```html
<b>{badge} Likely Chính Chủ (Score: {score})</b>
{prop_emoji} <b>{prop_label}</b>

📍 {district}
💰 {price} | {area}m²
📞 {phone}

🔗 Xem ảnh & chi tiết ({source})

📊 OSINT:
• Google: N results

#{prop_tag} #{source} | {source}-{source_id}
```

**Format tin nhắn (khi không có property_type — Nhatot, Muaban):**
```html
<b>🏠 {badge} Likely Chính Chủ (Score: {score})</b>

📍 {district}
💰 {price} | {area}m²
📞 {phone}
...
```

**Alert hệ thống (Admin):**
- Daily digest lúc 8:00 sáng

### 10.2 Zalo (Disabled)

Đã code nhưng tắt. Focus Telegram trước.

---

## 11. MODULE 5: AUTH & TOKEN MANAGEMENT

### 11.1 Nhatot

**Trạng thái hiện tại: KHÔNG CẦN AUTH**

Tài khoản Chotot bị ban 22/04/2026. Phone reveal API đã xóa. Spider hiện tại chỉ đọc `__NEXT_DATA__` từ SSR — không cần token, không cần login.

Phone: Lấy được nếu listing public. Nếu chủ nhà ẩn → `None`.

*Nếu muốn khôi phục phone reveal: Cần tạo tài khoản Chotot mới + implement lại RSA+Bearer flow. Xem git history session 1–3.*

### 11.2 Batdongsan

**Trạng thái: KHÔNG CÒN CẦN (phone decrypt đã xóa)**

Cookie-based auth và DecryptPhone API đã xóa khỏi codebase. Spider BDS hiện chỉ dùng StealthyFetcher (camoufox) để fetch trang HTML công khai. Không cần setup cookie hay token.

### 11.3 Muaban

**Trạng thái: KHÔNG CẦN AUTH**

Phone lấy từ HTML attr `data-phone` trên detail page — public, không cần login.

---

## 12. MODULE 6: AGENTIC ORCHESTRATOR

**File:** `orchestrator/agent.py`

### 12.1 Startup sequence

```
1. Init components (DB, spiders, dedup, classifier, AI, Telegram)
2. Seed dedup cache từ DB (1000 recent source IDs + content hashes)
3. Setup APScheduler: 3 jobs (scrape_cycle, muaban_cycle, batdongsan_cycle) + daily_digest
4. Chạy ngay scrape_cycle (nhatot) + muaban_cycle
5. BDS cycle chờ 20 phút mới chạy lần đầu
6. Event loop giữ chạy
```

### 12.2 Scheduling

```yaml
# config/schedule.yaml
schedules:
  scrape_cycle:
    function: run_scrape_cycle      # nhatot
    interval_minutes: 5
    enabled: true

  muaban_cycle:
    function: run_muaban_cycle
    interval_minutes: 20
    enabled: true

  batdongsan_cycle:
    function: run_batdongsan_cycle
    interval_minutes: 20
    enabled: true

  daily_digest:
    function: daily_digest
    cron: "0 8 * * *"
```

### 12.3 scrape_cycle (nhatot, mỗi 5 phút)

```
Acquire _browser_lock
→ Fetch nhatot (__NEXT_DATA__ SSR, nhanh)
→ Dedup
→ Per listing: classify → OSINT → DB → alert
→ Release _browser_lock
```

### 12.4 muaban_cycle (mỗi 20 phút)

```
→ Stage 1: API list (không cần browser)
    Early-stop khi gặp tin "hôm qua" hoặc cũ hơn
→ Stage 2: Detail page (curl_cffi Firefox133, per listing)
    Extract phone, contact_name, description, avatar_is_blank
→ Dedup
→ Per listing:
    Build phone_stats (trangtrang cached lookup nếu có phone)
    → Classify (scoring_muaban.yaml)
    → OSINT (score ≥ 50)
    → DB upsert
    → Alert (score ≥ 55, age ≤ 24h, district OK)
```

### 12.5 batdongsan_cycle (mỗi 20 phút)

```
Acquire _browser_lock
→ Seed spider.seen_ids từ dedup cache
→ Per URL (5 categories):
    Stage 1: list pages (StealthyFetcher, skip VIP + pro-agent, early-stop)
    Stage 2: detail pages (parallel sem=4, extract active count)
→ Dedup
→ Per listing:
    Broker veto: session_count > 4 || active > 5
    → Classify (scoring_batdongsan.yaml)
    → OSINT (score ≥ 50)
    → DB upsert
    → Alert (score ≥ 55, age ≤ 24h, district OK)
→ Release _browser_lock
```

### 12.6 _process_listing (core function)

```
1. Broker veto check
2. Transtrang cached lookup (nếu có phone trong DB osint_result)
3. AI classification (async, fail-safe)
4. Classify (rule-based + AI signal) → score + label
5. OSINT (nếu score ≥ 50 và có phone)
6. DB upsert (listing + classification)
7. Alert nếu đủ điều kiện
8. Log: score, label, age, active_count, signals_fired
```

---

## 13. MODULE 7: DATABASE SCHEMA (Supabase)

### Bảng chính: listings

```sql
id UUID PRIMARY KEY
source TEXT                -- 'nhatot', 'batdongsan', 'muaban'
source_id TEXT             -- ID gốc trên platform
source_url TEXT
title TEXT
description TEXT
price_vnd_monthly BIGINT
area_m2 FLOAT
district TEXT
address TEXT
phone TEXT
contact_name TEXT
posted_at TIMESTAMPTZ
scraped_at TIMESTAMPTZ
listing_age_hours FLOAT    -- computed once at scrape time
property_type TEXT         -- 'nha_mat_pho', 'shophouse', 'kho_nha_xuong', ... (BDS only)
classification_score INT
classification_label TEXT  -- 'chinh_chu', 'can_xac_minh', 'moi_gioi'
status TEXT                -- 'new', 'called', 'confirmed_owner', 'confirmed_broker', 'auto_vetoed_broker'
poster_total_listings INT  -- Số tin đang rao lúc scrape
poster_profile_hash TEXT   -- BDS profile hash (nếu có)
poster_join_year INT        -- Năm tham gia platform
ai_result JSONB            -- AI response
osint_result JSONB         -- OSINT kết quả (trangtrang, google, ...)
content_hash TEXT          -- SHA256 dedup
UNIQUE(source, source_id)
```

### Bảng phụ

**phones** — phone frequency tracking
**broker_phones** — known broker DB
**classification_feedback** — learning loop (confirmed owner/broker từ vợ)
**spider_logs** — execution history mỗi spider run
**alert_subscribers** — Hướng 2

---

## 14. CẤU HÌNH & VẬN HÀNH

### 14.1 Chạy hệ thống

```bash
# Khởi động orchestrator (full pipeline — 3 spiders)
python -m cli.main start

# Test spider đơn lẻ
python -m cli.main spider run nhatot
python -m cli.main spider run batdongsan
python -m cli.main spider run muaban

# Debug classification (xem score + signals chi tiết)
python -m cli.main classify <listing_uuid>

# Gửi digest ngay
python -m cli.main digest
```

### 14.2 Xem logs

```powershell
# Realtime
Get-Content logs\orchestrator.log -Wait -Tail 50

# Tìm signal cụ thể
Select-String -Path logs\orchestrator.log -Pattern "signals=\[" | Select-Object -Last 20

# Xem lý do không alert
Select-String -Path logs\orchestrator.log -Pattern "score=|BROKER VETO|skip" | Select-Object -Last 30
```

### 14.3 Key config files

| File | Mục đích |
|---|---|
| `config/scoring.yaml` | Scoring weights, thresholds, district whitelist (nhatot default) |
| `config/scoring_batdongsan.yaml` | Scoring riêng cho batdongsan |
| `config/scoring_muaban.yaml` | Scoring riêng cho muaban |
| `config/spiders.yaml` | Enable/disable spider, URLs, page limits |
| `config/schedule.yaml` | Cron schedules cho 3 cycles |
| `config/ai.yaml` | AI provider/model selection |
| `.env` | Secrets: Supabase URL/key, Telegram tokens, chat IDs |

### 14.4 Environment variables (.env)

```bash
# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_GROUP_CHAT_ID=    # Group vợ nhận alert
TELEGRAM_ADMIN_CHAT_ID=    # Admin alerts
```

*(Nhatot token và BDS cookies đã xóa khỏi .env vì không còn cần)*

---

## 15. SESSION CHANGELOG

Ghi lại thay đổi thực tế theo từng phiên làm việc. Format: ngày + tóm tắt tech + business impact.

---

### Session 1 — 13/04/2026
**Tech:** Nhatot phone reveal (RSA-3072 PKCS1v15 + Bearer token). District whitelist 16 quận. Token expire detection + Telegram alert.
**Business:** Bot có thể lấy số điện thoại chủ nhà từ Nhatot. Chỉ alert trong 16 quận trung tâm HCMC.

---

### Session 2 — 13/04/2026
**Tech:** Đổi Nhatot URL sang `f=p` (personal only). Fix `_page_url()` giữ query params. Tắt phone frequency signals. Thêm `account_type_personal` (+25), `account_type_business` (-25) từ `type` field Nhatot. Thêm `account_name_broker_keywords` (-20), `same_session_multi_listing` (-20), `description_many_emojis` (-15). Price filter ≥ 20M VND.
**Business:** Nhatot chỉ lấy tin đăng bởi cá nhân (f=p), bỏ qua doanh nghiệp — cải thiện tỷ lệ chính chủ ngay từ nguồn.

---

### Session 3 — 15/04/2026
**Tech:** Nhatot auto token refresh via Google OAuth + Playwright persistent profile (`.nhatot_browser_profile/`). `cli setup-nhatot` command. `send_admin()` helper. Scoring: `text_owner_language` +15 → +5 (môi giới giả danh), `text_marketing_superlatives` 10 → 24 keywords, `photo_count_low` <= 3 → <= 5, `same_session_multi_listing` > 1 → > 2.
**Business:** Token tự động gia hạn — vợ không bị mất alert vì token hết hạn. Bộ từ khóa môi giới mở rộng từ 10 lên 24.

---

### Session 4 — 15/04/2026
**Tech:** Batdongsan phone reveal (Cookie-based + DecryptPhone API `/microservice-architecture-router/Product/ProductDetail/DecryptPhone`). `cli setup-batdongsan`. BDS cookies auto-check + alert 24h trước expire. Fix trangtrang.com URL: `/dien-thoai/{phone}` → `/{phone}.html`.
**Business:** Bot có thể lấy SĐT từ Batdongsan. Tích hợp tra cứu spam trangtrang.com.

---

### Session 5 — 18/04/2026
**Tech:** Batdongsan 2-stage fetch (list → detail). Skip VIP cards, skip pro-agent cards. Early-stop: non-today card hoặc >70% dedup. Per-source scoring (`scoring_batdongsan.yaml`). Signals mới: `bds_broker_multi_active_listings` (-30), `bds_owner_few_active_listings` (+15), `bds_owner_single_listing` (+10), `poster_join_year_veteran` (-10), `detail_has_pro_agent_badge` (-40). `run_batdongsan_cycle` riêng (20-min). `SpiderEngine.fetch_all(only, exclude)`.
**Business:** Thêm BDS vào hệ thống với logic riêng. Bot phân biệt chính chủ/môi giới trên BDS dựa vào số tin đang rao.

---

### Session 6 — 19/04/2026
**Tech:** Fix signal bug guard `poster_total_listings >= 999`. File logging `logs/orchestrator.log`. Extract active count từ detail page sidebar thay vì guru profile. Broker veto 2: active > 5. Phone decrypt chỉ cho active ≤ 5. Authorization Bearer header DecryptPhone. Delay 2s + break on 429. BDS headless auto-refresh khi UMS fail. Browser lock `asyncio.Lock`. Alert age filter 48h → 24h.
**Business:** Giảm nhiễu (veto broker rõ ràng trước khi classify). Hệ thống ổn định hơn — không còn crash khi 2 browser chạy đồng thời.

---

### Session 7 — ~19–20/04/2026
**Tech:** Muaban spider v1 — Stage 1 API list, Stage 2 detail page httpx. Muaban-specific scoring config (`scoring_muaban.yaml`). Signals: `avatar_is_blank`, `account_name_is_phone`, `muaban_multi_active_listings`, `muaban_few_active_listings`. `run_muaban_cycle` trong orchestrator.
**Business:** Thêm muaban.net vào hệ thống — 3 nguồn tin song song thay vì 2.

---

### Session 8 — 20/04/2026
**Tech:** Rollback BDS về chiến lược skip VIP (bỏ "fetch tất cả detail rồi mới veto"). Xác nhận xóa BDS phone decrypt logic. Fix muaban Stage 2: dùng curl_cffi Firefox133 TLS thay vì httpx (bypass anti-bot). Fix `publish_at` ISO8601 parse, `locations_display` extract district, `avatar_is_blank` false positive. Muaban cycle chạy ổn định.
**Business:** BDS nhanh hơn — không fetch detail của tin môi giới rõ ràng. Muaban lấy phone miễn phí, đáng tin cậy.

---

### Session 9 — 22/04/2026
**Tech:** Xóa toàn bộ nhatot phone reveal (tài khoản Chotot bị ban). `_NHATOT_RSA_PUBLIC_KEY`, `PHONE_API`, `_fetch_phone`, `_encrypt_list_id` xóa khỏi `spiders/nhatot.py`. Orchestrator: xóa `_check_nhatot_token()` + `NhatotAuthClient` import. Spider nhatot giờ chỉ đọc `__NEXT_DATA__`, không cần token.
**Business:** Bot Nhatot không còn lấy được SĐT (do tài khoản bị khóa). Bù lại: không còn lỗi token expire spam log. Muaban và BDS vẫn có phone.

---

### Session 10 — 24/04/2026
**Tech:**
- **trangtrang_spam_penalty signal** (+signal mới): `pipeline/signals.py` thêm `check_transtrang_spam_penalty` (fire khi `trangtrang_report_count >= 5`). `db/client.py` thêm `get_phone_trangtrang_report_count()`. Orchestrator pre-lookup transtrang cached results trước classify. Weight: -25 (nhatot/default), -30 (muaban — môi giới spam nhiều hơn).
- **Fix `_parse_relative_time` bug** (`spiders/muaban.py`): "2 giờ trước" trả về `now` thay vì `now - 2h`. Fix bằng cách parse số N và return `now - timedelta(hours=N)`.
- **Property type display** (`notifications/telegram.py`): Loại BĐS (từ BDS) xuất hiện trên dòng riêng bên dưới classification header, không chung hàng với score nữa.
- **Debug logging**: Mỗi classify log thêm `age=Xh signals=[signal:±weight ...]` — giúp diagnose scoring issues mà không cần thêm code.

**Business:**
- Tin spam (SĐT bị báo cáo trên transtrang.com) bị trừ điểm nặng → ít alert sai hơn.
- Bug fix: muaban tính tuổi tin sai → score sai → miss alert. Đã sửa.
- Card Telegram rõ ràng hơn: thấy ngay "🏪 Nhà mặt phố" dưới dòng classification.

---

## 16. SUCCESS METRICS

| Metric | Target | Trạng thái (24/04) |
|---|---|---|
| Listings alert/ngày (chính chủ) | 5–20 | Đang theo dõi |
| Alert precision (chính chủ thật) | ≥ 80% | Chưa đủ feedback data |
| Coverage (3 platforms) | Nhatot + BDS + Muaban | ✅ Active |
| BDS cycle duration | ≤ 20 phút | ✅ ~10–15 phút |
| Muaban phone reveal rate | 100% (free từ HTML) | ✅ Stable |
| Nhatot phone reveal | ❌ Disabled (account banned) | Cần tài khoản mới |
| Uptime 3 cycles | ≥ 99% | Đang theo dõi |
| trangtrang spam detection | Fire khi ≥ 5 reports | ✅ Implemented |

---

## 17. RISKS & MITIGATIONS

| Risk | Khả năng | Tác động | Mitigation |
|---|---|---|---|
| Muaban thay đổi HTML `data-phone` | Trung bình | Trung bình | Monitor log, fix selector khi gặp |
| BDS IP block (camoufox) | Thấp | Cao | Delay 5s, 1 request tại 1 thời điểm, browser lock |
| Nhatot thay đổi `__NEXT_DATA__` schema | Thấp | Trung bình | Parse defensive, log khi field missing |
| False positive (alert môi giới) | Đang xảy ra | Trung bình | Broker veto cứng + tune YAML weights |
| False negative (miss chính chủ) | Đang xảy ra | Trung bình | Tune scoring sau khi có feedback data |
| camoufox crash (2 instances) | Đã fix | Cao | `_browser_lock` mutex — sequential execution |
| Muaban volume thấp (ít tin mới) | Thường xuyên | Thấp | Expected behavior — segment nhỏ |
| trangtrang miss lần đầu | Luôn xảy ra | Thấp | Trade-off chấp nhận: lần 2 trở đi mới penalty |

---

## PHẦN PHỤ LỤC

### A. Platforms chưa triển khai (Phase 2)

- Alonhadat.com.vn — đã code, tạm tắt. Ít anti-bot nhất.
- Homedy.com — top-tier, chat built-in
- CafeLand.vn, Dothi.net, Mogi.vn — secondary
- Facebook public groups — opensource facebook-scraper

### B. Luồng data tổng thể (từ crawl đến Telegram)

```
Web (BDS/Nhatot/Muaban)
  ↓ Spider (Stage 1 + Stage 2)
  ↓ RawListing dataclass
  ↓ Dedup (fingerprint hash, in-memory set)
  ↓ Transtrang cached lookup (nếu có phone trong DB)
  ↓ AI classification (ollama gemma4:e4b)
  ↓ Rule-based scoring (scoring_{source}.yaml)
  ↓ Score + Label + signals_fired
  ↓ DB upsert (listings table, Supabase)
  ↓ Alert filter (score ≥ 55, district whitelist, age ≤ 24h)
  ↓ Telegram message (group chat vợ)
```

### C. Về tài liệu này

PRD là **Product Requirements Document** — mô tả mục tiêu, thiết kế, và trạng thái sản phẩm. Phân biệt:

- **PRD** (tài liệu này) — *Cái gì* và *Tại sao*: mục tiêu, architecture, logic nghiệp vụ
- **TRD** (Technical Requirements Doc) — Chi tiết kỹ thuật từng component: API spec, schema chi tiết, error codes
- **CLAUDE.md** (trong repo) — *Làm sao*: coding notes, decisions, implementation hints cho AI assistant
- **ADR** (Architecture Decision Records) — Log quyết định kiến trúc: tại sao chọn X thay vì Y
- **RFC** — Đề xuất thay đổi lớn để team review trước khi implement

Cho dự án solo như RealEstork: PRD + CLAUDE.md là đủ.

---

*Tài liệu gốc: `docs/RealEstork_PRD_v2.1.md` (06/04/2026)*
*Cập nhật v2.2: `docs/RealEstork_PRD_v2.2.md` (20/04/2026)*
*Cập nhật v2.3: `docs/RealEstork_PRD_v2.3.md` (24/04/2026) — phiên bản này*
