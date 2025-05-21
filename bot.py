import os
import asyncio
from telethon import TelegramClient, events
from telethon.errors import UsernameNotOccupiedError
from telethon.tl.types import User
from telethon.tl.functions.users import GetFullUserRequest
from datetime import datetime
import statistics

# ─── ПОДСТЯЖКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ───────────────────────────────
api_id    = int(os.environ['API_ID'])
api_hash  = os.environ['API_HASH']
bot_token = os.environ['BOT_TOKEN']

# ─── КОНСТАНТЫ ─────────────────────────────────────────────────────
HISTORY_LIMIT = 100  # сколько последних сообщений анализировать

# ─── ИНИЦИАЛИЗАЦИЯ TELETHON ──────────────────────────────────────
client = TelegramClient('bot_session', api_id, api_hash)
client.start(bot_token=bot_token)

# ─── ФУНКЦИЯ СБОРА ИНФОРМАЦИИ ─────────────────────────────────────
async def fetch_info(entity):
    info = {
        'type': entity.__class__.__name__,
        'id': entity.id,
        'username': getattr(entity, 'username', None),
        'name': getattr(entity, 'title', None) or f"{getattr(entity, 'first_name','') or ''} {getattr(entity,'last_name','') or ''}".strip()
    }

    # подписчики/участники (для каналов и групп)
    try:
        info['subscribers'] = (await client.get_participants(entity, limit=0)).total
    except:
        info['subscribers'] = None

    # доп. для обычных пользователей
    if isinstance(entity, User):
        full = await client(GetFullUserRequest(entity.id))
        info.update({
            'is_bot': entity.bot,
            'is_verified': getattr(full.user, 'bot_info', None) is not None,
            'phone': getattr(full.user, 'phone', None),
            'about': getattr(full, 'about', ''),
            'about_len': len(getattr(full, 'about', '')),
            'status': str(getattr(entity, 'status', '')),
            'photos_count': (await client.get_profile_photos(entity, limit=0)).total,
            'common_chats': full.common_chats_count,
        })

    # определяем примерную дату создания — по первому сообщению
    first_msg = None
    async for m in client.iter_messages(entity, limit=1, reverse=True):
        first_msg = m
    info['creation_date'] = first_msg.date.strftime('%Y-%m-%d') if first_msg else None

    # анализ последних HISTORY_LIMIT сообщений
    msgs = []
    async for m in client.iter_messages(entity, limit=HISTORY_LIMIT):
        if m.date and m.message:
            msgs.append(m)

    info['total_posts'] = len(msgs)
    # посчитаем посты в день
    days = [m.date.date() for m in msgs]
    counts = {}
    for d in days:
        counts[d] = counts.get(d, 0) + 1
    per_day = list(counts.values())
    info['avg_per_day'] = round(statistics.mean(per_day), 2) if per_day else 0
    info['median_per_day'] = statistics.median(per_day) if per_day else 0

    # реакции
    total_reacts = sum(
        sum(r.count for r in m.reactions.reactions)
        for m in msgs
        if m.reactions
    )
    info['has_reactions'] = total_reacts > 0

    return info

# ─── ОБРАБОТЧИК КОМАНДЫ /info ─────────────────────────────────────
@client.on(events.NewMessage(pattern=r'/info(?: |$)(.+)'))
async def handler(event):
    target = event.pattern_match.group(1).strip()
    # если ссылка вида https://t.me/…
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

    # форматируем ответ
    lines = [f"• {k}: {v}" for k, v in info.items()]
    await event.reply("📊 Информация:\n" + "\n".join(lines))

# ─── СТАРТ БОТА ──────────────────────────────────────────────────
def main():
    print("Бот запущен…")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
