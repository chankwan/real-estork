"""
RealEstork — Nhatot Token Refresh via Google OAuth + Browser Profile

Flow:
  Setup (một lần duy nhất):
    python -m cli.main setup-nhatot
    → Mở Chrome visible → User click "Đăng nhập bằng Google" trên chotot.com
    → Browser tự intercept Bearer token khi page gọi API
    → Profile (cookies + localStorage) được lưu vào .nhatot_browser_profile/

  Refresh tự động (mỗi ~24h khi token expire):
    NhatotAuthClient.refresh_token()
    → Mở Chrome headless với profile đã lưu
    → chotot.com đọc session cookies → tự nhận ra user đã login
    → Intercept Bearer token từ background API calls khi page load
    → Trả về token, đóng browser (~15-20 giây)
    → Không cần mật khẩu, không cần OTP

  Nếu profile hết hạn (hiếm, Google session thường vài tháng):
    Bot gửi Telegram nhắc: chạy lại setup-nhatot
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger


PROFILE_DIR = Path(".nhatot_browser_profile")

# chotot.com pages to visit — home loads user data quickly, listings page as fallback
_CHOTOT_HOME = "https://www.chotot.com/"
_CHOTOT_LISTINGS = "https://www.chotot.com/tp-ho-chi-minh/cho-thue-nha-dat"

# gateway.chotot.com API domain — Bearer token intercepted from requests here
_API_DOMAIN = "gateway.chotot.com"


class NhatotAuthClient:
    """
    Quản lý Bearer token cho nhatot.com phone reveal API.
    Sử dụng Playwright + Chrome persistent profile với Google OAuth.
    """

    async def refresh_token(self) -> str | None:
        """
        Headless browser refresh — dùng profile đã lưu, không cần login lại.

        Returns:
            str  → Bearer token mới (thành công)
            None → Profile hết hạn, cần chạy setup-nhatot lại
        """
        if not PROFILE_DIR.exists():
            logger.error(
                "[nhatot_auth] Browser profile chưa tồn tại. "
                "Chạy: python -m cli.main setup-nhatot"
            )
            return None
        logger.info("[nhatot_auth] Đang refresh token (headless)...")
        return await self._extract_token(headless=True)

    async def setup_interactive(self) -> str | None:
        """
        Mở Chrome visible để user đăng nhập Google lần đầu.
        Gọi từ CLI: python -m cli.main setup-nhatot
        Caller chịu trách nhiệm in hướng dẫn cho user trước khi gọi method này.

        Returns:
            str  → Bearer token đã intercepted (setup thành công)
            None → Timeout hoặc user chưa đăng nhập trong 5 phút
        """
        logger.info("[nhatot_auth] Mở browser để setup Google OAuth...")
        return await self._extract_token(headless=False)

    # ────────────────────────────────────────────────────────

    async def _extract_token(self, headless: bool) -> str | None:
        """
        Core logic: mở Chrome với persistent profile, intercept Bearer token
        từ requests đến gateway.chotot.com.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "[nhatot_auth] playwright chưa được cài. "
                "Chạy: pip install playwright && playwright install chromium"
            )
            return None

        captured: list[str] = []  # List để có thể mutate trong callback

        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=headless,
                viewport={"width": 1280, "height": 800},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            # Intercept tất cả requests trong context (bao gồm cả background calls)
            def on_request(request) -> None:
                if captured:
                    return  # Đã lấy được rồi
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer ") and _API_DOMAIN in request.url:
                    captured.append(auth[len("Bearer "):])
                    logger.debug(
                        f"[nhatot_auth] Intercepted from: {request.url[:80]}"
                    )

            ctx.on("request", on_request)

            page = await ctx.new_page()
            await page.goto(_CHOTOT_HOME, wait_until="domcontentloaded")

            # Timeout: 5 phút cho setup (user cần login), 20 giây cho headless
            timeout_secs = 300 if not headless else 20
            waited = 0

            while not captured and waited < timeout_secs:
                await asyncio.sleep(1)
                waited += 1
                # Headless only: navigate để trigger API calls sau 8s
                # Setup mode: KHÔNG navigate, tránh interrupt OAuth popup của user
                if headless and waited == 8 and not captured:
                    logger.debug("[nhatot_auth] Navigating to listings page to trigger API calls...")
                    try:
                        await page.goto(_CHOTOT_LISTINGS, wait_until="domcontentloaded")
                    except Exception:
                        pass

            await ctx.close()

        if captured:
            logger.info("[nhatot_auth] Token intercepted thành công")
            return captured[0]

        if headless:
            logger.warning(
                "[nhatot_auth] Không intercept được token trong headless mode. "
                "Session profile có thể hết hạn. Cần chạy lại: python -m cli.main setup-nhatot"
            )
        else:
            logger.warning("[nhatot_auth] Timeout — không nhận được token trong 5 phút.")
        return None
