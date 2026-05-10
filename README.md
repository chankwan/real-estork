# RealEstork

Autonomous real estate scraper for HCMC commercial rentals (văn phòng / mặt bằng kinh doanh).  
Scrapes → deduplicates → scores (chính chủ vs môi giới) → sends Telegram alerts.

---

## Cài đặt lần đầu

```
setup-full.bat        # Tạo venv, cài deps, cài browser binaries, chạy health check
```

Sau đó điền tokens vào `.env` (xem `.env.example`).

---

## Lệnh thường dùng

| Lệnh | Mô tả |
|---|---|
| `bot-start` | Khởi động bot **có cửa sổ** (visible) — terminal hoặc double-click `bot-start.bat` |
| `bot-start-headless` | Khởi động bot **headless** (không cửa sổ) — sau khi `bot-stop` mà không muốn reboot |
| `bot-stop` | Dừng bot — terminal hoặc double-click `bot-stop.bat`. Hoạt động cho cả visible + headless |
| `bot doctor` | Health check toàn bộ hệ thống |
| `bot spider run nhatot` | Chạy thử 1 spider cụ thể |
| `bot classify <source-id>` | Xem điểm phân loại chi tiết của 1 tin |
| `bot mark <source-id> owner\|broker` | Ghi feedback kết quả thực tế |
| `bot digest` | Gửi báo cáo tổng kết ngay (không đợi 8:00 AM) |

**Telegram lifecycle notifications** (gửi vào General topic của group):
- 🟢 Bot started + mode (visible / headless / auto-headless)
- 🔴 Bot stopped (Ctrl+C hoặc `bot stop`) + uptime
- ⚠️ Crash detected — instance trước tắt đột ngột (cúp điện, BSOD, OOM, kill -9)

> `bot` = shorthand cho `venv\Scripts\python.exe -m cli.main`. Xem chi tiết: [`docs/cli.md`](docs/cli.md)

---

## Auto-start khi boot

Windows Task Scheduler job "RealEstork Bot" đã được tạo — bot tự khởi động mỗi khi đăng nhập Windows.

Quản lý thủ công:
```
# Xem trạng thái
Get-ScheduledTask -TaskName "RealEstork Bot"

# Tắt auto-start
Disable-ScheduledTask -TaskName "RealEstork Bot"

# Bật lại
Enable-ScheduledTask -TaskName "RealEstork Bot"

# Xóa hẳn
Unregister-ScheduledTask -TaskName "RealEstork Bot" -Confirm:$false
```

---

## Cấu hình

| File | Mục đích |
|---|---|
| `.env` | Secrets (Telegram token, Supabase keys, Chat IDs) |
| `config/scoring.yaml` | Scoring weights, thresholds, district whitelist |
| `config/spiders.yaml` | Enable/disable spiders, URLs, page limits |
| `config/schedule.yaml` | Cron schedules cho từng spider |
| `config/ai.yaml` | AI provider/model selection |

---

## Xem log

```
logs\orchestrator.log    # Log chi tiết tất cả cycles
```
