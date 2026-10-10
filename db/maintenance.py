"""Dọn tin cũ + backup cấu hình, chạy theo lịch hàng tuần.

VÌ SAO CẦN: Supabase free cho 500 MB database. Bot thêm ~750 tin/ngày, mỗi tin
~2,27 KB tính cả index → ~51 MB/tháng. Chạm trần thì Supabase chuyển DB sang
chỉ-đọc, tức lặp lại đúng sự cố 04-10/10/2026 (bot sống nhưng không ghi được).
Dọn tay thì sớm muộn sẽ quên, mà lúc quên đúng là lúc hỏng.

THỨ TỰ BẮT BUỘC — xuất → kiểm → đẩy lên Drive → kiểm lần nữa → MỚI xoá.
Hỏng ở bất kỳ bước nào thì dữ liệu vẫn còn nguyên trong DB. Bên GGEZ từng mất
dữ liệu vì nối thẳng lệnh xuất vào lệnh nạp: lệnh xuất chết giữa chừng mà lệnh
kia vẫn commit.

GIỮ LẠI, KHÔNG XOÁ:
  - Mọi tin trong `SO_NGAY_GIU` ngày gần nhất — lớp chống trùng cần ~2 tuần,
    60 ngày là dư an toàn.
  - Mọi tin ĐÃ TỪNG GỬI cho vợ, bất kể cũ cỡ nào. Lớp "đã gửi thì thôi" đọc
    cột này; xoá đi là tin cũ được đẩy tay (mang dấu giờ mới) sẽ gửi lại.
  - Mọi tin có phiếu 👍/👎. Khoá ngoại để NO ACTION nên xoá sẽ bị Postgres từ
    chối cả lệnh, không chỉ dòng đó.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from db.client import SupabaseDB

SO_NGAY_GIU = 60
SO_BAN_LUU_TREN_DRIVE = 26  # ~6 tháng chạy hàng tuần
TRANG = 1000


class LoiBaoTri(Exception):
    """Dừng giữa chừng. Dữ liệu trong DB còn nguyên."""


def _thu_muc_drive() -> Path:
    """Đọc đường dẫn Drive từ .env.

    Cố ý KHÔNG đặt giá trị mặc định: đường dẫn Drive khác nhau giữa các máy,
    hardcode vào git là lần sau chạy máy khác sẽ ghi nhầm chỗ hoặc im lặng
    không ghi. Thiếu thì dừng hẳn và nói rõ, hơn là backup không tới nơi.
    """
    raw = os.environ.get("BACKUP_DRIVE_DIR", "").strip().strip('"')
    if not raw:
        raise LoiBaoTri(
            "Thiếu BACKUP_DRIVE_DIR trong .env. Thêm dòng như:\n"
            '  BACKUP_DRIVE_DIR=G:\\My Drive\\real-estork\\bot-backup'
        )
    p = Path(raw)
    if not p.is_dir():
        raise LoiBaoTri(
            f"BACKUP_DRIVE_DIR trỏ tới chỗ không tồn tại: {p}\n"
            "Google Drive chưa đồng bộ xong, hoặc chưa đăng nhập Windows?"
        )
    return p


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for khoi in iter(lambda: f.read(1024 * 1024), b""):
            h.update(khoi)
    return h.hexdigest()


def _chuyen_vao_drive(nguon: Path, thu_muc_dich: Path) -> Path:
    """Chép lên Drive an toàn: ghi tên tạm rồi đổi tên trong CÙNG thư mục.

    Đổi tên cùng thư mục là thao tác nguyên khối, nên Drive không bao giờ bắt
    gặp file đang ghi dở dưới tên thật rồi đồng bộ một nửa lên mây.
    """
    thu_muc_dich.mkdir(parents=True, exist_ok=True)
    tam = thu_muc_dich / (nguon.name + ".part")
    dich = thu_muc_dich / nguon.name
    shutil.copy2(nguon, tam)
    tam.replace(dich)

    if _sha256(nguon) != _sha256(dich):
        dich.unlink(missing_ok=True)
        raise LoiBaoTri(f"Bản trên Drive lệch so với bản gốc: {dich}")
    return dich


def _lay_id_co_phieu(db: SupabaseDB) -> list[str]:
    """ID các tin đang có phiếu 👍/👎 — không được xoá (vướng khoá ngoại)."""
    r = db.client.table("classification_feedback").select("listing_id").execute()
    return sorted({row["listing_id"] for row in (r.data or []) if row.get("listing_id")})


def _dem_tin_can_don(db: SupabaseDB, moc: str, bo_qua: list[str]) -> int:
    """Đếm bằng cách lấy id theo trang, KHÔNG dùng count="exact".

    count="exact" bắt Postgres đếm hết mọi dòng khớp → chạm trần thời gian
    của Supabase (57014 statement timeout). Lấy riêng cột id thì nhẹ hơn
    nhiều, và số dòng cần dọn mỗi tuần vốn chỉ vài nghìn.

    Sắp theo `scraped_at` chứ KHÔNG theo `id`: có `idx_listings_scraped` nên
    điều kiện khoảng thời gian chạy thẳng trên index. Sắp theo `id` thì
    Postgres đi theo khoá chính và lọc từng dòng một — đo 10/10: 13.298 ms so
    với 1.912 ms, tức quá ngưỡng và cả lệnh bị huỷ. Phân trang theo offset vẫn
    đúng vì tin cũ hơn 60 ngày không còn bị ghi đè.
    """
    n = 0
    dau = 0
    while True:
        q = (
            db.client.table("listings")
            .select("id")
            .lt("scraped_at", moc)
            .not_.like("status", "alerted%")
            .order("scraped_at")
            .range(dau, dau + TRANG - 1)
        )
        if bo_qua:
            q = q.not_.in_("id", bo_qua)
        lo = q.execute().data or []
        n += len(lo)
        dau += len(lo)
        if len(lo) < TRANG:
            return n


def _xuat(db: SupabaseDB, moc: str, bo_qua: list[str], ra: Path) -> int:
    ra.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with ra.open("w", encoding="utf-8") as f:
        dau = 0
        while True:
            q = (
                db.client.table("listings")
                .select("*")
                .lt("scraped_at", moc)
                .not_.like("status", "alerted%")
                .order("scraped_at")
                .range(dau, dau + TRANG - 1)
            )
            if bo_qua:
                q = q.not_.in_("id", bo_qua)
            lo = q.execute().data or []
            if not lo:
                break
            for row in lo:
                dong = json.dumps(row, ensure_ascii=False, default=str)
                # json.dumps để nguyên U+2028/U+2029 nhưng splitlines() của
                # Python cắt dòng ở đó → bản ghi bị xé đôi khi đọc lại.
                dong = dong.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
                f.write(dong + "\n")
            n += len(lo)
            dau += len(lo)
            if len(lo) < TRANG:
                break
    return n


def _nen_va_kiem(nguon: Path, so_dong_mong_doi: int) -> Path:
    """Nén rồi GIẢI NÉN ĐỌC LẠI để chắc file dùng được.

    Backup chưa từng mở lại không phải backup, chỉ là file làm mình yên tâm.
    """
    nen = nguon.with_suffix(nguon.suffix + ".gz")
    with nguon.open("rb") as f, gzip.open(nen, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g, 1024 * 1024)

    dem = 0
    with gzip.open(nen, "rt", encoding="utf-8") as g:
        for dong in g:
            if dong.strip():
                json.loads(dong)  # hỏng thì ném ra ngoài, dừng cả quy trình
                dem += 1
    if dem != so_dong_mong_doi:
        raise LoiBaoTri(f"File nén đọc lại ra {dem} dòng, chờ {so_dong_mong_doi}")
    return nen


def _xoa(db: SupabaseDB, moc: str, bo_qua: list[str]) -> int:
    """Xoá thật. returning=minimal để khỏi tải ngược mấy nghìn row vừa xoá."""
    from postgrest.types import CountMethod, ReturnMethod

    q = (
        db.client.table("listings")
        .delete(count=CountMethod.exact, returning=ReturnMethod.minimal)
        .lt("scraped_at", moc)
        .not_.like("status", "alerted%")
    )
    if bo_qua:
        q = q.not_.in_("id", bo_qua)
    return q.execute().count or 0


def _backup_env(thu_muc_drive: Path) -> str:
    """Chép .env lên Drive, chỉ khi nội dung đã đổi so với bản mới nhất."""
    env = Path(".env")
    if not env.is_file():
        return "không thấy .env — bỏ qua"

    dich = thu_muc_drive / "configuration"
    dich.mkdir(parents=True, exist_ok=True)
    mdd = _sha256(env)
    for cu in sorted(dich.glob("dotenv-*.txt"), reverse=True):
        if _sha256(cu) == mdd:
            return f"không đổi từ {cu.name}"
        break

    moi = dich / f"dotenv-{datetime.now().strftime('%Y-%m-%d')}.txt"
    tam = moi.with_suffix(".txt.part")
    shutil.copy2(env, tam)
    tam.replace(moi)
    if _sha256(moi) != mdd:
        moi.unlink(missing_ok=True)
        raise LoiBaoTri("Bản .env trên Drive lệch so với bản gốc")
    return f"đã cập nhật → {moi.name}"


def _don_ban_cu(thu_muc: Path, giu: int) -> int:
    ban = sorted(thu_muc.glob("listings-expired-*.jsonl.gz"), reverse=True)
    xoa = 0
    for cu in ban[giu:]:
        cu.unlink(missing_ok=True)
        xoa += 1
    return xoa


def _don_rac_duoi_may(thu_muc_tam: Path) -> int:
    """Xoá file tạm dưới máy: bản chưa nén, và spool đã nạp xong."""
    xoa = 0
    for p in list(thu_muc_tam.glob("*.jsonl")) + list(
        Path(".db_spool").glob("*.jsonl.done")
    ):
        try:
            p.unlink()
            xoa += 1
        except OSError as e:
            logger.warning(f"[baotri] không xoá được {p}: {e}")
    return xoa


def chay(chi_thu: bool = False) -> dict:
    """Chạy một lượt bảo trì. Ném LoiBaoTri nếu phải dừng giữa chừng."""
    drive = _thu_muc_drive()
    db = SupabaseDB()

    # Mốc tuyệt đối, chốt một lần: nếu để "60 ngày" trôi theo đồng hồ thì
    # lệnh xuất và lệnh xoá sẽ nhìn hai tập tin hơi khác nhau.
    moc = (datetime.now(timezone.utc) - timedelta(days=SO_NGAY_GIU)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    bo_qua = _lay_id_co_phieu(db)
    can_don = _dem_tin_can_don(db, moc, bo_qua)
    bao_cao = {"moc": moc[:10], "can_don": can_don, "da_xoa": 0, "ban_luu": None}

    if chi_thu:
        bao_cao["env"] = "(chỉ thử — không đụng gì)"
        return bao_cao

    if can_don:
        tam = Path(".db_backup")
        ra = tam / f"listings-expired-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        n = _xuat(db, moc, bo_qua, ra)
        if n != can_don:
            raise LoiBaoTri(f"Xuất ra {n} dòng nhưng đếm được {can_don} — chưa xoá gì")

        nen = _nen_va_kiem(ra, n)
        tren_drive = _chuyen_vao_drive(nen, drive / "database-news-expired")

        # Tới đây bản sao đã nằm trên Drive và đã đối chiếu mã băm. Giờ mới xoá.
        da_xoa = _xoa(db, moc, bo_qua)
        bao_cao["da_xoa"] = da_xoa
        bao_cao["ban_luu"] = tren_drive.name
        if da_xoa != n:
            logger.warning(
                f"[baotri] xoá {da_xoa} nhưng xuất {n} — chênh lệch do tin mới "
                f"rơi qua mốc trong lúc chạy, bản lưu vẫn đủ"
            )
        ra.unlink(missing_ok=True)
        nen.unlink(missing_ok=True)
        bao_cao["don_ban_cu"] = _don_ban_cu(drive / "database-news-expired", SO_BAN_LUU_TREN_DRIVE)

    bao_cao["env"] = _backup_env(drive)
    bao_cao["rac_da_don"] = _don_rac_duoi_may(Path(".db_backup"))
    return bao_cao
