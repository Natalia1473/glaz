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

# ─── ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ─────────────────────────────────────────
API_ID   = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
PORT     = int(os.environ.get('PORT', 8000))

# ─── HTTP-сервер для Render (чтобы было прослушиваемое порт) ───────
class PingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, fmt, *args):
        pass

def run_http():
    with socketserver.TCPServer(("", PORT), PingHandler) as srv:
        srv.serve_forever()

# ─── ИНИЦИАЛИЗАЦИЯ ТЕЛЕФОННОГО КЛИЕНТА (ПОЛЬЗОВАТЕЛЬСКАЯ СЕССИЯ) ───
# Обратите внимание: имя сессии должно совпадать с файлом user_session.session
client = TelegramClient('user_session', API_ID, API_HASH)
client.start()  # Читает из user_session.session, никакого токена

# ─── ОБРАБОТЧИК /start ─────────────────────────────────────────────
@client.on(events.NewMessage(pattern=r'^/start$'))
async def start_handler(event):
    await event.reply(
        "Привет! Я User-бот, могу собрать публичные данные о пользователе.\n"
        "Используй: /info <username_or_link>"
    )

# ─── ФУНКЦИЯ СБОРА ИНФОРМАЦИИ О USER ───────────────────────────────
async def fetch_user_info(u: User):
    # Получаем полную информацию
    full = await client(GetFullUserRequest(u.id))
    data = getattr(full, 'full_user', full)

    # Собираем поля
    return {
        'id':           u.id,
        'username':     u.username or '—',
        'name':         f"{u.first_name or ''} {u.last_name or ''}".strip() or '—',
        'is_bot':       u.bot,
        'is_verified':  bool(getattr(data, 'bot_info', None)),
        'status':       str(u.status or ''),
        'about':        getattr(data, 'about', '') or '—',
        'about_len':    len(getattr(data, 'about', '') or ''),
        'photos_count': (await client.get_profile_photos(u, limit=0)).total,
        'common_chats': getattr(data, 'common_chats_count', 0),
    }

# ─── ОБРАБОТЧИК /info ──────────────────────────────────────────────
@client.on(events.NewMessage(pattern=r'/info(?: |$)(.+)'))
async def info_handler(event):
    target = event.pattern_match.group(1).strip()
    if target.startswith('http'):
        target = target.rstrip('/').split('/')[-1]

    try:
        ent = await client.get_entity(target)
    except UsernameNotOccupiedError:
        return await event.reply("❌ Пользователь не найден.")
    except Exception as e:
        return await event.reply(f"❌ Ошибка при поиске: {e}")

    if not isinstance(ent, User):
        return await event.reply("❗ Это не аккаунт. Я работаю только с физлицами.")

    msg = await event.reply("🔍 Собираю данные…")
    try:
        info = await fetch_user_info(ent)
    except Exception as e:
        return await msg.edit(f"❌ Не удалось получить данные: {e}")

    text = "📊 Информация о пользователе:\n" + "\n".join(
        f"• {k}: {v}" for k, v in info.items()
    )
    await msg.edit(text)

# ─── ЗАПУСК БОТА ───────────────────────────────────────────────────
def main():
    # Запускаем HTTP-ping
    threading.Thread(target=run_http, daemon=True).start()
    print("User-бот запущен…")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
