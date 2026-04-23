# RealEstork — PRD v2.1

## Nền tảng OSINT Bất động sản Cho thuê Mặt bằng HCMC

**Codename:** RealEstork
**Version:** 2.1
**Date:** 06/04/2026
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
7. Module 1: Scraper Engine (Scrapling)
8. Module 2: Dedup & Classification Pipeline
9. Module 3: OSINT Phone Lookup
10. Module 4: Alert / Notification System
11. Module 5: Company Database Extraction (browser-use)
12. Module 6: Agentic Orchestrator
13. Module 7: Database Schema (Supabase)
14. Module 8: Web UI — Sản phẩm chính Hướng 2
15. Cấu hình & Vận hành
16. Implementation Roadmap
17. Success Metrics
18. Risks & Mitigations
19. Phụ lục

---

## 1. TỔNG QUAN & BỐI CẢNH

### 1.1 Vấn đề

Vợ là Sale Admin tại công ty môi giới BĐS thương mại cho thuê ở TP.HCM. Khu vực được phân công: Quận 3, khu vực nhà thờ Tân Định (trục Hai Bà Trưng, Trần Quang Khải, Võ Thị Sáu). Thu nhập hiện tại: ~20 triệu VNĐ/tháng.

Quy trình kiếm tiền hiện tại:

1. PHÁT HIỆN — Dò thủ công trang 1 các web rao vặt (batdongsan.com.vn, nhatot.com, sanchinhchu.com, Facebook groups, Zalo groups) để tìm mặt bằng nhà phố mới đăng cho thuê.
2. XÁC MINH — Phân biệt chính chủ vs môi giới bằng kinh nghiệm.
3. LIÊN HỆ — Gọi chủ nhà xác nhận thông tin, hỏi hoa hồng.
4. ĐĂNG KÝ — Post lên database công ty (app nội bộ + group Zalo), ghi nhận quyền sở hữu lead.
5. SUPPORT — Hỗ trợ đội Sale trong quá trình đánh nhà, trung gian hỏi chủ nhà.
6. THU TIỀN — Sale chốt → chủ nhà trả 0.5–2 tháng tiền thuê hoa hồng → vợ nhận 5–10%.

Lưu ý quan trọng: Vợ KHÔNG phải môi giới. Vợ là Sale Admin — support cho môi giới trong công ty. Vợ không cạnh tranh với môi giới, không cần làm social media marketing, không cần xây brand cá nhân. Công việc chính là phát hiện nhà chính chủ nhanh nhất và đưa vào database công ty.

Bottleneck chính: Bước 1 & 2 — refresh thủ công liên tục + phân biệt chính chủ/môi giới tốn rất nhiều thời gian.

Lưu ý về khu vực: Vợ không tự chọn khu vực hay phân khúc giá. Công ty phân công. Quận 3 là khu vực giá thuê cao (trung bình 80–150 triệu/tháng cho mặt bằng kinh doanh trên trục chính), nên mỗi deal thành công có giá trị tốt.

### 1.2 Hai hướng kinh doanh song song

HƯỚNG 1 — Sale Admin Accelerator: Tool nội bộ hỗ trợ vợ phát hiện nhà chính chủ mới nhanh nhất. Notification channel: Zalo 1-1. Datasource của công ty vợ phục vụ công ty.

HƯỚNG 2 — Sàn Aggregate (kiểu SànChínhChủ): Platform tổng hợp và lọc tin chính chủ, bán subscription cho sale admin/môi giới. Notification channel: Telegram Bot. Database công ty vợ là datasource quý giá, pull vào phục vụ sản phẩm của Chankwan.

Nguyên tắc: Infrastructure build cho Hướng 1 phải được thừa kế và cải tiến cho Hướng 2. Shared core engine, khác channel output.

### 1.3 Thị trường HCMC

Dựa trên báo cáo Savills Q1/2025 và VnExpress: giá thuê mặt bằng bán lẻ trung tâm HCMC tăng 8–10%/năm. CBD đạt VND 4.5 triệu/m²/tháng. Tỷ lệ lấp đầy 93.5–94%. F&B chiếm 1/3 giao dịch. Nhiều nhà lên cho thuê = nhiều cơ hội.

Khu vực Quận 3 (nhà thờ Tân Định): Trục Hai Bà Trưng, Nguyễn Thị Minh Khai trung bình 120–135 triệu/tháng cho mặt bằng kinh doanh. Đây là khu vực cao giá, per-deal value tốt.

---

## 2. PHÂN TÍCH ĐỐI THỦ CẠNH TRANH

### 2.1 Bản đồ thị trường Proptech VN

Thị trường proptech VN phục vụ ngành BĐS chia thành 3 category:

CATEGORY A — Listing Platforms (Nơi đăng tin, là nguồn data của RealEstork, KHÔNG phải đối thủ):

- Batdongsan.com.vn: #1 VN, 7 triệu users/tháng, thuộc PropertyGuru Group (NYSE: PGRU). Revenue từ phí đăng tin + quảng cáo.
- Nhatot.com (Chợ Tốt): Owned by Carousell, đa ngành. Revenue từ phí đẩy tin + ads.
- Homedy.com: Focus chính chủ, có chat built-in.
- Alonhadat.com.vn: Đăng miễn phí, nhiều chính chủ.
- Muaban.net: Từ 2006, đa ngành.

CATEGORY B — Aggregator / Lọc chính chủ (ĐỐI THỦ TRỰC TIẾP):

- SànChínhChủ (sanchinhchu.vn/.net): Aggregate + lọc AI. Crawl ~300 website BĐS VN hàng ngày. Thu ~200,000 tin thô, dedup ~20,000, lọc 5,000–8,000 tin chính chủ. Accuracy: ~80% HCMC, ~90% Hà Nội. Hoạt động từ 2015. Revenue: Pay-per-view ~222đ/tin (100k VNĐ = 450 tin/15 ngày) + VIP subscription đọc không giới hạn. Đăng tin miễn phí, auto-classify. Nếu tin là môi giới thì vào "Danh bạ môi giới".
- GNha.vn: Chính chủ + pháp lý. Mỗi BĐS 1 tin duy nhất, verify pháp lý (quy hoạch, tranh chấp, xây dựng). 15+ năm kinh nghiệm. Revenue từ subscription + dịch vụ pháp lý. USP: tra cứu pháp lý BĐS minh bạch.
- Guland.vn: Map-based, overlay quy hoạch + giá BĐS xung quanh. Đăng bán trên bản đồ. Revenue: freemium (VIP account). USP: bản đồ trực quan.

CATEGORY C — B2B SaaS cho sàn/môi giới (không phải đối thủ trực tiếp, nhưng là ecosystem):

- TekaReal (tekareal.vn): CRM + bản đồ quy hoạch TekaMap. B2B SaaS cho Chủ đầu tư, Sàn BĐS, Môi giới. RBAC phân quyền, chống leak data, quản lý booking/cọc, đồng bộ trạng thái real-time. TekaMap: 10+ triệu thửa đất, lộ giới, ranh giới phường. Sếp công ty vợ dùng TekaReal để verify thông tin.
- Meey CRM (meeycrm.com): CRM cho BĐS, free tier.
- Meey Land / Meey Map: Map-based platform + data BĐS. Thuộc Meey Group (đang chuẩn bị IPO quốc tế).
- Remap (remaps.vn): Tương tự, bản đồ + quy hoạch.

### 2.2 Benchmark đối thủ Category B

```
Tiêu chí         | SànChínhChủ | GNha.vn   | Guland.vn  | RealEstork (target)
------------------+-------------+-----------+------------+---------------------
Số nguồn crawl    | ~300        | Ít        | Ít         | MVP: 5-10, scale dần
Accuracy chính chủ| 80-90%      | Cao (thủ) | Không rõ   | Target: 85%+ (AI)
Real-time alert   | KHÔNG       | KHÔNG     | KHÔNG      | CÓ — USP CHÍNH
Focus segment     | Toàn quốc   | Pháp lý   | Map-based  | HCMC mặt bằng thuê
Bản đồ quy hoạch  | Không       | Có        | Có         | Phase 2
AI/LLM            | Rule-based  | Không     | Không      | AI + learning loop
Mobile UX         | Cũ          | OK        | Tốt        | Modern
Giá               | 222đ/tin    | N/A       | Freemium   | 50k-200k/tháng sub
```

### 2.3 Lợi thế cạnh tranh của RealEstork

1. REAL-TIME ALERT — Không ai có. SànChínhChủ, GNha, Guland đều pull-based (user vào xem). RealEstork push-based (system alert user). USP lớn nhất.
2. AI CLASSIFICATION với LEARNING LOOP — SànChínhChủ dùng rule-based từ 2015. RealEstork dùng LLM + feedback loop = cải thiện liên tục.
3. FOCUS NICHE — Toàn bộ đối thủ "toàn quốc, mọi loại BĐS". RealEstork focus "mặt bằng cho thuê HCMC" = hiểu sâu hơn, classifier chính xác hơn.
4. COMPANY DATABASE INTEGRATION — Không ai có data nội bộ từ sàn thực tế. Đây là data moat.
5. AGENTIC ARCHITECTURE — Tự vận hành, daily digest, giảm thiểu intervention thủ công.

### 2.4 Cơ chế bảo vệ cạnh tranh của SànChínhChủ (learning)

