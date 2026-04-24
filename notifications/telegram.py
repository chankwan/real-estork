"""
RealEstork — Telegram Notification
Module 4 (M4) — Alert for product subscribers (Hướng 2)

Bot API: python-telegram-bot
"""

from __future__ import annotations

import html
import os
import textwrap
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from telegram import Bot
from telegram.error import TelegramError

load_dotenv()

# Same badges as Zalo for consistency
TELEGRAM_SCORE_BADGES = {
    "chinh_chu": "🟢",
    "can_xac_minh": "🟡",
    "moi_gioi": "🔴",
}


class TelegramNotifier:
    """Send Telegram messages to product subscribers."""

    def __init__(self) -> None:
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.bot = Bot(token=self.token) if self.token else None

        if not self.bot:
            logger.warning(
                "[telegram] TELEGRAM_BOT_TOKEN not set. "
                "Telegram product alerts DISABLED."
            )

    @property
    def is_configured(self) -> bool:
        return self.bot is not None

    async def send_admin(self, text: str) -> None:
        """Send HTML message to TELEGRAM_ADMIN_CHAT_ID."""
        admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
        if not self.is_configured or not admin_id:
            return
        try:
            await self.bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
        except TelegramError as e:
            logger.error(f"[telegram] send_admin error: {e}")

    async def send_listing_alert(
        self,
        listing: Any,
        result: Any,
        chat_id: int | str,
        osint: dict | None = None,
        message_thread_id: int | None = None,
        dry_run: bool = False,
    ) -> bool:
        """Send property alert to a specific Telegram chat/channel."""
        if not self.is_configured:
            return False

        message = self._format_listing_message(listing, result, osint)

        if dry_run:
            logger.info(f"[telegram][DRY_RUN] Would send to {chat_id} (topic {message_thread_id}):\n{message}")
            return True

        try:
             # Make sure we use an async context when actually sending
             await self.bot.send_message(
                 chat_id=chat_id,
                 message_thread_id=message_thread_id,
                 text=message,
                 parse_mode="HTML",
                 disable_web_page_preview=False,
             )
             logger.info(f"[telegram] Message sent to chat {chat_id} (topic {message_thread_id})")
             return True
        except TelegramError as e:
             logger.error(f"[telegram] Send error to {chat_id} (topic {message_thread_id}): {e}")
             return False

    def _format_listing_message(
        self,
        listing: Any,
        result: Any,
        osint: dict | None,
    ) -> str:
        """Format the listing alert in HTML for Telegram."""
        e = html.escape  # All user-provided text must be escaped for strict HTML parsers

        badge = TELEGRAM_SCORE_BADGES.get(result.label, "⚪")
        label_text = {
            "chinh_chu": "Likely Chính Chủ",
            "can_xac_minh": "Cần Xác Minh",
            "moi_gioi": "Likely Môi Giới",
        }.get(result.label, result.label)

        # Property type visual — BDS only
        _prop_display = {
            "nha_mat_pho":      ("🏪", "Nhà mặt phố"),
            "shophouse":        ("🏬", "Shophouse"),
            "kho_nha_xuong":    ("🏭", "Kho/Nhà xưởng"),
            "nha_rieng":        ("🏠", "Nhà riêng"),
            "biet_thu_lien_ke": ("🏘️", "Biệt thự/Liền kề"),
        }
        prop_type = getattr(listing, "property_type", "")
        prop_emoji, prop_label = _prop_display.get(prop_type, ("🏠", ""))
        prop_tag = f"#{prop_type} " if prop_type else ""

        # Price
        price_text = listing.price_text or ""
        if listing.price_vnd_monthly and not price_text:
            if listing.price_vnd_monthly >= 1_000_000_000:
                price_text = f"{listing.price_vnd_monthly / 1_000_000_000:.1f} tỷ/tháng"
            else:
                price_text = f"{listing.price_vnd_monthly / 1_000_000:.0f} triệu/tháng"

        # Floor text
        floor_text = ""
        if listing.floor_level:
            floor_text = f" | Tầng {'trệt' if listing.floor_level == 1 else listing.floor_level}"

        # Area text
        area_text = f" | {listing.area_m2:.0f}m²" if listing.area_m2 else ""

        # Main street tag
        is_main_street = getattr(listing, "is_main_street", None)
        street_tag = " | 🏪 Mặt tiền" if is_main_street else (" | 🏠 Hẻm" if is_main_street is False else "")

        # Phone display — some sources hide phone behind auth
        if listing.phone:
            phone_display = listing.phone
        elif listing.source == "nhatot":
            phone_display = "🔒 SĐT ẩn — mở app nhatot"
        elif listing.source == "batdongsan":
            phone_display = "🔒 SĐT ẩn — mở app BĐS"
        else:
            phone_display = "Chưa có SĐT"

        contact_part = f" ({e(listing.contact_name)})" if listing.contact_name else ""

        prop_line = f"\n{prop_emoji} <b>{prop_label}</b>" if prop_label else ""
        msg = textwrap.dedent(f"""
            <b>{badge} {label_text} (Score: {result.score})</b>{prop_line}

            📍 <i>{e(listing.address or '')}</i>
            💰 <b>{e(price_text)}</b>{area_text}{floor_text}{street_tag}

            📞 <b>{e(phone_display)}</b>{contact_part}

            <a href="{listing.source_url}">Xem ảnh &amp; chi tiết ({listing.source})</a>
            """).strip()

        # OSINT block
        if osint:
            lines = []
            if osint.get("zalo_name"):
                biz = " (Biz)" if osint.get("zalo_is_business") else ""
                lines.append(f"• Zalo: {e(osint['zalo_name'])}{biz}")
            google_cnt = osint.get("google_result_count")
            if google_cnt is not None:
                lines.append(f"• Google: {google_cnt} results")
            if lines:
                msg += "\n\n<b>📊 OSINT:</b>\n" + "\n".join(lines)

        # Append source hashtag for "All" topic visibility
        msg += f"\n\n{prop_tag}#{listing.source} | <code>{listing.source}-{e(listing.source_id)}</code>"
        return msg
