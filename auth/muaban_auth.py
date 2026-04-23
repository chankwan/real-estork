"""
RealEstork — Muaban Session/Token Interception via Browser Profile
Module 9 (M9) — Authentication

Flow similar to nhatot:
  1. python -m cli.main setup-muaban -> opens browser
  2. user logs in (Google OAuth)
  3. client intercepts Cookie/Authorization headers
  4. profile saved in .muaban_browser_profile/
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from loguru import logger

PROFILE_DIR = Path(".muaban_browser_profile")
COOKIES_FILE = Path(".muaban_cookies.json")

_MUABAN_HOME = "https://muaban.net/"
_MUABAN_LOGIN = "https://muaban.net/account/login"
_API_DOMAIN = "muaban.net/api"

class MuabanAuthClient:
    """
    Manages session for muaban.net.
    Uses Playwright to intercept auth headers and save persistent profile.
    """

    async def setup_interactive(self) -> bool:
        """Opens visible browser for user to log in."""
        logger.info("[muaban_auth] Mở browser để setup Muaban (Google OAuth)...")
        return await self._run_browser(headless=False)

    async def refresh_session(self) -> bool:
        """Headless check/refresh using persistent profile."""
        if not PROFILE_DIR.exists():
            logger.error("[muaban_auth] Browser profile not found. Run: python -m cli.main setup-muaban")
            return False
        logger.info("[muaban_auth] Đang refresh muaban session (headless)...")
        return await self._run_browser(headless=True)

    def load_cookies(self) -> dict[str, str]:
        """Load saved cookies for httpx/requests."""
        if not COOKIES_FILE.exists():
            return {}
        try:
            data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            return {c["name"]: c["value"] for c in cookies}
        except Exception as e:
            logger.error(f"[muaban_auth] Failed to load cookies: {e}")
            return {}

    async def _run_browser(self, headless: bool) -> bool:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[muaban_auth] playwright not installed.")
            return False

        success = False
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR.resolve()),
                headless=headless,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                ignore_default_args=["--enable-automation"],
                args=[
                    "--no-sandbox", 
                    "--disable-blink-features=AutomationControlled",
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                ],
            )

            page = await ctx.new_page()
            
            # Navigate to login if setup, else just home
            target_url = _MUABAN_LOGIN if not headless else _MUABAN_HOME
            await page.goto(target_url, wait_until="domcontentloaded")

            # Intercept auth headers if possible
            def on_request(request):
                # We can detect successful login if we see requests with auth headers to their API
                auth = request.headers.get("authorization", "")
                if auth and _API_DOMAIN in request.url:
                    # Could potentially save token here
                    pass

            ctx.on("request", on_request)

            timeout = 300 if not headless else 30
            waited = 0
            
            while waited < timeout:
                await asyncio.sleep(2)
                waited += 2
                
                # Check if logged in by looking for avatar or specific cookie/localStorage
                # For Muaban, let's check for 'token' in localStorage or 'uid' cookie
                is_logged_in = False
                try:
                    is_logged_in = await page.evaluate("""
                        () => {
                            const token = localStorage.getItem('token');
                            const hasAvatar = !!document.querySelector('.user-avatar, .avatar-wrapper');
                            return !!token || hasAvatar;
                        }
                    """)
                except Exception:
                    # Ignore errors during navigation (context destroyed)
                    pass
                
                if is_logged_in:
                    logger.info("[muaban_auth] Đã phát hiện trạng thái Đăng nhập!")
                    cookies = await ctx.cookies()
                    self._save_cookies(cookies)
                    success = True
                    # Chờ profile flush
                    await asyncio.sleep(3)
                    break
                
                if not headless and waited % 20 == 0:
                    logger.info(f"[muaban_auth] Đang chờ user đăng nhập... ({waited}s/{timeout}s)")

            await ctx.close()
        return success

    def _save_cookies(self, cookies: list[dict]) -> None:
        try:
            # Filter for muaban.net cookies
            relevant = [c for c in cookies if "muaban.net" in c.get("domain", "")]
            data = {
                "cookies": relevant,
                "saved_at": datetime.now(timezone.utc).isoformat()
            }
            COOKIES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info(f"[muaban_auth] Đã lưu {len(relevant)} cookies vào {COOKIES_FILE}")
        except Exception as e:
            logger.error(f"[muaban_auth] Failed to save cookies: {e}")
