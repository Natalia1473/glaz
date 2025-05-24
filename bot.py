import os
import threading
import statistics
from datetime import datetime

from telethon import TelegramClient, events
from telethon.errors import UsernameNotOccupiedError
from telethon.tl.types import User, InputPhoneContact
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
NUMVERIFY_KEY = os.environ.get('NUMVERIFY_KEY')  # опционально
PORT          = int(os.environ.get('PORT', 8000))

# ─── HTTP-ping для Render ─────────────────────────────────────────
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

# запускаем сервер сразу, чтобы порт был открыт
threading.Thread(target=run_http, daemon=True).start()

# ─── ИНИЦИАЛИЗАЦИЯ TELETHON (user-сессия) ─────────────────────────
client = TelegramClient('user_session', API_ID, API_HASH)
client.start()

# ─── /start ───────────────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'^/start$'))
async def start_handler(event):
    me = await client.get_me()
    await event.reply(
        f"🟢 Я запущен как @{me.username}\n"
        "Отправь мне ссылку на Telegram-аккаунт или номер:\n"
        "`/info <username_or_link_or_phone>`"
    )

# ─── СБОР ИНФОРМАЦИИ О USER ────────────────────────────────────────
async def fetch_user_info(u: User):
    full = await client(GetFullUserRequest(u.id))
    data = getattr(full, 'full_user', full)

    # последний онлайн
    last_seen = getattr(u.status, 'was_online', None)
    last_seen_str = last_seen.strftime('%Y-%m-%d %H:%M') if last_seen else '—'

    # проверка телефона на регистрацию в Telegram
    phone = getattr(data, 'phone', None)
    tg_phone_registered = False
    if phone:
        try:
            contact = InputPhoneContact(client_id=0, phone=phone, first_name="", last_name="")
            res = await client(ImportContactsRequest(contacts=[contact]))
            tg_phone_registered = bool(res.users)
            if tg_phone_registered:
                await client(DeleteContactsRequest(id=[u.id for u in res.users]))
        except:
            tg_phone_registered = False

    return {
        'id':               u.id,
        'username':         u.username or '—',
        'name':             f"{u.first_name or ''} {u.last_name or ''}".strip() or '—',
        'is_bot':           u.bot,
        'is_verified':      bool(getattr(data, 'bot_info', None)),
        'last_seen':        last_seen_str,
        'about_len':        len(getattr(data, 'about', '') or ''),
        'photos_count':     (await client.get_profile_photos(u, limit=0)).total,
        'common_chats':     getattr(data, 'common_chats_count', 0),
        'phone':            phone or '—',
        'tg_phone_reg':     tg_phone_registered
    }

# ─── ПРОСТАЯ ЭВРИСТИКА «ФЕЙКА» ────────────────────────────────────
def check_fake(info: dict):
    reasons = []
    if info['about_len']    == 0: reasons.append("нет био")
    if info['photos_count'] == 0: reasons.append("нет фото профиля")
    if info['common_chats'] == 0: reasons.append("нет общих чатов")
    return len(reasons) >= 2, reasons

# ─── АНАЛИЗ НОМЕРА ────────────────────────────────────────────────
def analyze_phone(number: str):
    pn        = phonenumbers.parse(number, None)
    valid     = phonenumbers.is_valid_number(pn)
    country   = geocoder.description_for_number(pn, "en") or '—'
    operator  = carrier.name_for_number(pn, "en") or '—'
    tz_list   = timezone.time_zones_for_number(pn)

    res = {
        'valid':      valid,
        'country':    country,
        'operator':   operator,
        'time_zones': ", ".join(tz_list) if tz_list else '—'
    }
    if NUMVERIFY_KEY:
        try:
            r = requests.get(
                "http://apilayer.net/api/validate",
                params={'access_key': NUMVERIFY_KEY, 'number': number}
            ).json()
            res.update({
                'nv_valid':     r.get('valid', valid),
                'nv_carrier':   r.get('carrier', '—'),
                'nv_line_type': r.get('line_type', '—')
            })
        except:
            pass
    return res

# ─── /info ────────────────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'/info(?: |$)(.+)'))
async def info_handler(event):
    arg = event.pattern_match.group(1).strip()
    if arg.startswith('http'):
        arg = arg.rstrip('/').split('/')[-1]

    # --- если это номер телефона
    if arg.startswith('+') and any(c.isdigit() for c in arg):
        await event.reply("🔍 Анализ номера…")
        pd = analyze_phone(arg)
        lines = [
            f"• Номер: {arg}",
            f"• Валиден: {pd['valid']}",
            f"• Страна: {pd['country']}",
            f"• Оператор: {pd['operator']}",
            f"• Часовые пояса: {pd['time_zones']}"
        ]
        if 'nv_valid' in pd:
            lines += [
                f"• Numverify валиден: {pd['nv_valid']}",
                f"• Numverify оператор: {pd['nv_carrier']}",
                f"• Numverify тип: {pd['nv_line_type']}"
            ]
        return await event.reply("📲 Информация по номеру:\n" + "\n".join(lines))

    # --- иначе: профиль Telegram
    try:
        ent = await client.get_entity(arg)
    except UsernameNotOccupiedError:
        return await event.reply("❌ Пользователь не найден.")
    except Exception as e:
        return await event.reply(f"❌ Ошибка: {e}")

    if not isinstance(ent, User):
        return await event.reply("❗ Это не профиль Telegram-пользователя.")

    msg = await event.reply("🔍 Собираю данные о пользователе…")
    info = await fetch_user_info(ent)
    fake, reasons = check_fake(info)

    lines = [
        f"• id: {info['id']}",
        f"• username: {info['username']}",
        f"• name: {info['name']}",
        f"• is_bot: {info['is_bot']}",
        f"• is_verified: {info['is_verified']}",
        f"• last_seen: {info['last_seen']}",
        f"• about_len: {info['about_len']}",
        f"• photos_count: {info['photos_count']}",
        f"• common_chats: {info['common_chats']}",
        f"• phone: {info['phone']}",
        f"• tg_phone_registered: {info['tg_phone_reg']}"
    ]
    verdict = (
        "⚠️ *Возможный фейк*:\n  – " + "\n  – ".join(reasons)
    ) if fake else "✅ Похоже на реального пользователя"
    await msg.edit("📊 Информация о пользователе:\n" + "\n".join(lines) + "\n\n" + verdict)

# ─── ЗАПУСК ───────────────────────────────────────────────────────
def main():
    print("🟢 User-бот запущен…", flush=True)
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
