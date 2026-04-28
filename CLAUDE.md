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