- Data ẩn sau paywall (trả tiền mới xem SĐT, chi tiết).
- Account-based access (login required).
- Rate-limit / block scraper.
- Giá trị thật: classifier accuracy (thuật toán phân loại chính chủ) xây dựng qua 10 năm.
- 300 website sources list là tài sản tích lũy lâu năm.

Bài học cho RealEstork: Không cần crawl 300 sites từ đầu. 80/20 rule: 5-10 platform lớn chứa 80%+ listings HCMC. Subscribe SànChínhChủ (~100k VNĐ/15 ngày) làm data source bổ sung ở MVP. Scale nguồn crawl khi có revenue.

---

## 3. HAI HƯỚNG KINH DOANH SONG SONG

### 3.1 Hướng 1: Sale Admin Accelerator

Mục tiêu: Giảm thời gian phát hiện nhà mới từ hàng giờ xuống vài phút. Tự động lọc chính chủ. Alert real-time qua Zalo 1-1 cho vợ.

Output cho vợ (Zalo message):
```
🏠 MẶT BẰNG MỚI — Likely Chính Chủ (Score: 78)

📍 123 Hai Bà Trưng, P. Bến Nghé, Q.3
💰 120 triệu/tháng | 80m²
📞 0901234567 (Anh Minh)
🔗 Xem trên Batdongsan: [link]

📊 OSINT Result:
  • Zalo: "Nguyễn Văn A" — ảnh cá nhân, không business
  • Truecaller: Không có record → khả năng cá nhân
  • Google: 1 kết quả duy nhất (tin này)
  • DB nội bộ: Chưa từng xuất hiện
  
⏰ Đăng 5 phút trước

[✅ Đã gọi] [❌ Môi giới] [👤 Chính chủ]
```

Giá trị: Vợ nhận alert → biết ngay nên gọi hay bỏ qua → ghi nhận lead trước đồng nghiệp.

OSINT output giúp vợ tiết kiệm 2-3 phút tra cứu thủ công mỗi listing. Với 20-30 listings/ngày = tiết kiệm 1-1.5 giờ/ngày. Thời gian đó dùng để gọi thêm chủ nhà.

### 3.2 Hướng 2: Sàn Aggregate

Mục tiêu: Xây platform giống SànChínhChủ nhưng tốt hơn ở segment mặt bằng cho thuê HCMC.

Output cho subscribers (Telegram Bot):
```
🏠 MẶT BẰNG MỚI — 🟢 Chính Chủ (Score: 82)

📍 456 Võ Thị Sáu, P. Tân Định, Q.3
💰 95 triệu/tháng | 65m²
📞 [Unlock: Premium]
🔗 [Xem chi tiết]

📊 Signals: SĐT 1 tin duy nhất, mô tả amateur, ảnh ít
```

Revenue model:

```
Stream              | Chi tiết                                    | Giá ước tính
--------------------+---------------------------------------------+-------------------
Freemium sub        | Free: 10 tin/ngày, delay 1-2 giờ            | 0
                    | Paid: unlimited, real-time alert             | 50k-200k VNĐ/tháng
Pay-per-view        | Mua lẻ từng tin (cho user ít dùng)          | 200-500đ/tin
API access          | Cho sàn BĐS nhỏ cần data chính chủ          | Negotiate/volume
Premium insights    | Báo cáo xu hướng giá, heatmap, vacancy pred | Gói cao cấp
Sponsored listing   | Môi giới trả phí để tin ưu tiên hiển thị    | CPM/CPC
```

### 3.3 Datasource đặc biệt: Company Database

Database công ty vợ = nguồn data quý giá:
- Data đã được verify bởi team sale thực tế.
- Thông tin chủ nhà, hoa hồng, lịch sử thuê, trạng thái.
- Không public trên bất kỳ platform nào.

App công ty: build nội bộ, cài dạng app Windows + Android/iOS. Không export CSV, chỉ nhận data vào. Phân quyền RBAC, log hành vi xem nhà để chống leak. Cần page-agent (Alibaba) cho extraction — xem Module 5.

Privacy & Ethics: Phase 1 chỉ dùng cross-reference (check listing public đã có trong DB công ty chưa). Phase 2 nếu publish, cần anonymize hoặc chỉ dùng public data.

### 3.4 Quyết định phát triển sau MVP

Build MVP serve Hướng 1 trước (validate income tăng cho vợ), đồng thời tích lũy data. Nếu data + engine hoạt động tốt → mở Hướng 2 từ tháng 3.

```
Tiêu chí        | Hướng 1 ưu tiên nếu...       | Hướng 2 ưu tiên nếu...
-----------------+-------------------------------+-----------------------------
Revenue speed    | Tăng income vợ ngay tháng đầu | Cần 3-6 tháng build users
Scalability      | Giới hạn capacity vợ          | Scale vô hạn (SaaS)
Risk             | Thấp (tool nội bộ)            | Trung bình (marketing, cạnh tranh)
Data moat        | Không (tool cá nhân)          | Có (database tích lũy)
```

---

## 4. ĐÁNH GIÁ REVENUE TIỀM NĂNG

### 4.1 Hướng 1: Sale Admin Accelerator

Thu nhập hiện tại vợ: ~20 triệu VNĐ/tháng.
Khu vực: Quận 3, mặt bằng trung bình 80-150 triệu/tháng.
Vợ không tự chọn khu vực hay shift giá — công ty phân công.

Cải thiện thu nhập bằng cách tăng tốc độ phát hiện listing:
- Tool alert nhanh hơn 2-3 giờ so với thủ công.
- Vợ ghi nhận lead trước đồng nghiệp cùng công ty.
- Classification chính xác → ít gọi "trượt" (gọi nhầm môi giới) → tiết kiệm thời gian → dành cho listings khác.
- Ước tính tăng 30-50% số căn lên → +6-10 triệu/tháng (tổng 26-30 triệu).

ROI: Chi phí tool = ~$0-7/tháng (self-hosted + proxy nếu cần). Build MVP = 4 tuần.

### 4.2 Hướng 2: Sàn Aggregate

```
Phase         | Users (paid) | ARPU        | MRR
--------------+--------------+-------------+------------------
MVP (tháng 1-3)| 10-20 beta  | 0           | 0 (validation)
Tháng 6       | 50-100       | 100k VNĐ   | 5-10 triệu
Tháng 12      | 200-500      | 150k VNĐ   | 30-75 triệu
Năm 2         | 1,000+       | 200k VNĐ   | 200+ triệu
```

Breakeven: Server cost ~$10-20/tháng (self-hosted, Supabase Pro khi cần). Chỉ cần 100-200 paid users × 100k = 10-20 triệu/tháng.

SànChínhChủ hoạt động 10+ năm = thị trường có nhu cầu thật.

---

## 5. KIẾN TRÚC HỆ THỐNG

### 5.1 Nguyên tắc

- Opensource / free cho MVP, sẵn sàng trả phí khi cần (proxy, Supabase Pro, AI API, Devi AI).
- Self-hosted trên CHANKWAN-WIN2.
- Supabase project RIÊNG cho RealEstork (KHÔNG share với GGEZ).
- Free tier khi MVP. Có MRR → trả phí Supabase Pro.
- Plugin-based scraper: thêm site mới = thêm 1 file config + 1 spider file.
- Config-driven scoring: thêm/sửa/optimize signals bằng edit YAML, không cần redeploy.
- AI 4-tier ngay trong MVP: zero-token gateway (free) → ChatGPT sub → API → Ollama local. Switchable via CLI/config.
- Rule-based classification là nền tảng chính, AI là signal bổ sung (~15%).
- Agentic orchestrator điều phối toàn bộ pipeline, output daily digest.
- Discord + Telegram cho sản phẩm aggregate (MVP). Web UI là sản phẩm chính (Phase 2).

### 5.2 High-level Architecture

```
CHANKWAN-WIN2 (On-premise, Tailscale)
├── Agentic Orchestrator (Python)
│   ├── Schedule: cron / APScheduler
│   ├── Orchestrate: spiders → pipeline → alerts
│   ├── Daily digest: summary → Telegram/Discord/Zalo
│   └── AI Gateway: openclaw-zero-token / Ollama / API
│
├── Scraper Engine (Scrapling)
│   ├── Spider: nhatot (API mode)
│   ├── Spider: batdongsan (StealthyFetcher)
│   ├── Spider: alonhadat (HTTP)
│   ├── Spider: homedy (HTTP) [Phase 2]
│   ├── Spider: muaban (HTTP) [Phase 2]
│   ├── Spider: facebook_public (facebook-scraper, opensource)
│   ├── Spider: zalo_web (optional, DynamicFetcher)
│   └── Config: spiders.yaml (enable/disable/interval)
│
├── Pipeline / Classifier Engine
│   ├── Dedup (address + phone + content hash)
│   ├── Phone frequency analysis (cross-platform)
│   ├── Text pattern matching (configurable YAML)
│   ├── AI classification (4-tier, switchable via CLI/config)
│   ├── Scoring: 0-100 (configurable weights YAML)
│   └── Learning loop: feedback → retrain weights
│
├── OSINT Phone Lookup
│   ├── Zalo profile check
│   ├── Truecaller lookup
│   ├── Google search (phone in quotes)
│   ├── Cross-platform frequency
│   └── Known broker DB match
│
├── Company DB Extractor (browser-use, Python) [Phase 2]
│   ├── Control app UI via natural language (Python native)
│   ├── Extract listings → normalize → import
│   └── Throttle + simulate human behavior
│
├── AI Gateway Layer
│   ├── Tier 1 (Free): openclaw-zero-token
│   │   └── DeepSeek Web, Qwen Web, Gemini Web, Kimi, GLM, Doubao
│   ├── Tier 2 ($20/mo): ChatGPT Plus / Gemini Pro via zero-token
│   ├── Tier 3 (Pay/token): Claude API, OpenAI API
│   └── Tier 4 (Local GPU): Ollama on GTX 1660 SUPER
│       └── Gemma 4 E4B (default), Qwen 2.5 7B, Phi-3, Llama 3.1
│
├── Notification System
│   ├── Zalo 1-1 (cho vợ, via Zalo OA/Bot)
│   ├── Telegram Bot (cho sản phẩm aggregate)
│   └── Discord Server (community + alerts, cho sản phẩm)
│
├── changedetection.io (Docker, backup monitor)
│
└── Supabase (Separate project, NOT shared with GGEZ)
    ├── listings, phones, broker_phones
    ├── classification_feedback
    ├── alert_subscribers
    ├── company_listings [Phase 2]
    ├── users [Phase 2]
    └── Realtime subscriptions (WebSocket push for Web UI)

External Access (via Tailscale)
├── MacBook M2 (Chankwan, remote management)
└── Web UI [Phase 2] (public, for aggregate platform)
```

