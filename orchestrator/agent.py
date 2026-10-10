"""
RealEstork — Main Agentic Orchestrator
Module 6 (M6) — Coordinates full pipeline

Flow per cycle:
  Scrape → Dedup → Classify → OSINT → DB upsert → Alert
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from loguru import logger

from db.client import SupabaseDB
from notifications.zalo import ZaloNotifier
from notifications.telegram import TelegramNotifier
from pipeline.classifier import ClassificationPipeline
from pipeline.dedup import DedupPipeline
from pipeline.ai import AIGateway
from spiders import SpiderEngine

load_dotenv()


def _pid_alive(pid: int) -> bool:
    """Cross-platform check if PID is alive. No external deps."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _doc_thoi_diem(raw: Any) -> datetime | None:
    """Đọc mốc thời gian ISO từ DB về datetime có múi giờ. Hỏng thì None."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_uptime(seconds: float) -> str:
    """Format uptime as '2h 15m' / '3d 4h' / '45m 12s'."""
    s = int(seconds)
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes, s = divmod(s, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {s}s"
    return f"{s}s"


_REASON_LABELS = {
    "alerted": "gửi",
    "veto_broker": "veto môi giới",
    "boost_dedup": "đã gửi rồi",
    "moi_gioi": "môi giới",
    "can_xac_minh": "chưa đủ điểm",
    "tin_cu": "tin cũ",
    "gia_thap": "giá thấp",
    "ngoai_quan": "ngoài quận",
    "pho_phu": "phố phụ",
    "telegram_fail": "lỗi Telegram",
    "chua_xac_minh_nguoi_ban": "hoãn — chưa đọc được số tin đăng",
}

# Số lần thử đọc số tin đăng của người bán (batdongsan) trước khi bỏ cuộc.
# 1 lần lúc crawl + 2 lần thử lại ở 2 cycle sau (~20 phút/cycle).
_BDS_MAX_VERIFY_ATTEMPTS = 3

# Lỗi CHỨNG CHỈ khác lỗi mạng: mạng vẫn thông, nhưng bắt tay TLS bị từ chối.
# Retry không giúp — phải có người sửa (thường là sai giờ máy). Session 20/21 gộp
# nó vào nhóm "chưa có mạng" nên bot thử lại vô hạn trong im lặng 16,5 giờ.
_CERT_ERROR_MARKERS = (
    "certificate_verify_failed",
    "certificate verify failed",
    "certificate is not yet valid",
    "certificate has expired",
    "ssl: ",
    "sslcertverificationerror",
)

# Ghi hỏng liên tiếp bao nhiêu lần thì coi là "bot sống nhưng câm" và báo động.
_WRITE_FAIL_ALARM_STREAK = 20
# Không lặp lại báo động sớm hơn khoảng này (giây) để khỏi spam khi sự cố kéo dài.
_ALARM_REPEAT_SECONDS = 3600
# File cắm cờ khi bot cần người xem — kênh báo động DUY NHẤT không cần mạng.
_ALARM_FILE = Path("BOT-CAN-NGUOI-XEM.txt")


def _is_cert_error(err_msg: str) -> bool:
    """Lỗi bắt tay TLS/chứng chỉ? (khác hẳn 'chưa có mạng')."""
    low = err_msg.lower()
    return any(m in low for m in _CERT_ERROR_MARKERS)


# Supabase cạn quota → khoá cả organization, mọi lệnh REST trả 402 kèm
# "Service for this project is restricted due to the following violations:
#  exceed_egress_quota". Không phải lỗi config, không sửa được từ máy mình —
# chỉ hết khi sang kỳ billing mới hoặc nâng plan.
_QUOTA_ERROR_MARKERS = (
    "exceed_egress_quota",
    "exceed_db_size_quota",
    "service for this project is restricted",
    "'code': 402",
    '"code": 402',
)


def _is_quota_error(err_msg: str) -> bool:
    """Supabase khoá vì hết quota? (khác hẳn lỗi config như sai key/RLS)."""
    low = err_msg.lower()
    return any(m in low for m in _QUOTA_ERROR_MARKERS)


# Hỏi nhiều máy chủ giờ: đo thực tế thấy pool.ntp.org rớt gói ngay lần gọi đầu
# rồi lần sau mới trả lời. Chỉ hỏi một nơi thì đúng lúc cần chẩn đoán nhất bot
# lại kết luận nhầm thành "mất mạng thật".
_NTP_SERVERS = ("pool.ntp.org", "time.google.com", "time.windows.com", "time.cloudflare.com")


def _ntp_offset_one(server: str, timeout: float) -> float | None:
    import socket
    import struct

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(b"\x1b" + 47 * b"\0", (server, 123))
        data, _ = sock.recvfrom(1024)
        # Trường Transmit Timestamp = word thứ 11, tính từ mốc 1900 → đổi sang epoch
        ntp_time = struct.unpack("!12I", data[:48])[10] - 2_208_988_800
        return ntp_time - time.time()
    except Exception:
        return None
    finally:
        if sock is not None:
            sock.close()


def _ntp_offset_seconds(server: str | None = None, timeout: float = 3.0) -> float | None:
    """Giờ máy lệch giờ chuẩn bao nhiêu giây (dương = máy chạy nhanh).

    Hỏi qua NTP (UDP cổng 123) chứ KHÔNG qua HTTPS — nhờ vậy vẫn hỏi được đúng
    lúc mọi kết nối HTTPS đang chết vì chứng chỉ. Trả None khi MỌI máy chủ đều
    im lặng (lúc đó mới thật sự là mất mạng).
    """
    for host in ([server] if server else _NTP_SERVERS):
        offset = _ntp_offset_one(host, timeout)
        if offset is not None:
            return offset
    return None

# Nguồn KHÔNG lấy trong cycle nhatot vì mỗi nguồn đã có cycle riêng.
# Thiếu "facebook_groups" ở đây là lý do tin FB từng chạy pipeline 2 lần.
_NHATOT_CYCLE_EXCLUDE = ["batdongsan", "muaban", "facebook_groups"]

# Chuông "đói tin" batdongsan: số cycle liên tiếp 0 trang đọc được trước khi báo
# Telegram admin (6 cycle × 20 phút ≈ 2h — đủ chậm để bỏ qua trục trặc thoáng qua).
_BDS_STARVE_CYCLES = 6
# Supabase/PostgREST gioi han do dai URL cho bo loc in_() -> chia lo.
_MUABAN_TRA_CUU_LO = 50

# Hàng chờ duyệt tay: số tin tối đa liệt kê trong 1 tin nhắn. Vượt ngưỡng →
# gửi cảnh báo hệ thống thay vì liệt kê, vì lúc đó vấn đề là batdongsan chặn
# hàng loạt chứ không phải vài tin cá biệt cần người xem (chống flood).
_BDS_REVIEW_MAX_ITEMS = 10


def _bds_poster_count_unknown(listing: Any) -> bool:
    """
    True khi CHƯA xác minh được người bán batdongsan đang có bao nhiêu tin đăng.

    Hai đường dẫn tới "chưa biết", cả hai đều KHÔNG được coi là chính chủ:
      None → trang chi tiết đọc được nhưng không thấy số (nút "Xem thêm N tin
             khác" do JS render, lúc kịp lúc không)
      -1   → fetch trang chi tiết hỏng hẳn (Cloudflare chặn)

    Chốt chặn môi giới chỉ hỏi "> 5 tin?" nên cả hai giá trị này đều lọt qua nó;
    đây là hàng rào thứ hai (audit 2026-08-18).
    """
    if getattr(listing, "source", "") != "batdongsan":
        return False
    count = getattr(listing, "poster_total_listings", None)
    return count is None or count < 0


def _format_skip_summary(reasons: Counter) -> str:
    """Format a Counter of skip reasons into a compact log string."""
    parts = []
    for reason, count in reasons.most_common():
        label = _REASON_LABELS.get(reason, reason)
        parts.append(f"{label}: {count}")
    return ", ".join(parts) if parts else "—"


class RealEstorkAgent:
    """
    Main orchestrator. Runs as background service on CHANKWAN-WIN2.
    Agentic: fully autonomous, Chankwan only needs to review daily digest.
    """

    def __init__(
        self,
        spider_config: str = "config/spiders.yaml",
        scoring_config: str = "config/scoring.yaml",
        schedule_config: str = "config/schedule.yaml",
        ai_config: str = "config/ai.yaml",
        dry_run: bool = False,
    ) -> None:
        self.dry_run = dry_run or os.environ.get("DRY_RUN", "false").lower() == "true"
        if self.dry_run:
            logger.warning("[orchestrator] DRY_RUN mode — no alerts will be sent")

        # Initialize components
        logger.info("[orchestrator] 🛠️  Initializing components...")
        self.db = SupabaseDB()
        self.spider_engine = SpiderEngine(spider_config)
        self.dedup = DedupPipeline()
        self.classifier = ClassificationPipeline(scoring_config)
        self.ai = AIGateway(ai_config)
        self.zalo = ZaloNotifier()
        self.telegram = TelegramNotifier()
        self.scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
        # FB capture heartbeat: True = đang trong "đợt im lặng" đã báo Telegram
        # (chỉ báo 1 lần/đợt; hồi phục thì báo lại + reset).
        self._fb_capture_silent = False
        # Lúc gần nhất kêu chuông "không ghi được DB" (None = đang bình thường).
        self._write_alarm_at: float | None = None
        # Tin ghi DB hỏng được append vào đây để nạp lại khi DB sống lại.
        self._spool_path = Path(".db_spool/pending_listings.jsonl")
        # True = Supabase đang khoá vì hết quota; bot chạy chế độ chỉ gửi alert.
        self._db_degraded = False
        # Batdongsan: tin đã crawl nhưng chưa đọc được số tin đăng của người bán.
        # source_id → (listing, số lần đã thử). Cycle sau đọc lại trang chi tiết.
        # Cố ý KHÔNG lưu DB khi đang hoãn — bot restart thì tin quay lại như tin mới.
        self._bds_pending: dict[str, tuple[Any, int]] = {}
        # Chuông "đói tin" batdongsan: N cycle liên tiếp fetch 0 tin → Telegram admin
        # (sự cố 15-18/08: 63 cycle trắng liên tiếp vì Cloudflare, không ai được báo).
        self._bds_zero_streak = 0
        self._bds_starved_alerted = False
        # Tích luỹ health 24h cho daily digest (reset sau mỗi digest).
        self._bds_day_health: Counter = Counter()
        # Tin bỏ cuộc trong cycle này → gộp 1 tin nhắn "cần duyệt tay" cuối cycle.
        self._bds_review_batch: list[Any] = []
        # Vòng nghe nút 👍/👎 (long polling) — tạo trong start(), huỷ khi tắt bot.
        self._feedback_task: Any = None
        # ── Chuông "nền tảng đổi cách hoạt động" (mọi nguồn) ──────────────
        # nguồn → mô tả sự cố đang mở. Có mặt = đã kêu rồi, đừng kêu lại.
        self._platform_alerted: dict[str, str] = {}
        # nguồn → thời điểm cycle gần nhất CHẠY XONG. Dùng cho chuông im lặng.
        # Ca 14/09: vòng Chợ Tốt treo giữa chừng lúc 04:20, scheduler chỉ cho
        # mỗi job 1 lượt chạy nên 8 tiếng sau vẫn không ai được báo — bot vẫn
        # sống, 2 nguồn kia vẫn chạy, mọi chuông hiện có đều thấy "bình thường".
        self._source_last_ok: dict[str, float] = {}
        self._silence_alerted: set[str] = set()
        # Spiders can run concurrently using ThreadPoolExecutor and scrapling StealthyFetcher.

        # Load schedule config
        self._schedule_config = self._load_yaml(schedule_config)

        # Seed dedup from recent DB
        logger.info("[orchestrator] 🧠 Seeding dedup cache from DB...")
        # 12000 ~ 2 tuần tin của cả 4 nguồn. Phải đủ rộng vì tin đã lưu DB nhưng
        # CHƯA từng alert (vd toàn bộ tin muaban trước 2026-09-08) không được lớp
        # "đã alert thì thôi" bảo vệ — cache mỏng là gửi lại hàng loạt.
        recent = self.db.get_recent_listings(limit=12000)
        if not recent:
            # Không đọc được DB (quota cạn → 402, hoặc mạng chết). Seed rỗng nghĩa
            # là MỌI tin thành "tin mới" → gửi lại hàng loạt. Log dưới máy có ghi
            # source_id của từng tin đã thấy, mỏng hơn DB nhưng đủ làm lưới đỡ.
            recent = self._seed_source_id_tu_log()
            logger.warning(
                f"[orchestrator] ⚠️  Không đọc được DB — seed dedup từ log dưới máy: "
                f"{len(recent)} source ID. Mỏng hơn seed từ DB, tin cũ hơn log có thể gửi lại."
            )
        self.dedup.seed_from_db(recent)

        logger.info("[orchestrator] ✨ Ready.")

    def _seed_source_id_tu_log(self, so_file: int = 12) -> list[dict]:
        """Gom source_id đã từng thấy từ log dưới máy, làm seed dedup dự phòng.

        Chỉ dùng khi đọc DB thất bại. Trả về đúng dạng `seed_from_db` nhận, nhưng
        mỗi dòng chỉ có source + source_id — log không ghi content_hash/SĐT/địa chỉ
        nên các lớp chống trùng phụ không được seed. Lớp theo source_id là lớp
        chính nên vẫn chặn được phần lớn.

        Hở đã biết: tin cũ hơn tầm log giữ (hiện ~9 ngày) không có trong đây. Phần
        lớn được bộ lọc tuổi tin chặn, trừ tin Facebook thường không parse được tuổi.
        """
        import re

        mau = re.compile(
            r"Source ID duplicate: ([a-z_]+):([A-Za-z0-9_\-]+)"
            r"|\[orchestrator\] ([a-z_]+)/([A-Za-z0-9_\-]+):"
        )
        thay: set[tuple[str, str]] = set()
        try:
            files = sorted(Path("logs").glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError as e:
            logger.warning(f"[orchestrator] Không đọc được thư mục log: {e}")
            return []

        for f in files[:so_file]:
            try:
                with f.open(encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        m = mau.search(line)
                        if m:
                            src, sid = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                            thay.add((src, sid))
            except OSError as e:
                logger.warning(f"[orchestrator] Bỏ qua log {f.name}: {e}")

        return [{"source": s, "source_id": i} for s, i in thay]

    def _load_yaml(self, path: str) -> dict:
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning(f"[orchestrator] Config not found: {path}")
            return {}

    # =========================================================
    # MAIN SCRAPE CYCLE (every 15 minutes)
    # =========================================================

    async def run_nhatot_cycle(self) -> None:
        """
        Nhatot (Chợ Tốt) pipeline cycle — API mode, no browser.
        Excludes batdongsan and muaban (each have dedicated cycles).
        Spider → Dedup → Classify → OSINT → DB → Alert
        """
        await self._run_nhatot_cycle_inner()

    async def _run_nhatot_cycle_inner(self) -> None:
        cycle_start = time.time()
        logger.info("[orchestrator] 🔄 Nhatot cycle started")

        try:
            # 1. Fetch all enabled spiders except những nguồn đã có cycle riêng.
            # facebook_groups nằm trong danh sách loại trừ từ session 23: trước đó
            # nó bị xử lý HAI lần (cycle riêng 3 phút + cycle này 5 phút) — cùng
            # một hàng post được rút ra và chạy pipeline hai lượt, và thống kê
            # "Nhatot cycle" lẫn số liệu Facebook nên đọc log dễ hiểu nhầm.
            for s in self.spider_engine.spiders:
                if s.name not in _NHATOT_CYCLE_EXCLUDE:
                    s.seen_ids = set(self.dedup.seen_source_ids)

            raw_listings = await self.spider_engine.fetch_all(exclude=_NHATOT_CYCLE_EXCLUDE)
            logger.info(f"[orchestrator] Nhatot fetched {len(raw_listings)} raw listings")

            if not raw_listings:
                return

            # 2. Dedup
            new_listings = self.dedup.filter_new(raw_listings)
            logger.info(f"[orchestrator] {len(new_listings)} new listings after dedup")

            if not new_listings:
                return

            # 3. Classify + OSINT + DB + Alert (per listing)
            processed_count = 0
            alerted_count = 0
            skip_reasons: Counter = Counter()
            for listing in new_listings:
                try:
                    spider = next((s for s in self.spider_engine.spiders if s.name == listing.source), None)
                    if spider and hasattr(spider, "enrich_listing") and not listing.phone:
                        await spider.enrich_listing(listing)

                    reason = await self._process_listing(listing)
                    processed_count += 1
                    if reason == "alerted":
                        alerted_count += 1
                    else:
                        skip_reasons[reason] += 1
                except Exception as e:
                    logger.error(f"[orchestrator] Error processing {listing.source_id}: {e}")

            duration = time.time() - cycle_start
            skip_summary = _format_skip_summary(skip_reasons)
            logger.info(
                f"[orchestrator] ✅ Nhatot cycle done: {len(new_listings)} new, "
                f"{processed_count} processed, {alerted_count} sent to Telegram"
                f"{' | ' + skip_summary if skip_reasons else ''} | {duration:.1f}s"
            )

            # Log to DB
            self.db.log_spider_run(
                spider_name="nhatot",
                status="success",
                listings_found=len(raw_listings),
                new_listings=len(new_listings),
                duration_seconds=duration,
            )

        except Exception as e:
            logger.error(f"[orchestrator] Nhatot cycle error: {e}")
            self.db.log_spider_run(
                spider_name="nhatot",
                status="failed",
                error_message=str(e),
            )
        finally:
            # Trong finally: cycle thoát sớm (0 tin, 0 tin mới) hay lỗi giữa
            # chừng thì vẫn phải tính là "đã chạy xong một lượt". Nếu không,
            # chuông im lặng sẽ kêu oan mỗi lần nguồn đơn giản là không có tin.
            self._mark_source_alive("nhatot")
            sp = self.spider_engine.get_spider("nhatot")
            if sp is not None:
                await self._check_platform_change("nhatot", sp)

    def _spool_listing(self, listing_data: dict) -> None:
        """Ghi tạm 1 tin ra file khi Supabase không nhận được lệnh ghi.

        Alert là sản phẩm, DB chỉ là sổ sách — mất chỗ ghi không được phép
        chặn việc gửi tin cho vợ. Sự cố 2026-10-04: org Supabase cạn quota
        egress, mọi lệnh đọc/ghi trả 402 suốt nhiều ngày; trước đó bot bỏ
        luôn tin nào ghi hỏng nên tin chính chủ rơi im lặng.

        File ghi theo dạng mỗi dòng một JSON, nạp lại theo đúng thứ tự —
        upsert khoá trên (source, source_id) nên dòng sau đè dòng trước,
        tin được gửi alert sẽ có thêm một dòng mang status mới.
        """
        try:
            self._spool_path.parent.mkdir(parents=True, exist_ok=True)
            with self._spool_path.open("a", encoding="utf-8") as f:
                dong = json.dumps(listing_data, ensure_ascii=False, default=str)
                # json.dumps để nguyên U+2028/U+2029, mà splitlines() của Python
                # lại cắt dòng ở đó → bản ghi bị xé đôi khi đọc lại. Escape để
                # file an toàn với mọi cách đọc, không chỉ cách của bot.
                dong = dong.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
                f.write(dong + "\n")
        except Exception as e:
            logger.warning(f"[orchestrator] spool thất bại: {type(e).__name__}: {e}")

    async def _process_listing(
        self,
        listing: Any,
        enrich_profile_spider: Any = None,
    ) -> str:
        """
        Process a single new listing through full pipeline.

        If `enrich_profile_spider` is provided (e.g. the batdongsan spider), the
        classifier runs twice: pass 1 on stage-1/stage-2 data, then — when the
        score falls in the uncertainty window [30, 75] and a profile hash is
        available — guru profile is fetched and classify is re-run with the
        broker/owner signals that depend on `poster_total_listings`.
        """

        # ── BOOST DEDUP: Check existing DB status (survives bot restarts) ──
        existing_status = self.db.get_listing_status(listing.source, listing.source_id)

        # ── Hard broker veto 1: cùng tài khoản đăng nhiều tin trong 1 batch ──
        # FB nới ngưỡng (>5 = >=6) vì chủ nhà có thể đăng vài group; portal giữ >4.
        session_count = getattr(listing, "same_session_account_count", 1)
        veto_session_threshold = 5 if listing.source == "facebook_groups" else 4
        if session_count > veto_session_threshold:
            logger.info(
                f"[orchestrator] BROKER VETO '{listing.contact_name}': "
                f"{session_count} listings trong session — bỏ qua alert"
            )
            listing_data = listing.to_dict()
            listing_data.update({
                "address_normalized": listing.address,
                "classification_score": 0,
                "classification_label": "moi_gioi",
                "status": "auto_vetoed_broker",
            })
            if not self.db.upsert_listing(listing_data):
                self._spool_listing(listing_data)
            if listing.phone:
                self.db.upsert_phone(listing.phone, listing.source)
            return "veto_broker"

        # ── Hard broker veto 2: >5 tin đang active (từ detail page) ─────
        active_count = getattr(listing, "poster_total_listings", None)
        if active_count is not None and active_count > 5:
            logger.info(
                f"[orchestrator] BROKER VETO active={active_count} "
                f"'{listing.contact_name}' {listing.source}/{listing.source_id} — skip scoring"
            )
            listing_data = listing.to_dict()
            listing_data.update({
                "address_normalized": listing.address,
                "classification_score": 10,
                "classification_label": "moi_gioi",
                "status": "auto_vetoed_broker",
            })
            if not self.db.upsert_listing(listing_data):
                self._spool_listing(listing_data)
            if listing.phone:
                self.db.upsert_phone(listing.phone, listing.source)
            return "veto_broker"
        # ─────────────────────────────────────────────────────────────────

        # Get phone stats for classification
        phone_stats = {}
        if listing.phone:
            phone_stats = self.db.get_phone_stats(listing.phone)
            if self.db.is_known_broker(listing.phone):
                phone_stats["is_known_broker"] = True
            # Trangtrang spam cache — inject before classification so penalty fires immediately
            spam_count = self.db.get_phone_trangtrang_report_count(listing.phone)
            if spam_count > 0:
                phone_stats["trangtrang_report_count"] = spam_count

        # AI Classification computation
        ai_result = None
        try:
            ai_result = await self.ai.analyze_listing(listing)
        except Exception as e:
            logger.warning(f"[orchestrator] AI skipped: {e}")

        # Classify — single pass (active count already known from detail page)
        result = self.classifier.classify(listing, phone_stats=phone_stats, ai_result=ai_result)
        age_str = f"{listing.listing_age_hours:.1f}h" if listing.listing_age_hours is not None else "?h"
        signals_str = " ".join(f"{k}:{v:+d}" for k, v in result.signals_fired.items()) if result.signals_fired else "none"
        logger.info(
            f"[orchestrator] {listing.source}/{listing.source_id}: "
            f"score={result.score} label={result.label} age={age_str} "
            f"active={active_count} signals=[{signals_str}]"
        )

        # OSINT (only for listings worth investigating: score >= 50)
        osint_result = None
        if result.score >= 50 and listing.phone:
            try:
                from osint.lookup import OSINTLookup
                osint = OSINTLookup()
                osint_result = await osint.lookup(listing.phone)
            except Exception as e:
                logger.warning(f"[orchestrator] OSINT failed for {listing.phone}: {e}")

        # Save to DB — preserve alerted status if listing was already sent
        listing_data = listing.to_dict()
        listing_data.update({
            "address_normalized": listing.address,  # Will be normalized by DB client
            "classification_score": result.score,
            "classification_label": result.label,
            "ai_result": {"reasoning": result.ai_reasoning} if result.ai_reasoning else None,
            "osint_result": osint_result,
            "status": existing_status if existing_status and existing_status.startswith("alerted") else "new",
        })
        saved = self.db.upsert_listing(listing_data)
        if not saved:
            # DB không nhận lệnh ghi → ghi tạm ra file rồi ĐI TIẾP. Trước đây
            # chỗ này `return "db_error"`, nghĩa là sổ sách hỏng thì tin chính
            # chủ cũng không được gửi — mất 7 tin trong 4,5h ngày 2026-10-04.
            self._spool_listing(listing_data)
            logger.warning(
                f"[orchestrator] {listing.source}/{listing.source_id}: ghi DB hỏng "
                f"— đã spool ra {self._spool_path}, vẫn xét gửi alert"
            )

        # Update phone frequency
        if listing.phone:
            self.db.upsert_phone(listing.phone, listing.source)

        # Check alert eligibility
        skip_reason = self.classifier.alert_skip_reason(result, listing)
        if skip_reason:
            return skip_reason

        # BOOST DEDUP: already alerted in a previous session
        if existing_status and existing_status.startswith("alerted"):
            logger.info(
                f"[orchestrator] BOOST DEDUP: {listing.source}/{listing.source_id} "
                f"already '{existing_status}' — skip re-alert"
            )
            return "boost_dedup"

        # DB chết thì không có id — alert vẫn gửi, chỉ mất 2 nút 👍/👎 dưới tin.
        listing_id = saved.get("id", "") if saved else ""

        # Collect unique chat IDs (admin + group, deduped)
        admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
        group_id = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "")

        # Map platform to specific Telegram topic (message_thread_id)
        topic_mapping = {
            "batdongsan": 5,
            "nhatot": 10,
            "muaban": 11,
        }
        topic_id = topic_mapping.get(listing.source)

        # FB (Bước 3.2): routing theo Ý ĐỊNH (§10.6). Broker đã bị loại bởi
        # veto/score ở trên → tới đây chỉ còn owner/tenant/unknown.
        #   offer → FBG Chủ (TELEGRAM_FB_CHU_TOPIC_ID | fallback TELEGRAM_FB_TOPIC_ID)
        #   seek  → FBG Khách (TELEGRAM_FB_KHACH_TOPIC_ID)
        #   unknown → không gửi (chờ rõ, spec §10.2)
        fb_intent: str | None = None
        if listing.source == "facebook_groups":
            from spiders.facebook_groups import detect_fb_intent
            # Đọc cả tiêu đề (dòng đầu post) lẫn thân bài, và đưa thêm giá + SĐT
            # đã parse để bước suy theo cấu trúc dùng được.
            fb_intent = detect_fb_intent(
                f"{listing.title or ''}\n{listing.description or ''}",
                price_vnd=listing.price_vnd_monthly,
                phone=listing.phone or "",
            )
            chu = os.environ.get("TELEGRAM_FB_CHU_TOPIC_ID", "") or os.environ.get("TELEGRAM_FB_TOPIC_ID", "")
            khach = os.environ.get("TELEGRAM_FB_KHACH_TOPIC_ID", "")
            if fb_intent == "offer" and chu.isdigit():
                # Tin Chủ (cho thuê): chỉ gửi khi giá >= fb_offer_min_price_vnd (mặc định
                # 20M). Không parse được giá (None) → vẫn gửi (lọc lỏng). Filter này CHỈ
                # cho offer — tin Khách (seek) bên dưới nhận MỌI giá.
                offer_min = self.classifier._alert_filters_for("facebook_groups").get("fb_offer_min_price_vnd", 0)
                if offer_min and listing.price_vnd_monthly and listing.price_vnd_monthly < offer_min:
                    logger.info(
                        f"[orchestrator] FB {listing.source_id}: offer giá "
                        f"{listing.price_vnd_monthly} < {offer_min} → gia_thap"
                    )
                    return "gia_thap"
                topic_id = int(chu)
            elif fb_intent == "seek" and khach.isdigit():
                topic_id = int(khach)
            else:
                logger.info(
                    f"[orchestrator] FB {listing.source_id}: intent={fb_intent} "
                    f"→ không route (chờ rõ offer/seek)"
                )
                return "intent_unclear"

        # Tin nước đôi (vừa "cho thuê" vừa sang nhượng/hợp tác) — vẫn gửi nhưng
        # cảnh báo ngay đầu tin nhắn. Loại rõ ràng KHÔNG phải cho thuê đã bị
        # alert_skip_reason chặn ở trên.
        notice: str | None = None
        if self.classifier.non_rental_verdict(listing) == "mixed":
            notice = "CÓ THỂ LÀ TIN SANG NHƯỢNG / HỢP TÁC — đọc kỹ trước khi đi xem"

        seen_chats: set[str] = set()
        chats_to_alert: list[str] = []
        for cid in [admin_id, group_id]:
            if cid and cid not in seen_chats:
                seen_chats.add(cid)
                chats_to_alert.append(cid)

        alert_sent = False
        for chat_id in chats_to_alert:
            # Apply topic_id only for the main group, skip for admin private chat
            target_thread = topic_id if chat_id == group_id else None

            sent = await self.telegram.send_listing_alert(
                listing,
                result,
                chat_id=chat_id,
                osint=osint_result,
                message_thread_id=target_thread,
                intent=fb_intent,
                notice=notice,
                listing_id=listing_id,
                dry_run=self.dry_run
            )
            if sent:
                alert_sent = True
                logger.info(f"[orchestrator] Alert sent to chat {chat_id} (topic {target_thread})")

        if alert_sent:
            if listing_id:
                self.db.update_listing_status(listing_id, "alerted_telegram")
            else:
                # Chưa có row trong DB → ghi thêm một dòng spool mang status mới.
                # Nạp lại theo thứ tự thì dòng này đè dòng "new" ở trên, nên sau
                # khi DB sống lại tin vẫn mang đúng trạng thái đã gửi.
                listing_data["status"] = "alerted_telegram"
                self._spool_listing(listing_data)

        # Alert vợ (Zalo) - TẠM TẮT ĐỂ TEST TELEGRAM
        # if self.classifier.should_alert_wife(result, listing):
        #     sent = await self.zalo.send_listing_alert(
        #         listing, result, osint=osint_result, dry_run=self.dry_run
        #     )
        #     if sent:
        #         self.db.update_listing_status(listing_id, "alerted")

        # Route 3: Alert product subscribers (Telegram/Discord) — Phase 2
        # if self.classifier.should_alert_product(result):
        #     ...
        return "alerted" if alert_sent else "telegram_fail"

    # =========================================================
    # BATDONGSAN CYCLE (separate — 2-stage fetch, 20-min interval)
    # =========================================================

    async def run_batdongsan_cycle(self) -> None:
        """
        Dedicated cycle for batdongsan (list → detail → lazy guru profile).
        Runs at a slower cadence than run_scrape_cycle because it fetches
        detail pages for every surviving card.
        Runs independently from run_scrape_cycle.
        """
        await self._run_batdongsan_cycle_inner()

    async def _run_batdongsan_cycle_inner(self) -> None:
        cycle_start = time.time()
        logger.info("[orchestrator] 🔄 Batdongsan cycle started")

        spider = self.spider_engine.get_spider("batdongsan")
        if spider is None:
            logger.warning("[orchestrator] batdongsan spider not loaded — cycle skipped")
            return

        # Seed seen_ids so spider can early-stop on dedup-heavy pages
        spider.seen_ids = set(self.dedup.seen_source_ids)

        # Nạp tin hoãn vào spider để enrich lại trong CÙNG session của cycle này
        # (cf_clearance dùng chung — không tốn lượt giải Cloudflare riêng).
        pending = list(self._bds_pending.values())
        self._bds_pending.clear()
        spider.pending_retry = [l for l, _ in pending]

        try:
            raw_listings = await spider.run()
            logger.info(f"[orchestrator] batdongsan fetched {len(raw_listings)} raw listings")

            self._track_bds_health(spider, len(raw_listings))
            await self._check_bds_starvation(spider)

            # Resolve tin hoãn: spider đã enrich in-place trong session
            retried_listings = self._resolve_bds_pending(pending)

            if not raw_listings and not retried_listings:
                return

            # Lưu tin pro-agent (badge môi giới chuyên nghiệp) vào DB — không alert
            pro_agent_listings = getattr(spider, "_pro_agent_listings", [])
            if pro_agent_listings:
                new_pro_agent = self.dedup.filter_new(pro_agent_listings)
                for pa in new_pro_agent:
                    try:
                        data = pa.to_dict()
                        data.update({
                            "address_normalized": pa.address,
                            "classification_score": 0,
                            "classification_label": "moi_gioi",
                            "status": "confirmed_broker",
                        })
                        if not self.db.upsert_listing(data):
                            self._spool_listing(data)
                    except Exception as e:
                        logger.warning(f"[orchestrator] pro-agent save failed {pa.source_id}: {e}")
                logger.info(f"[orchestrator] Saved {len(new_pro_agent)} new confirmed_broker listings")

            new_listings = self.dedup.filter_new(raw_listings)
            logger.info(f"[orchestrator] {len(new_listings)} new batdongsan listings after dedup")

            # Tin thử lại đã qua dedup từ cycle trước → không lọc lại, ghép thẳng vào.
            to_process = retried_listings + new_listings
            if not to_process:
                return

            processed_count = 0
            alerted_count = 0
            skip_reasons: Counter = Counter()
            for listing in to_process:
                try:
                    # Chưa biết người bán có bao nhiêu tin đăng → hoãn, không alert.
                    if _bds_poster_count_unknown(listing):
                        self._queue_bds_pending(listing)
                        skip_reasons["chua_xac_minh_nguoi_ban"] += 1
                        continue
                    reason = await self._process_listing(listing)
                    processed_count += 1
                    if reason == "alerted":
                        alerted_count += 1
                    else:
                        skip_reasons[reason] += 1
                except Exception as e:
                    logger.error(f"[orchestrator] batdongsan process {listing.source_id}: {e}")

            duration = time.time() - cycle_start
            skip_summary = _format_skip_summary(skip_reasons)
            logger.info(
                f"[orchestrator] ✅ Batdongsan cycle done: {len(new_listings)} new"
                f"{f' + {len(retried_listings)} thử lại' if retried_listings else ''}, "
                f"{processed_count} processed, {alerted_count} sent to Telegram"
                f"{f' | hàng chờ: {len(self._bds_pending)}' if self._bds_pending else ''}"
                f"{' | ' + skip_summary if skip_reasons else ''} | {duration:.1f}s"
            )
            self.db.log_spider_run(
                spider_name="batdongsan",
                status="success",
                listings_found=len(raw_listings),
                new_listings=len(new_listings),
                duration_seconds=duration,
            )
            await self._send_bds_review_batch(spider)
        except Exception as e:
            logger.error(f"[orchestrator] Batdongsan cycle error: {e}")
            # Cycle chết giữa chừng: tin hoãn quay lại hàng chờ (tăng lượt — session
            # hỏng cũng là 1 lần thử thất bại), health vẫn được track để chuông kêu.
            self._resolve_bds_pending(pending)
            self._track_bds_health(spider, 0)
            await self._check_bds_starvation(spider)
            self.db.log_spider_run(
                spider_name="batdongsan",
                status="failed",
                error_message=str(e),
            )
            await self._send_bds_review_batch(spider)
        finally:
            self._mark_source_alive("batdongsan")
            if spider is not None:
                await self._check_platform_change("batdongsan", spider)

    def _resolve_bds_pending(self, pending: list[tuple[Any, int]]) -> list[Any]:
        """
        Sau spider.run(): tin hoãn đã được enrich in-place trong session của cycle.
        Đọc được số tin đăng → trả về để chấm điểm; vẫn chưa → quay lại hàng chờ
        (hết lượt thì bỏ cuộc — xem _queue_bds_pending).
        """
        resolved: list[Any] = []
        for listing, attempts in pending:
            if _bds_poster_count_unknown(listing):
                self._queue_bds_pending(listing, attempts)
            else:
                resolved.append(listing)
                logger.info(
                    f"[orchestrator] batdongsan/{listing.source_id}: đọc lại được "
                    f"active={listing.poster_total_listings} (lần {attempts + 1})"
                )
        return resolved

    async def _send_bds_review_batch(self, spider: Any) -> None:
        """
        Cuối cycle: gộp các tin bot đã bỏ cuộc thành 1 tin nhắn cho người duyệt tay.

        Gộp theo cycle (không gửi từng tin) để không ngập máy như sự cố alert FB;
        cũng không gộp theo ngày vì tin BĐS quá 24h là nguội, duyệt cũng vô nghĩa.
        """
        batch = self._bds_review_batch
        self._bds_review_batch = []
        if not batch:
            return

        if len(batch) > _BDS_REVIEW_MAX_ITEMS:
            # Quá nhiều tin không xác minh được = hệ thống có vấn đề, không phải
            # việc của người duyệt. Báo 1 dòng kèm chẩn đoán thay vì liệt kê.
            health = getattr(spider, "cycle_health", {}) or {}
            await self.telegram.send_review(
                f"⚠️ <b>Batdongsan: {len(batch)} tin không xác minh được trong 1 cycle</b>\n"
                f"Quá nhiều để duyệt tay — nhiều khả năng batdongsan đang chặn bot, "
                f"không phải tin cá biệt.\n"
                f"Chẩn đoán: {self._format_bds_health(health)}\n"
                f"Các tin đã lưu DB với trạng thái <code>unverified_poster</code>."
            )
            logger.info(
                f"[orchestrator] hàng duyệt tay: {len(batch)} tin > ngưỡng "
                f"{_BDS_REVIEW_MAX_ITEMS} → gửi cảnh báo hệ thống thay vì liệt kê"
            )
            return

        lines = [
            f"🔍 <b>CẦN DUYỆT TAY — batdongsan ({len(batch)} tin)</b>",
            "Bot thử 3 lần vẫn không đọc được người bán đang có bao nhiêu tin đăng "
            "→ không tự phân loại chính chủ/môi giới được.",
            "",
        ]
        for i, l in enumerate(batch, 1):
            price = (
                f"{l.price_vnd_monthly / 1_000_000:.0f} triệu/tháng"
                if getattr(l, "price_vnd_monthly", None) else "chưa rõ giá"
            )
            district = getattr(l, "district", "") or "chưa rõ quận"
            title = (getattr(l, "title", "") or "(không tiêu đề)")[:70]
            lines.append(f"{i}. <b>{title}</b>")
            lines.append(f"   {price} · {district}")
            if getattr(l, "source_url", ""):
                lines.append(f"   {l.source_url}")
        await self.telegram.send_review("\n".join(lines))
        logger.info(f"[orchestrator] hàng duyệt tay: đã gửi {len(batch)} tin")

    def _track_bds_health(self, spider: Any, raw_count: int) -> None:
        """Cộng dồn health counters của cycle vào bộ đếm 24h cho daily digest."""
        health = getattr(spider, "cycle_health", {}) or {}
        self._bds_day_health.update(health)
        self._bds_day_health["cycles"] += 1
        if raw_count == 0:
            self._bds_day_health["zero_cycles"] += 1

    def _format_bds_health(self, health: dict) -> str:
        """1 dòng chẩn đoán từ health counters — dùng chung cho chuông + digest."""
        return (
            f"list OK/CF/mất-card: {health.get('list_pages_ok', 0)}"
            f"/{health.get('list_cf_blocked', 0)}/{health.get('list_no_cards', 0)} | "
            f"detail OK/CF/không-số: {health.get('detail_ok', 0)}"
            f"/{health.get('detail_cf', 0)}/{health.get('detail_unreadable', 0)}"
        )

    # =========================================================
    # CHUÔNG "NỀN TẢNG ĐỔI CÁCH HOẠT ĐỘNG" — dùng chung mọi nguồn
    # =========================================================

    async def _check_platform_change(self, source: str, spider: Any) -> None:
        """Nền tảng đổi thứ gì đó làm hỏng việc cào tin → nhắn Telegram admin.

        Đọc bộ đếm sức khoẻ spider tự ghi trong cycle vừa rồi. Mỗi dấu hiệu
        ứng với một kiểu đổi khác nhau, nên tin nhắn nói thẳng luôn phải đi
        xem chỗ nào:

          trang lặp   → nền tảng bỏ qua tham số phân trang (ca muaban 16/09)
          mất dữ liệu → nền tảng đổi cấu trúc trang
          tường chặn  → nền tảng siết chống bot (ca batdongsan 17/08)
          mã lỗi      → đổi đường dẫn hoặc chặn thẳng

        Chỉ kêu MỘT lần cho mỗi sự cố đang mở, và báo lại khi hồi phục — nếu
        không thì mỗi cycle một tin nhắn, vài tiếng sau không ai đọc nữa.

        NGƯỠNG KÊU — đo trên log thật trước khi đặt:
        "Không tìm thấy card" của batdongsan xảy ra 3-5 lần MỖI NGÀY suốt cả
        tuần (10/09: 3, 11/09: 5, 12/09: 4, 13/09: 3, 14/09: 4, 15/09: 5) —
        đó là nhiễu nền, một trang lỗi lẻ giữa hàng chục trang đọc tốt. Bản
        đầu của chuông này đặt ngưỡng 1 nên kêu oan ngay cycle đầu sau khi
        bật (16/09 11:11): cycle đó 1 URL hỏng, 3 URL còn lại chạy bình
        thường. Chuông kêu 4 lần/ngày thì chỉ vài hôm là không ai đọc nữa.

        Nên chia hai loại:
          • trang lặp → kêu từ lần đầu. Hai trang liên tiếp trùng khít từng
            ID không thể là trục trặc thoáng qua, và nó đã chặn crawl lại rồi.
          • ba dấu hiệu còn lại → chỉ kêu khi số trang hỏng NHIỀU HƠN số
            trang đọc được. Nền tảng đổi thật thì gãy gần hết, không gãy lẻ tẻ.

        Đánh đổi đã biết: hỏng một phần (vài URL chết, phần còn lại sống) sẽ
        KHÔNG kêu ở đây. Lưới đỡ là chuông đói tin và chuông nguồn im lặng —
        hỏng kéo dài kiểu gì cũng rơi vào một trong hai cái đó.
        """
        health = getattr(spider, "cycle_health", {}) or {}
        pages_ok = health.get("list_pages_ok", 0)

        trang_lap = health.get("list_repeat_page", 0)
        # `list_no_cards` là tên cũ của batdongsan, cùng nghĩa list_no_data.
        gay_le = [
            ("mất dữ liệu", health.get("list_no_data", 0) + health.get("list_no_cards", 0),
             "không tìm thấy khối dữ liệu trong trang — nền tảng đổi cấu trúc"),
            ("tường chặn", health.get("list_cf_blocked", 0),
             "dính tường chặn bot — nền tảng siết chống bot"),
            ("mã lỗi", health.get("list_http_error", 0),
             "nền tảng trả mã lỗi — có thể đổi đường dẫn"),
        ]
        tong_gay = sum(n for _, n, _ in gay_le)

        hit = []
        if trang_lap > 0:
            hit.append(("trang lặp", trang_lap,
                        "nền tảng bỏ qua tham số phân trang — bot chỉ còn thấy trang đầu"))
        if tong_gay > pages_ok:
            hit.extend((name, n, why) for name, n, why in gay_le if n > 0)

        if not hit:
            if source in self._platform_alerted:
                truoc = self._platform_alerted.pop(source)
                await self.telegram.send_admin(
                    f"✅ <b>{source} hoạt động lại bình thường</b>\n"
                    f"Sự cố trước đó: {truoc}\n"
                    f"Cycle vừa rồi đọc được {pages_ok} trang, không còn dấu hiệu lạ."
                )
            return

        mo_ta = ", ".join(f"{name} ×{n}" for name, n, _ in hit)
        # Cùng một sự cố đang mở thì im, đừng nhắc lại mỗi cycle.
        if self._platform_alerted.get(source) == mo_ta:
            return
        self._platform_alerted[source] = mo_ta

        chan_doan = "\n".join(f"  • {name}: {why}" for name, _, why in hit)
        await self.telegram.send_admin(
            f"🚨 <b>{source} — nền tảng có vẻ đã đổi cách hoạt động</b>\n"
            f"Dấu hiệu: {mo_ta}\n"
            f"{chan_doan}\n"
            f"Cycle vừa rồi đọc được {pages_ok} trang danh sách."
        )
        logger.warning(
            f"[orchestrator] 🚨 {source}: dấu hiệu nền tảng đổi — {mo_ta}"
        )

    def _mark_source_alive(self, source: str) -> None:
        """Đánh dấu nguồn vừa chạy xong một cycle. Gọi ở CUỐI mỗi cycle."""
        self._source_last_ok[source] = time.time()

    def _silence_limits(self) -> dict[str, float]:
        """nguồn → số giây được phép im lặng, = 4 lần chu kỳ, tối thiểu 30 phút."""
        lich = self._schedule_config.get("schedules", {})
        cap = {
            "nhatot": "nhatot_cycle",
            "muaban": "muaban_cycle",
            "batdongsan": "batdongsan_cycle",
        }
        out: dict[str, float] = {}
        for source, job in cap.items():
            cfg = lich.get(job, {})
            if not cfg.get("enabled", True):
                continue
            phut = float(cfg.get("interval_minutes", 20))
            out[source] = max(phut * 4 * 60, 30 * 60)
        return out

    async def check_source_silence(self) -> None:
        """Nguồn nào quá lâu không chạy xong cycle nào → nhắn Telegram admin.

        Khác chuông "đói tin" ở chỗ: đói tin là cycle CÓ chạy nhưng về tay
        không. Còn cái này bắt ca cycle không chạy nữa — treo giữa chừng,
        hoặc job chết lặng.

        Ca 14/09: vòng Chợ Tốt treo lúc 04:20 khi đang tải một trang, không
        lỗi, không hết giờ. Scheduler chỉ cho mỗi job một lượt chạy cùng lúc
        nên ~97 lượt sau đó đều bị bỏ qua. 8 tiếng không một tin Chợ Tốt nào,
        và không cơ chế nào hiện có phát hiện ra — vì bot vẫn sống, DB vẫn
        ghi được, hai nguồn kia vẫn chạy.

        Ngưỡng = 4 lần chu kỳ đã đặt của nguồn đó (tối thiểu 30 phút), đủ
        rộng để một cycle chậm bất thường không làm chuông kêu oan.
        """
        now = time.time()
        for source, gioi_han in self._silence_limits().items():
            moc = self._source_last_ok.get(source)
            if moc is None:
                # Chưa từng chạy xong lần nào kể từ lúc bot bật — tính từ lúc bật.
                moc = self._start_time
            im_lang = now - moc

            if im_lang <= gioi_han:
                if source in self._silence_alerted:
                    self._silence_alerted.discard(source)
                    await self.telegram.send_admin(
                        f"✅ <b>{source} chạy lại rồi</b> — vừa xong một cycle."
                    )
                continue

            if source in self._silence_alerted:
                continue
            self._silence_alerted.add(source)
            await self.telegram.send_admin(
                f"🚨 <b>{source} im lặng {_format_uptime(im_lang)}</b>\n"
                f"Không cycle nào chạy xong trong khi lẽ ra phải xong mỗi "
                f"{int(gioi_han / 4 / 60)} phút.\n"
                f"Nhiều khả năng một cycle treo giữa chừng và chặn mọi lượt sau."
            )
            logger.warning(
                f"[orchestrator] 🚨 {source} im lặng {_format_uptime(im_lang)} — "
                f"nghi cycle treo"
            )

    async def _check_bds_starvation(self, spider: Any) -> None:
        """
        Chuông "đói tin": _BDS_STARVE_CYCLES cycle liên tiếp không đọc được trang
        danh sách nào → Telegram admin 1 lần/đợt kèm chẩn đoán nguyên nhân
        (Cloudflare vs selector đổi), báo lại khi hồi phục. Cùng pattern heartbeat FB.
        """
        raw_ok = getattr(spider, "cycle_health", {}).get("list_pages_ok", 0) > 0
        if raw_ok:
            if self._bds_starved_alerted:
                await self.telegram.send_admin(
                    "✅ Batdongsan HỒI PHỤC — đã đọc lại được trang danh sách "
                    f"sau {self._bds_zero_streak} cycle trắng."
                )
                self._bds_starved_alerted = False
            self._bds_zero_streak = 0
            return

        self._bds_zero_streak += 1
        if self._bds_zero_streak >= _BDS_STARVE_CYCLES and not self._bds_starved_alerted:
            self._bds_starved_alerted = True
            health = getattr(spider, "cycle_health", {}) or {}
            await self.telegram.send_admin(
                f"🚨 Batdongsan ĐÓI TIN — {self._bds_zero_streak} cycle liên tiếp "
                f"không đọc được trang nào (~{self._bds_zero_streak * 20} phút).\n"
                f"Chẩn đoán cycle gần nhất: {self._format_bds_health(health)}\n"
                f"→ CF cao = Cloudflare nâng chặn; mất-card cao = BDS đổi UI/selector."
            )

    def _queue_bds_pending(self, listing: Any, attempts: int = 0) -> None:
        """
        Đưa tin vào hàng chờ đọc lại số tin đăng của người bán.

        Hết _BDS_MAX_VERIFY_ATTEMPTS lượt → bỏ cuộc: lưu DB (để lần crawl sau
        không lôi lại mãi) nhưng KHÔNG alert — thiếu bằng chứng thì không được
        coi là chính chủ.
        """
        attempts += 1
        if attempts < _BDS_MAX_VERIFY_ATTEMPTS:
            self._bds_pending[listing.source_id] = (listing, attempts)
            logger.info(
                f"[orchestrator] batdongsan/{listing.source_id}: chưa đọc được số tin "
                f"đăng (active={getattr(listing, 'poster_total_listings', None)}) — "
                f"hoãn, thử lại cycle sau ({attempts}/{_BDS_MAX_VERIFY_ATTEMPTS})"
            )
            return

        logger.info(
            f"[orchestrator] batdongsan/{listing.source_id}: bỏ cuộc sau {attempts} "
            f"lần thử đọc số tin đăng — lưu DB, không alert, đưa vào hàng duyệt tay"
        )
        self._bds_review_batch.append(listing)
        try:
            data = listing.to_dict()
            data.update({
                "address_normalized": listing.address,
                "classification_score": 0,
                "classification_label": "can_xac_minh",
                "status": "unverified_poster",
            })
            if not self.db.upsert_listing(data):
                self._spool_listing(data)
        except Exception as e:
            logger.warning(
                f"[orchestrator] lưu tin chưa xác minh {listing.source_id} lỗi: "
                f"{type(e).__name__}: {e}"
            )

    # =========================================================
    # MUABAN CYCLE (separate — heavy volume, 15-20 min interval)
    # =========================================================

    def _tin_cu_vua_duoc_day(self, raw_listings: list[Any], da_moi: list[Any]) -> list[Any]:
        """Tin bot ĐÃ BIẾT nhưng vừa được người đẩy lên lại → đem chấm lại.

        Vì sao cần: lớp chống trùng loại tin theo source_id, nên tin nào bot
        từng thấy sẽ không bao giờ được xem lại. Với sàn rao vặt thường thì
        đúng — nội dung không đổi thì điểm cũng không đổi. Nhưng với mặt bằng
        cho thuê, việc CHỦ ĐẨY LẠI TIN chính là tin tức: mặt bằng vừa được trả,
        chủ đẩy tin cũ lên tìm khách mới.

        Đo 22/09 trên 100 tin ở trang 1-5: 21 tin được đẩy tay trong ngày, và
        bot bỏ qua cả 21 vì đã biết. Trong đó 8 tin đã gửi rồi (bỏ qua là
        đúng), 10 tin đã loại vì môi giới (cũng đúng), còn 3 tin từng chấm
        nhưng chưa đủ điểm — đó là nhóm đáng xem lại.

        Chặn lặp: chỉ lấy tin có dấu MỚI HƠN dấu đang lưu trong DB. Chấm xong
        thì upsert ghi đè dấu mới, nên lần sau không kích hoạt lại. Mỗi lượt
        đẩy vì vậy chỉ sinh đúng một lần chấm lại.

        Chặn spam: không cần làm gì thêm — _process_listing đã có sẵn lớp
        "đã gửi rồi thì thôi" (BOOST DEDUP), nên tin từng alert sẽ không bị
        gửi lại dù được chấm lại.
        """
        id_moi = {l.source_id for l in da_moi}
        ung_vien = [
            l for l in raw_listings
            if getattr(l, "manually_bumped", False)
            and l.source_id not in id_moi
            and getattr(l, "posted_at", None) is not None
        ]
        if not ung_vien:
            return []

        dau_cu: dict[str, Any] = {}
        trang_thai_cu: dict[str, str] = {}
        ids = [str(l.source_id) for l in ung_vien]
        try:
            for i in range(0, len(ids), _MUABAN_TRA_CUU_LO):
                res = (
                    self.db.client.table("listings")
                    .select("source_id,posted_at,status")
                    .eq("source", "muaban")
                    .in_("source_id", ids[i:i + _MUABAN_TRA_CUU_LO])
                    .execute()
                )
                for row in res.data or []:
                    sid = str(row["source_id"])
                    dau_cu[sid] = _doc_thoi_diem(row.get("posted_at"))
                    trang_thai_cu[sid] = str(row.get("status") or "")
        except Exception as e:
            # Tra cứu hỏng thì bỏ qua lượt chấm lại — KHÔNG đoán bừa là "có
            # đẩy mới", vì đoán sai sẽ chấm lại toàn bộ mỗi cycle.
            logger.warning(
                f"[orchestrator] tra dấu thời gian cũ (muaban) lỗi: "
                f"{type(e).__name__}: {e}"
            )
            return []

        can_cham_lai = []
        for l in ung_vien:
            sid = str(l.source_id)
            if sid not in dau_cu:
                continue  # chưa có trong DB thì không phải "tin cũ"

            # ── KHÔNG chấm lại tin đã có phán quyết ────────────────────────
            # Bỏ qua tin từng bị loại vì môi giới. Lý do không hiển nhiên:
            # lớp chặn môi giới đếm "tài khoản này đăng bao nhiêu tin trong
            # CÙNG MẺ CÀO", nên nó phụ thuộc kích thước mẻ. Hồi 16/09 bot cào
            # 1040 tin một mẻ → thấy tài khoản có 5+ tin → loại đúng. Mẻ bây
            # giờ chỉ 80 tin, cùng tài khoản chỉ lộ 1-2 tin → lớp chặn không
            # fire nữa. Chấm lại trong mẻ nhỏ tức là VỨT BỎ bằng chứng môi
            # giới thu được từ mẻ lớn. Đo 22/09: tin 70746888 đúng kiểu này —
            # từng bị loại vì môi giới, chấm lại thành 65 điểm và sẽ được gửi.
            #
            # Môi giới không trở thành chính chủ chỉ vì họ bấm đẩy tin.
            #
            # Tin đã gửi rồi cũng bỏ qua ở đây cho đỡ tốn công — _process_listing
            # vẫn có lớp chặn riêng, đây chỉ là chặn sớm.
            tt = trang_thai_cu.get(sid, "")
            if tt.startswith("alerted") or tt in ("auto_vetoed_broker", "unverified_poster"):
                continue

            cu = dau_cu[sid]
            moi = l.posted_at
            if moi.tzinfo is None:
                moi = moi.replace(tzinfo=timezone.utc)
            if cu is None or (moi - cu).total_seconds() > 60:
                can_cham_lai.append(l)
        return can_cham_lai

    async def run_muaban_cycle(self) -> None:
        """
        Dedicated cycle for muaban.net.
        Volume is high (similar to batdongsan), requiring more time to reach
        'not-today' listings than fast sites like nhatot.
        """
        await self._run_muaban_cycle_inner()

    async def _run_muaban_cycle_inner(self) -> None:
        cycle_start = time.time()
        logger.info("[orchestrator] 🔄 Muaban cycle started")

        spider = self.spider_engine.get_spider("muaban")
        if spider is None:
            logger.warning("[orchestrator] muaban spider not loaded — cycle skipped")
            return

        # Seed seen_ids so spider can early-stop on dedup-heavy pages
        spider.seen_ids = set(self.dedup.seen_source_ids)

        try:
            raw_listings = await spider.run()
            logger.info(f"[orchestrator] muaban fetched {len(raw_listings)} raw listings")

            if not raw_listings:
                return

            new_listings = self.dedup.filter_new(raw_listings)
            logger.info(f"[orchestrator] {len(new_listings)} new muaban listings after dedup")

            # Tin cũ vừa được người đẩy lên lại cũng đáng xem lại — xem
            # _tin_cu_vua_duoc_day. Ghép vào cùng luồng xử lý; lớp "đã gửi rồi
            # thì thôi" trong _process_listing lo phần chống gửi lặp.
            cham_lai = self._tin_cu_vua_duoc_day(raw_listings, new_listings)
            if cham_lai:
                logger.info(
                    f"[orchestrator] {len(cham_lai)} tin muaban cũ vừa được đẩy tay "
                    f"— chấm lại"
                )

            can_xu_ly = new_listings + cham_lai
            if not can_xu_ly:
                return

            processed_count = 0
            alerted_count = 0
            skip_reasons: Counter = Counter()
            for listing in can_xu_ly:
                try:
                    reason = await self._process_listing(listing)
                    processed_count += 1
                    if reason == "alerted":
                        alerted_count += 1
                    else:
                        skip_reasons[reason] += 1
                except Exception as e:
                    logger.error(f"[orchestrator] muaban process {listing.source_id}: {e}")

            duration = time.time() - cycle_start
            skip_summary = _format_skip_summary(skip_reasons)
            logger.info(
                f"[orchestrator] ✅ Muaban cycle done: {len(new_listings)} new"
                f"{f' + {len(cham_lai)} đẩy tay' if cham_lai else ''}, "
                f"{processed_count} processed, {alerted_count} sent to Telegram"
                f"{' | ' + skip_summary if skip_reasons else ''} | {duration:.1f}s"
            )
            self.db.log_spider_run(
                spider_name="muaban",
                status="success",
                listings_found=len(raw_listings),
                new_listings=len(new_listings),
                duration_seconds=duration,
            )
        except Exception as e:
            logger.error(f"[orchestrator] Muaban cycle error: {e}")
            self.db.log_spider_run(
                spider_name="muaban",
                status="failed",
                error_message=str(e),
            )
        finally:
            self._mark_source_alive("muaban")
            if spider is not None:
                await self._check_platform_change("muaban", spider)

    # =========================================================
    # FACEBOOK GROUPS CYCLE (PUSH/drain — userscript → ingest queue)
    # =========================================================

    async def run_facebook_groups_cycle(self) -> None:
        """
        Drain cycle cho Facebook groups. Spider không kéo web — nó rút hàng đợi
        ingest (post do userscript Tampermonkey POST về localhost) rồi đẩy vào
        pipeline. No-op khi spider disabled hoặc hàng đợi rỗng.
        """
        await self._run_facebook_groups_cycle_inner()

    async def _run_facebook_groups_cycle_inner(self) -> None:
        cycle_start = time.time()

        spider = self.spider_engine.get_spider("facebook_groups")
        if spider is None:
            return  # spider disabled → silent no-op (không log spam mỗi 3 phút)

        await self._check_fb_capture_heartbeat(spider)

        spider.seen_ids = set(self.dedup.seen_source_ids)

        try:
            raw_listings = await spider.run()
            if not raw_listings:
                return  # hàng đợi rỗng — không có gì để xử lý

            logger.info(f"[orchestrator] 🔄 Facebook cycle: {len(raw_listings)} raw từ ingest")
            new_listings = self.dedup.filter_new(raw_listings)
            logger.info(
                f"[orchestrator] facebook_groups: received {len(raw_listings)}, "
                f"{len(new_listings)} new sau dedup"
            )
            if not new_listings:
                return

            processed_count = 0
            alerted_count = 0
            skip_reasons: Counter = Counter()
            for listing in new_listings:
                try:
                    # 3.3: tích luỹ hồ sơ poster FB (cross-group/cross-session) rồi gắn
                    # group_count vào listing để classify chấm tín hiệu rải tin (>=5 group).
                    uid = getattr(listing, "poster_account_id", None)
                    if uid:
                        url = listing.source_url or ""
                        gid = url.split("/groups/", 1)[1].split("/", 1)[0] if "/groups/" in url else ""
                        poster = self.db.upsert_fb_poster(
                            uid=uid,
                            group_id=gid,
                            display_name=listing.contact_name or "",
                            phone=listing.phone or "",
                        )
                        if poster:
                            listing.fb_poster_group_count = poster.get("group_count", 0) or 0
                            listing.fb_poster_post_count = poster.get("post_count", 0) or 0
                    reason = await self._process_listing(listing)
                    processed_count += 1
                    if reason == "alerted":
                        alerted_count += 1
                    else:
                        skip_reasons[reason] += 1
                except Exception as e:
                    logger.error(f"[orchestrator] facebook process {listing.source_id}: {e}")

            duration = time.time() - cycle_start
            skip_summary = _format_skip_summary(skip_reasons)
            logger.info(
                f"[orchestrator] ✅ Facebook cycle done: {len(new_listings)} new, "
                f"{processed_count} processed, {alerted_count} sent to Telegram"
                f"{' | ' + skip_summary if skip_reasons else ''} | {duration:.1f}s"
            )
            self.db.log_spider_run(
                spider_name="facebook_groups",
                status="success",
                listings_found=len(raw_listings),
                new_listings=len(new_listings),
                duration_seconds=duration,
            )
        except Exception as e:
            logger.error(f"[orchestrator] Facebook cycle error: {e}")
            self.db.log_spider_run(
                spider_name="facebook_groups",
                status="failed",
                error_message=str(e),
            )

    async def _check_fb_capture_heartbeat(self, spider) -> None:
        """
        Giám sát cửa sổ Chrome capture qua heartbeat (userscript ping /heartbeat 60s).
        - Chưa từng nhận từ lúc bot start → im lặng (anh chủ đích tắt Tampermonkey).
        - Đã từng nhận mà im >N phút → Telegram admin 1 lần/đợt (kèm cách khắc phục).
        - Nhận lại sau khi đã báo → báo hồi phục + reset để đợt sau báo tiếp được.
        """
        try:
            from ingest.fb_receiver import heartbeat_age

            age = heartbeat_age()
            if age is None:
                return  # chưa từng có heartbeat — extension đang tắt chủ đích
            threshold_s = float(spider.config.get("heartbeat_alert_minutes", 15)) * 60
            if age > threshold_s and not self._fb_capture_silent:
                self._fb_capture_silent = True
                logger.warning(
                    f"[orchestrator] FB capture im lặng {age / 60:.0f} phút "
                    f"(ngưỡng {threshold_s / 60:.0f}) → Telegram admin"
                )
                await self.telegram.send_admin(
                    f"⚠️ <b>FB capture im lặng {age / 60:.0f} phút</b>\n"
                    f"Cửa sổ Chrome capture có thể đã đóng/crash, hoặc via bị FB logout.\n"
                    f"→ Khắc phục: double-click <code>bot-fb-scan.bat</code> trên PC2 "
                    f"(hoặc chờ reboot — Task Scheduler tự mở lại).\n"
                    f"→ Nếu via bị logout: mở Chrome profile Default, login lại FB."
                )
            elif age <= threshold_s and self._fb_capture_silent:
                self._fb_capture_silent = False
                logger.info("[orchestrator] FB capture heartbeat hồi phục")
                await self.telegram.send_admin("✅ <b>FB capture hoạt động lại</b> — heartbeat đã nhận lại bình thường.")
        except Exception as e:
            logger.error(f"[orchestrator] heartbeat check lỗi: {type(e).__name__}: {e}")

    # _check_muaban_token: XOÁ (2026-09-08). Chỉ chạy khi spider bật cờ
    # token_expired, mà cờ đó do đường lấy SĐT qua cookie bật — đường này đã gỡ
    # vì muaban dựng Cloudflare Turnstile ở nút "Hiện số" từ 21/08 và endpoint cũ
    # trả 404. Không còn gì cần đăng nhập ở muaban.

    # =========================================================
    # DAILY DIGEST (8:00 AM)

    # =========================================================

    async def daily_digest(self) -> None:
        """Send daily summary to vợ and Chankwan."""
        logger.info("[orchestrator] Sending daily digest...")

        stats = self.db.get_daily_stats()
        feedback_rows = self.db.get_recent_feedback(days=7)
        feedback_analysis = self.classifier.analyze_feedback(feedback_rows)

        digest = (
            f"📊 DAILY DIGEST — RealEstork\n"
            f"📅 {datetime.now(timezone.utc).strftime('%d/%m/%Y')}\n\n"
            f"Hôm qua: {stats.get('total_new', 0)} listings mới\n"
            f"🟢 Chính chủ: {stats.get('chinh_chu', 0)} | "
            f"🟡 Xác minh: {stats.get('can_xac_minh', 0)} | "
            f"🔴 Môi giới: {stats.get('moi_gioi', 0)}\n"
            f"📞 Đã gọi: {stats.get('called', 0)} | "
            f"✅ Owner: {stats.get('confirmed_owner', 0)} | "
            f"❌ Broker: {stats.get('confirmed_broker', 0)}\n\n"
            f"🎯 Accuracy tuần này: {feedback_analysis.get('accuracy', 'N/A')}% "
            f"({feedback_analysis.get('total_samples', 0)} samples)\n"
        )

        # Health batdongsan 24h — phát hiện xu hướng BDS siết chặn tăng dần
        # (kiểu 11→14/08: tỉ lệ Cloudflare nhích dần trước khi chặn hẳn).
        bh = self._bds_day_health
        if bh.get("cycles"):
            digest += (
                f"\n🕷 Batdongsan 24h: {bh['cycles']} cycle, "
                f"{bh.get('zero_cycles', 0)} cycle trắng\n"
                f"   {self._format_bds_health(bh)}\n"
            )
        self._bds_day_health = Counter()

        telegram_admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
        if telegram_admin_id:
            logger.info("[orchestrator] Sending daily digest to Telegram...")
            # We reuse format but send via telegram directly (raw text is not supported by Telegram HTML format perfectly but it works well enough without tags)
            await self.telegram.bot.send_message(chat_id=telegram_admin_id, text=digest)
        else:
            await self.zalo.send_daily_digest(digest, dry_run=self.dry_run)
            
        logger.info("[orchestrator] Daily digest sent")

    # =========================================================
    # WEEKLY MODEL COMPARISON
    # =========================================================

    async def weekly_model_comparison(self) -> None:
        """Compare AI model accuracy — placeholder for Phase 1.5."""
        logger.info("[orchestrator] Weekly model comparison — not yet implemented")

    async def analyze_classification_feedback(self) -> None:
        """Analyze vợ's /mark feedback and adjust weights if needed."""
        logger.info("[orchestrator] Analyzing classification feedback...")
        feedback_rows = self.db.get_recent_feedback(days=7)
        analysis = self.classifier.analyze_feedback(feedback_rows)
        
        await self.telegram.send_admin(
            f"📈 <b>Feedback Analysis (Last 7 days)</b>\n\n"
            f"Accuracy: {analysis['accuracy']}%\n"
            f"Samples: {analysis['total_samples']}\n\n"
            f"<b>Signal Suggestions:</b>\n"
            f"{analysis['suggestions']}"
        )

    async def cleanup_old_phone_data(self) -> None:
        """Purge stale phone frequency data (Phase 2)."""
        logger.info("[orchestrator] Cleanup old phone data — not yet implemented")

    # =========================================================
    # SCHEDULER
    # =========================================================

    def _diagnose_tls_failure(self) -> str:
        """Đoán vì sao bắt tay TLS hỏng. Ưu tiên nghi phạm số 1: giờ máy sai."""
        offset = _ntp_offset_seconds()
        if offset is None:
            return (
                "Không hỏi được giờ chuẩn (NTP cũng không thông) — nhiều khả năng "
                "mất mạng thật, hoặc firewall chặn. Kiểm tra kết nối trước."
            )
        if abs(offset) > 300:
            huong = "chậm" if offset > 0 else "nhanh"
            return (
                f"GIỜ MÁY SAI: đang {huong} {abs(offset) / 3600:.1f} giờ so với giờ chuẩn. "
                f"Đây gần như chắc chắn là nguyên nhân — chứng chỉ của server bị coi là "
                f"'chưa có hiệu lực' hoặc 'đã hết hạn'. Sửa: Settings → Time & language → "
                f"Sync now. Nếu lặp lại sau mỗi lần mất điện thì pin CMOS hỏng."
            )
        return (
            f"Giờ máy đúng (lệch {offset:+.0f}s) nên KHÔNG phải lỗi đồng hồ. "
            f"Nghi phạm còn lại: phần mềm chặn/quét HTTPS (antivirus, proxy công ty), "
            f"hoặc server thật sự đổi chứng chỉ hỏng."
        )

    async def _raise_alarm(self, tieu_de: str, chi_tiet: str) -> None:
        """Báo động khi bot còn sống nhưng không làm được việc.

        Ba kênh, kênh sau không phụ thuộc kênh trước:
          1. Log ERROR (luôn được).
          2. File cắm cờ ở thư mục dự án — kênh DUY NHẤT không cần mạng, đây là
             thứ đã thiếu trong sự cố 16,5 giờ.
          3. Telegram — thử dù biết có thể fail (Telegram cũng đi qua HTTPS).
        """
        logger.error(f"[orchestrator] 🚨 {tieu_de} | {chi_tiet}")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            _ALARM_FILE.write_text(
                f"[{now}] {tieu_de}\n\n{chi_tiet}\n\n"
                f"Bot vẫn đang chạy nhưng KHÔNG làm được việc. Xử lý xong thì xoá file này.\n",
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"[orchestrator] Không ghi được file báo động: {e}")
        try:
            await self.telegram.send_lifecycle(
                f"🚨 <b>RealEstork — {tieu_de}</b>\n{chi_tiet}"
            )
        except Exception as e:
            logger.error(f"[orchestrator] Telegram cũng không gửi được: {e}")

    def _clear_alarm(self) -> None:
        try:
            if _ALARM_FILE.exists():
                _ALARM_FILE.unlink()
        except Exception:
            pass

    async def check_write_health(self) -> None:
        """Bot còn sống nhưng có ghi được gì vào DB không?

        Sự cố 26-27/08: bot chạy bình thường, log vẫn cuộn, nhưng MỌI lệnh ghi
        fail vì lỗi chứng chỉ suốt 16,5 giờ — 0 tin lưu, 0 alert, không ai biết.
        Chuông này bắt đúng trạng thái đó.
        """
        streak = getattr(self.db, "write_error_streak", 0)
        if streak < _WRITE_FAIL_ALARM_STREAK:
            if streak == 0 and self._write_alarm_at is not None:
                self._write_alarm_at = None
                self._clear_alarm()
                logger.info("[orchestrator] ✅ Ghi DB đã hoạt động lại")
                try:
                    await self.telegram.send_lifecycle(
                        "✅ <b>RealEstork — ghi dữ liệu đã hoạt động lại</b>"
                    )
                except Exception:
                    pass
            return

        now = time.time()
        if self._write_alarm_at and now - self._write_alarm_at < _ALARM_REPEAT_SECONDS:
            return
        self._write_alarm_at = now

        loi = getattr(self.db, "last_write_error", "")
        chi_tiet = f"{streak} lệnh ghi liên tiếp thất bại.\nLỗi: {loi[:200]}"
        if _is_cert_error(loi):
            chi_tiet += f"\n\nChẩn đoán: {self._diagnose_tls_failure()}"
        await self._raise_alarm("BOT KHÔNG GHI ĐƯỢC DỮ LIỆU", chi_tiet)

    def _save_feedback_vote(
        self, listing_id: str, is_good: bool, voter_id: str = ""
    ) -> tuple[int, int] | None:
        """Ghi 1 phiếu 👍/👎. Trả về (số phiếu đáng xem, số phiếu rác) sau khi ghi.

        Đây là ĐẦU VÀO duy nhất của vòng học. Trước session 23 bảng này trống
        vĩnh viễn: phần phân tích hàng tuần vẫn chạy nhưng không có dữ liệu nào
        để phân tích, nên mọi lần siết trọng số đều là phỏng đoán.

        Quy ước nhãn: 👍 → chinh_chu (tin đáng gửi), 👎 → moi_gioi (rác).
        Đây là "tin này có đáng gửi không" theo mắt vợ, không phải phán quyết
        pháp lý về danh tính người đăng — dùng để chỉnh ngưỡng, không dùng để
        khẳng định ai là môi giới.
        """
        row = self.db.get_listing_by_id(listing_id)
        if not row:
            logger.warning(f"[orchestrator] Phản hồi cho tin không tìm thấy: {listing_id}")
            return None
        rid = row.get("id") or listing_id
        # Định danh người bấm nằm trong feedback_source vì bảng không có cột
        # riêng. Nhờ vậy vợ và đồng nghiệp mỗi người giữ 1 phiếu độc lập trên
        # cùng một tin, và ai đổi ý thì chỉ ghi đè phiếu CỦA MÌNH.
        source = f"telegram_button:{voter_id}" if voter_id else "telegram_button"
        ok = self.db.save_feedback(
            listing_id=rid,
            predicted_label=row.get("classification_label") or "",
            predicted_score=int(row.get("classification_score") or 0),
            actual_label="chinh_chu" if is_good else "moi_gioi",
            feedback_source=source,
            signals_at_prediction={},
        )
        if not ok:
            return None
        # Ghi TRƯỚC, dọn SAU: mỗi người đúng 1 phiếu, và nếu ghi hỏng thì
        # phiếu cũ của họ vẫn còn nguyên chứ không mất trắng.
        self.db.prune_feedback(rid, source)
        return self.db.count_feedback(rid)

    def setup_scheduler(self) -> None:
        """Configure APScheduler from config/schedule.yaml."""
        schedules = self._schedule_config.get("schedules", {})

        function_map = {
            "run_nhatot_cycle": self.run_nhatot_cycle,
            "run_batdongsan_cycle": self.run_batdongsan_cycle,
            "run_muaban_cycle": self.run_muaban_cycle,
            "run_facebook_groups_cycle": self.run_facebook_groups_cycle,
            "daily_digest": self.daily_digest,
            "weekly_model_comparison": self.weekly_model_comparison,
            "analyze_classification_feedback": self.analyze_classification_feedback,
            "cleanup_old_phone_data": self.cleanup_old_phone_data,
            "check_write_health": self.check_write_health,
            "check_source_silence": self.check_source_silence,
        }

        for job_name, job_config in schedules.items():
            if not job_config.get("enabled", True):
                continue

            fn_name = job_config.get("function")
            fn = function_map.get(fn_name)
            if fn is None:
                logger.warning(f"[orchestrator] Unknown function '{fn_name}' for job '{job_name}'")
                continue

            if "interval_minutes" in job_config:
                self.scheduler.add_job(
                    fn,
                    "interval",
                    minutes=job_config["interval_minutes"],
                    id=job_name,
                    replace_existing=True,
                )
                logger.info(f"[orchestrator] 📅 Scheduled '{job_name}' every {job_config['interval_minutes']}m")

            elif "cron" in job_config:
                # Parse cron expression
                parts = job_config["cron"].split()
                self.scheduler.add_job(
                    fn,
                    "cron",
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    id=job_name,
                    replace_existing=True,
                )
                logger.info(f"[orchestrator] Scheduled '{job_name}' cron: {job_config['cron']}")

    async def start(self, source: str = "manual") -> None:
        """Start the orchestrator. Blocks until interrupted.

        source: 'manual-visible', 'manual-headless', 'auto-headless' — used
        for lifecycle Telegram notifications.
        """
        import atexit
        import sys
        from pathlib import Path

        crash_detected_pid: str | None = None
        lock_file = Path(".orchestrator.lock")
        if lock_file.exists():
            raw = lock_file.read_text().strip()
            try:
                existing_pid = int(raw)
            except ValueError:
                existing_pid = 0
            if existing_pid and _pid_alive(existing_pid):
                logger.error(
                    f"[orchestrator] Đã có instance đang chạy (PID {existing_pid}). "
                    "Tắt instance đó (Ctrl+C hoặc Stop-Process) trước khi start lại."
                )
                sys.exit(1)
            logger.warning(
                f"[orchestrator] Stale lock file (PID {raw or '?'} không còn chạy) — tự dọn dẹp."
            )
            crash_detected_pid = raw or "?"
            lock_file.unlink()

        clean_exit = False  # set True only on graceful stop; atexit skips lock cleanup on crash
        lock_file.write_text(str(os.getpid()))

        def _atexit_cleanup() -> None:
            if clean_exit:
                lock_file.unlink(missing_ok=True)
            # Crash path: leave lock so next start detects via PID-not-alive check.

        atexit.register(_atexit_cleanup)
        self._start_time = time.time()
        self._start_source = source

        if crash_detected_pid:
            await self.telegram.send_lifecycle(
                f"⚠️ <b>RealEstork Bot — Phát hiện crash</b>\n"
                f"Instance trước (PID <code>{crash_detected_pid}</code>) tắt đột ngột "
                f"(cúp điện, kill -9, BSOD, hoặc OOM).\n"
                f"Đang khởi động lại..."
            )

        # Lỗi mạng/DNS (vd cúp điện vừa có lại, router/ISP chưa kịp reconnect lúc
        # máy auto-logon) là TẠM THỜI — retry vô hạn mỗi 30s cho tới khi có mạng,
        # vì Task Scheduler -AtLogon KHÔNG tự retry khi task fail (đã verify thực
        # nghiệm: RestartCount/RestartInterval không kích hoạt cho trigger loại này).
        # Lỗi khác (RLS, sai key...) là lỗi config thật — retry vô ích, fail ngay + alert.
        #
        # Nhận diện bằng EXCEPTION TYPE (httpx.TransportError — cha chung của
        # ConnectError/ConnectTimeout/ReadTimeout/PoolTimeout/NetworkError...), KHÔNG
        # phải match chuỗi message: session trước match message ("getaddrinfo failed")
        # nên bị sự cố mạng KHÁC (ConnectTimeout, message "[WinError 10060] ...") lọt
        # qua — message lỗi socket phụ thuộc OS/locale, không ổn định để match. Type
        # exception thì ổn định vì httpx luôn raise TransportError cho mọi lỗi tầng
        # kết nối, bất kể message cụ thể là gì. Giữ string marker làm fallback phụ.
        _NETWORK_ERROR_MARKERS = (
            "getaddrinfo failed",
            "connecterror",
            "connecttimeout",
            "name or service not known",
            "temporary failure in name resolution",
            "network is unreachable",
            "winerror 10060",
            "winerror 10061",
        )
        attempt = 0
        while True:
            try:
                self.db.health_check_write()
                logger.info("[orchestrator] ✅ DB smoke test passed (write OK)")
                self._clear_alarm()
                break
            except Exception as e:
                err_msg = str(e)
                is_network = isinstance(e, httpx.TransportError) or any(
                    m in err_msg.lower() for m in _NETWORK_ERROR_MARKERS
                )
                # Lỗi CHỨNG CHỈ: mạng thông nhưng TLS bị từ chối. Vẫn retry (để tự
                # hồi phục ngay khi có người sửa giờ) NHƯNG phải kêu to, vì retry
                # im lặng chính là thứ khiến bot chết 16,5 giờ mà không ai biết.
                if _is_cert_error(err_msg):
                    attempt += 1
                    if attempt == 1 or attempt % 20 == 0:   # ngay lần đầu, rồi mỗi 10 phút
                        await self._raise_alarm(
                            "KHÔNG KHỞI ĐỘNG ĐƯỢC — LỖI CHỨNG CHỈ BẢO MẬT",
                            f"Đã thử {attempt} lần, mỗi 30s.\n"
                            f"Lỗi: {type(e).__name__}: {err_msg[:200]}\n\n"
                            f"Chẩn đoán: {self._diagnose_tls_failure()}\n\n"
                            f"Bot sẽ tự chạy tiếp ngay khi sửa xong, không cần khởi động lại.",
                        )
                    else:
                        logger.error(
                            f"[orchestrator] Lỗi chứng chỉ (lần thử {attempt}) — "
                            f"đang chờ người sửa. Thử lại sau 30s..."
                        )
                    await asyncio.sleep(30)
                    continue

                if is_network:
                    attempt += 1
                    logger.warning(
                        f"[orchestrator] Chưa có mạng/DNS (lần thử {attempt}): "
                        f"{type(e).__name__}: {err_msg}. Thử lại sau 30s..."
                    )
                    await asyncio.sleep(30)
                    continue

                # QUOTA CẠN: Supabase khoá cả org, mọi lệnh đọc/ghi trả 402. Khác
                # hẳn lỗi config — không sửa được từ máy mình, chỉ chờ hết kỳ billing
                # hoặc nâng plan. Thoát ở đây là sai: spider/scoring/Telegram không
                # đụng DB, bot vẫn gửi tin cho vợ được. Sự cố 2026-10-04: 108 tin đã
                # đủ điều kiện gửi bị bỏ trong 38 giờ vì DB chết kéo cả bot chết theo.
                if _is_quota_error(err_msg):
                    self._db_degraded = True
                    logger.warning(
                        "[orchestrator] ⚠️  Supabase hết quota (402) — chạy CHẾ ĐỘ CHỈ GỬI ALERT. "
                        "Tin vẫn gửi Telegram, ghi tạm ra file, nạp lại sau bằng: bot db-replay"
                    )
                    try:
                        await self.telegram.send_lifecycle(
                            "⚠️ <b>RealEstork Bot — CHẠY CHẾ ĐỘ CHỈ GỬI ALERT</b>\n"
                            "Supabase hết quota egress, DB tạm không ghi/đọc được.\n"
                            "Bot vẫn crawl, chấm điểm và gửi tin bình thường.\n"
                            "Tin được ghi tạm ra file, nạp lại khi quota reset."
                        )
                    except Exception as tg_err:
                        logger.error(f"[orchestrator] Telegram alert fail: {tg_err}")
                    break

                logger.error(
                    f"[orchestrator] ❌ DB smoke test FAILED — không thể write vào Supabase. "
                    f"{type(e).__name__}: {err_msg}"
                )
                is_rls = "row-level security" in err_msg.lower() or "42501" in err_msg
                hint = (
                    "RLS chặn write — kiểm tra <code>SUPABASE_SERVICE_KEY</code> "
                    "(phải là <code>sb_secret_*</code> hoặc JWT <code>eyJ...</code>, "
                    "KHÔNG phải <code>sb_publishable_*</code>). Chạy: <code>bot doctor</code>."
                    if is_rls else
                    "Kết nối Supabase fail — kiểm tra <code>SUPABASE_URL</code> + "
                    "<code>SUPABASE_SERVICE_KEY</code> trong .env. Chạy: <code>bot doctor</code>."
                )
                try:
                    await self.telegram.send_lifecycle(
                        f"🚨 <b>RealEstork Bot — KHỞI ĐỘNG THẤT BẠI</b>\n"
                        f"DB smoke test fail.\n"
                        f"Lỗi: <code>{type(e).__name__}: {err_msg[:200]}</code>\n"
                        f"→ {hint}"
                    )
                except Exception as tg_err:
                    logger.error(f"[orchestrator] Telegram alert cũng fail: {tg_err}")
                clean_exit = True  # controlled abort, not crash — lock should be cleaned
                sys.exit(1)

        # Start Facebook ingest receiver (localhost) if the spider is enabled.
        fb_spider = self.spider_engine.get_spider("facebook_groups")
        if fb_spider is not None:
            from ingest.fb_receiver import start_receiver
            cfg = fb_spider.config
            host = str(cfg.get("ingest_host", "127.0.0.1"))
            port = int(cfg.get("ingest_port", 8787))
            token = os.environ.get("FB_INGEST_TOKEN", str(cfg.get("ingest_token", "")))
            start_receiver(host, port, token)

        self.setup_scheduler()
        self.scheduler.start()
        logger.info("[orchestrator] ✅ Scheduler started. Running...")

        # Vòng nghe nút 👍/👎 — chạy thường trực, KHÔNG đặt vào scheduler.
        # Hai bên cùng hỏi Telegram sẽ đá nhau (Telegram chỉ cho một nơi đọc
        # hàng cập nhật), nên job theo lịch đã bị gỡ khỏi config/schedule.yaml.
        self._feedback_task = asyncio.create_task(
            self.telegram.run_feedback_listener(self._save_feedback_vote)
        )

        # Notify Telegram: bot started
        mode_label = {
            "manual-visible": "🖥️ Có cửa sổ (terminal)",
            "manual-headless": "👤 Headless (thủ công)",
            "auto-headless": "🤖 Headless (tự động khi đăng nhập)",
        }.get(source, source)
        await self.telegram.send_lifecycle(
            f"🟢 <b>RealEstork Bot started</b>\n"
            f"Mode: {mode_label}\n"
            f"PID: <code>{os.getpid()}</code>\n"
            f"Time: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Run immediate first cycle on startup
        logger.info("[orchestrator] 🚀 Initial cycles starting (Nhatot, Muaban & Batdongsan)...")
        asyncio.create_task(self.run_nhatot_cycle())
        asyncio.create_task(self.run_muaban_cycle())
        asyncio.create_task(self.run_batdongsan_cycle())

        # Keep running
        try:
            while True:
                await asyncio.sleep(60)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            clean_exit = True
            logger.info("[orchestrator] Shutting down...")
            uptime = _format_uptime(time.time() - self._start_time)
            try:
                await self.telegram.send_lifecycle(
                    f"🔴 <b>RealEstork Bot stopped</b> (Ctrl+C)\n"
                    f"Uptime: {uptime}\n"
                    f"PID: <code>{os.getpid()}</code>"
                )
            except Exception as e:
                logger.warning(f"[orchestrator] Lifecycle notify failed on shutdown: {e}")
            if self._feedback_task:
                self._feedback_task.cancel()
            self.scheduler.shutdown()
        except Exception as e:
            # Unhandled exception — clean_exit stays False → lock preserved for crash detection.
            logger.error(
                f"[orchestrator] ❌ Unhandled exception — bot đang crash. "
                f"{type(e).__name__}: {e}"
            )
            try:
                uptime = _format_uptime(time.time() - self._start_time)
                await self.telegram.send_lifecycle(
                    f"💥 <b>RealEstork Bot CRASHED</b>\n"
                    f"Lỗi: <code>{type(e).__name__}: {str(e)[:300]}</code>\n"
                    f"Uptime: {uptime} | PID: <code>{os.getpid()}</code>\n"
                    f"Lock file giữ lại — next start tự detect."
                )
            except Exception as tg_err:
                logger.error(f"[orchestrator] Telegram crash notify cũng fail: {tg_err}")
            try:
                self.scheduler.shutdown(wait=False)
            except Exception:
                pass
            raise


def _update_env_file(key: str, value: str) -> None:
    """Update or add a KEY=value line in .env file."""
    from pathlib import Path
    env_path = Path(".env")
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            lines[i] = f"{key}={value}\n"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}\n")
    env_path.write_text("".join(lines), encoding="utf-8")


async def main() -> None:
    """Entry point for running orchestrator directly."""
    agent = RealEstorkAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
