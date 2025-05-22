import os
import threading
import asyncio
import statistics
from datetime import datetime

from telethon import TelegramClient, events
from telethon.errors import UsernameNotOccupiedError, ChatAdminRequiredError
from telethon.tl.types import User
from telethon.tl.functions.users import GetFullUserRequest

import http.server
import socketserver

# ─── ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ─────────────────────────────────────────
API_ID    = int(os.environ['API_ID'])
API_HASH  = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
PORT      = int(os.environ.get('PORT', 8000))

# ─── КОНСТАНТЫ ─────────────────────────────────────────────────────
HISTORY_LIMIT = 50   # берём поменьше, чтобы точно уложиться в timeout
TIMEOUT_SEC   = 20   # секунд на сбор информации

# ─── HTTP-сервер для Render ───────────────────────────────────────
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

# ─── ИНИЦИАЛИЗАЦИЯ TELETHON ──────────────────────────────────────
client = TelegramClient('bot_session', API_ID, API_HASH)
client.start(bot_token=BOT_TOKEN)

# ─── /start ───────────────────────────────────────────────────────
@client.on(events.NewMessage(pattern=r'^/start$'))
async def start_handler(event):
    await event.reply(
        "Привет! Я умею проверять публичные данные аккаунтов Telegram.\n"
        "Используй: /info <username_or_link>"
    )

# ─── СБОР ИНФОРМAЦИИ ───────────────────────────────────────────────
async def fetch_info(entity):
    info = {
        'type':     entity.__class__.__name__,
        'id':       entity.id,
        'username': getattr(entity, 'username', None),
        'name':     getattr(entity, 'title', None) or
                    f"{getattr(entity,'first_name','')} {getattr(entity,'last_name','')}".strip()
    }

    # дата создания: если у Channel/Chat есть поле .date
    entity_date = getattr(entity, 'date', None)
    if entity_date:
        info['creation_date'] = entity_date.strftime('%Y-%m-%d')
    else:
        # fallback: первый пост
        first = None
        async for m in client.iter_messages(entity, limit=1, reverse=True):
            first = m
        info['creation_date'] = first.date.strftime('%Y-%m-%d') if first else None

    # подписчики/участники (каналы/группы)
    try:
        info['subscribers'] = (await client.get_participants(entity, limit=0)).total
    except ChatAdminRequiredError:
        info['subscribers'] = 'требуется права администратора'
    except:
        info['subscribers'] = None

    # если обычный пользователь — доп. данные
    if isinstance(entity, User):
        full = await client(GetFullUserRequest(entity.id))
        data = getattr(full, 'full_user', full)
        info.update({
            'is_bot':       entity.bot,
            'is_verified':  getattr(data, 'bot_info', None) is not None,
            'phone':        getattr(entity, 'phone', None),
            'about':        getattr(data, 'about', ''),
            'about_len':    len(getattr(data, 'about', '')),
            'status':       str(getattr(entity, 'status', '')),
            'photos_count': (await client.get_profile_photos(entity, limit=0)).total,
            'common_chats': getattr(data, 'common_chats_count', None),
        })

    # последние сообщения для статистики
    msgs = []
    async for m in client.iter_messages(entity, limit=HISTORY_LIMIT):
        if m.date and m.message:
            msgs.append(m)
    info['total_posts'] = len(msgs)

    # среднее и медиана постов в день
    days = [m.date.date() for m in msgs]
    counts = {}
    for d in days:
        counts[d] = counts.get(d, 0) + 1
    vals = list(counts.values())
    info['avg_per_day']    = round(statistics.mean(vals), 2) if vals else 0
    info['median_per_day'] = statistics.median(vals) if vals else 0

    # реакции
    total_reacts = sum(
        sum(r.count for r in m.reactions.reactions)
        for m in msgs if m.reactions
    )
    info['has_reactions'] = total_reacts > 0

    return info

# ─── /info ────────────────────────────────────────────────────────
@client.on(events.NewMessage(pattern=r'/info(?: |$)(.+)'))
async def handler(event):
    target = event.pattern_match.group(1).strip()
    if target.startswith('http'):
        target = target.rstrip('/').split('/')[-1]

    try:
        entity = await client.get_entity(target)
    except UsernameNotOccupiedError:
        return await event.reply("❌ Не найден пользователь или канал.")
    except Exception as e:
        return await event.reply(f"❌ Ошибка при поиске: {e}")

    msg = await event.reply("🔍 Собираю информацию…")
    try:
        info = await asyncio.wait_for(fetch_info(entity), timeout=TIMEOUT_SEC)
    except asyncio.TimeoutError:
        return await msg.edit("❌ Превышено время ожидания (timeout).")
    except Exception as e:
        return await msg.edit(f"❌ Ошибка при сборе данных: {e}")

    lines = [f"• {k}: {v}" for k, v in info.items()]
    await msg.edit("📊 Информация:\n" + "\n".join(lines))

# ─── СТАРТ ────────────────────────────────────────────────────────
def main():
    threading.Thread(target=run_http, daemon=True).start()
    print("Бот запущен…")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
