import os
import asyncio
import threading
from datetime import datetime
import statistics

from telethon import TelegramClient, events
from telethon.errors import UsernameNotOccupiedError
from telethon.tl.types import User
from telethon.tl.functions.users import GetFullUserRequest
from aiohttp import web

# ─── ПУЛЬ ОКРУЖЕНИЯ ──────────────────────────────────────────────
API_ID    = int(os.environ['API_ID'])
API_HASH  = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
PORT      = int(os.environ.get('PORT', 8000))

# ─── КОНСТАНТЫ ─────────────────────────────────────────────────────
HISTORY_LIMIT = 100

# ─── TELETHON ─────────────────────────────────────────────────────
client = TelegramClient('bot_session', API_ID, API_HASH)
client.start(bot_token=BOT_TOKEN)

async def fetch_info(entity):
    info = {
        'type': entity.__class__.__name__,
        'id': entity.id,
        'username': getattr(entity, 'username', None),
        'name': getattr(entity, 'title', None) or f"{getattr(entity, 'first_name','')} {getattr(entity,'last_name','')}".strip()
    }

    # подписчики/участники
    try:
        info['subscribers'] = (await client.get_participants(entity, limit=0)).total
    except:
        info['subscribers'] = None

    # для User
    if isinstance(entity, User):
        full = await client(GetFullUserRequest(entity.id))
        info.update({
            'is_bot':    entity.bot,
            'is_verified': getattr(full.user, 'bot_info', None) is not None,
            'phone':     getattr(full.user, 'phone', None),
            'about':     getattr(full, 'about', ''),
            'about_len': len(getattr(full, 'about', '')),
            'status':    str(getattr(entity, 'status', '')),
            'photos_count': (await client.get_profile_photos(entity, limit=0)).total,
            'common_chats': full.common_chats_count,
        })

    # дата первого сообщения
    first = None
    async for m in client.iter_messages(entity, limit=1, reverse=True):
        first = m
    info['creation_date'] = first.date.strftime('%Y-%m-%d') if first else None

    # последние HISTORY_LIMIT сообщений
    msgs = [m for m in await client.get_messages(entity, limit=HISTORY_LIMIT) if m.date and m.message]
    info['total_posts'] = len(msgs)

    days = [m.date.date() for m in msgs]
    counts = {}
    for d in days:
        counts[d] = counts.get(d, 0) + 1
    per_day = list(counts.values())
    info['avg_per_day']    = round(statistics.mean(per_day), 2) if per_day else 0
    info['median_per_day'] = statistics.median(per_day) if per_day else 0

    total_reacts = sum(
        sum(r.count for r in m.reactions.reactions)
        for m in msgs if m.reactions
    )
    info['has_reactions'] = total_reacts > 0

    return info

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
        return await event.reply(f"❌ Ошибка: {e}")

    await event.reply("🔍 Собираю информацию…")
    info = await fetch_info(entity)

    lines = [f"• {k}: {v}" for k, v in info.items()]
    await event.reply("📊 Информация:\n" + "\n".join(lines))

def run_http():
    async def ping(request):
        return web.Response(text="OK")
    app = web.Application()
    app.router.add_get('/', ping)
    web.run_app(app, port=PORT)

def main():
    threading.Thread(target=run_http, daemon=True).start()
    print("Бот запущен…")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
