# Tiếp tục ngày 9/10/2026 — Supabase hết khoá, nạp lại sổ sách

Cập nhật 2026-10-08. Đọc file này là đủ để làm tiếp, không cần nhớ gì từ phiên trước.

## ⚠️ Đã bỏ so với bản trước

**Bước "tách sang org free mới" KHÔNG LÀM NỮA.** Bản trước có hướng dẫn chuyển project — bỏ hẳn,
đừng làm theo. Lý do: GGEZ đã chuyển dữ liệu về máy nhà, project `gamegoldez erp` tuy còn trên
Supabase nhưng **sinh 0 request trong 24h** (đo 8/10 từ edge logs). Nó không đụng quota nữa, nên
real-estork coi như đứng một mình trong org — không cần tách.

Org free mới đã tạo (`jvpywiptywgghvubyvqc`) giờ bỏ không. Xoá hay để đó đều được.

---

## Chuyện gì đang xảy ra

Org Supabase `chankwan` (free) cạn quota egress 5 GB ngày **4/10 lúc 05:42**. Supabase khoá cả org:
mọi lệnh đọc/ghi qua REST trả `402 exceed_egress_quota`.

Thủ phạm là project `gamegoldez erp` nằm chung org — đốt ~1,4 GB/ngày, gấp ~150 lần real-estork
(~5–10 MB/ngày). Nguyên nhân không phải một lần deploy: code polling nặng có từ 6–12/8, nhưng bot
GGEZ **tắt từ ~24/9 tới 2/10** (Supabase tự pause project vì không hoạt động), bật lại ngày 2/10
rồi đốt ~2 GB trong 36 giờ tới lúc bị khoá.

**Kỳ billing: hoá đơn ngày 9 hàng tháng** → kỳ hiện tại 9/9 → **9/10**. Quota reset ngày 9/10.

## Bot đang chạy thế nào trong lúc bị khoá

Từ 5/10 20:25, bot chạy **chế độ chỉ gửi alert**: crawl + chấm điểm + gửi Telegram bình thường,
tin ghi tạm ra `.db_spool/pending_listings.jsonl`. Tới 8/10 đã có **617 dòng / 392 tin, trong đó
225 tin đã gửi cho vợ** — toàn bộ số này với code cũ đã rơi im lặng.

Chuông "BOT KHÔNG GHI ĐƯỢC DỮ LIỆU" kêu mỗi giờ là **đúng chức năng**, không phải sự cố mới.
Cùng cái chuông đó sẽ tự bắn **"✅ ghi dữ liệu đã hoạt động lại"** khi quota reset — đó là tín hiệu
để bắt đầu các bước dưới.

---

## Việc làm ngày 9/10

### 1. Xác nhận đã hết khoá

```bash
cd /d/Programming/real-estork
./venv/Scripts/python.exe -X utf8 -m cli.main doctor
```

Hoặc chờ Telegram báo "✅ ghi dữ liệu đã hoạt động lại".

### 2. Nạp lại tin đã ghi tạm

```bash
./venv/Scripts/python.exe -X utf8 -m cli.main db-replay --dry-run   # đếm trước
./venv/Scripts/python.exe -X utf8 -m cli.main db-replay             # ghi thật
```

Nạp theo đúng thứ tự file: tin được alert có thêm dòng mang `status='alerted_telegram'`, upsert
khoá trên `(source, source_id)` nên dòng sau đè dòng trước. Xong hết thì file tự đổi tên thành
`.jsonl.done`.

**Đã pre-flight ngày 8/10** — 26 cột của spool đều có trong bảng `listings`, không cột nào thừa,
4 cột bảng thiếu (`id`, `notes`, `created_at`, `updated_at`) đều có default hoặc cho phép rỗng,
không dòng nào sai kiểu dữ liệu. Nạp sẽ chạy.

### 3. Kiểm lại

```bash
./venv/Scripts/python.exe -X utf8 -m cli.main doctor
```

Theo dõi log vài cycle: không còn dòng `ghi DB hỏng`, không còn `exceed_egress_quota`.

### 4. TUYỆT ĐỐI KHÔNG ĐỤNG `.env`

Không có gì đổi về key — chỉ là hết khoá. Sự cố 21h im lặng tháng 5/2026 là do đi copy lại key
rồi dán nhầm `sb_publishable_*` vào chỗ cần `sb_secret_*`. Hiện `.env` đang đúng định dạng.

---

## Việc còn lại sau khi hết khoá

### A. Dọn tin cũ — hạn chót khoảng tháng 2/2027

DB **272 MB / 500 MB** (54%), tăng ~51 MB/tháng (751 tin/ngày × 2,27 KB gồm cả index).
Còn ~4,5 tháng là chạm trần → Supabase chuyển DB sang chỉ-đọc → lặp lại đúng sự cố này.

- 62.038 tin cũ hơn 60 ngày = 94 MB data thô (gần 140 MB tính cả index)
- Bot chỉ cần ~2 tuần gần nhất để chống trùng
- 24.110 tin từng alert — nhóm này nên giữ lâu hơn

Lưu ý: xoá row trong Postgres **không trả chỗ lại cho ổ đĩa ngay**. File giữ nguyên kích thước,
chỗ trống được tái dùng cho row mới. Dọn xong 272 MB sẽ không tụt, nhưng **ngừng tăng** — đủ để
giải quyết vấn đề. `VACUUM FULL` mới thu nhỏ file thật nhưng cần khoá bảng, thường không cần.

### B. Đường veto môi giới không spool

Chỗ xử lý tin bị veto gọi `upsert_listing` rồi bỏ qua kết quả, nên lúc DB chết thì tin bị veto
mất khỏi sổ sách. Không ảnh hưởng alert (tin môi giới vốn không gửi) và không gây gửi lại
(veto tính từ dữ liệu tin, chạy lại vẫn ra veto). Sửa khi rảnh.

### C. Backup của riêng mình — chưa có

Nếu Windows hỏng hôm nay thì mất: `.env` (4 KB, không thay thế được) và dữ liệu DB.
Phần còn lại tự dựng lại được: code ở GitHub `chankwan/real-estork`, môi trường bằng
`setup-full.bat` + `requirements-lock.txt`, kiểm bằng `bot doctor`. Cookie/profile trình duyệt
hiện **không tồn tại** nên không cần lo.

Đã bàn chuyện chuyển DB về máy nhà (Docker hoặc cài thẳng) — **quyết định: ở lại cloud**.
Docker Desktop không cài được trên máy này: Windows 10 IoT Enterprise LTSC build 19044, trong khi
Docker đòi Enterprise/Pro/Education 22H2 build 19045, và ảo hoá đang tắt trong BIOS. LTSC là nhánh
cố định tính năng nên không nâng lên 19045 được nếu không cài lại Windows.

---

## Trạng thái code

Đã sửa trong phiên 5/10, **đang chạy**, nhưng kiểm tra xem đã commit/push chưa:

1. Ghi DB hỏng vẫn gửi Telegram (bỏ dòng `if not saved: return "db_error"`)
2. Spool ra `.db_spool/pending_listings.jsonl` + lệnh `bot db-replay`
3. Smoke test lúc khởi động chịu được 402 → vào chế độ chỉ gửi alert thay vì `sys.exit(1)`
4. Dedup seed từ log khi không đọc được DB (`_seed_source_id_tu_log`, ~4.000 ID)
5. 4 test mới (`TestSoSachHongKhongDuocKeoAlertChetTheo`) — 135/135 pass

Nhờ 2 cái cuối mà **restart được bình thường** kể cả khi đang bị khoá. Luật "đừng restart" của bản
trước đã hết hiệu lực.
