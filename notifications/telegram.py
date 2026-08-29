"""
RealEstork — Telegram Notification
Module 4 (M4) — Alert for product subscribers (Hướng 2)

Bot API: python-telegram-bot
"""

from __future__ import annotations

import html
import os
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

load_dotenv()

# Same badges as Zalo for consistency
TELEGRAM_SCORE_BADGES = {
    "chinh_chu": "🟢",
    "can_xac_minh": "🟡",
    "moi_gioi": "🔴",
}


_FEEDBACK_PREFIX = "fb"


def _feedback_keyboard(
    listing_id: str | None,
    good_count: int = 0,
    bad_count: int = 0,
) -> InlineKeyboardMarkup | None:
    """2 nút 👍/👎 dưới mỗi tin. Không có listing_id thì không gắn nút.

    Hiện SỐ PHIẾU chứ không phải dấu ✅ của một người: nhiều người cùng đánh giá
    (vợ + đồng nghiệp), mà một tin nhắn Telegram chỉ có MỘT bộ nút chung — không
    thể hiện riêng lựa chọn của từng người được. Đếm phiếu thì ai cũng đọc được.

    Cả hai nút luôn còn nguyên → bấm nhầm bấm lại là đổi được phiếu của mình.

    callback_data giới hạn 64 byte của Telegram: "fb|1|<uuid 36 ký tự>" = 41 byte.
    """
    if not listing_id:
        return None
    good = f"👍 Đáng xem ({good_count})" if good_count else "👍 Đáng xem"
    bad = f"👎 Tin rác ({bad_count})" if bad_count else "👎 Tin rác"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(good, callback_data=f"{_FEEDBACK_PREFIX}|1|{listing_id}"),
        InlineKeyboardButton(bad, callback_data=f"{_FEEDBACK_PREFIX}|0|{listing_id}"),
    ]])


