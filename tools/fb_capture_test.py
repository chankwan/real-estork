"""
RealEstork — FB capture TEST harness (standalone, không đụng bot production).

Mục đích: cho anh THẤY post THẬT từ group Facebook chảy vào Telegram, trước khi
go-live. Chạy receiver localhost + mỗi vài giây rút hàng đợi → parse (district /
giá / SĐT) → chấm điểm → gửi tóm tắt vào ADMIN chat (riêng, không spam group vợ).

KHÔNG ghi DB, KHÔNG tạo instance orchestrator (an toàn với bot đang chạy PID khác,
vì receiver port riêng nếu cần). Dừng bằng Ctrl+C.

Cách dùng:
    venv\\Scripts\\python.exe -X utf8 -m tools.fb_capture_test
Tuỳ chọn: --port 8787  --token XXX  (mặc định đọc từ config/spiders.yaml + .env)
"""

from __future__ import annotations

import argparse
import asyncio

import yaml
from dotenv import load_dotenv
from loguru import logger

from ingest.fb_receiver import start_receiver, drain
from spiders.facebook_groups import FacebookGroupsSpider
from pipeline.classifier import ClassificationPipeline
from notifications.telegram import TelegramNotifier

load_dotenv()


def _fb_config() -> dict:
    with open("config/spiders.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for s in cfg.get("spiders", []):
        if s.get("name") == "facebook_groups":
            return s
    return {}


def _fmt(listing, result) -> str:
    price = (
        f"{listing.price_vnd_monthly/1_000_000:.0f} triệu"
        if listing.price_vnd_monthly else "?"
    )
    text = (listing.description or "").replace("\n", " ").strip()
    return (
        f"🆕 <b>FB capture test</b>\n"
        f"👤 {listing.contact_name or '?'} | 🏷️ score <b>{result.score}</b> {result.label}\n"
        f"📍 {listing.district or '?'} | 💰 {price} | 📞 {listing.phone or '—'}\n"
        f"📝 {text[:180]}\n"
        f"🔗 {listing.source_url}"
    )


async def main() -> None:
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--token", type=str, default=None)
    ap.add_argument("--interval", type=float, default=3.0, help="giây giữa mỗi lần drain")
    args = ap.parse_args()

    fb = _fb_config()
    host = str(fb.get("ingest_host", "127.0.0.1"))
    port = args.port or int(fb.get("ingest_port", 8787))
    token = args.token or os.environ.get("FB_INGEST_TOKEN", str(fb.get("ingest_token", "")))

    if not start_receiver(host, port, token):
        logger.error("Không khởi động được receiver — có thể bot production đang chiếm port. "
                     "Chạy lại với --port khác (vd --port 8790) và sửa port trong userscript.")
        return

    spider = FacebookGroupsSpider({"groups": []})
    classifier = ClassificationPipeline("config/scoring.yaml")
    telegram = TelegramNotifier()

    admin = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not admin:
        logger.error("TELEGRAM_ADMIN_CHAT_ID chưa set trong .env")
        return

    logger.info(
        f"✅ Test harness sẵn sàng. Receiver: http://{host}:{port}/ingest (token={'set' if token else 'OFF'}). "
        f"Mở 1 group FB thật với userscript → post sẽ hiện trong admin chat. Ctrl+C để dừng."
    )
    await telegram.send_admin(
        "🧪 <b>RealEstork FB capture test</b> đang chạy.\n"
        "Mở 1 group Facebook thật (có userscript) → post capture sẽ hiện ở đây."
    )

    seen: set[str] = set()
    try:
        while True:
            raw_posts = drain()
            for rp in raw_posts:
                try:
                    listing = spider.parse_listing(rp)
                except Exception as e:
                    logger.warning(f"parse error: {type(e).__name__}: {e}")
                    continue
                if listing is None or listing.source_id in seen:
                    continue
                seen.add(listing.source_id)
                result = classifier.classify(listing, phone_stats={}, ai_result=None)
                logger.info(
                    f"capture {listing.source_id}: district='{listing.district}' "
                    f"price={listing.price_vnd_monthly} phone='{listing.phone}' score={result.score}"
                )
                await telegram.send_admin(_fmt(listing, result))
            await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Dừng test harness.")


if __name__ == "__main__":
    asyncio.run(main())