---

## 6. TECH STACK

```
Layer                  | Tool                              | Lý do
-----------------------+-----------------------------------+--------------------------------
Scraping engine        | Scrapling (pip install scrapling)  | Adaptive selectors, bypass
                       |                                   | Cloudflare Turnstile OOB,
                       |                                   | built-in proxy rotation +
                       |                                   | spider framework, MCP server.
                       |                                   | 258k+ downloads, BSD-3.
                       |                                   | Thay thế Scrapy cho use case này.
Facebook scraping      | facebook-scraper (opensource)      | Public groups. MVP free.
                       | github.com/kevinzg/facebook-scraper| Phase 2+: Devi AI $50/mo hoặc
                       |                                   | Apify ($0.35/1k posts) cho
                       |                                   | private groups khi có revenue.
Quick monitor (backup) | changedetection.io (Docker)       | Alert nhanh khi scraper chưa sẵn
Interactive automation | browser-use (Python, 55k+ stars)  | Company DB extraction. Thay
                       | github.com/browser-use/browser-use| page-agent (JS). Python native,
                       |                                   | phù hợp stack, community lớn hơn.
Database               | Supabase (own project)            | PostgreSQL, realtime subs, auth.
                       |                                   | Free tier MVP, Pro khi có MRR.
                       |                                   | Realtime WebSocket cho Web UI push.
Backend API            | FastAPI (Python)                  | Async, auto-docs, cùng ecosystem
AI Gateway (4-tier)    | Tier 1: openclaw-zero-token       | Free. DeepSeek/Qwen/Gemini/Kimi
                       |   (zero API token, web chat)      | /GLM/Doubao qua browser login.
                       |   github.com/linuxhsj/            | OpenAI-compatible API at
                       |   openclaw-zero-token              | localhost:3001.
                       | Tier 2: ChatGPT Plus ($20/mo)     | Qua zero-token hoặc native
                       |   hoặc Gemini Pro sub             | OpenClaw Codex OAuth.
                       | Tier 3: API trực tiếp             | Claude Haiku $0.25/1M tokens.
                       |   (pay per token)                 | Khi cần accuracy cao nhất.
                       | Tier 4: Ollama local (GPU)        | Free. GTX 1660 SUPER 6GB.
                       |   Default: Gemma 4 E4B            | Backup khi internet down.
Local LLM models       | Gemma 4 E4B (~5GB, MỚI NHẤT)    | Multimodal, 128K ctx, reasoning,
  (Ollama, Tier 4)     | Gemma 4 E2B (~4GB)               | function calling. Apache 2.0.
                       | Qwen 2.5 7B (~5GB)               | Mạnh coding + tiếng Việt.
                       | Phi-3 Mini 3.8B (~3GB)            | Microsoft, nhẹ nhất.
                       | Llama 3.1 8B (~5GB)               | Meta, general purpose.
                       | Gemma 3 4B (~3GB)                 | Nhẹ, 128K context.
Notification (vợ)      | Zalo OA / Zalo Bot                | 1-1 chat, vợ quen dùng Zalo
Notification (product) | Telegram Bot API                  | MVP primary. Free, rich text.
                       | Discord Bot + Server              | Community + alerts. Free,
                       |                                   | organize by channel (quận/giá).
                       |                                   | Reuse GGEZ Discord experience.
Scheduling             | APScheduler / Windows Task Sched. | Đã có kinh nghiệm từ GGEZ
Proxy (nếu cần)        | Webshare residential VN           | $7/tháng/1GB, rẻ nhất.
                       |                                   | Bắt đầu KHÔNG CẦN proxy.
VPN/Remote             | Tailscale (đã có)                 | Access từ MacBook M2
Future reference       | Crawlee (apify/crawlee, 16k stars)| Phase 4 nếu scale 100+ sites.
                       | Firecrawl (mendableai, 30k stars) | Feed full page → LLM nếu cần.
                       | Supabase Realtime                 | WebSocket push cho Web UI.
```

### 6.1 Tại sao Scrapling thay Scrapy?

Scrapling (github.com/D4Vinci/Scrapling) giải quyết 3 pain point cụ thể mà Scrapy không có sẵn:

1. Adaptive selector: khi batdongsan/nhatot thay đổi layout HTML, selector tự phục hồi bằng similarity matching thay vì crash. Giảm maintenance.
2. StealthyFetcher: bypass Cloudflare Turnstile out-of-the-box. batdongsan.com.vn dùng Cloudflare. Scrapy cần thêm nhiều middleware.
3. Built-in spider framework + proxy rotation: Scrapy-like API nhưng tích hợp sẵn, ít setup.

Scrapy mature hơn (ecosystem, middleware), nhưng cho use case scraping 5-10 site VN BĐS, Scrapling fit hơn vì ít code, ít maintenance.

### 6.2 Proxy — Ước tính chi phí

Volume ước tính: ~500-1000 requests/ngày. Rất nhẹ.

Chiến lược: Bắt đầu KHÔNG CẦN proxy (dùng IP nhà). Nếu bị block → mua.

```
Provider      | Loại             | Giá           | Ghi chú
--------------+------------------+---------------+---------------------------
Webshare      | Residential VN   | $7/tháng/1GB  | Rẻ nhất, đủ cho volume nhỏ
Decodo        | Residential      | $2.2/GB       | Pay-as-you-go
IPRoyal       | Residential VN   | ~$3.5/GB      | 460k+ VN IPs
Bright Data   | Residential      | $8/GB         | Enterprise, overkill cho MVP
```

Ước tính: 1000 req/ngày × ~100KB/req = ~100MB/ngày = ~3GB/tháng. Cost: $7-21/tháng. Đề xuất Webshare $7/tháng nếu cần.

---

## 7. MODULE 1: SCRAPER ENGINE (SCRAPLING)

### 7.1 Mục tiêu

Crawl listings cho thuê mặt bằng HCMC từ các platform, extract structured data. Plugin-based: thêm site mới = thêm 1 file + 1 entry config.

### 7.2 Cấu hình Spider (config-driven)

File: `config/spiders.yaml`

```yaml
spiders:
  - name: nhatot
    enabled: true
    type: api
    # Dùng API ẩn gateway.chotot.com/v1/public/ad-listing
    # Params: region_v2, cg (category), limit, o (offset)
    # Tìm params: F12 → Network → XHR khi browse cho thuê mặt bằng HCMC
    interval_minutes: 15
    max_pages: 5
    
  - name: batdongsan
    enabled: true
    type: stealthy
    # StealthyFetcher cho Cloudflare bypass
    interval_minutes: 30
    max_pages: 3
    
  - name: alonhadat
    enabled: true
    type: http
    # HTTP đơn giản, ít anti-bot
    interval_minutes: 30
    max_pages: 3
    
  - name: homedy
    enabled: false  # Phase 2
    type: http
    interval_minutes: 60
    
  - name: muaban
    enabled: false  # Phase 2
    type: http
    interval_minutes: 60
    
  - name: cafeland
    enabled: false  # Phase 2
    type: http
    interval_minutes: 60
    
  - name: facebook_groups
    enabled: false  # Enable khi ready. Opensource facebook-scraper cho public groups.
    type: http
    # pip install facebook-scraper (github.com/kevinzg/facebook-scraper)
    # Chỉ public groups. Private groups cần Devi AI $50/mo (Phase 3).
    interval_minutes: 60
    groups:
      - "cho.thue.mat.bang.kinh.doanh.tphcm"
      - "sang.nhuong.quan.cho.thue.mat.bang.tphcm"
    
  - name: zalo_web
    enabled: false  # Optional, risk bị block account
    type: dynamic
    # DynamicFetcher trên chat.zalo.me
```

Thêm site mới: Tạo file `spiders/new_site.py` implement interface chuẩn + thêm entry trong YAML. Không cần redeploy.

### 7.3 Spider Interface

Mỗi spider phải implement:

