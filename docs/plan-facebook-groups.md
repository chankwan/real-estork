# Plan — Crawl 9 group Facebook đóng (passive capture)

> **Bước 0 khi approve:** move file này từ `.claude/plans/` sang docs tầng project — `D:\Programming\real-estork\docs\plan-facebook-groups.md` (dễ tìm, đi cùng codebase qua git).

## Context — vì sao làm cái này

Bot RealEstork hiện crawl 3 portal (nhatot, alonhadat/batdongsan, muaban). Nhiều tin chính chủ cho thuê mặt bằng/văn phòng ở HCMC **chỉ xuất hiện trong các group Facebook đóng**, không lên portal. Đây là nguồn tin chất lượng cao nhưng đang bị bỏ sót hoàn toàn.

**Sự thật phải nói thẳng trước khi làm:** group đóng nằm sau "tường đăng nhập" của FB — không có API công khai, không có đường "no-login". Bắt buộc phải có **1 account là thành viên** của group. Apify (dịch vụ managed) **chỉ crawl được group public**, nên hướng "thuê ngoài, zero-maintenance" không khả thi cho group đóng. Năm 2026 Meta bắt automation rất gắt (AI chấm hành vi, đội 100+ người chống scraping, chấm điểm IP, phát hiện account-linkage). Vì vậy **không thể đạt cùng lúc: ổn định + rẻ + zero-bảo-trì + zero-thủ-công**. Một đòn bẩy phải nhường.

**Quyết định đã chốt (anh chọn):** nhường ở "tự bảo trì parser khi FB đổi giao diện" và "1 PC always-on" — đổi lại được **ban risk thấp nhất + gần như free**, vì bot không tự động đăng nhập, không bơm traffic lạ; nó chỉ **đọc thụ động** chính màn hình FB mà một người thật đang mở.

**Kết quả mong muốn:** post chính chủ từ 9 group đóng chảy vào đúng pipeline sẵn có (dedup → chấm điểm chính chủ/môi giới → alert Telegram cho vợ), không cần thao tác tay hằng ngày.

---

## Cách hoạt động (góc nhìn vận hành)

```
[PC2 always-on]
  Chrome — PROFILE RIÊNG "RealEstork Bot" (tách hẳn profile cá nhân)
    login sẵn 1 via FB, là member 9 group
    └─ Tampermonkey chạy userscript "RealEstork FB capture"
         ├─ tự cuộn chậm trang group (giả người đọc)
         ├─ đọc các post hiện trên màn hình → trích: text, tên người đăng,
         │   link người đăng, link post, thời gian, post-id
         ├─ đẩy (POST) các post mới về bot qua http://localhost  (mạng nội bộ, không ra ngoài)
         └─ sau N giây → tự chuyển sang group kế tiếp (xoay vòng 9 group)
                            ↓
[Bot RealEstork]  cổng nhận nội bộ (localhost)  →  hàng đợi
                            ↓  (mỗi nhịp lịch)
        dedup (bỏ post đã thấy)  →  chấm điểm chính chủ  →  alert Telegram (topic FB riêng)
```

**Điểm cốt lõi:** đây là **đẩy (push)**, khác 3 spider hiện tại là **kéo (pull)**. Bot không tự vào FB; nó **nhận** dữ liệu từ userscript. Nhờ vậy mọi hành vi "giống bot" biến mất khỏi phía FB.

---

## Thành phần sẽ xây

| # | Thành phần | Việc nó làm | Độ phức tạp |
|---|---|---|---|
| 1 | **Userscript (Tampermonkey)** | Chạy trên `facebook.com/groups/*`: tự cuộn, bắt post, xoay vòng 9 group, POST về bot. Có chống trùng tại chỗ (nhớ post-id đã gửi) + cuộn ngẫu nhiên hoá để giống người. | Trung bình |
| 2 | **Cổng nhận nội bộ trong bot** | Mở 1 listener localhost nhỏ, nhận JSON post từ userscript, ghi vào hàng đợi. Có shared-secret token để không ai khác POST bừa. | Thấp |
| 3 | **"Spider" facebook_groups (kiểu drain)** | Không kéo gì cả — mỗi nhịp lịch nó **rút hàng đợi**, biến mỗi post thành 1 listing chuẩn (RawListing), parse SĐT/quận/giá/diện tích từ text tự do. | Trung bình |
| 4 | **Cấu hình chấm điểm riêng cho FB** | Post FB không có field "account_type", "số tin đang đăng"... như portal → cần bộ tín hiệu **dựa trên text** + tái dùng tín hiệu SĐT-cross-platform (rất mạnh). | Thấp–Trung bình |
| 5 | **Định tuyến alert** | Thêm 1 topic Telegram riêng cho nguồn `facebook_groups`, cách hiển thị SĐT phù hợp (FB thường để SĐT thẳng trong text). | Thấp |

