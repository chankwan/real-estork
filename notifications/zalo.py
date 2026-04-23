"""
RealEstork — Zalo OA Notification
Module 4 (M4) — Alert for vợ

Zalo Official Account API v3:
  POST https://openapi.zalo.me/v3.0/oa/message/cs
  Authorization: Bearer {access_token}
"""

from __future__ import annotations

import os
import textwrap
from typing import Any

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

ZALO_API_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"
ZALO_SCORE_BADGES = {
    "chinh_chu": "🟢",
    "can_xac_minh": "🟡",
    "moi_gioi": "🔴",
}


class ZaloNotifier:
    """
    Send Zalo OA messages to vợ.
    Requires Zalo OA Access Token and vợ's user_id.
    """

    def __init__(self) -> None:
        self.access_token = os.environ.get("ZALO_OA_ACCESS_TOKEN", "")
        self.wife_user_id = os.environ.get("ZALO_WIFE_USER_ID", "")

        if not self.access_token or not self.wife_user_id:
            logger.warning(
                "[zalo] ZALO_OA_ACCESS_TOKEN or ZALO_WIFE_USER_ID not set. "
                "Zalo alerts DISABLED."
            )

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.wife_user_id)

    async def send_listing_alert(
        self,
        listing: Any,      # RawListing
        result: Any,       # ClassificationResult
        osint: dict | None = None,
        dry_run: bool = False,
    ) -> bool:
        """
        Send a new listing alert to vợ via Zalo OA.
        Returns True if sent successfully.
        """
        if not self.is_configured:
            logger.warning("[zalo] Not configured — skipping alert")
            return False

        message = self._format_listing_message(listing, result, osint)

        if dry_run:
            logger.info(f"[zalo][DRY_RUN] Would send:\n{message}")
            return True

        return await self._send_message(self.wife_user_id, message)

    async def send_daily_digest(
        self, digest_text: str, dry_run: bool = False
    ) -> bool:
        """Send daily digest to vợ."""
        if not self.is_configured:
            return False
        if dry_run:
            logger.info(f"[zalo][DRY_RUN] Digest:\n{digest_text}")
            return True
        return await self._send_message(self.wife_user_id, digest_text)

    async def _send_message(self, user_id: str, text: str) -> bool:
        """Send a text message via Zalo OA API v3."""
        payload = {
            "recipient": {"user_id": user_id},
            "message": {"text": text},
        }
        headers = {
            "Content-Type": "application/json",
            "access_token": self.access_token,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(ZALO_API_URL, json=payload, headers=headers)
                data = resp.json()
                if data.get("error") == 0:
                    logger.info(f"[zalo] Message sent to user {user_id[:6]}***")
                    return True
                else:
                    logger.error(f"[zalo] API error: {data}")
                    return False
        except Exception as e:
            logger.error(f"[zalo] Send error: {e}")
            return False

    def _format_listing_message(
        self,
        listing: Any,
        result: Any,
        osint: dict | None,
    ) -> str:
        """
        Format alert message for vợ.
        Matches format from PRD section 3.1.
        """
        badge = ZALO_SCORE_BADGES.get(result.label, "⚪")
        label_text = {
            "chinh_chu": "Likely Chính Chủ",
            "can_xac_minh": "Cần Xác Minh",
            "moi_gioi": "Likely Môi Giới",
        }.get(result.label, result.label)

        # Age display
        age_text = ""
        if listing.listing_age_hours is not None:
            if listing.listing_age_hours < 1:
                age_text = f"{int(listing.listing_age_hours * 60)} phút trước"
            elif listing.listing_age_hours < 24:
                age_text = f"{listing.listing_age_hours:.0f} giờ trước"
            else:
                age_text = f"{listing.listing_age_hours / 24:.0f} ngày trước"

        # Price display
        price_text = listing.price_text or ""
        if listing.price_vnd_monthly and not price_text:
            if listing.price_vnd_monthly >= 1_000_000_000:
                price_text = f"{listing.price_vnd_monthly / 1_000_000_000:.1f} tỷ/tháng"
            else:
                price_text = f"{listing.price_vnd_monthly / 1_000_000:.0f} triệu/tháng"

        # Floor text
        floor_text = ""
        if listing.floor_level:
            floor_text = f" | {'Tầng trệt' if listing.floor_level == 1 else f'Lầu {listing.floor_level - 1}'}"

        # Area text
        area_text = f" | {listing.area_m2:.0f}m²" if listing.area_m2 else ""

        # OSINT section
        osint_lines = ""
        if osint:
            lines = []
            if osint.get("zalo_name"):
                biz = " (business)" if osint.get("zalo_is_business") else " (cá nhân)"
                lines.append(f"  • Zalo: \"{osint['zalo_name']}\"{biz}")
            if osint.get("truecaller_name"):
                lines.append(f"  • Truecaller: {osint['truecaller_name']}")
            google_count = osint.get("google_result_count")
            if google_count is not None:
                if google_count == 1:
                    lines.append("  • Google: 1 kết quả (chỉ tin này) ✅")
                elif google_count == 0:
                    lines.append("  • Google: Không tìm thấy → cá nhân")
                else:
                    lines.append(f"  • Google: {google_count} kết quả ⚠️")
            internal_count = osint.get("internal_listing_count", 0)
            if internal_count == 0:
                lines.append("  • DB nội bộ: Chưa từng xuất hiện ✅")
            else:
                lines.append(f"  • DB nội bộ: Đã thấy {internal_count} lần ⚠️")
            osint_lines = "\n📊 OSINT:\n" + "\n".join(lines)

        # Top signals
        top_signals = sorted(result.signals_fired.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        signal_text = ""
        if top_signals:
            sig_parts = []
            for sig_name, contrib in top_signals:
                arrow = "↑" if contrib > 0 else "↓"
                sig_parts.append(f"{sig_name.replace('_', ' ')} {arrow}")
            signal_text = "\n📌 Signals: " + " · ".join(sig_parts)

        msg = textwrap.dedent(f"""
            🏠 MẶT BẰNG MỚI — {badge} {label_text} (Score: {result.score})

            📍 {listing.address}
            💰 {price_text}{area_text}{floor_text}
            📞 {listing.phone or 'Chưa có SĐT'}{f' ({listing.contact_name})' if listing.contact_name else ''}
            🔗 {listing.source_url}

            ⏰ Đăng {age_text}
            """).strip()

        if osint_lines:
            msg += osint_lines
        if signal_text:
            msg += signal_text

        msg += "\n\n[✅ Đã gọi: /mark called] [❌ Môi giới: /mark broker] [👤 Chính chủ: /mark owner]"
        msg += f"\nID: {listing.source}-{listing.source_id}"

        return msg
