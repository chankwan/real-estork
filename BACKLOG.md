# Backlog

Tasks chưa làm — sắp xếp theo trạng thái. Item nào unblock thì kéo xuống commit thẳng.

---

## ⏳ Chờ input

_(không có item chờ)_

---

## 🐞 Bug đã biết, chưa fix

### Pre-existing test failure: `test_known_broker_phone_crushes_score`
- File: `tests/test_pipeline.py`
- Triệu chứng: signal `is_known_broker` không fire khi phone_stats có `is_known_broker=True`. Score=68 thay vì <40 như expected.
- Phát hiện: session 14 khi chạy full test suite. Pre-existing trước commit 077337f.
- Mức độ: thấp — chỉ ảnh hưởng test, không ảnh hưởng production logic (vì known_broker phone list hiện rất nhỏ).

### ~~Bot bị silent crash khi browser context die~~ ✅ Fixed session 16 (2026-05-26)
- Xem `orchestrator/agent.py` → `start()` — `clean_exit` flag + `_atexit_cleanup` + `except Exception` crash handler.
