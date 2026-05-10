# Backlog

Tasks chưa làm — sắp xếp theo trạng thái. Item nào unblock thì kéo xuống commit thẳng.

---

## ⏳ Chờ input

### Mở rộng muaban URL category

**Trigger**: 3 tin nhà cho thuê bị sót (session 14, 2026-05-10):
- `muaban-70852975` — nhà hẻm Bình Thạnh
- `muaban-70856856` — nhà mặt tiền Phú Nhuận
- `muaban-70853623` — nhà mặt tiền Tân Phú

**Root cause**: Spider muaban chỉ crawl 1 URL `cho-thue-van-phong-mat-bang-ho-chi-minh` (`config/spiders.yaml:54`). 3 tin trên thuộc category `/bat-dong-san/cho-thue-nha-...` (nhà cho thuê — khác văn phòng/mặt bằng kinh doanh).

**Blocker**: Đợi vợ gửi danh sách URL category muốn crawl thêm (vd `cho-thue-nha-mat-tien-ho-chi-minh`, `cho-thue-nha-hem-ho-chi-minh`, `cho-thue-nha-nguyen-can-ho-chi-minh`).

**Cần làm khi unblock**:
1. Refactor `config/spiders.yaml` muaban: `url:` (single) → `urls:` (list) — copy pattern từ batdongsan (`spiders.yaml:32-38`).
2. Refactor `spiders/muaban.py` để loop qua nhiều URL — copy pattern từ `spiders/batdongsan.py`.
3. Test 1 URL mới trước: `bot spider run muaban`.
4. Tune `dedup_stop_ratio` nếu volume tăng nhiều.

**Ước lượng**: 1-2h sau khi nhận danh sách URL.

---

## 🐞 Bug đã biết, chưa fix

### Pre-existing test failure: `test_known_broker_phone_crushes_score`
- File: `tests/test_pipeline.py`
- Triệu chứng: signal `is_known_broker` không fire khi phone_stats có `is_known_broker=True`. Score=68 thay vì <40 như expected.
- Phát hiện: session 14 khi chạy full test suite. Pre-existing trước commit 077337f.
- Mức độ: thấp — chỉ ảnh hưởng test, không ảnh hưởng production logic (vì known_broker phone list hiện rất nhỏ).

### Bot bị silent crash khi browser context die
- Triệu chứng: pythonw exit không log shutdown, không gửi Telegram "stopped". Lock file bị atexit dọn → crash detection ở next start MISS.
- Workaround đề xuất: thêm `sys.excepthook` mark "crash mode" trong lock trước khi atexit chạy, hoặc unhandled exception → notify trước khi crash.
- Mức độ: trung bình — đã có thiết kế trong session 14 nhưng không scope.