Tất cả nối vào pipeline qua field `source = "facebook_groups"` — dedup, chấm điểm, lưu DB, gửi Telegram đều tái dùng nguyên cơ chế hiện có.

---

## Chống ban & vận hành (runbook cho via 50k)

Via 50k là tài khoản low-trust → coi như **tiêu hao**. Cách giữ nó sống lâu nhất chính là kiến trúc passive này. Nguyên tắc:

- **Profile Chrome riêng cho bot:** tạo profile mới tên "RealEstork Bot" (Chrome → menu profile → Add → đặt tên), **tách hoàn toàn** khỏi profile cá nhân anh dùng hằng ngày. Chỉ cài Tampermonkey + login via trong profile này. Lợi: (1) cookies/lịch sử/fingerprint của via không trộn với tài khoản FB cá nhân → giảm rủi ro FB liên kết account & vạ lây ban; (2) tab always-on không phá phiên làm việc thường của anh; (3) gỡ bỏ/đổi via chỉ cần xoá profile, không đụng dữ liệu cá nhân.
- **Login 1 lần, để yên:** trong profile "RealEstork Bot", đăng nhập via, **không** để bot đụng vào mật khẩu/login. Khi FB thỉnh thoảng đăng xuất hoặc đòi xác minh → anh login lại tay (việc thủ công duy nhất, ~vài tuần/lần).
- **IP nhà của anh** (residential) — điểm tin cậy cao hơn hẳn IP datacenter mà các tool thuê ngoài dùng. Không cần proxy.
- **Tần suất thấp, giống người:** xoay vòng 9 group, mỗi group cuộn ~30–60s bắt ~20–40 post mới nhất rồi nghỉ ngẫu nhiên; vòng đầy đủ ~mỗi 2–4 giờ. Không cào sâu, không cào liên tục.
- **Warm-up trước khi cào:** sau khi mua via, để 1–2 tuần dùng như người thật (đọc, like lai rai, join 9 group **giãn ra vài ngày**, đợi admin duyệt) **rồi** mới bật userscript. Bật capture ngay trên via mới = cờ đỏ.
- **Dự phòng:** mua sẵn **2–3 via**, warm song song. Khi 1 via chết, swap sang via khác — chi phí ~100–150k, không gián đoạn.

→ Việc thủ công thực tế: **mua + warm via ban đầu** (1 lần), và **login lại khi bị đăng xuất** (thưa). Hằng ngày = 0 thao tác.

---

## Chi phí

| Khoản | Chi phí |
|---|---|
| Tampermonkey | Free |
| Cổng nhận + spider + scoring (mình tự build) | Free (chạy trong bot sẵn có) |
| Điện PC2 always-on | Không đáng kể (đã chạy bot rồi) |
| Via Facebook | ~50k/via × 2–3 via dự phòng = ~100–150k, mua lại khi chết |
| **Tổng định kỳ** | **≈ 0–50k/tháng** — dưới xa mức $5 anh đặt |

---

## Chấm điểm chính chủ trên post FB (khác portal)

Post FB **không có** các tín hiệu portal (`account_type`, số tin đang đăng, badge môi giới). Bù lại có tín hiệu text + 1 tín hiệu tái dùng cực mạnh:

- **SĐT trong text** → chính chủ FB hay để SĐT thẳng. Parse SĐT từ text (tái dùng logic làm sạch SĐT của spider hiện có).
- **SĐT trùng môi giới đã biết (cross-platform)** → tái dùng nguyên `phone_count_all_platforms` / `phone_is_known_broker`: nếu SĐT trong post FB đã xuất hiện như môi giới ở portal khác → trừ điểm mạnh. **Đây là điểm cộng lớn của việc gộp chung pipeline.**
- **Ngôn ngữ chính chủ** ("chính chủ", "nhà mình", "cần cho thuê") vs **từ khoá môi giới** ("em có nhiều căn", "quỹ hàng", "LH em"...).
- **Spam emoji / superlatives** → giống tín hiệu môi giới đã có.
- **Một account đăng nhiều mặt bằng trong 1 vòng quét** → đếm `same_session_account_count` (tái dùng).
- **Quận + giá + diện tích** → parse từ text tự do (regex), rồi đưa qua `_normalize_district` + bộ lọc whitelist/price-override sẵn có để quyết định có alert vợ không.

→ Tạo bộ cấu hình điểm riêng cho `facebook_groups`, chỉ gồm tín hiệu khả dụng; tránh để tín hiệu portal trống làm lệch điểm.

---

