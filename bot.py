import os
import threading
import re
from datetime import datetime

from telethon import TelegramClient, events
from telethon.errors import UsernameNotOccupiedError
from telethon.tl.types import (
    User, UserStatusOnline, UserStatusOffline,
    UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth,
    InputPhoneContact
)
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest

import http.server
import socketserver

import phonenumbers
from phonenumbers import geocoder, carrier, timezone
import requests

# ─── ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ─────────────────────────────────────────
API_ID        = int(os.environ['API_ID'])
API_HASH      = os.environ['API_HASH']
NUMVERIFY_KEY = os.environ.get('NUMVERIFY_KEY')  # если есть
PORT          = int(os.environ.get('PORT', 8000))

# ─── HTTP-ping для Render ─────────────────────────────────────────
class _Ping(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *args): pass

threading.Thread(
    target=lambda: socketserver.TCPServer(("", PORT), _Ping).serve_forever(),
    daemon=True
).start()

# ─── Инициализация Telethon (user-сессия) ─────────────────────────
client = TelegramClient('user_session', API_ID, API_HASH)
client.start()

# ─── Помощник: формат статуса ─────────────────────────────────────
def _format_status(status):
    if status is None:
        return '—'
    if isinstance(status, UserStatusOnline):
        return 'online'
    if isinstance(status, UserStatusOffline):
        return status.was_online.strftime('%Y-%m-%d %H:%M')
    # Recent / LastWeek / LastMonth и т.п.
    name = type(status).__name__.replace('UserStatus', '')
    return name

# ─── Сбор расширённой информации о пользователе ────────────────────
async def fetch_user_info(u: User):
    full = await client(GetFullUserRequest(u.id))
    data = getattr(full, 'full_user', full)

    # статус online/offline
    last_seen = _format_status(u.status)

    # телефон из профиля и проверка, зарегистрирован ли он в Telegram
    phone = getattr(data, 'phone', None) or '—'
    tg_phone_reg = False
    if phone != '—':
        try:
            contact = InputPhoneContact(client_id=0, phone=phone, first_name='', last_name='')
            res = await client(ImportContactsRequest(contacts=[contact]))
            tg_phone_reg = bool(res.users)
            if tg_phone_reg:
                await client(DeleteContactsRequest(id=[x.id for x in res.users]))
        except:
            pass

    # базовые поля
    username = u.username or ''
    about = getattr(data, 'about', '') or ''

    # дополнительные поля
    has_username         = bool(username)
    username_len         = len(username)
    username_digit_count = sum(c.isdigit() for c in username)
    bio_len              = len(about)
    bio_snippet          = about if bio_len <= 50 else about[:50] + '...'
    bio_has_url          = bool(re.search(r'https?://', about))
    bio_has_email        = bool(re.search(r'\b[\w\.-]+@[\w\.-]+\.\w{2,4}\b', about))

    photos_count   = (await client.get_profile_photos(u, limit=0)).total
    common_count   = getattr(data, 'common_chats_count', 0)

    return {
        'id':                   u.id,
        'username':             username or '—',
        'has_username':         has_username,
        'username_len':         username_len,
        'username_digits':      username_digit_count,
        'name':                 f"{u.first_name or ''} {u.last_name or ''}".strip() or '—',
        'is_bot':               u.bot,
        'is_verified':          bool(getattr(data, 'bot_info', None)),
        'last_seen':            last_seen,
        'bio_len':              bio_len,
        'bio_snippet':          bio_snippet,
        'bio_has_url':          bio_has_url,
        'bio_has_email':        bio_has_email,
        'photos_count':         photos_count,
        'common_chats':         common_count,
        'phone':                phone,
        'tg_phone_registered':  tg_phone_reg,
    }

# ─── Эвристика «фейка» ─────────────────────────────────────────────
def check_fake(info: dict):
    reasons = []
    if not info['has_username']:
        reasons.append("нет username")
    if info['bio_len'] == 0:
        reasons.append("нет bio")
    if info['photos_count'] == 0:
        reasons.append("нет фото профиля")
    if info['common_chats'] == 0:
        reasons.append("нет общих чатов")
    return len(reasons) >= 2, reasons

