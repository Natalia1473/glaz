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

import phonenumbers
from phonenumbers import geocoder, carrier, timezone
import requests

# ─── ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ─────────────────────────────────────────
API_ID        = int(os.environ['API_ID'])
API_HASH      = os.environ['API_HASH']
NUMVERIFY_KEY = os.environ.get('NUMVERIFY_KEY')  # ваш ключ Numverify, если есть
PORT          = int(os.environ.get('PORT', 8000))

# ─── HTTP-ping для Render ────────────────────────────────────────
class PingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, *args): pass

def run_http():
    with socketserver.TCPServer(("", PORT), PingHandler) as srv:
        srv.serve_forever()

# ─── Телеграм-клиент (user-сессия) ───────────────────────────────
client = TelegramClient('user_session', API_ID, API_HASH)
client.start()

# ─── Стартовый ответ ──────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'^/start$'))
async def start_handler(event):
    await event.reply(
        "Привет! Отправь мне ссылку на Telegram-аккаунт или номер телефона в формате +71234567890:\n"
        "/info <username_or_link_or_phone>"
    )

# ─── Сбор данных о Telegram-пользователе ──────────────────────────
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

# ─── Проверка на фейк (эвристики) ────────────────────────────────
def check_fake(info: dict) -> (bool, list[str]):
    reasons = []
    if info.get('about_len', 0) == 0:
        reasons.append("нет био")
    if info.get('photos_count', 0) == 0:
        reasons.append("нет фото профиля")
    if info.get('common_chats', 0) == 0:
        reasons.append("нет общих чатов")
    is_fake = len(reasons) >= 2
    return is_fake, reasons

# ─── Анализ номера через phonenumbers и Numverify ─────────────────
def analyze_phone(number: str) -> dict:
    pn = phonenumbers.parse(number, None)
    valid = phonenumbers.is_valid_number(pn)
    country = geocoder.description_for_number(pn, "en")
    op = carrier.name_for_number(pn, "en")
    tz = timezone.time_zones_for_number(pn)
    result = {
        'valid': valid,
        'country': country or '—',
        'operator': op or '—',
        'time_zones': ", ".join(tz) if tz else '—'
    }
    # Numverify API
    if NUMVERIFY_KEY:
        try:
            r = requests.get(
                "http://apilayer.net/api/validate",
                params={'access_key': NUMVERIFY_KEY, 'number': number}
            ).json()
            result.update({
                'numverify_line_type': r.get('line_type', '—'),
                'numverify_carrier': r.get('carrier', '—'),
                'numverify_valid': r.get('valid', valid)
            })
        except Exception:
            pass
    return result

# ─── Обработчик /info ─────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'/info(?: |$)(.+)'))
async def info_handler(event):
    arg = event.pattern_match.group(1).strip()
    if arg.startswith('http'):
        arg = arg.rstrip('/').split('/')[-1]

    # если похоже на номер телефона
    if arg.startswith('+') and any(ch.isdigit() for ch in arg):
        await event.reply("🔍 Анализ номера…")
        try:
            phone_data = analyze_phone(arg)
        except Exception as e:
            return await event.reply(f"❌ Ошибка анализа номера: {e}")
        lines = [
            f"• Номер: {arg}",
            f"• Валиден: {phone_data['valid']}",
            f"• Страна: {phone_data['country']}",
            f"• Оператор: {phone_data['operator']}",
            f"• Часовые пояса: {phone_data['time_zones']}"
        ]
        if 'numverify_line_type' in phone_data:
            lines += [
                f"• Numverify valid: {phone_data['numverify_valid']}",
                f"• Numverify carrier: {phone_data['numverify_carrier']}",
                f"• Numverify line type: {phone_data['numverify_line_type']}"
            ]
        return await event.reply("📲 Информация по номеру:\n" + "\n".join(lines))

    # иначе — аккаунт Telegram
    try:
        ent = await client.get_entity(arg)
    except UsernameNotOccupiedError:
        return await event.reply("❌ Пользователь не найден.")
    except Exception as e:
        return await event.reply(f"❌ Ошибка при поиске: {e}")

    if not isinstance(ent, User):
        return await event.reply("❗ Это не профиль пользователя Telegram.")

    msg = await event.reply("🔍 Собираю данные о пользователе…")
    try:
        info = await fetch_user_info(ent)
    except Exception as e:
        return await msg.edit(f"❌ Не удалось получить данные: {e}")

    is_fake, reasons = check_fake(info)
    lines = [
        f"• id: {info['id']}",
        f"• username: {info['username']}",
        f"• name: {info['name']}",
        f"• is_bot: {info['is_bot']}",
        f"• is_verified: {info['is_verified']}",
        f"• status: {info['status']}",
        f"• about_len: {info['about_len']}",
        f"• photos_count: {info['photos_count']}",
        f"• common_chats: {info['common_chats']}"
    ]
    verdict = ("⚠️ *Возможный фейк*:\n  – " + "\n  – ".join(reasons)) if is_fake else "✅ Похоже на реального пользователя"
    await msg.edit("📊 Информация о пользователе:\n" + "\n".join(lines) + "\n\n" + verdict)

# ─── Запуск ───────────────────────────────────────────────────────
def main():
    threading.Thread(target=run_http, daemon=True).start()
    print("User-бот запущен…")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()