## Rủi ro & giới hạn (nói thẳng)

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| FB đổi giao diện → userscript bắt sai/trống | Trung bình (đây là "đòn bẩy đã nhường") | Gom toàn bộ selector vào 1 chỗ dễ sửa; bot log "nhận 0 post X giờ" để mình biết mà vá sớm |
| Via bị ban/đăng xuất | Trung bình (via rẻ) | Coi via là tiêu hao, giữ 2–3 dự phòng đã warm; passive + IP nhà giúp sống lâu hơn |
| Post free-text → parse quận/giá sai | Trung bình | Parse "best-effort"; thiếu quận thì xếp `can_xac_minh` thay vì bỏ; vẫn gửi alert nếu đủ tín hiệu chính chủ |
| PC2 phải always-on + tab FB mở | Thấp (đã always-on cho bot) | Userscript tự xoay group, không cần anh đụng |
| ToS Facebook | — | Chấp nhận; passive đọc bằng tài khoản thật là vùng xám nhẹ nhất, không bơm traffic tự động |

**Giới hạn rõ:** chỉ bắt được post **hiện ra khi cuộn** (post mới nhất), không cào lịch sử sâu. Với mục tiêu "tin mới ≤48h" thì đủ.

---

## Verification (kiểm tra end-to-end khi build xong)

1. **Cổng nhận sống:** khởi động bot → log báo `FB receiver listening on localhost:<port>`.
2. **Userscript bắt được:** cài Tampermonkey + script trên Chrome đã login via → mở 1 group → console của script log `captured N posts`, và mỗi POST trả `200 OK`.
3. **Bot nhận + dedup:** log bot `facebook_groups: received N, M new sau dedup`.
4. **Alert dương tính:** dựng 1 post test có SĐT + "chính chủ" + quận trong whitelist + giá ≥ ngưỡng → kỳ vọng **1 alert Telegram** vào topic FB, hiển thị SĐT + link post.
5. **Alert âm tính:** post môi giới (nhiều mặt bằng / từ khoá môi giới / SĐT trùng broker đã biết) → **không** alert.
6. **Xoay vòng:** để chạy 1 vòng đầy đủ → log cho thấy lần lượt 9 group được ghé, không kẹt ở 1 group.

---

## Technical appendix (chỉ để lúc execute — không phải để review)

*Điểm tích hợp đã xác minh trong codebase; liệt kê file để thực thi, không kèm code.*

- **Userscript mới** (ngoài repo, cài qua Tampermonkey) — sẽ lưu bản nguồn trong repo, vd `extension/realestork-fb-capture.user.js`.
- **Cổng nhận + hàng đợi:** thêm vào `orchestrator/agent.py` (listener localhost nhỏ, có token; ghi vào queue). Cân nhắc aiohttp/`http.server` để khỏi thêm dependency nặng.
- **Spider drain:** `spiders/facebook_groups.py` (kế thừa `BaseSpider`, `fetch_listings` = rút hàng đợi thay vì kéo web; parse SĐT/quận/giá từ text). Đăng ký trong `spiders/__init__.py` (`SPIDER_REGISTRY`). Cấu hình trong `config/spiders.yaml`.
- **Cycle + lịch:** `run_facebook_groups_cycle()` trong `orchestrator/agent.py` (copy mẫu `run_muaban_cycle`), đăng ký ở `setup_scheduler()` + `config/schedule.yaml`.
- **Chấm điểm riêng:** thêm `"facebook_groups"` vào `PER_SOURCE_CONFIGS` (`pipeline/classifier.py`) + tạo `config/scoring_facebook_groups.yaml`. Tín hiệu text mới (nếu cần) thêm vào `pipeline/signals.py` đúng contract `check_<name>(ctx) -> bool|float` + map vào `SIGNAL_FUNCTIONS`.
- **Định tuyến Telegram:** thêm `"facebook_groups"` vào topic_mapping (`orchestrator/agent.py`) + nhánh hiển thị SĐT trong `notifications/telegram.py`.
- **RawListing:** field hiện có đã đủ (`source`, `source_id`, `source_url`, `title`/`description`, `district`, `price_*`, `phone`, `contact_name`, `posted_at`, `same_session_account_count`); không cần thêm field.

---

### Thứ tự thực thi đề xuất (từng bước, chờ duyệt giữa các bước lớn)
1. Cổng nhận nội bộ + spider drain + đăng ký nguồn (bot nhận được post giả lập POST bằng tay).
2. Userscript capture + auto-scroll + xoay vòng 9 group.
3. Bộ chấm điểm `scoring_facebook_groups.yaml` + tín hiệu text.
4. Định tuyến Telegram (topic FB) + verify end-to-end.
5. Runbook warm via + go-live thật.
