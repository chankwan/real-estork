"""
RealEstork — lấy message_thread_id của 1 topic Telegram.

Dùng để thêm topic mới (vd "Facebook Groups") vào routing. Cách dùng:
  1. Trong group Telegram, tạo topic mới.
  2. Gửi 1 tin nhắn bất kỳ vào topic đó (vd "test").
  3. Chạy:  venv\\Scripts\\python.exe -X utf8 -m tools.tg_get_topic_id
  4. Script in ra chat_id + message_thread_id + tên topic của các tin nhắn gần đây.
  5. Copy message_thread_id của topic FB → set vào .env:  TELEGRAM_FB_TOPIC_ID=<số đó>
     → restart bot. Alert FB sẽ vào đúng topic.

Lưu ý: Telegram chỉ giữ update ~24h. Nếu không thấy gì, gửi lại tin trong topic rồi chạy lại.
Đừng chạy khi bot đang poll getUpdates (bot này chỉ gửi, không poll → an toàn).
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from telegram import Bot

load_dotenv()


async def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN chưa set trong .env")
        return

    bot = Bot(token=token)
    updates = await bot.get_updates(timeout=5)

    if not updates:
        print("⚠️ Không có update nào. Gửi 1 tin nhắn vào topic mới rồi chạy lại (trong vòng 24h).")
        return

    seen: set[tuple] = set()
    print(f"\n{'chat_id':<18} {'thread_id':<10} topic / nội dung")
    print("-" * 70)
    for u in updates:
        msg = u.message or u.channel_post or (u.edited_message if hasattr(u, "edited_message") else None)
        if not msg:
            continue
        chat_id = msg.chat.id
        thread_id = getattr(msg, "message_thread_id", None)
        topic_name = ""
        if getattr(msg, "forum_topic_created", None):
            topic_name = f"[TOPIC TẠO MỚI: {msg.forum_topic_created.name}]"
        text = (msg.text or msg.caption or "").replace("\n", " ")[:40]
        key = (chat_id, thread_id)
        if key in seen:
            continue
        seen.add(key)
        label = topic_name or text or "(không có text)"
        print(f"{str(chat_id):<18} {str(thread_id):<10} {label}")
    print("-" * 70)
    print("→ thread_id của topic FB chính là số ở cột giữa. Set: TELEGRAM_FB_TOPIC_ID=<số>")


if __name__ == "__main__":
    asyncio.run(main())