```python
class BaseSpider:
    name: str
    
    async def fetch_listings(self, config: dict) -> list[RawListing]:
        """Fetch raw listings from platform. Return list of RawListing."""
        raise NotImplementedError
    
    def parse_listing(self, raw: Any) -> RawListing:
        """Parse raw response into RawListing schema."""
        raise NotImplementedError
```

### 7.4 Output Schema (mỗi listing)

```python
@dataclass
class RawListing:
    source: str           # "nhatot", "batdongsan", "alonhadat", ...
    source_id: str        # Original listing ID on platform
    source_url: str       # Full URL
    title: str
    description: str      # Full text
    address: str
    district: str         # Raw district string
    city: str             # Default "HCMC"
    area_m2: float | None
    price_vnd_monthly: int | None
    price_text: str       # Raw price string
    phone: str            # Raw phone string
    contact_name: str | None
    images: list[str]     # URLs
    posted_at: datetime | None
    scraped_at: datetime  # Auto-set
    raw_html_hash: str    # SHA256 for dedup
```

### 7.5 Platform-specific Notes

NHATOT.COM (Chợ Tốt) — DỄ NHẤT, LÀM TRƯỚC:
- API ẩn: `gateway.chotot.com/v1/public/ad-listing`
- Trả JSON, không cần headless browser.
- Params: `region_v2` (HCMC), `cg` (category cho thuê mặt bằng), `limit`, `o` (offset).
- Tìm params chính xác: F12 → Network → XHR khi browse danh mục cho thuê mặt bằng HCMC.
- Summary data có sẵn, full detail cần fetch individual page.

BATDONGSAN.COM.VN — TRUNG BÌNH, CẦN STEALTH:
- JS rendering + Cloudflare.
- Dùng Scrapling StealthyFetcher.
- Nếu bị block: thêm proxy rotation (Webshare).
- URL target: `/cho-thue-mat-bang-tp-hcm` sorted by newest.

ALONHADAT.COM.VN — DỄ:
- HTTP scraping đơn giản, ít anti-bot.
- Scrapling Fetcher (HTTP mode) đủ.

### 7.6 Anti-detection

- User-Agent rotation: list 20+ UA strings.
- Request delay: random 2-5 giây giữa requests.
- Scrapling StealthyFetcher: TLS fingerprint spoofing, auto.
- Proxy rotation: chỉ khi bị block, config trong `config/proxy.yaml`.
- Respect rate limits: không quá 1 req/2s/site.

### 7.7 Error Handling

- Retry 3 lần với exponential backoff.
- Alert Discord/Telegram nếu spider fail liên tục.
- Log errors vào file + Supabase `spider_logs` table.
- Circuit breaker: nếu 1 spider fail > 5 lần liên tiếp → disable tự động, alert operator.

---

## 8. MODULE 2: DEDUP & CLASSIFICATION PIPELINE

### 8.1 Dedup Logic

Address normalization:
- Lowercase.
- Bỏ dấu (unidecode).
- Chuẩn hóa abbreviations: "Q." → "Quận", "P." → "Phường", "Đ." → "Đường", "HBT" → "Hai Bà Trưng".
- Strip extra spaces.

Phone normalization:
- Bỏ +84, 0084, spaces, dashes, dots.
- Format: 10 digits (0XXXXXXXXX).

Dedup rules:
- Same phone + same district + price within ±10% → likely duplicate, keep earliest.
- Same address (normalized) → definite duplicate, keep earliest.
- Content hash (SHA256 of title+description+phone) match → exact duplicate.

### 8.2 Classification Architecture: Rule-based Foundation + AI Enhancement

QUAN TRỌNG: RealEstork dùng RULE-BASED làm nền tảng chính, giống SànChínhChủ. Lý do:
- Rule-based nhanh (ms, không cần GPU), deterministic, dễ debug.
- SànChínhChủ chạy rule-based 10 năm và vẫn hoạt động tốt — proven approach.
- Khi 1 listing bị classify sai, bạn biết chính xác signal nào gây ra và sửa ngay.

AI/LLM là 1 SIGNAL BỔ SUNG trong hệ thống rule-based, không phải thay thế:
- Trong `scoring.yaml`, có ~12 rule-based signals + 1 AI signal.
- AI signal có weight 30 (trên tổng ~200 điểm range), chiếm ~15% ảnh hưởng.
- Nếu AI model chậm/unavailable, system vẫn classify bằng rules còn lại.
- AI giúp catch cases mà rules miss (ví dụ: mô tả tinh vi, ngữ cảnh phức tạp).

Pipeline xử lý: Rules chạy trước (instant) → AI chạy async song song → merge score.

### 8.3 Classification Scoring Config

Config-driven. File: `config/scoring.yaml`. Editable runtime, không cần redeploy.

```yaml
# RealEstork Classification Scoring Config
# Score 0-100. Cao = likely chính chủ.
# Thêm/sửa/xóa signals tự do. Restart scheduler để apply.

version: 2
threshold_chinh_chu: 65       # score >= này → "chinh_chu"
threshold_can_xac_minh: 40    # score >= này → "can_xac_minh"
                               # score < 40 → "moi_gioi"

base_score: 50  # Mọi listing bắt đầu ở 50

signals:
  # === Phone-based signals ===
  phone_single_listing:
    description: "SĐT chỉ xuất hiện 1 listing trên tất cả platforms"
    weight: +20
    check: "phone_count_all_platforms == 1"
    
  phone_multi_listing_same_platform:
    description: "SĐT >= 5 listings trên cùng 1 platform"
    weight: -25
    check: "phone_count_max_single_platform >= 5"
    
  phone_multi_platform:
    description: "SĐT xuất hiện trên >= 3 platforms khác nhau"
    weight: -15
    check: "phone_platform_count >= 3"
    # Giảm từ -30 vì người bán đồ cũ cũng cross-post
    # Chỉ -15, cần kết hợp signals khác
    
  phone_known_broker:
    description: "SĐT trong broker_phones database"
    weight: -50
    check: "phone in broker_phones_db"
    
  # === Text-based signals ===
  text_owner_language:
    description: "Description chứa ngôn ngữ chính chủ"
    weight: +15
    keywords: ["nhà tôi", "chính chủ cần cho thuê", "liên hệ trực tiếp"]
    check: "any(kw in description_lower for kw in keywords)"
    
  text_marketing_superlatives:
    description: "Description chứa superlatives marketing"
    weight: -20
    keywords: ["đắc địa", "siêu hot", "sinh lợi cao", "vị trí vàng", 
               "không thể bỏ lỡ", "cơ hội hiếm có", "giá tốt nhất"]
    check: "any(kw in description_lower for kw in keywords)"
    
  text_commission_mention:
    description: "Description nhắc đến hoa hồng/commission"
    weight: -15
    keywords: ["hoa hồng", "commission", "phí môi giới", "% cho sale"]
    check: "any(kw in description_lower for kw in keywords)"
    
  # === Posting pattern signals ===
  photo_count_low:
    description: "Ít ảnh (<= 3), style amateur"
    weight: +5
    check: "len(images) <= 3"
    
  photo_count_high:
    description: "Nhiều ảnh (>= 8), professional"
    weight: -10
    check: "len(images) >= 8"
    
  posted_outside_business_hours:
    description: "Đăng ngoài giờ hành chính (tối/cuối tuần)"
    weight: +5
    check: "posted_hour < 8 or posted_hour > 18 or is_weekend"
    
  account_new_or_few_posts:
    description: "Account mới / ít tin trên platform (nếu data available)"
    weight: +10
    check: "poster_total_listings <= 2"
    
  # === AI signal (BỔ SUNG, không thay thế rules ở trên) ===
  ai_classification:
    description: "LLM phân tích text + metadata — chỉ là 1 signal trong ~13 signals"
    weight: 30
    # ~15% tổng ảnh hưởng. Nếu AI unavailable, rules vẫn chạy.
    model: "ollama/gemma4:e4b"  # Switchable: zero-token/deepseek-web, anthropic/claude-haiku
    check: "ai_owner_probability"  # 0.0-1.0, nhân với weight
    
  # === Description quality signals ===
  description_too_short:
    description: "Mô tả rất ngắn (< 50 chars) — có thể chính chủ viết qua loa"
    weight: +5
    check: "len(description) < 50"
    
  description_too_long:
    description: "Mô tả rất dài (> 500 chars) — có thể copy-paste marketing"
    weight: -5
    check: "len(description) > 500"
```

QUAN TRỌNG: Signals config là YAML, editable anytime. Thêm signal mới = thêm entry YAML + viết 1 function check trong `classifiers/signals.py`. Chỉnh weight = edit YAML, restart scheduler. Đây là operational tuning, KHÔNG phải feature release.

### 8.4 Learning Feedback Loop (ngay từ MVP)

Flow:
1. Vợ nhận alert → gọi → confirm kết quả qua Zalo command: `/mark <id> owner` hoặc `/mark <id> broker`.
2. System log vào `classification_feedback` table: listing features + ground truth label + timestamp.
3. Hàng tuần: Agent chạy analysis trên labeled data:
   - Precision/recall mỗi signal.
   - Suggest weight adjustments.
   - Output report → Telegram cho Chankwan review.
4. AI model: Pass listing text + metadata vào LLM → output `{"is_owner": 0.82}` → integrate vào score.
5. Model switching: config `ai.provider` + `ai.*.model` → đổi giữa 4 tiers bằng edit YAML hoặc CLI `realestork ai switch <provider/model>`.
6. A/B test: chạy 2 models song song trên cùng data, so sánh accuracy mỗi tuần. CLI: `realestork ai compare model1 model2`.

