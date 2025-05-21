# bot.py
import asyncio
from telethon import TelegramClient, events
from telethon.errors import UsernameNotOccupiedError
from datetime import datetime, timedelta
import statistics

# ─── НАСТРОЙКИ ─────────────────────────────────────────────────────
api_id   = 1234567           # ваш API ID
api_hash = 'abcdef1234567890abcdef1234567890'
bot_token= '1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ'

# сколько последних сообщений анализировать для статистики
HISTORY_LIMIT = 100  

# ─── ИНИЦИАЛИЗАЦИЯ TELETHON ──────────────────────────────────────
client = TelegramClient('bot_session', api_id, api_hash)
client.start(bot_token=bot_token)


# ─── ФУНКЦИЯ СБОРА ИНФЫ ───────────────────────────────────────────
async def fetch_info(entity):
    info = {}
    # 1) Тип аккаунта
    info['type'] = entity.__class__.__name__  # Channel, Chat, User, etc.
    
    # 2) Кол-во подписчиков / участников
    try:
        count = await client.get_participants(entity, limit=0)
        info['subscribers'] = count.total  # точное число
    except:
        info['subscribers'] = 'неизвестно'
    
    # 3) Дата первого сообщения → приближенно дата создания канала/группы
    first = None
    async for msg in client.iter_messages(entity, limit=1, reverse=True):
        first = msg
    info['creation_date'] = first.date.strftime('%Y-%m-%d') if first else '—'

    # 4) Статистика по последним HISTORY_LIMIT сообщениям
    msgs = []
    async for msg in client.iter_messages(entity, limit=HISTORY_LIMIT):
        if msg.date and msg.message:  # фильтруем системные
            msgs.append(msg)
    info['total_posts'] = len(msgs)
    # подсчёт по дням
    days = [m.date.date() for m in msgs]
    counts = {}
    for d in days:
        counts[d] = counts.get(d, 0) + 1
    # среднее и медиана постов в день
    per_day = list(counts.values())
    info['avg_per_day'] = round(statistics.mean(per_day),2) if per_day else 0
    info['median_per_day'] = statistics.median(per_day) if per_day else 0

    # 5) Активность реакций
    total_reacts = 0
    for m in msgs:
        if m.reactions:
            total_reacts += sum(r.count for r in m.reactions.reactions)
    info['has_reactions'] = total_reacts > 0

    return info


# ─── ОБРАБОТЧИК КОМАНДЫ /info ─────────────────────────────────────
@client.on(events.NewMessage(pattern=r'/info(?: |$)(.*)'))
async def handler(event):
    arg = event.pattern_match.group(1).strip()
    if not arg:
        return await event.reply("Используй: /info <username_or_link>")

    # нормализуем: если ссылка вида https://t.me/...
    username = arg.split('/')[-1]
    try:
        entity = await client.get_entity(username)
    except UsernameNotOccupiedError:
        return await event.reply("Пользователь или канал не найден.")
    except Exception as e:
        return await event.reply(f"Ошибка при получении сущности: {e}")

    msg = await event.reply("Собираю информацию…")
    info = await fetch_info(entity)

    text = (
        f"📊 Информация по `{username}`:\n"
        f"• Тип: `{info['type']}`\n"
        f"• Подписчиков: `{info['subscribers']}`\n"
        f"• Примерная дата создания: `{info['creation_date']}`\n"
        f"• Всего постов в последних {len(days := info.get('total_posts',0))} сообщениях: `{len(days)}`\n"
        f"• Среднее/медиана постов в день: `{info['avg_per_day']}` / `{info['median_per_day']}`\n"
        f"• Есть реакции: `{info['has_reactions']}`"
    )
    await msg.edit(text)


# ─── ЗАПУСК БОТА ──────────────────────────────────────────────────
def main():
    print("Бот запущен…")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
