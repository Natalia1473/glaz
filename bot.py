import os
import threading
import statistics
from datetime import datetime

from telethon import TelegramClient, events
from telethon.errors import UsernameNotOccupiedError
from telethon.tl.types import User
from telethon.tl.functions.users import GetFullUserRequest

import http.server
import socketserver

# ─── ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ────────────────────────────────────────
API_ID   = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
PORT     = int(os.environ.get('PORT', 8000))

# ─── HTTP-ping для Render ────────────────────────────────────────
class PingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *args):
        pass

def run_http():
    with socketserver.TCPServer(("", PORT), PingHandler) as srv:
        srv.serve_forever()

# ─── Инициализация Telethon (user-сессия) ─────────────────────────
client = TelegramClient('user_session', API_ID, API_HASH)
client.start()

# ─── /start ───────────────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'^/start$'))
async def start_handler(event):
    await event.reply(
        "Привет! Я User-бот. Отправь мне:\n"
        "/info <username_or_link>\n"
        "— и я соберу публичные данные и проверю на признаки фейка."
    )

# ─── Сбор данных о пользователе ────────────────────────────────────
async def fetch_user_info(u: User):
    full = await client(GetFullUserRequest(u.id))
    data = getattr(full, 'full_user', full)
    return {
        'id':           u.id,
        'username':     u.username or '—',
        'name':         f"{u.first_name or ''} {u.last_name or ''}".strip() or '—',
        'is_bot':       u.bot,
        'is_verified':  bool(getattr(data, 'bot_info', None)),
        'status':       str(u.status or ''),
        'about_len':    len(getattr(data, 'about', '') or ''),
        'photos_count': (await client.get_profile_photos(u, limit=0)).total,
        'common_chats': getattr(data, 'common_chats_count', 0),
    }

# ─── Эвристики фейка ──────────────────────────────────────────────
def check_fake(info: dict) -> (bool, list[str]):
    reasons = []
    if info['about_len'] == 0:
        reasons.append("нет био")
    if info['photos_count'] == 0:
        reasons.append("нет фото профиля")
    if info['common_chats'] == 0:
        reasons.append("нет общих чатов")
    is_fake = len(reasons) >= 2
    return is_fake, reasons

# ─── /info ───────────────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'/info(?: |$)(.+)'))
async def info_handler(event):
    arg = event.pattern_match.group(1).strip()
    if arg.startswith('http'):
        arg = arg.rstrip('/').split('/')[-1]

    try:
        ent = await client.get_entity(arg)
    except UsernameNotOccupiedError:
        return await event.reply("❌ Пользователь не найден.")
    except Exception as e:
        return await event.reply(f"❌ Ошибка при поиске: {e}")

    if not isinstance(ent, User):
        return await event.reply("❗ Я работаю только с аккаунтами пользователей.")

    msg = await event.reply("🔍 Собираю данные…")
    try:
        info = await fetch_user_info(ent)
    except Exception as e:
        return await msg.edit(f"❌ Не удалось получить данные: {e}")

    # проверяем на фейк
    is_fake, reasons = check_fake(info)

    # формируем ответ
    lines = [
        f"• id: {info['id']}",
        f"• username: {info['username']}",
        f"• name: {info['name']}",
        f"• is_bot: {info['is_bot']}",
        f"• is_verified: {info['is_verified']}",
        f"• status: {info['status']}",
        f"• about_len: {info['about_len']}",
        f"• photos_count: {info['photos_count']}",
        f"• common_chats: {info['common_chats']}",
    ]
    verdict = ("⚠️ *Возможный фейк*:\n" + "  – ".join(reasons)) if is_fake else "✅ Похоже на реального пользователя"
    await msg.edit("📊 Информация о пользователе:\n" + "\n".join(lines) + "\n\n" + verdict)

# ─── Запуск ───────────────────────────────────────────────────────
def main():
    threading.Thread(target=run_http, daemon=True).start()
    print("User-бот запущен…")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