Mục tiêu: Accuracy cải thiện dần 60% → 75% → 85%+ qua feedback loop.

### 8.5 AI Classification Prompt (cho LLM)

```
Bạn là chuyên gia phân tích tin đăng bất động sản cho thuê tại Việt Nam.
Cho tin đăng sau, hãy đánh giá khả năng người đăng là CHÍNH CHỦ (chủ nhà thật sự)
hay MÔI GIỚI (broker/agent).

Tiêu đề: {title}
Mô tả: {description}
SĐT: {phone}
Số ảnh: {photo_count}
Platform: {source}

Trả lời CHÍNH XÁC theo format JSON (không thêm text khác):
{
  "is_owner_probability": 0.0-1.0,
  "reasoning": "giải thích ngắn 1-2 câu",
  "signals_detected": ["signal1", "signal2"]
}
```

---

## 9. MODULE 3: OSINT PHONE LOOKUP

### 9.1 Mục tiêu

Tra cứu SĐT từ listing mới, output kết quả vào alert message. Giúp vợ/user biết thêm context trước khi gọi.

### 9.2 Lookup Pipeline

Chạy tự động cho mỗi listing mới có score >= threshold:

```
Step 1: Zalo Profile Lookup (free)
  - Search SĐT trong Zalo "Add Friend" API (nếu có) hoặc 
    dùng Scrapling DynamicFetcher trên chat.zalo.me
  - Extract: tên, ảnh, business account hay không
  
Step 2: Truecaller Lookup (free basic)
  - API hoặc web scrape truecaller.com
  - Extract: tên đăng ký, business/personal, spam score
  
Step 3: Google Search (free)
  - Search "0901234567" (phone in quotes)
  - Count: bao nhiêu kết quả? Xuất hiện trên mấy platform?
  - Extract: tóm tắt context
  
Step 4: Internal DB Check
  - Kiểm tra phone trong phones table: đã xuất hiện bao nhiêu lần?
  - Kiểm tra phone trong broker_phones table: known broker?
  
Step 5: Trangtrang.com (free, optional)
  - DB 325k+ reviews, 201k+ SĐT
  - Check spam/scam classification
```

### 9.3 Output Format

Cho vợ (Zalo 1-1):
```
📞 0901234567 — KẾT QUẢ TRA CỨU:
• Zalo: "Nguyễn Văn A" — ảnh cá nhân, không phải business
• Truecaller: Không có record → khả năng cá nhân
• Google: 1 kết quả duy nhất (tin này) → chưa đăng tin khác
• DB nội bộ: Chưa từng xuất hiện
• Kết luận: Likely chính chủ (Score 78)
```

Cho sản phẩm aggregate (Telegram): Score badge + tooltip signals. SĐT ẩn sau paywall (paid users mới thấy).

### 9.4 Business Registration Lookup (optional)

dangkykinhdoanh.gov.vn: tra cứu ĐKKD theo tên/mã số thuế. Luật KDBĐS 2023 (hiệu lực 2025): môi giới phải hoạt động qua công ty đăng ký. Nếu tìm được công ty BĐS liên quan đến SĐT → flag môi giới.

---

## 10. MODULE 4: ALERT / NOTIFICATION SYSTEM

### 10.1 Ba channel

```
                    | Cho vợ (Hướng 1)        | Cho sản phẩm (Hướng 2)
--------------------+-------------------------+----------------------------------
Channel             | Zalo 1-1                | Telegram Bot + Discord Server
                    | (Zalo OA hoặc Zalo Bot) |
Nội dung            | Alert chi tiết +        | Alert listing + score badge.
                    | OSINT result +          | SĐT ẩn sau paywall.
                    | action buttons          |
Audience            | 1 người (vợ)            | Subscribers (paid users)
Trigger             | Score >= threshold       | Score >= threshold
                    | + match filter          | + match user filter
```

Discord Server cho RealEstork Aggregate:
- Channels tổ chức theo quận: #quan-1, #quan-3, #binh-thanh, ...
- Channel #all-listings: tất cả listings mới
- Channel #chinh-chu-only: score >= 65
- Channel #announcements: updates, maintenance
- Community discussion: users thảo luận, share kinh nghiệm
- Discord = competitive moat qua community engagement (SànChínhChủ không có)
- Bot post listings mới vào channel tương ứng tự động

Notification priority cho sản phẩm:

```
Phase    | Channel          | Role
---------+------------------+------------------------------------
MVP      | Telegram Bot     | Primary push notification
MVP      | Discord Server   | Community + organized alerts
Phase 2  | Web UI           | SẢN PHẨM CHÍNH, Telegram/Discord
         |                  | là extensions
Phase 2+ | Zalo OA          | VN-native option nếu có nhu cầu
Phase 2+ | Email digest     | Weekly summary
```

### 10.2 Zalo Bot Commands (cho vợ)

```
/start              — Register, set preferences
/filter Q3,Q1       — Set district filter
/minprice 50        — Min price (triệu VNĐ/tháng)
/maxprice 200       — Max price
/pause              — Tạm dừng alert
/resume             — Resume
/stats              — Thống kê: tổng listings hôm nay, chính chủ, đã gọi
/mark <id> called   — Đánh dấu đã gọi
/mark <id> broker   — Confirm là môi giới → update DB + training data
/mark <id> owner    — Confirm là chính chủ → update DB + training data
```

### 10.3 Telegram Bot Commands (cho subscribers)

```
/start              — Register
/subscribe          — Chọn gói subscription
/filter Q3,Q1,Q7    — Set district filter
/minprice 30        — Min price
/maxprice 500       — Max price
/minscore 60        — Min classification score
/today              — Listings hôm nay matching filter
/stats              — Thống kê tuần/tháng
```

### 10.4 Discord Bot Commands (cho subscribers)

```
!subscribe            — Link Discord account to RealEstork
!filter Q3,Q1,Q7      — Set district filter
!minprice 30          — Min price
!maxprice 500         — Max price
!minscore 60          — Min classification score
!today                — Listings hôm nay matching filter
!stats                — Thống kê tuần/tháng
```