# ─── Анализ номера телефона ────────────────────────────────────────
def analyze_phone(number: str):
    pn      = phonenumbers.parse(number, None)
    valid   = phonenumbers.is_valid_number(pn)
    country = geocoder.description_for_number(pn, "ru") or '—'
    op      = carrier.name_for_number(pn, "ru") or '—'
    tz_list = timezone.time_zones_for_number(pn)

    res = {
        'Номер':          number,
        'Валиден':        valid,
        'Страна':         country,
        'Оператор':       op,
        'Часовые пояса':  ", ".join(tz_list) if tz_list else '—'
    }
    if NUMVERIFY_KEY:
        try:
            r = requests.get(
                "http://apilayer.net/api/validate",
                params={'access_key': NUMVERIFY_KEY, 'number': number}
            ).json()
            res.update({
                'Numverify валиден':   r.get('valid', valid),
                'Numverify оператор':  r.get('carrier', '—'),
                'Numverify тип':       r.get('line_type', '—')
            })
        except:
            pass
    return res

# ─── /start ───────────────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'^/start$'))
async def start_handler(event):
    me = await client.get_me()
    await event.reply(
        f"🟢 Бот запущен под @{me.username}\n"
        "Пришли мне ссылку на аккаунт или номер:\n"
        "/info <username_or_link_or_phone>"
    )

# ─── /info ────────────────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'/info(?: |$)(.+)'))
async def info_handler(event):
    arg = event.pattern_match.group(1).strip()
    if arg.startswith('http'):
        arg = arg.rstrip('/').split('/')[-1]

    # если телефон
    if arg.startswith('+') and any(c.isdigit() for c in arg):
        await event.reply("🔍 Анализ номера…")
        data = analyze_phone(arg)
        lines = [f"• {k}: {v}" for k, v in data.items()]
        return await event.reply("📲 Информация по номеру:\n" + "\n".join(lines))

    # иначе профиль пользователя
    try:
        user = await client.get_entity(arg)
    except UsernameNotOccupiedError:
        return await event.reply("❌ Пользователь не найден.")
    except Exception as e:
        return await event.reply(f"❌ Ошибка: {e}")

    if not isinstance(user, User):
        return await event.reply("❗ Это не профиль Telegram-пользователя.")

    msg = await event.reply("🔍 Сбор данных о пользователе…")
    info = await fetch_user_info(user)
    fake, reasons = check_fake(info)

    # формат вывода
    lines = [
        f"• id: {info['id']}",
        f"• username: {info['username']}",
        f"• есть username: {info['has_username']}",
        f"• длина username: {info['username_len']}",
        f"• цифр в username: {info['username_digits']}",
        f"• имя: {info['name']}",
        f"• бот: {info['is_bot']}",
        f"• верифицирован: {info['is_verified']}",
        f"• последний онлайн: {info['last_seen']}",
        f"• длина bio: {info['bio_len']}",
        f"• bio содержит ссылку: {info['bio_has_url']}",
        f"• bio содержит email: {info['bio_has_email']}",
        f"• фрагмент bio: {info['bio_snippet']}",
        f"• фото в профиле: {info['photos_count']}",
        f"• общие чаты: {info['common_chats']}",
        f"• телефон в профиле: {info['phone']}",
        f"• телефон в Telegram: {info['tg_phone_registered']}",
    ]
    verdict = (
        "⚠️ Возможный фейк:\n  – " + "\n  – ".join(reasons)
    ) if fake else "✅ Похоже на реального пользователя"

    await msg.edit("📊 Информация о пользователе:\n" + "\n".join(lines) + "\n\n" + verdict)

# ─── Запуск ───────────────────────────────────────────────────────
def main():
    print("🟢 User-бот запущен…", flush=True)
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
