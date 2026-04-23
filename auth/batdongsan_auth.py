"""
RealEstork — Batdongsan Cookie Refresh via Browser Profile

Flow:
  Setup (một lần duy nhất):
    python -m cli.main setup-batdongsan
    → Mở Chrome visible → Trang đăng nhập batdongsan.com.vn
    → Hỗ trợ 2 loại account:
        (A) Google OAuth: click "Đăng nhập với Google" → chọn account
        (B) SĐT/Email + Password: điền trực tiếp
    → Account phải đã verify SĐT trên batdongsan profile
    → Playwright lưu browser profile vào .batdongsan_browser_profile/
    → Session lưu vài tháng → không cần login lại

  Refresh tự động (mỗi ~30h khi con.ses.id sắp expire):
    BatdongsanAuthClient.refresh_cookies()
    → Mở Chrome headless với profile đã lưu
    → batdongsan.com nhận ra session → user đã login
    → Capture cookies mới (con.ses.id TTL ~38h được reset)
    → Lưu vào .batdongsan_cookies.json (~15-20 giây)
    → Không cần mật khẩu, không cần OTP

  Nếu session hết hạn (hiếm, vài tháng):
    Bot gửi Telegram nhắc: chạy lại setup-batdongsan
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


PROFILE_DIR = Path(".batdongsan_browser_profile").resolve()
COOKIES_FILE = Path(".batdongsan_cookies.json")

_BDS_LOGIN = "https://batdongsan.com.vn/dang-nhap"
_BDS_HOME  = "https://batdongsan.com.vn/"
_BDS_LISTING = "https://batdongsan.com.vn/cho-thue-nha-mat-pho-tp-hcm"

# Cookies bắt buộc để load_cookies() không trả None
# con.ses.id bị loại vì TTL chỉ ~30 phút — con.unl.usr.id (1 năm) mới là auth token thực
_REQUIRED_COOKIES = {"AWSALB", "AWSALBCORS", "con.unl.usr.id"}

# Warn trước khi hết hạn (dựa trên required cookies)
_WARN_BEFORE_HOURS = 24


class BatdongsanAuthClient:
    """
    Quản lý session cookies cho batdongsan.com.vn DecryptPhone API.
    Hỗ trợ cả Google OAuth và SĐT/Email + Password.
    Account phải đã verify SĐT trên batdongsan profile.
    """

    cookies_expired: bool = False  # Set True khi DecryptPhone trả 401/403

    def load_cookies(self) -> dict[str, str] | None:
        """
        Load cookies từ file cho httpx/requests.
        Returns:
            dict  → {name: value} nếu cookies còn hạn
            None  → Chưa setup hoặc bất kỳ required cookie nào đã expired
        """
        if not COOKIES_FILE.exists():
            logger.debug("[bds_auth] Cookies file chưa tồn tại. Chạy: setup-batdongsan")
            return None

        try:
            data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            cookie_map = {c["name"]: c for c in cookies}
            now = datetime.now(timezone.utc).timestamp()

            for name in _REQUIRED_COOKIES:
                c = cookie_map.get(name)
                if not c:
                    continue
                expires = c.get("expires", 0)
                if expires > 0 and now > expires:
                    logger.warning(
                        f"[bds_auth] Cookie '{name}' đã expired. "
                        "Đang trigger auto-refresh..."
                    )
                    return None

            hours_left = self._min_hours_remaining(cookies, now)
            if hours_left is not None and hours_left < _WARN_BEFORE_HOURS:
                logger.warning(
                    f"[bds_auth] Cookies sắp expire trong {hours_left:.1f}h — cần refresh"
                )

            return {c["name"]: c["value"] for c in cookies}

        except Exception as e:
            logger.error(f"[bds_auth] Lỗi đọc cookies file: {e}")
            return None

    def expires_in_hours(self) -> float | None:
        """Số giờ còn lại của required cookie ngắn nhất. None nếu không xác định."""
        if not COOKIES_FILE.exists():
            return None
        try:
            data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            now = datetime.now(timezone.utc).timestamp()
            hours = self._min_hours_remaining(cookies, now)
            return max(0.0, hours) if hours is not None else None
        except Exception:
            pass
        return None

    def is_expired(self) -> bool:
        return self.load_cookies() is None

    def _min_hours_remaining(self, cookies: list[dict], now: float) -> float | None:
        cookie_map = {c["name"]: c for c in cookies}
        min_remaining = None
        for name in _REQUIRED_COOKIES:
            c = cookie_map.get(name)
            if not c:
                continue
            expires = c.get("expires", 0)
            if expires > 0:
                remaining = (expires - now) / 3600
                if min_remaining is None or remaining < min_remaining:
                    min_remaining = remaining
        return min_remaining

    async def refresh_cookies(self) -> bool:
        """
        Headless auto-refresh — dùng profile đã lưu, không cần login lại.

        Returns:
            True  → Cookies mới đã lưu thành công
            False → Session hết hạn, cần chạy setup-batdongsan lại
        """
        if not PROFILE_DIR.exists():
            logger.error(
                "[bds_auth] Browser profile chưa tồn tại. "
                "Chạy: python -m cli.main setup-batdongsan"
            )
            return False
        logger.info("[bds_auth] Đang refresh cookies (headless)...")
        return await self._refresh_headless()

    async def setup_interactive(self) -> bool:
        """
        Mở Chrome visible để user đăng nhập lần đầu (hoặc khi session hết hạn).
        Hỗ trợ cả Google OAuth và SĐT/Email + Password.
        Gọi từ CLI: python -m cli.main setup-batdongsan

        Returns:
            True  → Setup thành công, profile + cookies đã lưu
            False → Timeout hoặc lỗi
        """
        logger.info("[bds_auth] Mở browser để setup (Google OAuth hoặc SĐT/Email + Password)...")
        return await self._setup_visible()

    # ────────────────────────────────────────────────────────────────────

    async def _setup_visible(self) -> bool:
        """
        Setup flow (visible browser):
        1. Xóa TOÀN BỘ profile cũ → đảm bảo không có stale session trong cookies/localStorage/IndexedDB
        2. Navigate thẳng đến trang đăng nhập batdongsan
        3. Chờ user đăng nhập (Google hoặc SĐT/email + password)
        4. Sau khi login: navigate listing → server cấp con.ses.id mới
        5. Lưu cookies + profile mới (dùng cho headless auto-refresh)
        """
        import shutil

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "[bds_auth] playwright chưa được cài. "
                "Chạy: pip install playwright && playwright install chromium"
            )
            return False

        # Xóa profile cũ để đảm bảo clean state tuyệt đối
        # (cookies, localStorage, IndexedDB đều bị reset — tránh auto-login với session cũ)
        if PROFILE_DIR.exists():
            try:
                shutil.rmtree(PROFILE_DIR)
                logger.debug("[bds_auth] Profile cũ đã xóa — bắt đầu fresh session")
            except Exception as ex:
                logger.warning(f"[bds_auth] Không xóa được profile cũ: {ex}")

        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1280, "height": 900},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )

            page = await ctx.new_page()

            # Mở trang chủ — login là popup modal, URL không đổi
            await page.goto(_BDS_HOME, wait_until="domcontentloaded")
            logger.info(
                "[bds_auth] Đã mở batdongsan.com.vn. "
                "Vui lòng click [Đăng nhập] trên header và đăng nhập..."
            )

            timeout_secs = 300  # 5 phút
            waited = 0
            success = False
            navigated_to_listing = False

            while waited < timeout_secs:
                await asyncio.sleep(2)
                waited += 2

                # Detect login bằng DOM text trong header:
                # - Chưa login: header có nút "Đăng nhập" và "Đăng ký" visible
                # - Đã login: các nút đó biến mất, thay bằng user avatar/tên
                try:
                    header_has_login_btn = await page.evaluate("""
                        () => {
                            // Tìm header element
                            const header = document.querySelector(
                                'header, .re__header, #header, [class*="header"]'
                            );
                            if (!header) return true; // Chưa load xong → coi như chưa login

                            // Walk text nodes trong header, tìm "Đăng nhập" visible
                            const walker = document.createTreeWalker(
                                header, NodeFilter.SHOW_TEXT, null, false
                            );
                            let node;
                            while ((node = walker.nextNode())) {
                                if (node.textContent.trim() === 'Đăng nhập') {
                                    const el = node.parentElement;
                                    if (!el) continue;
                                    const s = window.getComputedStyle(el);
                                    const rect = el.getBoundingClientRect();
                                    if (
                                        s.display !== 'none' &&
                                        s.visibility !== 'hidden' &&
                                        rect.width > 0 && rect.height > 0
                                    ) {
                                        return true; // Nút "Đăng nhập" còn visible
                                    }
                                }
                            }
                            return false; // Không tìm thấy → đã login
                        }
                    """)
                except Exception:
                    header_has_login_btn = True  # JS lỗi → coi như chưa login

                if header_has_login_btn:
                    if waited % 10 == 0:
                        logger.debug(f"[bds_auth] Chờ user đăng nhập... ({waited}s/{timeout_secs}s)")
                    continue

                # Nút "Đăng nhập" đã biến mất khỏi header → login thành công!
                if not navigated_to_listing:
                    navigated_to_listing = True
                    logger.info("[bds_auth] Đã login! Navigating để lấy fresh session...")
                    try:
                        await page.goto(_BDS_LISTING, wait_until="domcontentloaded")
                    except Exception:
                        pass
                    await asyncio.sleep(6)
                    continue

                # Capture và save cookies
                now_ts = datetime.now(timezone.utc).timestamp()
                success = await self._save_cookies(await ctx.cookies())
                if success:
                    final_map = {c["name"]: c for c in await ctx.cookies()}
                    ses = final_map.get("con.ses.id", {})
                    ses_hours = (ses.get("expires", 0) - now_ts) / 3600
                    logger.info(f"[bds_auth] Cookies saved! con.ses.id còn {ses_hours:.1f}h")

                # Chờ Chrome flush profile xuống disk trước khi đóng.
                # Windows cần thêm thời gian — nếu close ngay thì Default/ không được ghi.
                logger.debug("[bds_auth] Chờ Chrome flush profile (5s)...")
                await asyncio.sleep(5)
                break

            if not success:
                logger.warning("[bds_auth] Setup timeout — user chưa đăng nhập trong 5 phút")

            await ctx.close()

        return success

    async def _refresh_headless(self) -> bool:
        """
        Headless refresh flow — dùng profile đã lưu để auto-login.
        Dùng networkidle để chờ JS auto-refresh accessToken xong.
        Nếu session hết hạn → trả về False → orchestrator alert Telegram.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[bds_auth] playwright chưa được cài.")
            return False

        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=True,
                viewport={"width": 1280, "height": 900},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )

            page = await ctx.new_page()
            
            # Formulate Playwright cookie domains
            from urllib.parse import urlparse
            def _pw_cookie(entry):
                d = {
                    "name": entry["name"],
                    "value": entry["value"],
                    "domain": entry.get("domain", ".batdongsan.com.vn"),
                    "path": entry.get("path", "/"),
                }
                if "sameSite" in entry and entry["sameSite"] in ("Strict", "Lax", "None"):
                    d["sameSite"] = entry["sameSite"]
                if "secure" in entry:
                    d["secure"] = entry["secure"]
                if "httpOnly" in entry:
                    d["httpOnly"] = entry["httpOnly"]
                if "expires" in entry and entry["expires"] > 0:
                    d["expires"] = entry["expires"]
                return d

            # Force inject any recent cookies we have
            recent_cookies = self.load_cookies()
            if recent_cookies:
                pw_cookies = []
                for name, value in recent_cookies.items():
                    # Minimal cookie injection
                    pw_cookies.append({
                        "name": name,
                        "value": value,
                        "domain": ".batdongsan.com.vn",
                        "path": "/",
                    })
                try:
                    await ctx.add_cookies(pw_cookies)
                except Exception as e:
                    logger.warning(f"[bds_auth] Failed to pre-inject cookies: {e}")

            # networkidle đảm bảo JS đã chạy xong và auto-refresh accessToken
            try:
                await page.goto(_BDS_LISTING, wait_until="networkidle", timeout=60000)
            except Exception:
                await page.goto(_BDS_LISTING, wait_until="domcontentloaded", timeout=30000)

            # Chờ thêm để JS hoàn tất token refresh / render login state
            await asyncio.sleep(10)

            # Kiểm tra login bằng cookie c_u_id (non-HttpOnly, JS-readable)
            # Không dùng header text vì có thể render trước khi token refresh xong
            try:
                c_u_id = await page.evaluate(
                    "() => document.cookie.split(';').map(c=>c.trim()).find(c=>c.startsWith('c_u_id=')) || ''"
                )
                is_logged_in = bool(c_u_id and c_u_id.split('=')[1].strip())
            except Exception:
                is_logged_in = False

            success = False
            if is_logged_in:
                logger.debug("[bds_auth] Đã login (c_u_id present), saving cookies...")
                now_ts = datetime.now(timezone.utc).timestamp()
                saved = await self._save_cookies(await ctx.cookies())
                if saved:
                    final_map = {c["name"]: c for c in await ctx.cookies()}
                    at = final_map.get("accessToken", {})
                    at_expires = at.get("expires", 0)
                    at_hours = (at_expires - now_ts) / 3600 if at_expires > 0 else 0
                    logger.info(f"[bds_auth] Cookies saved! accessToken cookie còn {at_hours:.0f}h")
                    # Verify the saved accessToken JWT is actually fresh (not just the
                    # stale cookie from the Playwright profile — server may have invalidated
                    # the session even if c_u_id still exists in the browser jar).
                    if self._is_access_token_fresh():
                        success = True
                    else:
                        logger.warning(
                            "[bds_auth] Headless refresh saved cookies but accessToken JWT "
                            "vẫn hết hạn — session bị invalidate server-side. "
                            "Cần chạy lại: setup-batdongsan"
                        )
                        self.cookies_expired = True
            else:
                logger.warning(
                    "[bds_auth] Headless: c_u_id không có — session hết hạn. "
                    "Cần chạy lại: setup-batdongsan"
                )

            await ctx.close()

        return success

    # ────────────────────────────────────────────────────────────────────
    # curl_cffi-based phone reveal (bypasses Cloudflare via Firefox133 TLS)
    # ────────────────────────────────────────────────────────────────────

    def refresh_via_ums(self) -> bool:
        """
        Refresh accessToken via UMS endpoint using curl_cffi Firefox133 fingerprint.
        Bypasses Cloudflare — gets 200 from UMS if session is still valid.
        Updates cookies file with new accessToken.

        Returns:
            True  → accessToken refreshed and saved
            False → session expired (isSuccess:false) or network error
        """
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError:
            logger.error("[bds_auth] curl_cffi chưa cài. Chạy: pip install curl_cffi")
            return False

        cookies = self.load_cookies()
        if not cookies:
            logger.warning("[bds_auth] Không có cookies để gọi UMS refresh")
            return False

        UMS_REFRESH_URL = (
            "https://batdongsan.com.vn"
            "/user-management-service/api/v1/User/RefreshToken"
        )

        try:
            resp = cffi_requests.get(
                UMS_REFRESH_URL,
                cookies=cookies,
                headers={
                    "Origin": "https://batdongsan.com.vn",
                    "Referer": "https://batdongsan.com.vn/",
                    "X-Requested-With": "XMLHttpRequest",
                },
                impersonate="firefox133",
                timeout=15,
            )
        except Exception as e:
            logger.error(f"[bds_auth] UMS refresh network error: {e}")
            return False

        logger.debug(f"[bds_auth] UMS refresh HTTP {resp.status_code}")

        if resp.status_code != 200:
            logger.warning(f"[bds_auth] UMS refresh HTTP {resp.status_code} — unexpected")
            return False

        try:
            data = resp.json()
        except Exception:
            logger.warning(f"[bds_auth] UMS refresh: không parse được JSON: {resp.text[:200]}")
            return False

        if not data.get("isSuccess"):
            logger.warning(
                "[bds_auth] UMS refresh isSuccess=false — session hết hạn server-side. "
                "Cần chạy lại: python -m cli.main setup-batdongsan"
            )
            self.cookies_expired = True
            return False

        # Extract new cookies from response Set-Cookie headers
        new_cookies = {name: value for name, value in resp.cookies.items()}
        if not new_cookies:
            logger.warning("[bds_auth] UMS refresh: không có cookies mới trong response")
            return False

        if self._update_cookies_file(new_cookies):
            logger.info(
                f"[bds_auth] UMS refresh OK — {len(new_cookies)} cookies updated: "
                f"{list(new_cookies.keys())}"
            )
            return True

        return False

    def _update_cookies_file(self, new_cookies: dict[str, str]) -> bool:
        """Update specific cookies in the JSON file with fresh values from UMS refresh."""
        try:
            if not COOKIES_FILE.exists():
                return False

            data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            existing_names = {c["name"] for c in cookies}
            now_ts = datetime.now(timezone.utc).timestamp()
            updated = 0

            for i, c in enumerate(cookies):
                if c["name"] in new_cookies:
                    cookies[i] = {**c, "value": new_cookies[c["name"]]}
                    updated += 1

            # Add completely new cookies not previously in file
            for name, value in new_cookies.items():
                if name not in existing_names:
                    cookies.append({
                        "name": name,
                        "value": value,
                        "domain": ".batdongsan.com.vn",
                        "path": "/",
                        "expires": now_ts + 3600,  # 1h default
                        "httpOnly": False,
                        "secure": True,
                        "sameSite": "None",
                    })
                    updated += 1

            data["cookies"] = cookies
            data["ums_refreshed_at"] = datetime.now(timezone.utc).isoformat()
            COOKIES_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug(f"[bds_auth] _update_cookies_file: {updated} entries updated")
            return True

        except Exception as e:
            logger.error(f"[bds_auth] Lỗi update cookies file: {e}")
            return False

    def _is_access_token_fresh(self, min_seconds: int = 120) -> bool:
        """
        Return True if accessToken JWT exp claim is at least min_seconds in the future.
        Decodes JWT payload directly (no signature verification needed).
        Falls back to cookie expires attribute if JWT decode fails.
        """
        if not COOKIES_FILE.exists():
            return False
        try:
            import base64 as _b64
            data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            now = datetime.now(timezone.utc).timestamp()
            for c in data.get("cookies", []):
                if c["name"] == "accessToken":
                    token = c.get("value", "")
                    parts = token.split(".")
                    if len(parts) == 3:
                        # base64url decode JWT payload (pad to multiple of 4)
                        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
                        payload = json.loads(_b64.urlsafe_b64decode(payload_b64))
                        jwt_exp = payload.get("exp", 0)
                        fresh = jwt_exp > now + min_seconds
                        if not fresh:
                            logger.debug(
                                f"[bds_auth] accessToken JWT exp "
                                f"{datetime.fromtimestamp(jwt_exp, tz=timezone.utc).strftime('%H:%M UTC')} "
                                f"— đã hết hạn, cần UMS refresh"
                            )
                        return fresh
                    # Fallback: cookie expires attribute
                    return c.get("expires", 0) > now + min_seconds
        except Exception as e:
            logger.debug(f"[bds_auth] _is_access_token_fresh error: {e}")
        return False

    async def decrypt_phones_via_cffi(
        self,
        payloads: list[dict],
        account_phone: str = "",
    ) -> dict[str, str]:
        """
        Decrypt phone numbers using curl_cffi Firefox133 TLS fingerprint.
        Cloudflare bypass — gets 401 (auth) instead of 403 (CF block).
        Refreshes accessToken via UMS before calling DecryptPhone if needed.

        Args:
            payloads: list of {raw, prid, uid}
            account_phone: BDS_ACCOUNT_PHONE from .env (optional)

        Returns:
            dict prid → phone_number (only successfully revealed)
        """
        if not payloads:
            return {}

        try:
            from curl_cffi import requests as cffi_requests
        except ImportError:
            logger.error("[bds_auth] curl_cffi chưa cài. Chạy: pip install curl_cffi")
            return {}

        # Refresh accessToken via UMS if it's expired or about to expire
        loop = asyncio.get_event_loop()
        if not self._is_access_token_fresh():
            logger.info("[bds_auth] accessToken cũ/hết hạn — đang refresh via UMS...")
            await loop.run_in_executor(None, self.refresh_via_ums)
            if self.cookies_expired:
                logger.warning("[bds_auth] Session hết hạn — không thể decrypt phones")
                return {}

        cookies = self.load_cookies()
        if not cookies:
            logger.warning("[bds_auth] Không có cookies để decrypt phones")
            return {}

        DECRYPT_URL = (
            "https://batdongsan.com.vn"
            "/microservice-architecture-router/Product/ProductDetail/DecryptPhone"
        )

        import re as _re
        import time as _time

        access_token = cookies.get("accessToken", "")

        def _decrypt_batch() -> dict[str, str]:
            result: dict[str, str] = {}
            for p in payloads:
                raw = p.get("raw", "")
                prid = str(p.get("prid", ""))
                uid = p.get("uid", "")
                if not raw:
                    continue

                form_data = {
                    "PhoneNumber": raw,
                    "createLead[sellerId]": uid or "",
                    "createLead[productId]": prid,
                    "createLead[productType]": "0",
                    "createLead[leadSourcePage]": "BDS_SEARCH_RESULT_PAGE",
                    "createLead[leadSourceAction]": "PHONE_REVEAL",
                    "createLead[fromLeadType]": "AGENT_LISTING",
                }
                if account_phone:
                    form_data["createLead[mobile]"] = account_phone

                req_headers = {
                    "Origin": "https://batdongsan.com.vn",
                    "Referer": "https://batdongsan.com.vn/cho-thue-nha-mat-pho-tp-hcm",
                    "X-Requested-With": "XMLHttpRequest",
                }
                if access_token:
                    req_headers["Authorization"] = f"Bearer {access_token}"

                try:
                    resp = cffi_requests.post(
                        DECRYPT_URL,
                        data=form_data,
                        cookies=cookies,
                        headers=req_headers,
                        impersonate="firefox133",
                        timeout=10,
                    )

                    if resp.status_code == 200:
                        text = resp.text.strip().lstrip("|").strip()
                        digits = _re.sub(r"\D", "", text)
                        if digits.startswith("84") and len(digits) == 11:
                            digits = "0" + digits[2:]
                        if len(digits) == 10:
                            result[prid] = digits
                        else:
                            logger.debug(
                                f"[bds_auth] Decrypt 200 but unexpected body prid={prid}: {text[:60]}"
                            )
                    elif resp.status_code == 429:
                        logger.warning(
                            f"[bds_auth] DecryptPhone 429 — chờ 20s rồi retry "
                            f"({len(result)}/{len(payloads)} đã lấy)"
                        )
                        _time.sleep(20)
                        try:
                            resp = cffi_requests.post(
                                DECRYPT_URL,
                                data=form_data,
                                cookies=cookies,
                                headers=req_headers,
                                impersonate="firefox133",
                                timeout=10,
                            )
                            if resp.status_code == 200:
                                text = resp.text.strip().lstrip("|").strip()
                                digits = _re.sub(r"\D", "", text)
                                if digits.startswith("84") and len(digits) == 11:
                                    digits = "0" + digits[2:]
                                if len(digits) == 10:
                                    result[prid] = digits
                            elif resp.status_code == 429:
                                logger.warning(
                                    f"[bds_auth] DecryptPhone vẫn 429 sau retry — dừng batch, "
                                    f"đã lấy {len(result)}/{len(payloads)}"
                                )
                                break
                        except Exception as e:
                            logger.error(f"[bds_auth] DecryptPhone retry error: {e}")
                            break
                    elif resp.status_code in (401, 403):
                        logger.warning(
                            f"[bds_auth] DecryptPhone {resp.status_code} prid={prid} — "
                            "accessToken hết hạn hoặc session invalid"
                        )
                        self.cookies_expired = True
                        break
                    else:
                        logger.debug(
                            f"[bds_auth] DecryptPhone {resp.status_code} prid={prid}: "
                            f"{resp.text[:60]}"
                        )

                except Exception as e:
                    logger.error(f"[bds_auth] DecryptPhone error prid={prid}: {e}")

                _time.sleep(2.0)  # 0.5 req/s — tránh rate limit BDS

            return result

        phone_map = await loop.run_in_executor(None, _decrypt_batch)
        return phone_map

    async def fetch_phone_via_profile(
        self,
        payloads: list[dict],
        account_phone: str = "",
    ) -> dict[str, str]:
        """
        Deprecated: Playwright Chromium is Cloudflare-blocked for batdongsan.
        Delegates to decrypt_phones_via_cffi() which uses curl_cffi Firefox133.
        """
        logger.debug(
            "[bds_auth] fetch_phone_via_profile → delegating to decrypt_phones_via_cffi"
        )
        return await self.decrypt_phones_via_cffi(payloads, account_phone=account_phone)

    async def _save_cookies(self, cookies: list[dict]) -> bool:
        """Lưu cookies batdongsan domain vào COOKIES_FILE."""
        try:
            bds_cookies = [
                c for c in cookies
                if "batdongsan" in c.get("domain", "")
            ]

            if not bds_cookies:
                logger.error("[bds_auth] Không tìm thấy cookies của batdongsan.com.vn")
                return False

            data = {
                "cookies": bds_cookies,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            COOKIES_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            for c in bds_cookies:
                if c["name"] == "con.ses.id" and c.get("expires", 0) > 0:
                    expires_dt = datetime.fromtimestamp(c["expires"], tz=timezone.utc)
                    logger.info(
                        f"[bds_auth] con.ses.id expires: "
                        f"{expires_dt.strftime('%d/%m/%Y %H:%M UTC')}"
                    )

            logger.info(f"[bds_auth] Đã lưu {len(bds_cookies)} cookies → {COOKIES_FILE}")
            return True

        except Exception as e:
            logger.error(f"[bds_auth] Lỗi lưu cookies: {e}")
            return False
