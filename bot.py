import os
import threading
import statistics
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
from telethon.tl.functions.messages import GetCommonChatsRequest

import http.server
import socketserver

import phonenumbers
from phonenumbers import geocoder, carrier, timezone
import requests

# ─── ENV ─────────────────────────────────────────────────────────
API_ID        = int(os.environ['API_ID'])
API_HASH      = os.environ['API_HASH']
NUMVERIFY_KEY = os.environ.get('NUMVERIFY_KEY')
PORT          = int(os.environ.get('PORT', 8000))

# ─── HTTP-PING ──────────────────────────────────────────────────
class Ping(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self,*args): pass

threading.Thread(target=lambda: socketserver.TCPServer(("", PORT), Ping).serve_forever(), daemon=True).start()

# ─── INIT TELETHON ───────────────────────────────────────────────
client = TelegramClient('user_session', API_ID, API_HASH)
client.start()

# ─── HELPERS ─────────────────────────────────────────────────────
def format_status(status):
    if status is None:
        return '—'
    if isinstance(status, UserStatusOnline):
        return 'online'
    if isinstance(status, UserStatusOffline):
        return status.was_online.strftime('%Y-%m-%d %H:%M')
    # Recent / LastWeek / LastMonth etc.
    name = type(status).__name__.replace('UserStatus','')
    return name

async def get_common_chats(u):
    r = await client(GetCommonChatsRequest(user_id=u.id, max_id=0, limit=5))
    return [getattr(c, 'title', None) or c.username or '—' for c in r.chats]

def analyze_phone_osint(number: str):
    # сюда можно подключить внешние OSINT-API: Pipl, HaveIBeenPwned, Truecaller и т.п.
    return {}

def analyze_phone(number: str):
    pn      = phonenumbers.parse(number, None)
    valid   = phonenumbers.is_valid_number(pn)
    country = geocoder.description_for_number(pn, "en") or '—'
    op      = carrier.name_for_number(pn, "en") or '—'
    tz_list = timezone.time_zones_for_number(pn)

    res = {
        'valid':      valid,
        'country':    country,
        'operator':   op,
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
                'nv_carrier':   r.get('carrier','—'),
                'nv_line_type': r.get('line_type','—')
            })
        except:
            pass
    res.update(analyze_phone_osint(number))
    return res

# ─── COMMANDS ────────────────────────────────────────────────────
@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'^/start$'))
async def start(event):
    me = await client.get_me()
    await event.reply(
        f"Я User-бот @{me.username}\n"
        "/info <@username│link│+71234567890>"
    )

@client.on(events.NewMessage(incoming=True, outgoing=True, pattern=r'/info(?: |$)(.+)'))
async def info(event):
    arg = event.pattern_match.group(1).strip()
    if arg.startswith('http'):
        arg = arg.rstrip('/').split('/')[-1]

    # 1) PHONE
    if arg.startswith('+') and any(c.isdigit() for c in arg):
        data = analyze_phone(arg)
        lines = [f"• {k}: {v}" for k,v in data.items()]
        return await event.reply("📲 Phone Info:\n" + "\n".join(lines))

    # 2) TELEGRAM USER
    try:
        u = await client.get_entity(arg)
    except UsernameNotOccupiedError:
        return await event.reply("❌ Not found")
    except Exception as e:
        return await event.reply(f"❌ Error: {e}")

    if not isinstance(u, User):
        return await event.reply("❗ Not a user profile")

    msg = await event.reply("🔍 Gathering user info…")
    full = await client(GetFullUserRequest(u.id))
    data = getattr(full, 'full_user', full)

    # last seen
    last_seen = format_status(u.status)

    # mutual chats
    common = await get_common_chats(u)

    # phone registration
    phone = getattr(data, 'phone', '—')
    tg_reg = False
    if phone != '—':
        cnt = await client(ImportContactsRequest(contacts=[InputPhoneContact(0,phone,'','')]))
        tg_reg = bool(cnt.users)
        if tg_reg: await client(DeleteContactsRequest(id=[x.id for x in cnt.users]))

    info = {
        'id':           u.id,
        'username':     u.username or '—',
        'name':         f"{u.first_name or ''} {u.last_name or ''}".strip() or '—',
        'is_bot':       u.bot,
        'is_verified':  bool(getattr(data,'bot_info',None)),
        'last_seen':    last_seen,
        'about_len':    len(getattr(data,'about','') or ''),
        'photos_cnt':   (await client.get_profile_photos(u, limit=0)).total,
        'common_chats': len(common),
        'common_list':  ", ".join(common) or '—',
        'phone':        phone,
        'tg_phone':     tg_reg
    }

    # fake heuristic
    reasons = []
    if info['about_len']==0:    reasons.append("no bio")
    if info['photos_cnt']==0:   reasons.append("no photos")
    if info['common_chats']==0: reasons.append("no mutual chats")
    fake = len(reasons)>=2

    lines = [f"• {k}: {v}" for k,v in info.items()]
    verdict = ("⚠️ Fake? Reasons:\n  – " + "\n  – ".join(reasons)) if fake else "✅ Seems real"
    await msg.edit("📊 User Info:\n" + "\n".join(lines)+"\n\n"+verdict)

# ─── RUN ─────────────────────────────────────────────────────────
print("🟢 Bot started…")
client.run_until_disconnected()
