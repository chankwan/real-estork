"""Đo: muaban có tự đẩy hàng loạt tin lúc giao ngày không?

Câu hỏi cần trả lời — dấu thời gian trên tin muaban nhảy về 00:0X là do
NỀN TẢNG tự đẩy hàng loạt, hay do CHỦ NHÀ bấm làm mới tin?

Chuyện này quan trọng vì nó quyết định "tin vừa được đẩy" có phải tín hiệu
đáng cộng điểm không. Với mặt bằng cho thuê, chủ lấy lại được mặt bằng thì
đẩy tin cũ lên tìm khách mới — nếu tách được nhóm đó ra thì đó là tín hiệu
tốt nhất mình có. Còn nếu 100% là hệ thống tự đẩy thì nó vô nghĩa.

Vì sao không trả lời được từ DB của bot: mỗi tin chỉ có ĐÚNG MỘT dấu thời
gian, ghi lúc bot thấy lần đầu; lớp chống trùng khiến tin đã thấy không bao
giờ được ghi lại. Không có trước/sau của cùng một tin thì không kết luận được.

Cách đo — chụp cùng một tập tin hai lần, cách nhau qua nửa đêm:

    truoc   (~23:30)  ghi lại id -> dấu thời gian
    sau     (~00:30)  đọc lại ĐÚNG những id đó, so xem có nhảy không

Một chỗ dễ sai mà thiết kế này phải né: tin được đẩy sẽ NHẢY LÊN ĐẦU danh
sách. Đọc lại đúng số trang cũ thì không còn thấy nó nữa. Nên lượt "sau"
quét từ trang 1 tới _TRANG_QUET_LAI rồi mới tra theo id.

Lấy mẫu ở CẢ HAI tầng để đối chứng:
    trang 1      — tin vừa được đẩy, đang nổi
    trang sâu    — tin nằm im lâu ngày
Nếu chỉ tầng sâu bị nhảy hàng loạt thì đó là dọn dẹp định kỳ của nền tảng.
Nếu cả hai tầng đều lác đác vài tin nhảy thì đó là người thật bấm.

Chạy:
    python -m tools.do_day_tin_muaban truoc     # lượt trước nửa đêm
    python -m tools.do_day_tin_muaban sau       # lượt sau nửa đêm
    python -m tools.do_day_tin_muaban bao-cao   # đọc kết quả đã gom
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from curl_cffi import requests

BASE = (
    "https://muaban.net/bat-dong-san/cho-thue-nha-ho-chi-minh"
    "?sort=1&price=15000000-100000000"
)
HEADERS = {"Referer": "https://www.google.com/"}
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)
VN = timezone(timedelta(hours=7))

# Trang lấy mẫu ở lượt "truoc": 1 = tầng nổi, còn lại = tầng nằm im.
_TRANG_LAY_MAU = [1, 5, 10, 15, 20, 25, 30]
# Lượt "sau" quét rộng hơn hẳn: tin bị đẩy sẽ nhảy lên đầu, tin không bị đẩy
# thì chìm xuống vài trang. Quét tới đây để bắt được cả hai chiều.
_TRANG_QUET_LAI = 40
# Mang chap thi thu lai, dung de mot request hong giet ca dem do (su co 18/09).
_SO_LAN_THU = 3
_TRANG_HONG: list[int] = []

THU_MUC = Path(__file__).resolve().parent.parent / "logs" / "muaban_day_tin"


def _lay_trang(trang: int) -> list[dict]:
    """Đọc một trang. Hỏng thì trả về [] — KHÔNG ném lỗi lên trên.

    Đêm 18/09 mất trắng vì chuyện này: một trang timeout 30s giữa lượt quét,
    lỗi ném thẳng ra ngoài, cả đêm đo đổ sông — trong khi 139/140 tin còn lại
    hoàn toàn đọc được. Một request hỏng không được phép giết cả phép đo.
    """
    url = BASE if trang == 1 else f"{BASE}&page={trang}"
    for lan in range(1, _SO_LAN_THU + 1):
        try:
            r = requests.get(url, impersonate="firefox133", timeout=30, headers=HEADERS)
        except Exception as e:
            print(f"  trang {trang}: lỗi mạng lần {lan}/{_SO_LAN_THU} ({type(e).__name__})")
            if lan < _SO_LAN_THU:
                time.sleep(5 * lan)
            continue
        if r.status_code != 200:
            print(f"  trang {trang}: HTTP {r.status_code} (lần {lan}/{_SO_LAN_THU})")
            if lan < _SO_LAN_THU:
                time.sleep(5 * lan)
            continue
        m = NEXT_DATA_RE.search(r.text)
        if not m:
            print(f"  trang {trang}: không tìm thấy khối dữ liệu")
            return []
        return (
            json.loads(m.group(1))
            .get("props", {})
            .get("pageProps", {})
            .get("classified", {})
            .get("items", [])
        )
    print(f"  trang {trang}: BỎ QUA sau {_SO_LAN_THU} lần thử")
    _TRANG_HONG.append(trang)
    return []


def _bay_gio() -> str:
    return datetime.now(VN).strftime("%Y-%m-%d %H:%M:%S")


def chup_truoc() -> None:
    THU_MUC.mkdir(parents=True, exist_ok=True)
    mau: dict[str, dict] = {}
    for trang in _TRANG_LAY_MAU:
        items = _lay_trang(trang)
        for it in items:
            mau[str(it.get("id"))] = {
                "publish_at": it.get("publish_at"),
                "trang": trang,
                "tang": "noi" if trang == 1 else "nam-im",
            }
        print(f"  trang {trang}: {len(items)} tin")
    dem = datetime.now(VN).strftime("%Y%m%d")
    f = THU_MUC / f"truoc_{dem}.json"
    f.write_text(
        json.dumps({"luc": _bay_gio(), "tin": mau}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\nĐã ghi {len(mau)} tin -> {f.name}")


def chup_sau() -> None:
    # Lượt "sau" chạy sau nửa đêm nên đã sang ngày mới — file "truoc" là của
    # hôm qua. Lấy file truoc_* mới nhất thay vì đoán theo ngày hiện tại.
    files = sorted(THU_MUC.glob("truoc_*.json")) if THU_MUC.exists() else []
    if not files:
        print("Chưa có lượt 'truoc' nào. Chạy `truoc` trước đã.")
        return
    f_truoc = files[-1]
    goc = json.loads(f_truoc.read_text(encoding="utf-8"))
    can_tim = goc["tin"]

    hien_tai: dict[str, str] = {}
    for trang in range(1, _TRANG_QUET_LAI + 1):
        items = _lay_trang(trang)
        if not items:
            # Rỗng vì HẾT TIN thì dừng, nhưng rỗng vì ĐỌC HỎNG thì phải đi
            # tiếp — dừng ở đây nghĩa là mọi tin nằm sau trang hỏng đều bị
            # tính nhầm thành "không tìm lại được".
            if trang in _TRANG_HONG:
                continue
            break
        for it in items:
            hien_tai[str(it.get("id"))] = it.get("publish_at")
        if trang % 10 == 0:
            print(f"  đã quét {trang} trang, gom {len(hien_tai)} tin")

    ket_qua = []
    for sid, cu in can_tim.items():
        moi = hien_tai.get(sid)
        ket_qua.append({
            "id": sid,
            "tang": cu["tang"],
            "truoc": cu["publish_at"],
            "sau": moi,
            "mat_dau": moi is None,
        })

    dem = f_truoc.stem.replace("truoc_", "")
    f = THU_MUC / f"sau_{dem}.json"
    f.write_text(
        json.dumps(
            {
                "luc": _bay_gio(),
                "doi_chieu_voi": f_truoc.name,
                "trang_khong_doc_duoc": list(_TRANG_HONG),
                "ket_qua": ket_qua,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nĐã ghi {len(ket_qua)} tin -> {f.name}")
    _in_mot_dem(f)


def _doc(x) -> datetime | None:
    if not x:
        return None
    try:
        return datetime.fromisoformat(str(x)).astimezone(VN)
    except ValueError:
        return None


def _in_mot_dem(f_sau: Path) -> None:
    d = json.loads(f_sau.read_text(encoding="utf-8"))
    rows = d["ket_qua"]
    print(f"\n=== {f_sau.name} (chụp lại lúc {d['luc']}) ===")
    for tang, ten in (("noi", "trang 1 (tin đang nổi)"), ("nam-im", "trang sâu (tin nằm im)")):
        nhom = [r for r in rows if r["tang"] == tang]
        if not nhom:
            continue
        doi = nhay_00h = mat = 0
        for r in nhom:
            if r["mat_dau"]:
                mat += 1
                continue
            a, b = _doc(r["truoc"]), _doc(r["sau"])
            if a and b and abs((b - a).total_seconds()) > 60:
                doi += 1
                if b.hour == 0:
                    nhay_00h += 1
        so_sanh = len(nhom) - mat
        ty = f"{doi / so_sanh * 100:.0f}%" if so_sanh else "-"
        print(f"  {ten}: {len(nhom)} tin")
        print(f"    đổi dấu thời gian : {doi}/{so_sanh}  ({ty})")
        print(f"    trong đó nhảy về 00h: {nhay_00h}")
        if mat:
            print(f"    không tìm lại được : {mat}")


def bao_cao() -> None:
    if not THU_MUC.exists():
        print("Chưa có dữ liệu.")
        return
    files = sorted(THU_MUC.glob("sau_*.json"))
    if not files:
        print("Chưa có đêm nào đo xong.")
        return
    for f in files:
        _in_mot_dem(f)
    print(f"\n{len(files)} đêm đã đo.")
    print(
        "\nĐọc kết quả:\n"
        "  Trang sâu đổi gần hết + nhảy về 00h  -> nền tảng tự đẩy hàng loạt.\n"
        "     Dấu thời gian không dùng làm tín hiệu 'chủ vừa đẩy' được.\n"
        "  Cả hai tầng chỉ lác đác vài tin đổi   -> người thật bấm làm mới.\n"
        "     Lúc đó 'vừa được đẩy' đáng cộng điểm: mặt bằng vừa trống."
    )


if __name__ == "__main__":
    viec = sys.argv[1] if len(sys.argv) > 1 else ""
    if viec == "truoc":
        chup_truoc()
    elif viec == "sau":
        chup_sau()
    elif viec == "bao-cao":
        bao_cao()
    else:
        print(__doc__)