Discord Bot tự động post listings mới vào channel phù hợp (#quan-1, #quan-3, etc.) dựa trên district. Users chọn channels muốn follow.

### 10.5 Alert Trigger Rules

- Alert ngay: listing mới pass filter + score >= `threshold_chinh_chu` (65).
- Batch digest mỗi 2 giờ: listings score 40-64 (cần xác minh).
- Daily summary lúc 8h sáng: tổng listings hôm qua, top 10 chính chủ chưa gọi, accuracy stats.

---

## 11. MODULE 5: COMPANY DATABASE EXTRACTION (browser-use)

### 11.1 Mục tiêu

Extract data từ app nội bộ công ty vợ vào `company_listings` table. Phase 2, khi Hướng 2 cần data.

### 11.2 App characteristics

- Build nội bộ, cài dạng native Windows + Android/iOS.
- Không export CSV, chỉ nhận data vào.
- Phân quyền RBAC: mỗi user chỉ thấy listings được phân công.
- Log hành vi: ai xem nhà nào, khi nào → chống leak nội bộ.
- Chủ công ty kiểm soát chặt.

### 11.3 Extraction Strategy: browser-use (Python)

browser-use (github.com/browser-use/browser-use, 55k+ stars): Python library, control browser bằng natural language cho AI agents. Thay thế page-agent (Alibaba, JS-based) vì:
- Python native → match RealEstork stack, không cần JS runtime riêng.
- Community 55k stars (vs page-agent 12k) → actively maintained, nhiều examples.
- Dễ integrate với Scrapling và FastAPI trong cùng Python process.

Approach:
1. Nếu app có web version (admin dashboard): browser-use control browser → navigate → extract.
2. Nếu chỉ có mobile app: chạy Android emulator → screen mirror → browser-use hoặc OCR.
3. Nếu chỉ có Windows app: UI automation (pyautogui + OCR) hoặc browser-use nếu app dùng web tech (Electron/WebView).

Anti-detection:
- Throttle extraction: max 20-30 listings/session, random delay 10-30 giây giữa views.
- Simulate human browsing: scroll, pause, random navigation.
- Chỉ chạy vào giờ làm việc (9-17h) để pattern giống user bình thường.
- Rotate sessions: không xem quá nhiều trong 1 ngày.

CHỜ THÊM ĐÁNH GIÁ APP TỪ CHANKWAN để design strategy chi tiết.

### 11.4 Privacy & Ethics

- Phase 1: Chỉ cross-reference (check listing public đã có trong DB công ty chưa → tránh duplicate work cho vợ).
- Phase 2: Nếu muốn publish trên sàn aggregate → chỉ dùng data public (address, price range) + anonymize owner info. KHÔNG publish SĐT chủ nhà từ DB công ty.
- Risk: Nếu bị phát hiện extract data → vợ có thể bị kỷ luật. Cân nhắc kỹ.

---

## 12. MODULE 6: AGENTIC ORCHESTRATOR

### 12.1 Mục tiêu

Agentic layer điều phối toàn bộ pipeline. Tự vận hành, output daily digest. Chankwan chỉ cần review digest hàng ngày.

### 12.2 Architecture

```python
class RealEstorkAgent:
    """Main orchestrator. Runs as background service on CHANKWAN-WIN2."""
    
    def __init__(self):
        self.scheduler = APScheduler()
        self.scraper_engine = ScraperEngine(config="config/spiders.yaml")
        self.pipeline = ClassificationPipeline(config="config/scoring.yaml")
        self.osint = OSINTLookup()
        self.alerter = AlertSystem()
        self.ai = AIClassifier(config="config/ai.yaml")
        self.db = SupabaseClient()
    
    async def run_scrape_cycle(self):
        """Called every 15-30 minutes by scheduler."""
        # 1. Fetch new listings from all enabled spiders
        raw_listings = await self.scraper_engine.fetch_all()
        
        # 2. Dedup against existing DB
        new_listings = self.pipeline.dedup(raw_listings)
        
        # 3. Classify each new listing
        for listing in new_listings:
            listing.score = self.pipeline.classify(listing)
            listing.ai_result = await self.ai.classify(listing)
            listing.score += listing.ai_result.weight
            listing.label = self.pipeline.label(listing.score)
        
        # 4. OSINT lookup for high-score listings
        for listing in new_listings:
            if listing.score >= 50:
                listing.osint = await self.osint.lookup(listing.phone)
        
        # 5. Save to DB
        self.db.upsert_listings(new_listings)
        
        # 6. Send alerts
        await self.alerter.send_alerts(new_listings)
    
    async def daily_digest(self):
        """Called at 8:00 AM daily."""
        stats = self.db.get_daily_stats()
        feedback_analysis = self.pipeline.analyze_feedback()
        
        digest = f"""
        📊 DAILY DIGEST — RealEstork
        
        Hôm qua: {stats.total_new} listings mới
        Chính chủ: {stats.chinh_chu} | Cần xác minh: {stats.can_xac_minh} | Môi giới: {stats.moi_gioi}
        Vợ đã gọi: {stats.called} | Confirm owner: {stats.confirmed_owner} | Confirm broker: {stats.confirmed_broker}
        
        Classification accuracy (tuần này): {feedback_analysis.accuracy}%
        Top 10 chính chủ chưa gọi: [list]
        
        Signals effectiveness:
        {feedback_analysis.signal_report}
        
        Weight adjustment suggestions:
        {feedback_analysis.suggestions}
        """
        
        await self.alerter.send_digest(digest, channel="telegram")
        await self.alerter.send_digest(digest_vn, channel="zalo")
    
    async def weekly_model_comparison(self):
        """Called weekly. Compare AI model accuracy."""
        # Run same test set through multiple models
        # Output comparison report
        pass
```

### 12.3 Scheduling

```yaml
# config/schedule.yaml
schedules:
  scrape_cycle:
    interval: "*/15 * * * *"  # every 15 minutes
    function: run_scrape_cycle
    
  daily_digest:
    cron: "0 8 * * *"  # 8:00 AM daily
    function: daily_digest
    
  weekly_analysis:
    cron: "0 9 * * 1"  # Monday 9:00 AM
    function: weekly_model_comparison
    
  phone_db_cleanup:
    cron: "0 2 * * *"  # 2:00 AM daily
    function: cleanup_old_phone_data
```

---

## 13. MODULE 7: DATABASE SCHEMA (SUPABASE)

Supabase project RIÊNG cho RealEstork. KHÔNG share với GGEZ. Free tier khi MVP, trả phí khi có MRR.

```sql
-- =====================================================
-- RealEstork Database Schema v2
-- Supabase (PostgreSQL)
-- =====================================================

-- Core listings table
CREATE TABLE listings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    source_id TEXT,
    source_url TEXT,
    title TEXT,
    description TEXT,
    address TEXT,
    address_normalized TEXT,
    district TEXT,
    city TEXT DEFAULT 'HCMC',
    area_m2 NUMERIC,
    price_vnd_monthly BIGINT,
    price_text TEXT,
    phone TEXT,
    contact_name TEXT,
    images TEXT[],
    posted_at TIMESTAMPTZ,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    content_hash TEXT,
    
    -- Classification
    classification_score INTEGER DEFAULT 50,
    classification_label TEXT DEFAULT 'can_xac_minh',
    ai_result JSONB,
    osint_result JSONB,
    
    -- Status tracking
    status TEXT DEFAULT 'new',
    -- Values: new, alerted, called, confirmed_owner, confirmed_broker, archived
    notes TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(source, source_id)
);

-- Phone frequency tracking
CREATE TABLE phones (
    phone TEXT PRIMARY KEY,
    total_listings INTEGER DEFAULT 0,
    platforms TEXT[],
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    is_known_broker BOOLEAN DEFAULT FALSE,
    broker_company TEXT,
    zalo_name TEXT,
    truecaller_name TEXT,
    google_result_count INTEGER,
    notes TEXT
);

-- Known broker phone database (seed from vợ's knowledge)
CREATE TABLE broker_phones (
    phone TEXT PRIMARY KEY,
    name TEXT,
    company TEXT,
    source TEXT,  -- "manual", "confirmed_by_wife", "auto_detected"
    confidence NUMERIC DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Classification feedback (learning loop)
CREATE TABLE classification_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID REFERENCES listings(id),
    predicted_label TEXT,
    predicted_score INTEGER,
    actual_label TEXT,  -- "owner" or "broker"
    feedback_source TEXT,  -- "wife_zalo", "subscriber_telegram"
    signals_at_prediction JSONB,  -- snapshot of all signal values
    ai_model_used TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Alert subscribers (Hướng 2)
CREATE TABLE alert_subscribers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_chat_id BIGINT UNIQUE,
    discord_user_id TEXT,
    discord_channel_id TEXT,
    name TEXT,
    district_filter TEXT[],
    min_price BIGINT DEFAULT 0,
    max_price BIGINT DEFAULT 999999999,
    min_score INTEGER DEFAULT 60,
    subscription_tier TEXT DEFAULT 'free',
    -- Values: free, basic, premium
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Company listings (Phase 2, from company DB extraction)
CREATE TABLE company_listings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address TEXT,
    address_normalized TEXT,
    district TEXT,
    owner_phone TEXT,
    owner_name TEXT,
    price_vnd_monthly BIGINT,
    area_m2 NUMERIC,
    commission_months NUMERIC,
    commission_rate NUMERIC,
    lease_status TEXT,
    -- Values: available, rented, expired
    tenant_name TEXT,
    lease_end_date DATE,
    imported_at TIMESTAMPTZ DEFAULT NOW(),
    source_notes TEXT
);

-- Spider execution logs
CREATE TABLE spider_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spider_name TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT,  -- "success", "partial", "failed"
    listings_found INTEGER DEFAULT 0,
    new_listings INTEGER DEFAULT 0,
    error_message TEXT,
    duration_seconds NUMERIC
);

-- Indexes
CREATE INDEX idx_listings_phone ON listings(phone);
CREATE INDEX idx_listings_district ON listings(district);
CREATE INDEX idx_listings_score ON listings(classification_score DESC);
CREATE INDEX idx_listings_scraped ON listings(scraped_at DESC);
CREATE INDEX idx_listings_status ON listings(status);
CREATE INDEX idx_listings_source ON listings(source);
CREATE INDEX idx_listings_hash ON listings(content_hash);
CREATE INDEX idx_phones_broker ON phones(is_known_broker);
CREATE INDEX idx_company_district ON company_listings(district);
CREATE INDEX idx_company_status ON company_listings(lease_status);
CREATE INDEX idx_feedback_listing ON classification_feedback(listing_id);
CREATE INDEX idx_feedback_created ON classification_feedback(created_at DESC);
CREATE INDEX idx_spider_logs_name ON spider_logs(spider_name);
```

---

## 14. MODULE 8: WEB UI — SẢN PHẨM CHÍNH CỦA HƯỚNG 2

### 14.1 Chiến lược phân kỳ

Web UI là sản phẩm chính của RealEstork Aggregate. Telegram Bot là extension/notification channel, KHÔNG phải sản phẩm thay thế.

Phân kỳ:
- MVP (tháng 1-2): Telegram Bot only → validate nhu cầu thị trường, thu feedback, build user base. Chi phí hạ tầng = $0.
- Phase 2 (tháng 3+): Web UI launch. Telegram Bot trở thành notification extension của Web (user nhận alert qua Telegram, click link → mở Web xem chi tiết).
- Long-term: Web là trung tâm. Telegram/Zalo là push channel. Mobile app nếu có nhu cầu.

### 14.2 Tham chiếu: Giao diện SànChínhChủ

RealEstork Web cần giao diện tương tự sanchinhchu.vn cho user quen thuộc. Các thành phần chính:

TRANG CHỦ / BROWSE LISTINGS:
- Header: Logo RealEstork + thanh tìm kiếm + Login/Register
- Bộ lọc chính: Loại BĐS (mặt bằng kinh doanh, nhà nguyên căn, ...), Quận/Huyện, Khoảng giá, Diện tích, Mặt tiền (m)
- Badge phân loại: 🟢 Chính chủ | 🟡 Cần xác minh | 🔴 Môi giới (tương tự SànChínhChủ)
- Danh sách listings: card view hoặc list view
  - Mỗi card: Ảnh thumbnail, tiêu đề, địa chỉ, giá, diện tích, score badge, thời gian đăng
  - SĐT chủ nhà: ẨN sau paywall (free user thấy "09xxxxx567", paid user thấy đầy đủ)
- Sort: Mới nhất, Giá cao-thấp, Score cao-thấp
- Pagination

CHI TIẾT LISTING:
- Ảnh gallery (slideshow)
- Thông tin đầy đủ: tiêu đề, mô tả, địa chỉ, giá, diện tích, mặt tiền
- Score badge + breakdown signals (tooltip: "SĐT chỉ 1 tin, mô tả ngắn, ảnh amateur")
- SĐT + tên liên hệ (ẩn sau paywall)
- OSINT summary (paid users): Zalo name, Truecaller result, Google frequency
- Nút: "Gọi ngay" (click-to-call trên mobile), "Lưu tin", "Báo sai"
- Map embed: vị trí trên bản đồ (Google Maps hoặc OpenStreetMap)
- Listings tương tự gần đó

ĐĂNG KÝ / ĐĂNG NHẬP:
- Supabase Auth: email/password, Google OAuth, phone OTP (Zalo nếu được)
- Onboarding: chọn quận quan tâm, khoảng giá, tần suất alert

QUẢN LÝ TÀI KHOẢN:
- Profile: tên, SĐT, email
- Subscription: gói hiện tại, upgrade/downgrade, lịch sử thanh toán
- Filter preferences: quận, giá, score threshold
- Notification settings: Telegram Bot link, email digest on/off
- Lịch sử xem tin: danh sách tin đã xem, đã lưu

TRANG THANH TOÁN:
- Gói subscription: Free / Basic (50k/tháng) / Premium (200k/tháng)
- Payment methods: VNPay, MoMo, thẻ cào, chuyển khoản ngân hàng
- Hoá đơn / lịch sử thanh toán

ADMIN PANEL (cho Chankwan):
- Dashboard: tổng listings, users, MRR, churn rate
- Listings management: approve/reject, manual classify, edit
- User management: view, ban, upgrade tier
- AI model config: switch model, view accuracy metrics
- Spider health: status mỗi spider, last run, error rate
- Classification feedback: review labeled data, adjust weights

### 14.3 Tech Stack Web UI

```
Component       | Tech                     | Lý do
----------------+--------------------------+--------------------------------
Frontend        | Next.js 14+ (React)      | SSR cho SEO, fast, ecosystem
Styling         | Tailwind CSS             | Rapid UI development
UI components   | shadcn/ui                | Professional, accessible
Auth            | Supabase Auth            | Tích hợp sẵn DB
API             | FastAPI (Python)         | Shared với scraper backend
                | hoặc Supabase Edge Func  | 
Map             | Leaflet + OpenStreetMap  | Free, no API key
                | hoặc Google Maps         | Nếu cần accuracy cao hơn
Payment         | VNPay SDK               | Phổ biến nhất VN
                | + MoMo deeplink          | Mobile payment
Hosting         | Self-hosted (WIN2)       | MVP, $0
                | hoặc Vercel (free tier)  | Nếu cần CDN/edge
```

### 14.4 Luồng User chính

```
User mới → Landing page → Browse listings (free, SĐT ẩn, delay 1-2h)
        → Thấy listing hay → Click xem chi tiết → Cần SĐT → Prompt đăng ký
        → Đăng ký (free) → Được 10 tin/ngày có SĐT
        → Muốn nhiều hơn + real-time → Subscribe Basic/Premium
        → Kết nối Telegram Bot → Nhận push alert
        → Click alert → Mở Web chi tiết → Gọi chủ nhà
```

### 14.5 Data Flow: Telegram ↔ Web

Telegram Bot KHÔNG phải sản phẩm riêng biệt. Nó là extension:
- User đăng ký trên Web → link Telegram account → nhận alert qua Telegram
- Alert Telegram chứa deeplink về Web: "Xem chi tiết: realestork.vn/listing/abc123"
- Filter/preferences set trên Web, sync sang Telegram Bot
- Paid features (xem SĐT, OSINT) chỉ available trên Web sau login

### 14.6 SEO Strategy

Mỗi listing có URL unique: `realestork.vn/cho-thue-mat-bang/quan-3/hai-ba-trung-123`
- Meta tags: title, description, price, address cho Google structured data
- Sitemap auto-generated
- Mục tiêu: rank cho "cho thuê mặt bằng quận 3", "mặt bằng kinh doanh Hai Bà Trưng"

---

## 15. CẤU HÌNH & VẬN HÀNH

### 15.1 Config Files

```
config/
├── spiders.yaml          # Spider enable/disable/interval/type
├── scoring.yaml          # Classification signals + weights
├── ai.yaml               # AI model selection + prompts
├── proxy.yaml            # Proxy provider credentials (if needed)
├── schedule.yaml         # Cron/interval schedules
├── alerts.yaml           # Notification channels + filters
└── .env                  # Secrets: Supabase URL, Telegram token,
                          #          Zalo credentials, AI API keys
```

### 15.2 Thêm site mới (Plugin-based)

1. Tạo file `spiders/new_site.py` implement `BaseSpider` interface.
2. Thêm entry trong `config/spiders.yaml`.
3. Restart scheduler.
4. Không cần thay đổi pipeline, classifier, hoặc alert code.

### 15.3 Thêm/sửa classification signals

1. Thêm entry trong `config/scoring.yaml` với name, weight, check logic.
2. Nếu signal cần custom code: thêm function trong `classifiers/signals.py`.
3. Restart scheduler.
4. Không cần redeploy.

### 15.4 Switch AI model

### 15.4 Switch AI Model (4 tầng)

Bạn tự switch trên WIN2, không cần request AI assistant. 3 cách:

CÁCH A — Edit YAML (30 giây):

File: `config/ai.yaml`
```yaml
ai:
  # === TIER SELECTION ===
  # Chọn 1 tier. Uncomment tier muốn dùng, comment tier khác.
  
  # Tier 1: Free — openclaw-zero-token gateway (web chat)
  provider: "zero-token"
  zero_token:
    base_url: "http://localhost:3001/v1"
    model: "deepseek-web/deepseek-chat"       # Free unlimited
    # model: "qwen-web/qwen-max"              # Free tier
    # model: "gemini-web/gemini-pro"           # Free tier
    # model: "kimi-web/kimi-chat"              # Free
    # model: "glm-web/glm-4"                  # Free
    # model: "doubao-web/doubao-seed-2.0"      # Free
  
  # Tier 2: $20/mo — ChatGPT Plus / Gemini Pro via zero-token
  # provider: "zero-token"
  # zero_token:
  #   base_url: "http://localhost:3001/v1"
  #   model: "chatgpt-web/gpt-4o"             # ChatGPT Plus sub
  #   # model: "claude-web/claude-sonnet-4-6"  # Claude Pro sub (check ToS)
  
  # Tier 3: Pay per token — API trực tiếp
  # provider: "anthropic"
  # anthropic:
  #   model: "claude-haiku-4-5-20251001"       # $0.25/1M input tokens
  #   api_key_env: "ANTHROPIC_API_KEY"         # from .env
  
  # Tier 4: Local GPU — Ollama (free, offline backup)
  # provider: "ollama"
  # ollama:
  #   base_url: "http://localhost:11434"
  #   model: "gemma4:e4b"                     # DEFAULT — newest, multimodal
  #   # model: "gemma4:e2b"                   # Lighter
  #   # model: "qwen2.5:7b"                   # Strong Vietnamese
  #   # model: "phi3:mini"                    # Lightest
  #   # model: "llama3.1:8b"                  # General purpose
  #   # model: "gemma3:4b"                    # Fallback
  
  # === COMMON SETTINGS ===
  temperature: 0.1
  max_tokens: 200
  timeout_seconds: 30
  fallback_to_rules_on_error: true  # Nếu AI fail, dùng rules only
```

CÁCH B — CLI Commands (build sẵn trong MVP):
```bash
# Xem model hiện tại + accuracy tuần này
realestork ai status

# Switch nhanh
realestork ai switch zero-token/deepseek-web
realestork ai switch zero-token/chatgpt-web/gpt-4o
realestork ai switch ollama/gemma4:e4b
realestork ai switch anthropic/claude-haiku

# So sánh accuracy 2 models tuần trước
realestork ai compare ollama/gemma4:e4b zero-token/deepseek-web

# List tất cả models available
realestork ai models
```

CÁCH C — Admin Web UI (Phase 2):
Dashboard → Settings → AI Model → dropdown → Save. Kèm bảng accuracy mỗi model.

### 15.5 Chiến lược mở rộng nguồn crawl

```
Phase     | Sites                                    | Lý do
----------+------------------------------------------+---------------------------
MVP       | nhatot, batdongsan, alonhadat             | 80%+ listings HCMC
MVP       | + facebook public groups (facebook-scraper)| Opensource, free
Phase 1.5 | + homedy, muaban                          | Tăng coverage
Phase 2   | + cafeland, dothi, bds123, mogi           | Nearing SànChínhChủ level
Phase 3   | + facebook private groups                 | Devi AI $50/mo hoặc
          |   (khi có revenue)                        | Apify $0.35/1k posts
Phase 4   | + 50-100 site nhỏ                         | Compete with SànChínhChủ
          | + sanchinhchu (subscribe, not crawl)       | Cross-reference data source
```

---

## 16. IMPLEMENTATION ROADMAP

```
Tuần    | Deliverable                                    | Module
--------+------------------------------------------------+---------
Tuần 1  | Project setup: Python env, Supabase schema,    | M7
        | config files structure                          |
        |                                                 |
        | Spider nhatot.com (API mode) — easiest first   | M1
        |                                                 |
        | changedetection.io Docker deploy               | Backup
        | (quick win cho vợ ngay tuần 1)                  |
        |                                                 |
Tuần 2  | Spider batdongsan.com.vn (StealthyFetcher)     | M1
        | Spider alonhadat.com.vn (HTTP)                  | M1
        | Dedup pipeline                                  | M2
        |                                                 |
Tuần 3  | Classification scoring (YAML-driven)            | M2
        | AI classification (Ollama Gemma 4 E4B            | M2
        |   + openclaw-zero-token setup)                   |
        | OSINT phone lookup pipeline                     | M3
        | Phone frequency analysis + Broker DB seed       | M2
        |                                                 |
Tuần 4  | Zalo Bot / OA alert for vợ                      | M4
        | Telegram Bot + Discord Server for product        | M4
        | Agentic orchestrator + scheduling               | M6
        | Integration test, vợ beta test                  | All
        |                                                 |
Tuần 5-6| Feedback loop: /mark commands                   | M2
        | Weekly analysis reports                         | M6
        | Iterate based on vợ feedback                    | All
        | Add homedy + muaban spiders                     | M1
        |                                                 |
Tháng 2 | Validate Hướng 1 revenue improvement            | -
        | Company DB connector investigation              | M5
        |                                                 |
Tháng 3+| If Hướng 1 validated → start Hướng 2 Web UI    | M8
        | Open Telegram bot to beta users                 | M4
```

---

## 17. SUCCESS METRICS

### 17.1 Hướng 1 (tháng 1-3)

- Thời gian phát hiện listing mới: < 15 phút (từ đăng đến vợ nhận alert).
- Classification accuracy: >= 75% (so với feedback thực tế từ vợ).
- Số căn vợ lên/tuần tăng >= 30%.
- Income vợ tăng >= 30% (từ 20 triệu → 26+ triệu/tháng).
- False positive rate (alert chính chủ nhưng thực tế môi giới): < 25%.

### 17.2 Hướng 2 (tháng 3-6)

- 50 beta users đăng ký.
- 10 paid users.
- MRR >= 1 triệu VNĐ (breakeven server cost).
- Retention: 70%+ users active sau 1 tháng.

---

## 18. RISKS & MITIGATIONS

```
Risk                              | Impact    | Mitigation
----------------------------------+-----------+------------------------------------------
Platform block scraper IP         | High      | Start without proxy, add Webshare $7/mo
                                  |           | when blocked. Scrapling StealthyFetcher.
                                  |           | Fallback: changedetection.io manual alerts.
                                  |           |
SànChínhChủ cạnh tranh            | Medium    | Differentiate: real-time alerts, AI,
                                  |           | niche focus HCMC mặt bằng, company data.
                                  |           |
Supabase free tier hết quota      | Medium    | Monitor usage. Upgrade to Pro ($25/mo)
                                  |           | when approaching limits. Have MRR first.
                                  |           |
Company DB extraction detected    | High      | Design carefully with browser-use.
                                  |           | Throttle, simulate human. Phase 2 only.
                                  |           | Worst case: skip this module.
                                  |           |
Vợ không dùng (UX kém)           | High      | Beta test tuần 4. Zalo = familiar UX.
                                  |           | Iterate dựa trên feedback thực tế.
                                  |           | Keep simple: alert + 3 buttons.
                                  |           |
Classification accuracy thấp      | Medium    | Learning loop + AI. Start conservative
                                  |           | (alert nhiều hơn, user filter). Improve
                                  |           | qua weekly feedback analysis.
                                  |           |
Scrapling project discontinued    | Low       | BSD-3 license, can fork. 258k downloads,
                                  |           | active development. Fallback to Scrapy.
                                  |           |
Ollama model quality insufficient | Low       | Switch to Claude API Haiku ($0.25/1M
                                  |           | tokens). Config change only.
```

---

## 19. PHỤ LỤC

### 19.1 Platforms bổ sung nên monitor (Phase 2+)

- Homedy.com: Top-tier, chat built-in, section cho thuê nhà mặt phố HCMC.
- Muaban.net: Từ 2006, tỷ lệ chính chủ cao.
- CafeLand.vn (nhadat.cafeland.vn): 1 triệu+ thành viên.
- Dothi.net, BDS123.vn, Mogi.vn: Secondary.
- Facebook Marketplace: Category "Property for Rent", underutilized.
- Meey Map (meeymap.com), Remap (remaps.vn): Map-based.
- Google Maps Street View: Phát hiện biển "cho thuê" — LƯU Ý: hầu hết SĐT trên biển là môi giới, không phải chính chủ. Giá trị thấp.

### 19.2 Facebook Groups HCMC nên monitor

- "Cho Thuê Mặt Bằng KINH DOANH Tp.HCM"
- "Nhóm Sang Nhượng Quán - Cho Thuê Mặt Bằng TP.HCM"
- "Hội Cần thuê và Cho thuê Cửa Hàng, Mặt Bằng Kinh Doanh"
- "Cho Thuê Mặt Bằng, Nhà Nguyên Căn Kinh Doanh Ăn Uống" (F&B specific)
- Groups theo quận: "Mặt bằng cho thuê Quận 1", "...Quận 3", "...Bình Thạnh"

### 19.3 Xây dựng mạng lưới chủ nhà (cho vợ, chiến lược thực tế)

Vợ không cần social media marketing, không cần xây brand. Vợ là sale admin support.

Cách mở rộng network tự nhiên qua từng giao dịch thành công:
1. Sau mỗi deal chốt: Hỏi chủ nhà "Anh/chị có biết chủ nhà nào khác cần tìm khách thuê không?"
2. Xin SĐT nhà thầu sửa chữa từ chủ nhà (chủ nhà thường sửa trước khi giao) → liên hệ nhà thầu → đề xuất referral 2 chiều: "Anh giới thiệu nhà cần thuê, em giới thiệu khách cần sửa."
3. Tương tự với luật sư/kế toán gặp qua giao dịch thuê → xin liên lạc → referral 2 chiều.
4. Quan hệ bảo vệ/quản lý tòa nhà (bảo vệ, quản lý): biết trước khi khách thuê rời đi. Tết gifts, occasional coffee.
5. KHÔNG cần chủ động cold outreach — leverage từng giao dịch thành công để mở rộng tự nhiên.

### 19.4 Luật & quy định liên quan

- Luật Kinh doanh BĐS 2023 (hiệu lực 01/01/2025): Môi giới phải hoạt động qua công ty đăng ký. Tra cứu ĐKKD (dangkykinhdoanh.gov.vn) để verify.
- Sổ đỏ/Sổ hồng: Không tra cứu online được. Phải yêu cầu bản gốc hoặc gửi yêu cầu VP Đăng ký đất đai.
- Web scraping VN: Chưa có luật cụ thể. Respect ToS từng platform, tránh gây quá tải server.
- Mã định danh điện tử BĐS (Nghị định 357/2025, hiệu lực 01/03/2026): Mỗi BĐS sẽ có mã định danh duy nhất. Khi hệ thống này hoạt động → có thể cross-reference data chính xác hơn.

### 19.5 Opensource alternatives reference

```
Paid tool             | Opensource alternative
----------------------+------------------------------------------
Distill.io            | changedetection.io (self-hosted)
Apify batdongsan      | Scrapling (self-code spiders)
Devi AI (Facebook)    | facebook-scraper (public groups, free)
                      | Phase 2+: Devi $50/mo for private groups
ZenRows               | Scrapling StealthyFetcher + Webshare proxy
LLM API costs         | openclaw-zero-token (web chat gateway, free)
                      | + Ollama local (Gemma 4 E4B on GPU)
page-agent (Alibaba)  | browser-use (Python, 55k stars)
Bitrix24 CRM          | Supabase + custom UI
Meey CRM              | Self-built trên Supabase
Airtable              | NocoDB (self-hosted, Docker)
Scrapy (large scale)  | Crawlee (apify/crawlee, 16k stars) [Phase 4]
```

---

## END OF DOCUMENT

This document serves as the complete spec for implementation via:
- Antigravity Flash & Claude Sonnet (primary coding agents)
- Claude Code in Antigravity Terminal (CLI tasks, debugging)

Each Module (sections 7-14) is an independent coding task. Config files (Section 15) define the contract between modules.

Implementation order: M7 (DB) → M1 (Scrapers, nhatot first) → M2 (Pipeline) → M3 (OSINT) → M4 (Alerts) → M6 (Orchestrator) → M5 (Company DB, Phase 2) → M8 (Web UI, Phase 2).

Key coding instructions for agents:
- Python 3.12+, async/await throughout.
- All config in YAML files under config/ — never hardcode values.
- Type hints on all functions.
- Logging to both file and Supabase spider_logs.
- Error handling: retry with backoff, circuit breaker, alert on failure.
- Tests: pytest, minimum coverage for dedup and classification logic.
- CLI tool `realestork` with subcommands: ai, spider, classify, alert.
- Docker Compose for changedetection.io and openclaw-zero-token.
- .env for secrets (Supabase URL/key, Telegram token, Zalo creds, API keys).
- README.md with setup instructions for CHANKWAN-WIN2.
