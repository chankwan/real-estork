"""
RealEstork — Main Agentic Orchestrator
Module 6 (M6) — Coordinates full pipeline

Flow per cycle:
  Scrape → Dedup → Classify → OSINT → DB upsert → Alert
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from loguru import logger

from auth.muaban_auth import MuabanAuthClient
from db.client import SupabaseDB
from notifications.zalo import ZaloNotifier
from notifications.telegram import TelegramNotifier
from pipeline.classifier import ClassificationPipeline
from pipeline.dedup import DedupPipeline
from pipeline.ai import AIGateway
from spiders import SpiderEngine

load_dotenv()

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
    "db_error": "lỗi DB",
    "telegram_fail": "lỗi Telegram",
}


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
        self.muaban_auth = MuabanAuthClient()
        self.scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
        # Spiders can run concurrently using ThreadPoolExecutor and scrapling StealthyFetcher.

        # Load schedule config
        self._schedule_config = self._load_yaml(schedule_config)

        # Seed dedup from recent DB
        logger.info("[orchestrator] 🧠 Seeding dedup cache from DB...")
        recent = self.db.get_recent_listings(limit=1000)
        self.dedup.seed_from_db(recent)

        logger.info("[orchestrator] ✨ Ready.")

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
            # 1. Fetch all enabled spiders except batdongsan and muaban
            # (nhatot is fast, muaban is heavy)
            for s in self.spider_engine.spiders:
                if s.name not in ["batdongsan", "muaban"]:
                    s.seen_ids = set(self.dedup.seen_source_ids)

            raw_listings = await self.spider_engine.fetch_all(exclude=["batdongsan", "muaban"])
            logger.info(f"[orchestrator] Nhatot fetched {len(raw_listings)} raw listings")

            # Check token/cookie expiry — notify once per day
            await self._check_muaban_token()

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

        # ── Hard broker veto 1: cùng tài khoản đăng >4 tin trong 1 batch ──
        session_count = getattr(listing, "same_session_account_count", 1)
        if session_count > 4:
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
            self.db.upsert_listing(listing_data)
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
            self.db.upsert_listing(listing_data)
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

        # AI Classification computation
        ai_result = None
        try:
            ai_result = await self.ai.analyze_listing(listing)
        except Exception as e:
            logger.warning(f"[orchestrator] AI skipped: {e}")

        # Classify — single pass (active count already known from detail page)
        result = self.classifier.classify(listing, phone_stats=phone_stats, ai_result=ai_result)
        logger.info(
            f"[orchestrator] {listing.source}/{listing.source_id}: "
            f"score={result.score} label={result.label} active={active_count}"
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

        # Update phone frequency
        if listing.phone:
            self.db.upsert_phone(listing.phone, listing.source)

        # Check alert eligibility
        skip_reason = self.classifier.alert_skip_reason(result, listing)
        if skip_reason:
            return skip_reason

        if not saved:
            return "db_error"

        # BOOST DEDUP: already alerted in a previous session
        if existing_status and existing_status.startswith("alerted"):
            logger.info(
                f"[orchestrator] BOOST DEDUP: {listing.source}/{listing.source_id} "
                f"already '{existing_status}' — skip re-alert"
            )
            return "boost_dedup"

        listing_id = saved.get("id", "")

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
                dry_run=self.dry_run
            )
            if sent:
                alert_sent = True
                logger.info(f"[orchestrator] Alert sent to chat {chat_id} (topic {target_thread})")

        if alert_sent:
            self.db.update_listing_status(listing_id, "alerted_telegram")

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

        try:
            raw_listings = await spider.run()
            logger.info(f"[orchestrator] batdongsan fetched {len(raw_listings)} raw listings")

            if not raw_listings:
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
                        self.db.upsert_listing(data)
                    except Exception as e:
                        logger.warning(f"[orchestrator] pro-agent save failed {pa.source_id}: {e}")
                logger.info(f"[orchestrator] Saved {len(new_pro_agent)} new confirmed_broker listings")

            new_listings = self.dedup.filter_new(raw_listings)
            logger.info(f"[orchestrator] {len(new_listings)} new batdongsan listings after dedup")
            if not new_listings:
                return

            processed_count = 0
            alerted_count = 0
            skip_reasons: Counter = Counter()
            for listing in new_listings:
                try:
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
                f"[orchestrator] ✅ Batdongsan cycle done: {len(new_listings)} new, "
                f"{processed_count} processed, {alerted_count} sent to Telegram"
                f"{' | ' + skip_summary if skip_reasons else ''} | {duration:.1f}s"
            )
            self.db.log_spider_run(
                spider_name="batdongsan",
                status="success",
                listings_found=len(raw_listings),
                new_listings=len(new_listings),
                duration_seconds=duration,
            )
        except Exception as e:
            logger.error(f"[orchestrator] Batdongsan cycle error: {e}")
            self.db.log_spider_run(
                spider_name="batdongsan",
                status="failed",
                error_message=str(e),
            )

    # =========================================================
    # MUABAN CYCLE (separate — heavy volume, 15-20 min interval)
    # =========================================================

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
            if not new_listings:
                return

            processed_count = 0
            alerted_count = 0
            skip_reasons: Counter = Counter()
            for listing in new_listings:
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
                f"[orchestrator] ✅ Muaban cycle done: {len(new_listings)} new, "
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

    async def _check_muaban_token(self) -> None:
        """If muaban token expired, try headless refresh via saved profile."""
        muaban_spider = next(
            (s for s in self.spider_engine.spiders if s.name == "muaban"), None
        )
        if not muaban_spider or not getattr(muaban_spider, "token_expired", False):
            return

        logger.info("[orchestrator] Muaban session expired — attempting headless refresh...")
        if self.dry_run:
            return

        success = await self.muaban_auth.refresh_session()
        if success:
            muaban_spider.token_expired = False
            logger.info("[orchestrator] Muaban session refreshed successfully")
        else:
            logger.warning("[orchestrator] Muaban session refresh failed — profile may be expired")
            await self.telegram.send_admin(
                "⚠️ <b>RealEstork: Muaban session hết hạn</b>\n\n"
                "Profile Google hết hạn hoặc không tìm thấy. Chạy lệnh sau để setup lại:\n"
                "<code>python -m cli.main setup-muaban</code>"
            )
            # Reset flag to avoid spamming every cycle
            muaban_spider.token_expired = False

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

    def setup_scheduler(self) -> None:
        """Configure APScheduler from config/schedule.yaml."""
        schedules = self._schedule_config.get("schedules", {})

        function_map = {
            "run_nhatot_cycle": self.run_nhatot_cycle,
            "run_batdongsan_cycle": self.run_batdongsan_cycle,
            "run_muaban_cycle": self.run_muaban_cycle,
            "daily_digest": self.daily_digest,
            "weekly_model_comparison": self.weekly_model_comparison,
            "analyze_classification_feedback": self.analyze_classification_feedback,
            "cleanup_old_phone_data": self.cleanup_old_phone_data,
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

    async def start(self) -> None:
        """Start the orchestrator. Blocks until interrupted."""
        import atexit
        import sys
        from pathlib import Path
        
        # Lock file — prevent multiple instances
        lock_file = Path(".orchestrator.lock")
        if lock_file.exists():
            existing_pid = lock_file.read_text().strip()
            logger.error(
                f"[orchestrator] Đã có instance đang chạy (PID {existing_pid}). "
                "Nếu không còn process nào, xóa file .orchestrator.lock rồi chạy lại."
            )
            sys.exit(1)
            
        lock_file.write_text(str(os.getpid()))
        atexit.register(lambda: lock_file.unlink(missing_ok=True))
        
        self.setup_scheduler()
        self.scheduler.start()
        logger.info("[orchestrator] ✅ Scheduler started. Running...")

        # Run immediate first cycle on startup
        logger.info("[orchestrator] 🚀 Initial cycles starting (Nhatot, Muaban & Batdongsan)...")
        asyncio.create_task(self.run_nhatot_cycle())
        asyncio.create_task(self.run_muaban_cycle())
        asyncio.create_task(self.run_batdongsan_cycle())

        # Keep running
        try:
            while True:
                await asyncio.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            logger.info("[orchestrator] Shutting down...")
            self.scheduler.shutdown()


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
