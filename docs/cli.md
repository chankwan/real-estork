# RealEstork CLI — Hướng dẫn Vận hành

Tất cả lệnh dùng qua `bot.bat` (shorthand) hoặc đầy đủ `venv\Scripts\python.exe -m cli.main`.

```
bot <command>                         # shorthand (dùng bot.bat)
venv\Scripts\python.exe -m cli.main <command>   # đầy đủ
```

---

## 1. Vận hành chính

### `bot-start`
**Lệnh:** `bot-start` (terminal) hoặc double-click `bot-start.bat` (Explorer)
- Khởi động Orchestrator có cửa sổ (visible mode) — thấy log trực tiếp, dừng bằng `Ctrl+C`.
- Source mode: `manual-visible` → Telegram báo "🖥️ Có cửa sổ (terminal)".

### `bot-start-headless`
**Lệnh:** `bot-start-headless` (terminal) hoặc double-click `bot-start-headless.bat` (Explorer)
- Khởi động Orchestrator **headless** (không cửa sổ, dùng `pythonw.exe`).
- Use case: sau khi `bot-stop` mà không muốn reboot máy.
- Source mode: `manual-headless` → Telegram báo "👤 Headless (thủ công)".
- Bot cũng tự khởi động headless khi đăng nhập Windows qua Task Scheduler "RealEstork Bot" → source `auto-headless`, Telegram báo "🤖 Headless (tự động khi đăng nhập)".

### `bot-stop`
**Lệnh:** `bot-stop` (terminal) hoặc double-click `bot-stop.bat` (Explorer)
- Dừng bot đang chạy (đọc PID từ `.orchestrator.lock` và kill process).
- Dùng được cho cả bot chạy headless lẫn visible.
- Gửi Telegram lifecycle "🔴 Bot stopped" trước khi kill.

### Telegram lifecycle notifications
Bot tự động gửi 3 loại sự kiện vào **General topic** của group + admin chat:

| Sự kiện | Khi nào | Format |
|---|---|---|
| 🟢 Started | Mỗi lần bot khởi động | Mode + PID + Time |
| 🔴 Stopped | Ctrl+C hoặc `bot stop` | Uptime + PID |
| ⚠️ Crash detected | Lần start kế tiếp sau crash | PID đã chết + lý do gợi ý |

**Cơ chế phát hiện crash**: lock file (`.orchestrator.lock`) còn lại sau shutdown. Cả 3 cách shutdown êm (Ctrl+C / `bot stop` / atexit) đều xóa lock — còn lock = crash. Tự động khôi phục: lần start kế tiếp tự dọn lock + gửi notify.

### `bot digest`
**Lệnh:** `bot digest`
- Gửi Daily Digest ngay lập tức (không đợi 8:00 AM).

---

## 2. Quản lý Spider

### `bot spider list`
**Lệnh:** `bot spider list`
- Liệt kê danh sách spiders và trạng thái enable/disable.

### `bot spider run <name>`
**Lệnh:** `bot spider run nhatot` / `bot spider run batdongsan` / `bot spider run muaban`
- Chạy thủ công 1 spider — kiểm tra xem site có bị chặn không, hoặc lấy dữ liệu ngay.
- `--dry-run`: in kết quả ra màn hình, không lưu DB.

---

## 3. Cấu hình & Auth

### `bot setup-muaban`
**Lệnh:** `bot setup-muaban`
- Mở trình duyệt để đăng nhập Muaban.net và lưu session cookies.
- Chạy khi cookie muaban hết hạn (bot sẽ cảnh báo qua Telegram).

---

## 4. Phân tích & Phản hồi

### `bot classify <id>`
**Lệnh:** `bot classify nhatot-132087311`
- Xem bảng điểm chi tiết của 1 tin: signal nào fire, tại sao được/không được alert.
- Dùng để tinh chỉnh weights trong `config/scoring.yaml`.

### `bot mark <id> <status>`
**Lệnh:** `bot mark batdongsan-45309426 owner`
- Ghi feedback kết quả thực tế sau khi kiểm tra tin.
- Status hợp lệ: `called` / `owner` / `broker` / `archived`

---

## 5. Quản lý AI

### `bot ai status`
- Xem model AI đang dùng và cấu hình hiện tại.

### `bot ai models`
- Liệt kê các model khả dụng (local Ollama, Gemini web, API).

### `bot ai switch <provider/model>`
- Chuyển đổi model AI.

---

## 6. Health Check

### `bot doctor`
**Lệnh:** `bot doctor`
- Pre-flight check 8 hạng mục: Python, packages, browser binaries, .env, config files, Supabase, Telegram, lock file.
- Chạy sau mỗi lần cài đặt mới hoặc khi bot hoạt động bất thường.

---

## Ghi chú Vận hành

- Log chi tiết: `logs\orchestrator.log`
- Nếu bot không start được sau crash: tự xử lý từ phiên bản hiện tại (self-healing lock).
- Mọi cấu hình thay đổi không cần restart bot nếu chỉnh `config/*.yaml` — scheduler tự reload.
