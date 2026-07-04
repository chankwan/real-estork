"""
RealEstork — Facebook Group ingest receiver (PUSH model).

Khác 3 spider portal (PULL: Python tự fetch web): userscript Tampermonkey chạy
trên Chrome (profile riêng, login via FB, là member 9 group đóng) đọc THỤ ĐỘNG
post hiện trên màn hình rồi POST về đây qua localhost. Receiver chỉ nhận + xếp
hàng; FacebookGroupsSpider rút hàng đợi mỗi nhịp lịch và đẩy vào pipeline
dedup → classify → telegram như mọi nguồn khác.

Anti-abuse: bind 127.0.0.1 (chỉ tiến trình cùng máy POST được) + shared-secret
token header. Zero dependency ngoài stdlib (http.server + queue + threading).
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from loguru import logger

_MAX_BODY_BYTES = 8 * 1024 * 1024  # 8 MB hard cap / request

_inbox: "queue.Queue[dict[str, Any]]" = queue.Queue()
_token: str = ""
_server: ThreadingHTTPServer | None = None


def pending_count() -> int:
    """Số post đang chờ trong hàng đợi."""
    return _inbox.qsize()


def drain(max_items: int | None = None) -> list[dict[str, Any]]:
    """Rút tất cả (hoặc tối đa max_items) post đang chờ. Không blocking."""
    out: list[dict[str, Any]] = []
    while max_items is None or len(out) < max_items:
        try:
            out.append(_inbox.get_nowait())
        except queue.Empty:
            break
    return out


class _Handler(BaseHTTPRequestHandler):
    server_version = "RealEstorkIngest/1.0"

    def _reply(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        # Userscript chạy trên origin facebook.com → cần CORS để fetch() không bị chặn.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Ingest-Token")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 — CORS preflight
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Ingest-Token")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._reply(200, {"ok": True, "pending": pending_count()})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/ingest":
            self._reply(404, {"error": "not found"})
            return
        if _token and self.headers.get("X-Ingest-Token") != _token:
            self._reply(401, {"error": "bad token"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY_BYTES:
            self._reply(400, {"error": "bad content-length"})
            return
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._reply(400, {"error": f"bad json: {e}"})
            return

        posts = data.get("posts") if isinstance(data, dict) else data
        if not isinstance(posts, list):
            self._reply(400, {"error": "expected a list under 'posts'"})
            return

        accepted = 0
        for p in posts:
            if isinstance(p, dict):
                _inbox.put(p)
                accepted += 1
        logger.debug(f"[fb_receiver] accepted {accepted} posts (pending={pending_count()})")
        self._reply(200, {"received": accepted, "pending": pending_count()})

    def log_message(self, fmt: str, *args: Any) -> None:  # mute default stderr access log
        return


def start_receiver(host: str = "127.0.0.1", port: int = 8787, token: str = "") -> bool:
    """
    Khởi động HTTP ingest server trong 1 daemon thread. Idempotent (gọi lần 2 = no-op).
    Trả True nếu đang chạy, False nếu bind fail (vd port đã bị chiếm).
    """
    global _server, _token
    if _server is not None:
        logger.debug("[fb_receiver] already running")
        return True
    _token = token or ""
    try:
        _server = ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        logger.error(f"[fb_receiver] không bind được {host}:{port} — {type(e).__name__}: {e}")
        return False
    threading.Thread(target=_server.serve_forever, name="fb-ingest", daemon=True).start()
    logger.info(
        f"[fb_receiver] FB receiver listening on http://{host}:{port}/ingest "
        f"(token={'set' if _token else 'OFF'})"
    )
    return True