class TelegramNotifier:
    """Send Telegram messages to product subscribers."""

    def __init__(self) -> None:
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.bot = Bot(token=self.token) if self.token else None
        # Vị trí đã đọc tới trong hàng cập nhật của Telegram (nút 👍/👎).
        # None = lần đầu. Telegram tự xoá update đã xác nhận nên restart không đọc lại.
        self._feedback_offset: int | None = None

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

    async def send_review(self, text: str) -> None:
        """
        Gửi tin "cần duyệt tay" — tin bot không tự phân loại được.

        Đích đến theo thứ tự ưu tiên:
          1. Group + topic riêng nếu có TELEGRAM_BDS_REVIEW_TOPIC_ID (tạo topic
             trong group rồi điền ID vào .env) — tách khỏi luồng alert của vợ.
          2. Chưa cấu hình topic → chat admin (việc vận hành, không làm phiền group).
        """
        if not self.is_configured:
            return
        topic = os.environ.get("TELEGRAM_BDS_REVIEW_TOPIC_ID", "")
        group_id = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "")
        if topic.isdigit() and group_id:
            try:
                await self.bot.send_message(
                    chat_id=group_id,
                    text=text,
                    parse_mode="HTML",
                    message_thread_id=int(topic),
                    disable_web_page_preview=True,
                )
                return
            except TelegramError as e:
                logger.error(f"[telegram] send_review to group topic {topic} error: {e}")
        await self.send_admin(text)

    async def poll_feedback(self, save_fn: Any) -> int:
        """Đọc các lần bấm 👍/👎 rồi giao cho save_fn lưu lại.

        save_fn(listing_id: str, is_good: bool, voter_id: str)
            -> (số phiếu đáng xem, số phiếu rác) nếu lưu được, None nếu hỏng

        Dùng get_updates thay vì chạy Application/webhook: bot này chỉ cần đọc
        nút bấm, không cần xử lý lệnh chat. Gọi định kỳ từ scheduler.
        Trả về số phản hồi đã ghi nhận.
        """
        if not self.is_configured:
            return 0
        try:
            updates = await self.bot.get_updates(
                offset=self._feedback_offset,
                timeout=0,
                allowed_updates=["callback_query"],
            )
        except TelegramError as e:
            logger.warning(f"[telegram] poll_feedback error: {e}")
            return 0

        saved = 0
        for u in updates:
            self._feedback_offset = u.update_id + 1
            q = getattr(u, "callback_query", None)
            data = getattr(q, "data", "") or ""
            if not q or not data.startswith(f"{_FEEDBACK_PREFIX}|"):
                continue
            try:
                _, flag, listing_id = data.split("|", 2)
            except ValueError:
                # Payload lạ (vd nút cũ từ phiên bản trước) — vẫn phải trả lời,
                # nếu không Telegram quay vòng vòng trên máy người bấm.
                try:
                    await q.answer("Nút này không còn dùng")
                except TelegramError:
                    pass
                continue
            is_good = flag == "1"
            voter = getattr(q, "from_user", None)
            voter_id = str(getattr(voter, "id", "") or "")
            counts = None
            try:
                counts = save_fn(listing_id, is_good, voter_id)
            except Exception as e:
                logger.error(f"[telegram] save feedback error: {type(e).__name__}: {e}")
            ok = counts is not None
            try:
                await q.answer("Đã ghi nhận, cảm ơn!" if ok else "Chưa lưu được, thử lại sau")
                if ok:
                    # Giữ CẢ HAI nút + hiện số phiếu → người sau bấm được, người
                    # bấm nhầm sửa được.
                    g, b = counts
                    await q.edit_message_reply_markup(
                        reply_markup=_feedback_keyboard(listing_id, good_count=g, bad_count=b)
                    )
            except TelegramError as e:
                # "message is not modified" khi bấm lại đúng nút cũ — vô hại.
                if "not modified" not in str(e).lower():
                    logger.warning(f"[telegram] answer callback error: {e}")
            if ok:
                saved += 1
                logger.info(
                    f"[telegram] Phản hồi: {listing_id} → {'đáng xem' if is_good else 'tin rác'}"
                )
        return saved

    async def send_lifecycle(self, text: str) -> None:
        """Send bot lifecycle event (start/stop/crash) to admin + group General topic."""
        if not self.is_configured:
            return
        admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
        group_id = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "")
        targets = [c for c in (admin_id, group_id) if c]
        # Dedupe (admin and group could be same)
        seen: set[str] = set()
        for chat_id in targets:
            if chat_id in seen:
                continue
            seen.add(chat_id)
            try:
                # No message_thread_id = goes to General topic in supergroups with topics
                await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            except TelegramError as e:
                logger.error(f"[telegram] send_lifecycle to {chat_id} error: {e}")

    async def send_listing_alert(
        self,
        listing: Any,
        result: Any,
        chat_id: int | str,
        osint: dict | None = None,
        message_thread_id: int | None = None,
        intent: str | None = None,
        notice: str | None = None,
        listing_id: str | None = None,
        dry_run: bool = False,
    ) -> bool:
        """Send property alert to a specific Telegram chat/channel."""
        if not self.is_configured:
            return False

        message = self._format_listing_message(listing, result, osint, intent, notice)

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
                 reply_markup=_feedback_keyboard(listing_id),
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
        intent: str | None = None,
        notice: str | None = None,
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
        elif listing.source == "facebook_groups":
            phone_display = "📋 SĐT trong nội dung post — mở link"
        else:
            phone_display = "Chưa có SĐT"

        contact_part = f" ({e(listing.contact_name)})" if listing.contact_name else ""

        # Build message as flat list of left-aligned lines.
        # Avoid textwrap.dedent: nhúng prop_line (chứa \n) vào f-string sẽ phá
        # common leading whitespace của dedent → các dòng sau bị thụt phải.
        lines: list[str] = [
            f"<b>{badge} {label_text} (Score: {result.score})</b>",
        ]
        if notice:
            lines.append(f"⚠️ <b>{e(notice)}</b>")
        if prop_label:
            lines.append(f"{prop_emoji} <b>{prop_label}</b>")
        lines.append("")
        # 📍 địa chỉ — bỏ qua nếu trống (FB không có địa chỉ chuẩn)
        if listing.address:
            lines.append(f"📍 <i>{e(listing.address)}</i>")
        # 💰 dòng giá — bỏ qua khi hoàn toàn trống (FB thường không parse được giá)
        if price_text or area_text or floor_text or street_tag:
            lines.append(f"💰 <b>{e(price_text)}</b>{area_text}{floor_text}{street_tag}")
        # FB: link group không preview được → nhúng thẳng nội dung post vào message
        if listing.source == "facebook_groups":
            desc = (listing.description or "").strip()
            if desc:
                snippet = desc[:600] + ("…" if len(desc) > 600 else "")
                lines.extend(["", f"📝 <i>{e(snippet)}</i>"])
        # Link label — FB: phân biệt permalink bài thật (userscript moi được từ
        # set=gm/pcb → /posts/ hoặc /commerce/listing/) vs fallback link người đăng
        # (/user/ hoặc trang group). Chỉ khi có link bài mới ghi "Link chi tiết".
        if listing.source == "facebook_groups":
            _url = listing.source_url or ""
            _is_real_permalink = ("/posts/" in _url) or ("/commerce/listing/" in _url)
            link_label = "🔗 Link chi tiết" if _is_real_permalink else "👤 Xem người đăng + các tin khác"
        else:
            link_label = "Xem ảnh &amp; chi tiết"
        lines.extend([
            "",
            f"📞 <b>{e(phone_display)}</b>{contact_part}",
            "",
            f'<a href="{listing.source_url}">{link_label} ({listing.source})</a>',
        ])
        msg = "\n".join(lines)

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

        # Append source hashtag for "All" topic visibility.
        # FB: thêm sub-tag theo intent để bấm xem riêng Chủ / Khách. Giữ
        # #facebook_groups (bấm → xem CẢ hai loại).
        source_tag = f"#{listing.source}"
        if listing.source == "facebook_groups" and intent in ("offer", "seek"):
            sub = "chu" if intent == "offer" else "khach"
            source_tag = f"#{listing.source} #{listing.source}_{sub}"
        msg += f"\n\n{prop_tag}{source_tag} | <code>{listing.source}-{e(listing.source_id)}</code>"
        return msg
