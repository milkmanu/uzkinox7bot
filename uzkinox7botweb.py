# -*- coding: utf-8 -*-
"""
uzkinox7 — Telegram kino-tarqatish boti
aiogram 3.x + SQLite

Ishga tushirishdan oldin:
1. Fayldagi BOT_TOKEN qiymatini o'zingizning tokeningizga almashtiring.
2. Kerakli kutubxonalar YO'Q bo'lsa, quyidagi kod ularni AVTOMATIK o'rnatadi
   (internet aloqasi bo'lishi kerak). Shunchaki: python3 uzkinox7_bot.py
"""

import sys
import subprocess
import importlib
import site

REQUIRED_PACKAGES = ["aiogram", "aiohttp_socks"]
PIP_NAMES = {"aiohttp_socks": "aiohttp-socks"}
MIN_AIOGRAM_VERSION = (3, 20)  # Bot API 9.4 (rangli tugmalar / style maydoni) uchun shart


def _pip_install(pip_name: str, upgrade: bool = False):
    cmd = [sys.executable, "-m", "pip", "install", "-q"]
    if upgrade:
        cmd.append("-U")
    cmd.append(pip_name)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        subprocess.check_call(cmd + ["--break-system-packages"])


def ensure_packages():
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)

    for pkg in missing:
        pip_name = PIP_NAMES.get(pkg, pkg)
        print(f"[o'rnatilmoqda] {pip_name} topilmadi, o'rnatilyapti...")
        _pip_install(pip_name)
        print(f"[tayyor] {pip_name} o'rnatildi.")

    if missing:
        # Yangi o'rnatilgan --user paketlar shu jarayonda ko'rinishi uchun path'ni yangilaymiz
        try:
            importlib.reload(site)
            paths = list(getattr(site, "getsitepackages", lambda: [])()) + [site.getusersitepackages()]
            for path in paths:
                if path not in sys.path:
                    sys.path.append(path)
            importlib.invalidate_caches()
        except Exception:
            pass

    # aiogram eski versiyada bo'lsa, rangli tugmalar (style maydoni) ishlamaydi —
    # shuning uchun versiyani tekshirib, kerak bo'lsa avtomatik yangilaymiz.
    try:
        import aiogram as _aiogram_check
        ver_parts = tuple(int(p) for p in _aiogram_check.__version__.split(".")[:2])
        if ver_parts < MIN_AIOGRAM_VERSION:
            print(
                f"[yangilanmoqda] aiogram {_aiogram_check.__version__} eski "
                f"(kamida {'.'.join(map(str, MIN_AIOGRAM_VERSION))} kerak, rangli tugmalar uchun) — yangilanyapti..."
            )
            _pip_install("aiogram", upgrade=True)
            importlib.reload(site)
            importlib.invalidate_caches()
            print("[tayyor] aiogram yangilandi. Botni qayta ishga tushiring.")
            raise SystemExit(
                "✅ aiogram yangilandi. Iltimos, botni QAYTA ishga tushiring "
                "(python3 uzkinox7bot.py) — yangi versiya shu jarayonda to'liq faollashishi uchun."
            )
    except ImportError:
        pass


ensure_packages()

import asyncio
import time
from urllib.parse import quote
import logging
import sqlite3
import re
import difflib
from datetime import datetime, timedelta
from contextlib import closing

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    ErrorEvent,
    WebAppInfo,
    MenuButtonWebApp,
)

# ============================================================
# SOZLAMALAR
# ============================================================

BOT_TOKEN = "8844323602:AAHiifl8LXTAk3PbS2-Bgchs0UrGQKxQXQg"  # ODDIY (foydalanuvchilar) bot tokeni
ADMIN_BOT_TOKEN = "SIZNING_ADMIN_BOT_TOKENINGIZ"              # ADMIN bot tokeni — @BotFather'dan alohida bot yarating
BOT_USERNAME = "uzkinox7bot"  # @ belgisisiz, ODDIY botning haqiqiy usernamesi (referal havolalar shu bot uchun tuziladi)
MINIAPP_URL = "https://USERNAME.pythonanywhere.com/"  # ⚠️ miniapp_api_server.py joylashtirilgan HTTPS manzilga almashtiring
OWNER_ID = 8168552332

if BOT_TOKEN in ("SIZNING_BOT_TOKENINGIZ", "") or ":" not in BOT_TOKEN:
    raise SystemExit(
        "❌ BOT_TOKEN sozlanmagan! Fayl boshidagi BOT_TOKEN qiymatini "
        "@BotFather bergan haqiqiy (ODDIY foydalanuvchilar uchun) tokenga almashtiring, "
        "so'ng botni qayta ishga tushiring."
    )
if ADMIN_BOT_TOKEN in ("SIZNING_ADMIN_BOT_TOKENINGIZ", "") or ":" not in ADMIN_BOT_TOKEN:
    raise SystemExit(
        "❌ ADMIN_BOT_TOKEN sozlanmagan! @BotFather orqali ALOHIDA (ikkinchi) bot yarating "
        "va uning tokenini ADMIN_BOT_TOKEN qiymatiga qo'ying, so'ng botni qayta ishga tushiring.\n"
        "⚠️ Diqqat: BASE/CODES/VIP/PRO kanallariga faqat ODDIY bot (BOT_TOKEN) admin qilib "
        "qo'shilishi kerak — bu o'zgarmaydi. Yangi ADMIN bot faqat adminlar bilan shaxsiy chatda ishlaydi."
    )

BASE_CHANNEL = "https://t.me/+L7Zi_AgEOPRkM2Qy"      # baza kanali (link, foydalanuvchiga ko'rsatish uchun)
CODES_CHANNEL = "https://t.me/uzkinox7"               # kodlar kanali
VIP_CHANNEL = "https://t.me/+KiYZ1p2l2WRmZTli"        # VIP (qo'rqinchli) kanali (link)
PRO_CHANNEL = "https://t.me/+_TErDK6GxARjYThi"        # PRO (hammadan oldin yuklangan kinolar) kanali

BASE_CHANNEL_ID = -1003927240240   # baza kanal chat_id
CODES_CHANNEL_ID = -1003970440747  # kodlar kanal chat_id
VIP_CHANNEL_ID = -1003986003501    # VIP kanal chat_id
PRO_CHANNEL_ID = -1003719328165    # PRO kanal chat_id

DB_PATH = "uzkinox7.db"

CATEGORIES = ["Anime", "Drama", "Uzbek kino", "Multfilm"]  # Horror alohida VIP orqali

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("uzkinox7_errors.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("uzkinox7")

import os

# PythonAnywhere kabi ba'zi bepul hostinglar internetga faqat proxy orqali
# chiqishga ruxsat beradi. Bu holatda muhit o'zgaruvchilarida proxy manzili
# avtomatik mavjud bo'ladi — shuni topib, aiogram sessiyasiga ulaymiz.
_proxy_url = (
    os.environ.get("https_proxy")
    or os.environ.get("HTTPS_PROXY")
    or os.environ.get("http_proxy")
    or os.environ.get("HTTP_PROXY")
)

if _proxy_url:
    from aiogram.client.session.aiohttp import AiohttpSession
    logger.info(f"Proxy topildi, ishlatilmoqda: {_proxy_url}")
    user_bot = Bot(token=BOT_TOKEN, session=AiohttpSession(proxy=_proxy_url), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    admin_bot = Bot(token=ADMIN_BOT_TOKEN, session=AiohttpSession(proxy=_proxy_url), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
else:
    user_bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    admin_bot = Bot(token=ADMIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# ODDIY (foydalanuvchilar) va ADMIN uchun butunlay alohida Router/Dispatcher juftligi.
# Har biri o'z tokeni bilan alohida "ishga tushadi" — ikkita alohida Telegram bot bo'lib qoladi.
user_router = Router()
admin_router = Router()
user_dp = Dispatcher(storage=MemoryStorage())
admin_dp = Dispatcher(storage=MemoryStorage())
user_dp.include_router(user_router)
admin_dp.include_router(admin_router)


async def _notify_error(bot_obj: Bot, event: ErrorEvent):
    """Har qanday handler ichida chiqqan xatolik shu yerga tushadi.
    Ilgari bunday xatolar hech qanday izsiz "yo'qolib" ketardi — foydalanuvchi
    tugmani bossa ham hech narsa bo'lmagandek ko'rinardi. Endi xatolik to'liq
    log fayliga (uzkinox7_errors.log) yoziladi va foydalanuvchiga xabar beriladi."""
    logger.error("Handlerda kutilmagan xatolik:", exc_info=event.exception)
    try:
        update = event.update
        chat_id = None
        if update.message:
            chat_id = update.message.chat.id
        elif update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
        if chat_id:
            await bot_obj.send_message(
                chat_id,
                "⚠️ Kutilmagan xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring "
                "yoki /start bosing. Muammo davom etsa, admin bilan bog'laning.",
            )
        if update.callback_query:
            try:
                await update.callback_query.answer("Xatolik yuz berdi.", show_alert=False)
            except Exception:
                pass
    except Exception:
        logger.exception("Xatolik haqida foydalanuvchiga xabar berib bo'lmadi")
    return True


@user_dp.error()
async def user_error_handler(event: ErrorEvent):
    return await _notify_error(user_bot, event)


@admin_dp.error()
async def admin_error_handler(event: ErrorEvent):
    return await _notify_error(admin_bot, event)

# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table: str, column: str, coltype_and_default: str):
    """Jadvalda kerakli ustun yo'q bo'lsa qo'shadi. Bu botning eski versiyasidan
    qolgan uzkinox7.db faylida ustunlar to'liq bo'lmasa ham xatoliksiz ishlashini
    ta'minlaydi (masalan 'no such column' xatosi bo'lmasligi uchun)."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype_and_default}")
            logger.info(f"Migratsiya: {table}.{column} ustuni qo'shildi")
        except Exception as e:
            logger.warning(f"Migratsiya xatosi ({table}.{column}): {e}")


def init_db():
    with closing(db()) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                joined_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                telegram_id INTEGER PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                name TEXT,
                genre TEXT,
                country TEXT,
                language TEXT,
                file_id TEXT,
                channel_chat_id INTEGER,
                channel_message_id INTEGER,
                is_vip INTEGER DEFAULT 0,
                series_id INTEGER,
                part_number INTEGER DEFAULT 1,
                views INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vip_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                full_name TEXT,
                phone TEXT,
                birthdate TEXT,
                status TEXT DEFAULT 'pending',
                vip_code TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mandatory_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                link TEXT,
                title TEXT,
                threshold INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                telegram_id INTEGER PRIMARY KEY,
                amount INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bonus_codes (
                code TEXT PRIMARY KEY,
                amount INTEGER,
                used_by INTEGER,
                used_at TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS partners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                channel_link TEXT,
                letter_prefix TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topup_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                amount INTEGER,
                receipt_file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS revenue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                telegram_id INTEGER,
                amount INTEGER,
                note TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                last_message_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                sender TEXT,
                text TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS genres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS languages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tariff_codes (
                code TEXT PRIMARY KEY,
                tier TEXT,
                plan TEXT,
                telegram_id INTEGER,
                redeemed_by INTEGER,
                redeemed_at TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memberships (
                telegram_id INTEGER,
                tier TEXT,
                plan TEXT,
                expires_at TEXT,
                PRIMARY KEY (telegram_id, tier)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tier_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                tier TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        for g in ["Anime", "Drama", "Uzbek kino", "Multfilm", "Qo'rqinchli"]:
            conn.execute("INSERT OR IGNORE INTO genres (name) VALUES (?)", (g,))
        # Davlatlar va tillar uchun standart (built-in) ro'yxat endi ISHLATILMAYDI —
        # admin faqat o'zi Sozlamalar orqali qo'shgan davlat/tillardan foydalanadi.
        # Eski o'rnatishlarda avtomatik qo'shilgan standart qiymatlarni BIR MARTALIK tozalaymiz
        # (agar admin keyinchalik xuddi shu nom bilan o'zi qayta qo'shsa, endi o'chirilmaydi):
        if not conn.execute("SELECT 1 FROM settings WHERE key='_cleaned_default_geo'").fetchone():
            for c in ["O'zbekiston", "Turkiya", "Rossiya", "AQSH", "Hindiston", "Koreya"]:
                conn.execute("DELETE FROM countries WHERE name=?", (c,))
            for l in ["O'zbek", "Rus", "Ingliz", "Turk"]:
                conn.execute("DELETE FROM languages WHERE name=?", (l,))
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('_cleaned_default_geo', '1')"
            )
        defaults = {
            "reklama_info": "Reklama joylashtirish uchun: @uzkinox7_admin",
            "hamkorlik_info": "Hamkorlik taklifi uchun: @uzkinox7_admin",
            "boglanish_info": "Bog'lanish uchun: @uzkinox7_admin",
            "price_hamkorlik": "0",
            "price_reklama": "0",
            "price_majburiy_obuna": "0",
            "price_vip": "0",
            "price_vip_1m": "0",
            "price_vip_3m": "0",
            "price_vip_6m": "0",
            "price_vip_lifetime": "0",
            "price_pro_1m": "0",
            "price_pro_3m": "0",
            "price_pro_6m": "0",
            "price_pro_12m": "0",
            "price_hamkor_1m": "0",
            "price_hamkor_3m": "0",
            "price_hamkor_6m": "0",
            "price_hamkor_12m": "0",
            "referral_bonus": "0",
            "daily_push_enabled": "0",
            "weekly_push_enabled": "0",
            "push_hour": "10",
            "last_daily_push_date": "",
            "last_weekly_push_date": "",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )
        conn.execute(
            "INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (OWNER_ID,)
        )

        # --- Eski bazalardan qolgan jadvallarni yangi ustunlar bilan moslashtiramiz ---
        ensure_column(conn, "mandatory_channels", "threshold", "INTEGER DEFAULT 0")
        ensure_column(conn, "mandatory_channels", "active", "INTEGER DEFAULT 1")
        ensure_column(conn, "balances", "amount", "INTEGER DEFAULT 0")
        ensure_column(conn, "bonus_codes", "used_by", "INTEGER")
        ensure_column(conn, "bonus_codes", "used_at", "TEXT")
        ensure_column(conn, "partners", "letter_prefix", "TEXT")
        ensure_column(conn, "partners", "status", "TEXT DEFAULT 'pending'")
        ensure_column(conn, "topup_requests", "status", "TEXT DEFAULT 'pending'")
        ensure_column(conn, "movies", "series_id", "INTEGER")
        ensure_column(conn, "movies", "part_number", "INTEGER DEFAULT 1")
        ensure_column(conn, "movies", "views", "INTEGER DEFAULT 0")
        ensure_column(conn, "movies", "is_vip", "INTEGER DEFAULT 0")
        ensure_column(conn, "movies", "lang_group", "INTEGER")
        ensure_column(conn, "partners", "banned", "INTEGER DEFAULT 0")
        ensure_column(conn, "partners", "can_upload", "INTEGER DEFAULT 1")
        ensure_column(conn, "partners", "can_upload_vip", "INTEGER DEFAULT 0")
        ensure_column(conn, "partners", "can_upload_pro", "INTEGER DEFAULT 0")
        ensure_column(conn, "partners", "bypass_majburiy", "INTEGER DEFAULT 0")
        ensure_column(conn, "partners", "can_send_ads", "INTEGER DEFAULT 0")
        ensure_column(conn, "partners", "can_view_stats", "INTEGER DEFAULT 0")
        ensure_column(conn, "memberships", "banned", "INTEGER DEFAULT 0")
        # --- Bitta kod ostida bir nechta til uchun qo'shimcha fayl maydonlari (2..5) ---
        for _n in (2, 3, 4, 5):
            ensure_column(conn, "movies", f"file_id{_n}", "TEXT")
            ensure_column(conn, "movies", f"language{_n}", "TEXT")
            ensure_column(conn, "movies", f"channel_chat_id{_n}", "INTEGER")
            ensure_column(conn, "movies", f"channel_message_id{_n}", "INTEGER")
        ensure_column(conn, "movies", "is_pro", "INTEGER DEFAULT 0")
        ensure_column(conn, "users", "referred_by", "INTEGER")
        ensure_column(conn, "users", "ui_lang", "TEXT DEFAULT 'uz'")
        ensure_column(conn, "users", "lang_chosen", "INTEGER DEFAULT 0")
        ensure_column(conn, "users", "first_name", "TEXT")
        ensure_column(conn, "users", "full_name", "TEXT")
        ensure_column(conn, "users", "phone", "TEXT")
        ensure_column(conn, "users", "onboarded", "INTEGER DEFAULT 0")
        ensure_column(conn, "memberships", "reminded", "INTEGER DEFAULT 0")
        ensure_column(conn, "users", "banned", "INTEGER DEFAULT 0")
        ensure_column(conn, "users", "vip_trial_used", "INTEGER DEFAULT 0")
        ensure_column(conn, "users", "pro_trial_used", "INTEGER DEFAULT 0")
        ensure_column(conn, "movies", "trailer_file_id", "TEXT")
        ensure_column(conn, "bonus_codes", "max_uses", "INTEGER DEFAULT 1")
        ensure_column(conn, "tariff_codes", "max_uses", "INTEGER DEFAULT 1")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bonus_code_uses (
                code TEXT,
                telegram_id INTEGER,
                used_at TEXT,
                PRIMARY KEY (code, telegram_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tariff_code_uses (
                code TEXT,
                telegram_id INTEGER,
                redeemed_at TEXT,
                PRIMARY KEY (code, telegram_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coming_soon (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                note TEXT,
                poster_file_id TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                query TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                telegram_id INTEGER,
                movie_id INTEGER,
                created_at TEXT,
                PRIMARY KEY (telegram_id, movie_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                telegram_id INTEGER,
                movie_id INTEGER,
                stars INTEGER,
                created_at TEXT,
                PRIMARY KEY (telegram_id, movie_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                detail TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                slot TEXT PRIMARY KEY,
                content_type TEXT,
                text TEXT,
                file_id TEXT,
                btn_text TEXT,
                btn_url TEXT,
                updated_at TEXT
            )
        """)


def get_setting(key: str) -> str:
    with closing(db()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""


# ---------- Segmentlashtirilgan reklamalar (VIP/PRO/HAMMAGA/ODDIYLARGA/KOD KANAL) ----------

AD_SLOTS = {
    "vip": "⭐️ VIP REKLAMA",
    "pro": "💎 PRO REKLAMA",
    "hammaga": "📢 HAMMAGA",
    "oddiylarga": "👤 ODDIYLARGA",
    "kod_kanal": "🎬 KOD KANALGA REKLAMA",
}


def get_ad(slot: str):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM ads WHERE slot=?", (slot,)).fetchone()


def set_ad(slot: str, content_type: str, text: str, file_id: str, btn_text: str, btn_url: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO ads (slot, content_type, text, file_id, btn_text, btn_url, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(slot) DO UPDATE SET content_type=excluded.content_type, text=excluded.text, "
            "file_id=excluded.file_id, btn_text=excluded.btn_text, btn_url=excluded.btn_url, "
            "updated_at=excluded.updated_at",
            (slot, content_type, text, file_id, btn_text, btn_url, datetime.utcnow().isoformat()),
        )


def clear_ad(slot: str):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM ads WHERE slot=?", (slot,))


async def deliver_ad(chat_id: int, ad: sqlite3.Row) -> bool:
    """Bitta reklama yozuvini (ads jadvalidan) berilgan chatga yuboradi.
    Muvaffaqiyatli bo'lsa True, aks holda False qaytaradi."""
    if not ad:
        return False
    kb = None
    if ad["btn_text"] and ad["btn_url"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=ad["btn_text"], url=ad["btn_url"], style="primary")]])
    try:
        if ad["content_type"] == "photo" and ad["file_id"]:
            await user_bot.send_photo(chat_id, ad["file_id"], caption=ad["text"] or None, reply_markup=kb)
        elif ad["content_type"] == "video" and ad["file_id"]:
            await user_bot.send_video(chat_id, ad["file_id"], caption=ad["text"] or None, reply_markup=kb)
        elif ad["text"]:
            await user_bot.send_message(chat_id, ad["text"], reply_markup=kb)
        else:
            return False
        return True
    except Exception as e:
        logger.warning(f"Reklama yuborilmadi ({chat_id}, slot={ad['slot']}): {e}")
        return False


# ---------- Janr / Davlat / Til (admin boshqaradigan ro'yxatlar) ----------

def list_genres():
    with closing(db()) as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM genres ORDER BY name")]


def add_genre(name: str):
    with closing(db()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO genres (name) VALUES (?)", (name,))


def remove_genre(name: str):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM genres WHERE name=?", (name,))


def list_countries():
    with closing(db()) as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM countries ORDER BY name")]


def add_country(name: str):
    with closing(db()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO countries (name) VALUES (?)", (name,))


def remove_country(name: str):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM countries WHERE name=?", (name,))


def list_languages():
    with closing(db()) as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM languages ORDER BY name")]


def add_language(name: str):
    with closing(db()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO languages (name) VALUES (?)", (name,))


def remove_language(name: str):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM languages WHERE name=?", (name,))


def get_recent_movies(limit: int = 8, is_vip: int = 0):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE is_vip=? ORDER BY id DESC LIMIT ?",
            (is_vip, limit),
        ).fetchall()


def set_setting(key: str, value: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def is_admin(telegram_id: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT 1 FROM admins WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return row is not None


def add_admin(telegram_id: int):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (telegram_id,)
        )


def remove_admin(telegram_id: int):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM admins WHERE telegram_id=?", (telegram_id,))


def user_exists(telegram_id: int) -> bool:
    with closing(db()) as conn:
        return conn.execute(
            "SELECT 1 FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone() is not None


def register_user(telegram_id: int, username: str, first_name: str = ""):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, first_name, joined_at) VALUES (?, ?, ?, ?)",
            (telegram_id, username or "", first_name or "", datetime.utcnow().isoformat()),
        )
        # Foydalanuvchi username/ismini o'zgartirgan bo'lishi mumkin — har safar yangilab boramiz.
        conn.execute(
            "UPDATE users SET username=?, first_name=? WHERE telegram_id=?",
            (username or "", first_name or "", telegram_id),
        )


# ---------- Interfeys tili (/lang) ----------

UI_LANGS = {
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
    "tr": "🇹🇷 Türkçe",
}

WELCOME_TEXT = {
    "uz": "Assalomu alaykum! <b>uzkinox7</b> botiga xush kelibsiz 🎬",
    "ru": "Здравствуйте! Добро пожаловать в бот <b>uzkinox7</b> 🎬",
    "en": "Hello! Welcome to the <b>uzkinox7</b> bot 🎬",
    "tr": "Merhaba! <b>uzkinox7</b> botuna hoş geldiniz 🎬",
}

# ---------- Foydalanuvchiga ko'rinadigan asosiy tugmalar tarjimasi ----------
MENU_LABELS = {
    "cancel": {"uz": "❌ BEKOR QILISH", "ru": "❌ ОТМЕНА", "en": "❌ CANCEL", "tr": "❌ İPTAL"},
    "skip": {"uz": "⏭ OʻTKAZIB YUBORISH", "ru": "⏭ ПРОПУСТИТЬ", "en": "⏭ SKIP", "tr": "⏭ GEÇ"},
    "back_normal": {"uz": "⬅️ ODDIY REJIMGA QAYTISH", "ru": "⬅️ НАЗАД В ОБЫЧНЫЙ РЕЖИМ", "en": "⬅️ BACK TO NORMAL MODE", "tr": "⬅️ NORMAL MODA DÖN"},
    "search": {"uz": "🔎 KINO QIDIRISH", "ru": "🔎 ПОИСК ФИЛЬМА", "en": "🔎 SEARCH MOVIE", "tr": "🔎 FİLM ARA"},
    "codes": {"uz": "🎬 KINO KODLARI", "ru": "🎬 КОДЫ ФИЛЬМОВ", "en": "🎬 MOVIE CODES", "tr": "🎬 FİLM KODLARI"},
    "genres": {"uz": "🗂 JANRLAR", "ru": "🗂 ЖАНРЫ", "en": "🗂 GENRES", "tr": "🗂 TÜRLER"},
    "wallet": {"uz": "💰 HISOBIM", "ru": "💰 МОЙ БАЛАНС", "en": "💰 MY BALANCE", "tr": "💰 BAKİYEM"},
    "favorites": {"uz": "⭐️ SEVIMLILARIM", "ru": "⭐️ ИЗБРАННОЕ", "en": "⭐️ FAVORITES", "tr": "⭐️ FAVORİLERİM"},
    "top": {"uz": "🔥 TOP KINOLAR", "ru": "🔥 ТОП ФИЛЬМЫ", "en": "🔥 TOP MOVIES", "tr": "🔥 EN İYİ FİLMLER"},
    "services": {"uz": "🛠 XIZMATLAR", "ru": "🛠 УСЛУГИ", "en": "🛠 SERVICES", "tr": "🛠 HİZMETLER"},
    "vip": {"uz": "⭐️ VIP", "ru": "⭐️ VIP", "en": "⭐️ VIP", "tr": "⭐️ VIP"},
    "pro": {"uz": "💎 PRO", "ru": "💎 PRO", "en": "💎 PRO", "tr": "💎 PRO"},
    "invite": {"uz": "🎁 DO'STNI TAKLIF QILISH", "ru": "🎁 ПРИГЛАСИТЬ ДРУГА", "en": "🎁 INVITE A FRIEND", "tr": "🎁 ARKADAŞINI DAVET ET"},
    "partner_upload": {"uz": "⬆️ HAMKOR KINO YUKLASH", "ru": "⬆️ ЗАГРУЗКА ФИЛЬМА (ПАРТНЁР)", "en": "⬆️ PARTNER MOVIE UPLOAD", "tr": "⬆️ ORTAK FİLM YÜKLEME"},
    "contact": {"uz": "☎️ BOG'LANISH", "ru": "☎️ СВЯЗАТЬСЯ", "en": "☎️ CONTACT US", "tr": "☎️ İLETİŞİM"},
    "ads": {"uz": "📢 REKLAMA", "ru": "📢 РЕКЛАМА", "en": "📢 ADVERTISING", "tr": "📢 REKLAM"},
    "mandatory_sub": {"uz": "📡 MAJBURIY OBUNA", "ru": "📡 ОБЯЗАТЕЛЬНАЯ ПОДПИСКА", "en": "📡 MANDATORY SUBSCRIPTION", "tr": "📡 ZORUNLU ABONELİK"},
    "partnership": {"uz": "🤝 HAMKORLIK", "ru": "🤝 ПАРТНЁРСТВО", "en": "🤝 PARTNERSHIP", "tr": "🤝 ORTAKLIK"},
    "chatbot": {"uz": "💬 CHAT BOT", "ru": "💬 ЧАТ С БОТОМ", "en": "💬 CHAT BOT", "tr": "💬 SOHBET BOTU"},
    "topup": {"uz": "💳 HISOBNI TO'LDIRISH", "ru": "💳 ПОПОЛНИТЬ БАЛАНС", "en": "💳 TOP UP BALANCE", "tr": "💳 BAKİYE YÜKLE"},
    "bonus_code": {"uz": "🎁 BONUS KOD KIRITISH", "ru": "🎁 ВВЕСТИ БОНУС-КОД", "en": "🎁 ENTER BONUS CODE", "tr": "🎁 BONUS KODU GİR"},
    "vip_codes": {"uz": "🎬 VIP KINO KODLARI", "ru": "🎬 VIP КОДЫ ФИЛЬМОВ", "en": "🎬 VIP MOVIE CODES", "tr": "🎬 VIP FİLM KODLARI"},
    "vip_search_code": {"uz": "🔎 VIP KOD ORQALI QIDIRISH", "ru": "🔎 ПОИСК ПО VIP КОДУ", "en": "🔎 SEARCH BY VIP CODE", "tr": "🔎 VIP KODU İLE ARA"},
    "vip_enter_code": {"uz": "🔑 VIP KOD KIRITISH", "ru": "🔑 ВВЕСТИ VIP КОД", "en": "🔑 ENTER VIP CODE", "tr": "🔑 VIP KOD GİR"},
    "vip_apply": {"uz": "📝 VIP ARIZA YUBORISH", "ru": "📝 ПОДАТЬ ЗАЯВКУ VIP", "en": "📝 SUBMIT VIP APPLICATION", "tr": "📝 VIP BAŞVURUSU GÖNDER"},
    "vip_pay_confirm": {"uz": "💳 VIP PULGA TASDIQLASH", "ru": "💳 ПОДТВЕРДИТЬ ОПЛАТУ VIP", "en": "💳 CONFIRM VIP PAYMENT", "tr": "💳 VIP ÖDEMESİNİ ONAYLA"},
    "pro_codes": {"uz": "🎬 PRO KINO KODLARI", "ru": "🎬 PRO КОДЫ ФИЛЬМОВ", "en": "🎬 PRO MOVIE CODES", "tr": "🎬 PRO FİLM KODLARI"},
    "pro_search_code": {"uz": "🔎 PRO KOD ORQALI QIDIRISH", "ru": "🔎 ПОИСК ПО PRO КОДУ", "en": "🔎 SEARCH BY PRO CODE", "tr": "🔎 PRO KODU İLE ARA"},
    "pro_enter_code": {"uz": "🔑 PRO KOD KIRITISH", "ru": "🔑 ВВЕСТИ PRO КОД", "en": "🔑 ENTER PRO CODE", "tr": "🔑 PRO KOD GİR"},
    "pro_apply": {"uz": "📝 PRO ARIZA YUBORISH", "ru": "📝 ПОДАТЬ ЗАЯВКУ PRO", "en": "📝 SUBMIT PRO APPLICATION", "tr": "📝 PRO BAŞVURUSU GÖNDER"},
    "pro_pay_confirm": {"uz": "💳 PRO PULGA TASDIQLASH", "ru": "💳 ПОДТВЕРДИТЬ ОПЛАТУ PRO", "en": "💳 CONFIRM PRO PAYMENT", "tr": "💳 PRO ÖDEMESİNİ ONAYLA"},
    "recommend": {"uz": "🎯 TAVSIYA", "ru": "🎯 РЕКОМЕНДАЦИИ", "en": "🎯 RECOMMENDATIONS", "tr": "🎯 ÖNERİLER"},
    "search_history": {"uz": "🕘 QIDIRUV TARIXI", "ru": "🕘 ИСТОРИЯ ПОИСКА", "en": "🕘 SEARCH HISTORY", "tr": "🕘 ARAMA GEÇMİŞİ"},
    "vip_trial": {"uz": "🎁 3 KUNLIK BEPUL SINOV", "ru": "🎁 3-ДНЕВНЫЙ БЕСПЛАТНЫЙ ПРОБНЫЙ", "en": "🎁 3-DAY FREE TRIAL", "tr": "🎁 3 GÜNLÜK ÜCRETSİZ DENEME"},
    "pro_trial": {"uz": "🎁 3 KUNLIK BEPUL SINOV", "ru": "🎁 3-ДНЕВНЫЙ БЕСПЛАТНЫЙ ПРОБНЫЙ", "en": "🎁 3-DAY FREE TRIAL", "tr": "🎁 3 GÜNLÜK ÜCRETSİZ DENEME"},
    "random_movie": {"uz": "🎲 TASODIFIY KINO", "ru": "🎲 СЛУЧАЙНЫЙ ФИЛЬМ", "en": "🎲 RANDOM MOVIE", "tr": "🎲 RASTGELE FİLM"},
    "coming_soon": {"uz": "📅 TEZ ORADA", "ru": "📅 СКОРО", "en": "📅 COMING SOON", "tr": "📅 YAKINDA"},
}


def menu_label(key: str, telegram_id: int = None) -> str:
    """Berilgan tugma-kaliti uchun foydalanuvchi tilidagi matnni qaytaradi."""
    lang = get_user_lang(telegram_id) if telegram_id is not None else "uz"
    variants = MENU_LABELS[key]
    return variants.get(lang, variants["uz"])


def btn(key: str):
    """Shu tugmaning barcha til-variantlaridan birortasiga mos keladigan aiogram filtri."""
    return F.text.in_(list(MENU_LABELS[key].values()))


# ---------- Eng ko'p uchraydigan javob matnlari uchun tarjima ----------
RESPONSE_TEXT = {
    "search_prompt": {
        "uz": "Kino nomi yoki kodini kiriting:", "ru": "Введите название или код фильма:",
        "en": "Enter the movie name or code:", "tr": "Film adını veya kodunu girin:",
    },
    "search_not_found": {
        "uz": "❌ Hech narsa topilmadi.", "ru": "❌ Ничего не найдено.",
        "en": "❌ Nothing found.", "tr": "❌ Hiçbir şey bulunamadı.",
    },
    "code_not_found_generic": {
        "uz": "❌ Bunday kod topilmadi yoki allaqachon ishlatilgan.",
        "ru": "❌ Такой код не найден или уже использован.",
        "en": "❌ Code not found or already used.",
        "tr": "❌ Böyle bir kod bulunamadı veya zaten kullanıldı.",
    },
    "tariff_code_not_found": {
        "uz": "❌ Bunday kod topilmadi yoki boshqa foydalanuvchi tomonidan ishlatilgan.",
        "ru": "❌ Код не найден или уже использован другим пользователем.",
        "en": "❌ Code not found or already used by another user.",
        "tr": "❌ Kod bulunamadı veya başka bir kullanıcı tarafından kullanıldı.",
    },
    "vip_code_not_found": {
        "uz": "❌ Bunday VIP kod topilmadi.", "ru": "❌ Такой VIP-код не найден.",
        "en": "❌ VIP code not found.", "tr": "❌ Böyle bir VIP kod bulunamadı.",
    },
    "pro_code_not_found": {
        "uz": "❌ Bunday PRO kod topilmadi.", "ru": "❌ Такой PRO-код не найден.",
        "en": "❌ PRO code not found.", "tr": "❌ Böyle bir PRO kod bulunamadı.",
    },
    "mandatory_none": {
        "uz": "Hozircha majburiy obuna kanallari yo'q.", "ru": "Пока нет обязательных каналов для подписки.",
        "en": "There are no mandatory subscription channels yet.", "tr": "Henüz zorunlu abonelik kanalı yok.",
    },
    "mandatory_header": {
        "uz": "📡 <b>Majburiy obuna kanallari:</b>", "ru": "📡 <b>Обязательные каналы для подписки:</b>",
        "en": "📡 <b>Mandatory subscription channels:</b>", "tr": "📡 <b>Zorunlu abone olunacak kanallar:</b>",
    },
    "favorites_empty": {
        "uz": "⭐️ Sevimlilar ro'yxatingiz bo'sh.\nKino ochganingizda \"⭐️ Sevimlilarga qo'shish\" tugmasini bosing.",
        "ru": "⭐️ Список избранного пуст.\nОткрыв фильм, нажмите \"⭐️ Добавить в избранное\".",
        "en": "⭐️ Your favorites list is empty.\nWhen you open a movie, tap \"⭐️ Add to favorites\".",
        "tr": "⭐️ Favori listeniz boş.\nBir film açtığınızda \"⭐️ Favorilere ekle\" düğmesine basın.",
    },
    "favorites_header": {
        "uz": "⭐️ Sevimlilaringiz ({n}):", "ru": "⭐️ Ваше избранное ({n}):",
        "en": "⭐️ Your favorites ({n}):", "tr": "⭐️ Favorileriniz ({n}):",
    },
    "balance_line": {
        "uz": "💰 Balansingiz: <b>{balance}</b> so'm", "ru": "💰 Ваш баланс: <b>{balance}</b> сум",
        "en": "💰 Your balance: <b>{balance}</b> UZS", "tr": "💰 Bakiyeniz: <b>{balance}</b> so'm",
    },
    "menu_label": {
        "uz": "Menyu:", "ru": "Меню:", "en": "Menu:", "tr": "Menü:",
    },
    "ask_name": {
        "uz": "👤 Iltimos, ismingizni kiriting:",
        "ru": "👤 Пожалуйста, введите ваше имя:",
        "en": "👤 Please enter your name:",
        "tr": "👤 Lütfen adınızı girin:",
    },
    "ask_name_invalid": {
        "uz": "❌ Iltimos, haqiqiy ism kiriting (kamida 2 ta harf).",
        "ru": "❌ Пожалуйста, введите настоящее имя (минимум 2 буквы).",
        "en": "❌ Please enter a valid name (at least 2 letters).",
        "tr": "❌ Lütfen geçerli bir isim girin (en az 2 harf).",
    },
    "ask_phone": {
        "uz": "📞 Endi telefon raqamingizni pastdagi tugma orqali ulashing:",
        "ru": "📞 Теперь поделитесь своим номером телефона кнопкой снизу:",
        "en": "📞 Now share your phone number using the button below:",
        "tr": "📞 Şimdi telefon numaranızı aşağıdaki düğmeyle paylaşın:",
    },
    "share_phone_btn": {
        "uz": "📞 Raqamni ulashish", "ru": "📞 Поделиться номером",
        "en": "📞 Share phone number", "tr": "📞 Numarayı paylaş",
    },
    "phone_invalid": {
        "uz": "❌ Iltimos, faqat pastdagi \"📞 Raqamni ulashish\" tugmasidan foydalaning.",
        "ru": "❌ Пожалуйста, используйте только кнопку \"📞 Поделиться номером\" снизу.",
        "en": "❌ Please use the \"📞 Share phone number\" button below.",
        "tr": "❌ Lütfen sadece aşağıdaki \"📞 Numarayı paylaş\" düğmesini kullanın.",
    },
    "onboard_done": {
        "uz": "✅ Rahmat! Ro'yxatdan o'tish yakunlandi.",
        "ru": "✅ Спасибо! Регистрация завершена.",
        "en": "✅ Thank you! Registration complete.",
        "tr": "✅ Teşekkürler! Kayıt tamamlandı.",
    },
}


def t(key: str, telegram_id: int = None, **kwargs) -> str:
    """RESPONSE_TEXT lug'atidan foydalanuvchi tilidagi matnni qaytaradi (format() bilan)."""
    lang = get_user_lang(telegram_id) if telegram_id is not None else "uz"
    variants = RESPONSE_TEXT[key]
    text = variants.get(lang, variants["uz"])
    return text.format(**kwargs) if kwargs else text


def get_user_lang(telegram_id: int) -> str:
    with closing(db()) as conn:
        row = conn.execute("SELECT ui_lang FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        return (row["ui_lang"] if row and row["ui_lang"] else "uz")


def set_user_lang(telegram_id: int, lang: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, joined_at) VALUES (?, '', ?)",
            (telegram_id, datetime.utcnow().isoformat()),
        )
        conn.execute(
            "UPDATE users SET ui_lang=?, lang_chosen=1 WHERE telegram_id=?", (lang, telegram_id)
        )


def has_chosen_lang(telegram_id: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT lang_chosen FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return bool(row and row["lang_chosen"])


def welcome_text(telegram_id: int) -> str:
    return WELCOME_TEXT.get(get_user_lang(telegram_id), WELCOME_TEXT["uz"])


# ---------- Ro'yxatdan o'tish (ism + telefon) ----------

def set_user_full_name(telegram_id: int, full_name: str):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE users SET full_name=? WHERE telegram_id=?", (full_name, telegram_id))


def set_user_phone(telegram_id: int, phone: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE users SET phone=?, onboarded=1 WHERE telegram_id=?", (phone, telegram_id)
        )


def has_onboarded(telegram_id: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT onboarded FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return bool(row and row["onboarded"])


# ---------- Bir nechta til-slot (1..5) uchun yordamchi funksiyalar ----------
LANG_SLOT_NUMS = [1, 2, 3, 4, 5]
MAX_LANG_SLOTS = len(LANG_SLOT_NUMS)


def _slot_suffix(n: int) -> str:
    return "" if n == 1 else str(n)


def movie_slot_data(movie, n: int) -> dict:
    """n-slot (1..5) uchun til/fayl/kanal ma'lumotlarini qaytaradi."""
    suf = _slot_suffix(n)
    return {
        "language": movie[f"language{suf}"],
        "file_id": movie[f"file_id{suf}"],
        "channel_chat_id": movie[f"channel_chat_id{suf}"],
        "channel_message_id": movie[f"channel_message_id{suf}"],
    }


def movie_filled_slots(movie) -> list:
    """Kino ichida video biriktirilgan til-slotlar ro'yxati (kamida [1] bo'ladi)."""
    slots = []
    for n in LANG_SLOT_NUMS:
        suf = _slot_suffix(n)
        if movie[f"file_id{suf}"]:
            slots.append(n)
    return slots or [1]


def add_movie(code, name, genre, country, language, file_id, channel_chat_id=None,
              channel_message_id=None, is_vip=0, series_id=None, part_number=1,
              is_pro=0, **extra_slot_fields):
    """extra_slot_fields orqali 2..5-slotlar uchun language2..5, file_id2..5,
    channel_chat_id2..5, channel_message_id2..5 kabi maydonlar qo'shilishi mumkin."""
    fields = {
        "code": code, "name": name, "genre": genre, "country": country,
        "language": language, "file_id": file_id, "channel_chat_id": channel_chat_id,
        "channel_message_id": channel_message_id, "is_vip": is_vip,
        "series_id": series_id, "part_number": part_number, "is_pro": is_pro,
        "created_at": datetime.utcnow().isoformat(),
    }
    fields.update(extra_slot_fields)
    cols = ", ".join(fields.keys())
    placeholders = ", ".join(["?"] * len(fields))
    with closing(db()) as conn, conn:
        cur = conn.execute(
            f"INSERT INTO movies ({cols}) VALUES ({placeholders})",
            tuple(fields.values()),
        )
        return cur.lastrowid


def get_movie_by_code(code: str):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM movies WHERE code=?", (code,)).fetchone()


def search_movies_by_name(name: str, vip: bool = False):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE name LIKE ? AND is_vip=? LIMIT 20",
            (f"%{name}%", 1 if vip else 0),
        ).fetchall()


def fuzzy_search_movies_by_name(name: str, vip: bool = False, limit: int = 8):
    """LIKE qidiruv hech narsa topmasa ishlatiladigan, imlo xatolariga chidamli qidiruv.
    Standart kutubxonadagi difflib yordamida eng yaqin nomlarni topadi."""
    query = name.strip().lower()
    if not query:
        return []
    with closing(db()) as conn:
        rows = conn.execute(
            "SELECT * FROM movies WHERE is_vip=?", (1 if vip else 0,)
        ).fetchall()
    if not rows:
        return []
    by_name = {}
    for r in rows:
        key = (r["name"] or "").strip().lower()
        by_name.setdefault(key, r)
    close_names = difflib.get_close_matches(query, list(by_name.keys()), n=limit, cutoff=0.5)
    if not close_names:
        # So'z darajasida ham urinib ko'ramiz (masalan ko'p so'zli nomlarda bitta so'z xato bo'lsa)
        scored = []
        for key, r in by_name.items():
            ratio = difflib.SequenceMatcher(None, query, key).ratio()
            if ratio >= 0.4 or query in key or key in query:
                scored.append((ratio, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]
    return [by_name[k] for k in close_names]


def get_movies_by_genre(genre: str):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE genre LIKE ? AND is_vip=0", (f"%{genre}%",)
        ).fetchall()


def get_movie_by_id(movie_id: int):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()


def update_movie_field(movie_id: int, field: str, value):
    allowed = {"code", "name", "genre", "country", "language", "trailer_file_id"}
    if field not in allowed:
        raise ValueError(f"Bu maydonni o'zgartirib bo'lmaydi: {field}")
    with closing(db()) as conn, conn:
        conn.execute(f"UPDATE movies SET {field}=? WHERE id=?", (value, movie_id))


def delete_movie(movie_id: int):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM movies WHERE id=?", (movie_id,))


def search_movies_any(query: str, limit: int = 15):
    """Admin qidiruvi uchun — VIP va oddiy kinolarning barchasi orasidan qidiradi."""
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE name LIKE ? OR code LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()


def get_lang_variants(lang_group_id: int):
    """Bitta til-guruhidagi barcha variantlarni qaytaradi (turli tillardagi bir xil kino)."""
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE lang_group=? ORDER BY id", (lang_group_id,)
        ).fetchall()


def set_lang_group(movie_id: int, lang_group_id: int):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE movies SET lang_group=? WHERE id=?", (lang_group_id, movie_id))


def increment_views(movie_id: int):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE movies SET views = views + 1 WHERE id=?", (movie_id,))


# ---------- Sevimlilar ----------

def toggle_favorite(telegram_id: int, movie_id: int) -> bool:
    """True qaytaradi -> qo'shildi, False -> olib tashlandi."""
    with closing(db()) as conn, conn:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE telegram_id=? AND movie_id=?", (telegram_id, movie_id)
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM favorites WHERE telegram_id=? AND movie_id=?", (telegram_id, movie_id)
            )
            return False
        conn.execute(
            "INSERT INTO favorites (telegram_id, movie_id, created_at) VALUES (?, ?, ?)",
            (telegram_id, movie_id, datetime.utcnow().isoformat()),
        )
        return True


def is_favorite(telegram_id: int, movie_id: int) -> bool:
    with closing(db()) as conn:
        return conn.execute(
            "SELECT 1 FROM favorites WHERE telegram_id=? AND movie_id=?", (telegram_id, movie_id)
        ).fetchone() is not None


def list_favorites(telegram_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT m.* FROM favorites f JOIN movies m ON m.id = f.movie_id "
            "WHERE f.telegram_id=? ORDER BY f.created_at DESC", (telegram_id,)
        ).fetchall()


# ---------- Top kinolar ----------

def get_top_movies(limit: int = 10, is_vip: int = 0, is_pro: int = 0):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE is_vip=? AND is_pro=? ORDER BY views DESC LIMIT ?",
            (is_vip, is_pro, limit),
        ).fetchall()


# ---------- Kino reytingi ----------

def set_rating(telegram_id: int, movie_id: int, stars: int):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO ratings (telegram_id, movie_id, stars, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(telegram_id, movie_id) DO UPDATE SET stars=excluded.stars, created_at=excluded.created_at",
            (telegram_id, movie_id, stars, datetime.utcnow().isoformat()),
        )


def get_rating_summary(movie_id: int):
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT AVG(stars) as avg_stars, COUNT(*) as cnt FROM ratings WHERE movie_id=?", (movie_id,)
        ).fetchone()
        return row


# ---------- Serial (barcha qismlar) ----------

def get_series_parts(series_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE series_id=? ORDER BY part_number", (series_id,)
        ).fetchall()


def series_part_count(series_id: int) -> int:
    with closing(db()) as conn:
        return conn.execute("SELECT COUNT(*) c FROM movies WHERE series_id=?", (series_id,)).fetchone()["c"]


# ---------- Do'stlarni taklif qilish (referral) ----------

def set_referrer(telegram_id: int, referrer_id: int):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE users SET referred_by=? WHERE telegram_id=?", (referrer_id, telegram_id))


def get_referral_count(telegram_id: int) -> int:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE referred_by=?", (telegram_id,)
        ).fetchone()
        return row["cnt"] if row else 0


# ---------- Adminlar logi ----------

def log_admin_action(admin_id: int, action: str, detail: str = ""):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO admin_logs (admin_id, action, detail, created_at) VALUES (?, ?, ?, ?)",
            (admin_id, action, detail, datetime.utcnow().isoformat()),
        )


def get_recent_admin_logs(limit: int = 20):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


# ---------- Obuna tugashi haqida eslatma ----------

def get_memberships_needing_reminder(hours_ahead: int = 24):
    now = datetime.utcnow()
    soon = now + timedelta(hours=hours_ahead)
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM memberships WHERE expires_at IS NOT NULL AND reminded=0 "
            "AND expires_at <= ? AND expires_at > ?",
            (soon.isoformat(), now.isoformat()),
        ).fetchall()


def mark_membership_reminded(telegram_id: int, tier: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE memberships SET reminded=1 WHERE telegram_id=? AND tier=?", (telegram_id, tier)
        )


def get_next_part(series_id: int, part_number: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE series_id=? AND part_number=?",
            (series_id, part_number + 1),
        ).fetchone()


def get_max_part_number(series_id: int) -> int:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT MAX(part_number) m FROM movies WHERE series_id=?", (series_id,)
        ).fetchone()
        return row["m"] or 1


def link_movie_to_series(movie_id: int, series_id: int, part_number: int):
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE movies SET series_id=?, part_number=? WHERE id=?",
            (series_id, part_number, movie_id),
        )


def stats_users_count():
    with closing(db()) as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def stats_movies_count():
    with closing(db()) as conn:
        return conn.execute("SELECT COUNT(*) c FROM movies WHERE is_vip=0").fetchone()["c"]


def stats_top10():
    with closing(db()) as conn:
        return conn.execute(
            "SELECT name, views, code FROM movies WHERE is_vip=0 ORDER BY views DESC LIMIT 10"
        ).fetchall()


def create_vip_application(telegram_id, full_name, phone, birthdate):
    with closing(db()) as conn, conn:
        cur = conn.execute(
            """INSERT INTO vip_applications (telegram_id, full_name, phone, birthdate, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (telegram_id, full_name, phone, birthdate, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_pending_applications():
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM vip_applications WHERE status='pending' ORDER BY id"
        ).fetchall()


def approve_application(app_id: int, code: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE vip_applications SET status='approved', vip_code=? WHERE id=?",
            (code, app_id),
        )


def reject_application(app_id: int):
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE vip_applications SET status='rejected' WHERE id=?", (app_id,)
        )


def get_application(app_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM vip_applications WHERE id=?", (app_id,)
        ).fetchone()


def user_has_approved_vip(telegram_id: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT 1 FROM vip_applications WHERE telegram_id=? AND status='approved'",
            (telegram_id,),
        ).fetchone()
        return row is not None


def has_pending_vip_application(telegram_id: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT 1 FROM vip_applications WHERE telegram_id=? AND status='pending'",
            (telegram_id,),
        ).fetchone()
        return row is not None


# ---------- TARIF TIZIMI (VIP / Pro / Hamkor muddatlari) ----------
# tier: "vip" | "pro" | "hamkor"
# plan: "1m" (1 oylik), "3m" (3 oylik), "6m" (6 oylik), "12m" (1 yillik), "lifetime" (doimiy)

PLAN_LABELS = {
    "1m": "1 oylik",
    "3m": "3 oylik",
    "6m": "6 oylik",
    "12m": "1 yillik",
    "lifetime": "♾ Doimiy",
    "trial": "🎁 3 kunlik sinov",
}
PLAN_DAYS = {"1m": 30, "3m": 90, "6m": 180, "12m": 365, "lifetime": None}
TIER_PLANS = {
    "vip": ["1m", "3m", "6m", "lifetime"],
    "pro": ["1m", "3m", "6m", "12m"],
    "hamkor": ["1m", "3m", "6m", "12m"],
}
TIER_PREFIX = {"vip": "VIP", "pro": "PRO", "hamkor": "HMK"}
TIER_TITLES = {"vip": "⭐️ VIP", "pro": "💎 PRO", "hamkor": "🤝 Hamkor"}


def tariff_price(tier: str, plan: str) -> int:
    return int(get_setting(f"price_{tier}_{plan}") or "0")


def generate_tariff_code(tier: str) -> str:
    import random, string
    prefix = TIER_PREFIX.get(tier, "GEN")
    while True:
        code = f"{prefix}-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        with closing(db()) as conn:
            exists = conn.execute("SELECT 1 FROM tariff_codes WHERE code=?", (code,)).fetchone()
        if not exists:
            return code


def issue_tariff_code(tier: str, plan: str, telegram_id: int = None, max_uses: int = 1) -> str:
    code = generate_tariff_code(tier)
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO tariff_codes (code, tier, plan, telegram_id, created_at, max_uses) VALUES (?, ?, ?, ?, ?, ?)",
            (code, tier, plan, telegram_id, datetime.utcnow().isoformat(), max_uses),
        )
    return code


def get_tariff_code(code: str):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM tariff_codes WHERE code=?", (code,)).fetchone()


def get_membership(telegram_id: int, tier: str):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM memberships WHERE telegram_id=? AND tier=?", (telegram_id, tier)
        ).fetchone()


def has_active_membership(telegram_id: int, tier: str) -> bool:
    m = get_membership(telegram_id, tier)
    if not m:
        return False
    if m["banned"]:
        return False
    if m["expires_at"] is None:
        return True
    try:
        return datetime.fromisoformat(m["expires_at"]) > datetime.utcnow()
    except Exception:
        return False


def set_membership(telegram_id: int, tier: str, plan: str):
    """Muddatni yozadi. Agar hozirgi obuna hali tugamagan bo'lsa, yangi muddat
    ustiga QO'SHILADI (cho'ziladi), boshidan sanalmaydi."""
    days = PLAN_DAYS.get(plan)
    now = datetime.utcnow()
    existing = get_membership(telegram_id, tier)

    if existing and existing["expires_at"] is None:
        expires_at = None  # allaqachon cheksiz — cheksiz bo'lib qoladi
    elif days is None:
        expires_at = None
    else:
        base = now
        if existing and existing["expires_at"]:
            try:
                existing_exp = datetime.fromisoformat(existing["expires_at"])
                if existing_exp > now:
                    base = existing_exp
            except Exception:
                pass
        expires_at = (base + timedelta(days=days)).isoformat()

    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO memberships (telegram_id, tier, plan, expires_at, reminded) VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(telegram_id, tier) DO UPDATE SET plan=excluded.plan, expires_at=excluded.expires_at, reminded=0",
            (telegram_id, tier, plan, expires_at),
        )


def redeem_tariff_code(code: str, telegram_id: int, expected_tier: str = None):
    """Kodni faollashtiradi.
    - Yangi kod bo'lsa: birinchi marta ishlatiladi, muddat HOZIRDAN boshlab hisoblanadi.
    - Kod ALLAQACHON shu FOYDALANUVCHI tomonidan ishlatilgan bo'lsa (masalan admin uni
      Hamkor/VIP/PRO ro'yxatidan o'chirib yuborgan, lekin muddati hali tugamagan):
      qayta kiritilganda ASL muddat (birinchi faollashtirilgan vaqt + tarif kunlari)
      asosida obuna QAYTA tiklanadi (cho'zilmaydi).
    - Kod muddati allaqachon tugagan bo'lsa -> "EXPIRED" qaytariladi.
    - Kod boshqa foydalanuvchi tomonidan ishlatilgan bo'lsa -> None (rad etiladi).
    Muvaffaqiyatli bo'lsa tariff_codes qatorini qaytaradi, aks holda None yoki "EXPIRED"."""
    row = get_tariff_code(code)
    if not row:
        return None
    if expected_tier and row["tier"] != expected_tier:
        return None

    max_uses = row["max_uses"] if row["max_uses"] is not None else 1

    if max_uses != 1:
        # Ko'p martalik (multi-use) generik kod — turli foydalanuvchilar mustaqil ravishda
        # o'zlarining muddatini oladi, redeemed_by ustuni ishlatilmaydi.
        with closing(db()) as conn:
            own_use = conn.execute(
                "SELECT * FROM tariff_code_uses WHERE code=? AND telegram_id=?", (code, telegram_id)
            ).fetchone()
        if own_use:
            days = PLAN_DAYS.get(row["plan"])
            if days is None:
                set_membership(telegram_id, row["tier"], row["plan"])
                return row
            try:
                redeemed_at = datetime.fromisoformat(own_use["redeemed_at"])
            except Exception:
                redeemed_at = datetime.utcnow()
            original_expiry = redeemed_at + timedelta(days=days)
            if original_expiry <= datetime.utcnow():
                return "EXPIRED"
            with closing(db()) as conn, conn:
                conn.execute(
                    "INSERT INTO memberships (telegram_id, tier, plan, expires_at, reminded) VALUES (?, ?, ?, ?, 0) "
                    "ON CONFLICT(telegram_id, tier) DO UPDATE SET plan=excluded.plan, expires_at=excluded.expires_at, reminded=0",
                    (telegram_id, row["tier"], row["plan"], original_expiry.isoformat()),
                )
            return row

        if max_uses > 0:
            with closing(db()) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) c FROM tariff_code_uses WHERE code=?", (code,)
                ).fetchone()["c"]
            if count >= max_uses:
                return None  # limit tugagan

        with closing(db()) as conn, conn:
            conn.execute(
                "INSERT INTO tariff_code_uses (code, telegram_id, redeemed_at) VALUES (?, ?, ?)",
                (code, telegram_id, datetime.utcnow().isoformat()),
            )
        set_membership(telegram_id, row["tier"], row["plan"])
        return row

    if row["redeemed_by"] is not None:
        if row["redeemed_by"] != telegram_id:
            return None  # boshqa foydalanuvchining kodi — rad etiladi

        # O'zining eski kodini qayta kiritmoqda — asl muddatni tiklaymiz.
        days = PLAN_DAYS.get(row["plan"])
        if days is None:
            set_membership(telegram_id, row["tier"], row["plan"])
            return row
        try:
            redeemed_at = datetime.fromisoformat(row["redeemed_at"])
        except Exception:
            redeemed_at = datetime.utcnow()
        original_expiry = redeemed_at + timedelta(days=days)
        if original_expiry <= datetime.utcnow():
            return "EXPIRED"
        with closing(db()) as conn, conn:
            conn.execute(
                "INSERT INTO memberships (telegram_id, tier, plan, expires_at, reminded) VALUES (?, ?, ?, ?, 0) "
                "ON CONFLICT(telegram_id, tier) DO UPDATE SET plan=excluded.plan, expires_at=excluded.expires_at, reminded=0",
                (telegram_id, row["tier"], row["plan"], original_expiry.isoformat()),
            )
        return row

    # Birinchi marta ishlatilishi
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE tariff_codes SET redeemed_by=?, redeemed_at=? WHERE code=?",
            (telegram_id, datetime.utcnow().isoformat(), code),
        )
    set_membership(telegram_id, row["tier"], row["plan"])
    return row


def issue_and_activate_code(tier: str, plan: str, telegram_id: int) -> str:
    """Ma'lum bir foydalanuvchi uchun kodni yaratadi VA darhol unga faollashtiradi
    (masalan admin arizani tasdiqlaganda yoki foydalanuvchi pul bilan sotib olganda)."""
    code = issue_tariff_code(tier, plan, telegram_id)
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE tariff_codes SET redeemed_by=?, redeemed_at=? WHERE code=?",
            (telegram_id, datetime.utcnow().isoformat(), code),
        )
    set_membership(telegram_id, tier, plan)
    return code


def membership_status_text(telegram_id: int, tier: str) -> str:
    m = get_membership(telegram_id, tier)
    if not m or not has_active_membership(telegram_id, tier):
        return "❌ Faol obuna yo'q."
    if m["expires_at"] is None:
        return f"✅ Faol ({PLAN_LABELS.get(m['plan'], m['plan'])}) — ♾ muddatsiz."
    return f"✅ Faol ({PLAN_LABELS.get(m['plan'], m['plan'])}) — {m['expires_at'][:10]} gacha."


def list_active_memberships(tier: str):
    now = datetime.utcnow().isoformat()
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM memberships WHERE tier=? AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY telegram_id", (tier, now),
        ).fetchall()


def set_membership_banned(telegram_id: int, tier: str, banned: bool):
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE memberships SET banned=? WHERE telegram_id=? AND tier=?",
            (1 if banned else 0, telegram_id, tier),
        )


def delete_membership(telegram_id: int, tier: str):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM memberships WHERE telegram_id=? AND tier=?", (telegram_id, tier))


def list_admins():
    with closing(db()) as conn:
        return [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM admins ORDER BY telegram_id")]


def tariff_plan_kb(tier: str, callback_prefix: str) -> InlineKeyboardMarkup:
    kb = []
    for plan in TIER_PLANS[tier]:
        price = tariff_price(tier, plan)
        kb.append([InlineKeyboardButton(
            text=f"{PLAN_LABELS[plan]} — {price} so'm",
            callback_data=f"{callback_prefix}:{plan}",
        style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ---------- Oddiy (generik) arizalar — Pro va (keyinchalik) Hamkor uchun ----------

def create_tier_application(telegram_id: int, tier: str) -> int:
    with closing(db()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO tier_applications (telegram_id, tier, created_at) VALUES (?, ?, ?)",
            (telegram_id, tier, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_tier_application(app_id: int):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM tier_applications WHERE id=?", (app_id,)).fetchone()


def get_pending_tier_applications(tier: str):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM tier_applications WHERE tier=? AND status='pending' ORDER BY id", (tier,)
        ).fetchall()


def has_pending_tier_application(telegram_id: int, tier: str) -> bool:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT 1 FROM tier_applications WHERE telegram_id=? AND tier=? AND status='pending'",
            (telegram_id, tier),
        ).fetchone()
        return row is not None


def set_tier_application_status(app_id: int, status: str):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE tier_applications SET status=? WHERE id=?", (status, app_id))


# ---------- HISOBIM (balans) ----------

def get_balance(telegram_id: int) -> int:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT amount FROM balances WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return row["amount"] if row else 0


def add_balance(telegram_id: int, amount: int):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO balances (telegram_id, amount) VALUES (?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET amount = amount + excluded.amount",
            (telegram_id, amount),
        )


def set_balance(telegram_id: int, amount: int):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO balances (telegram_id, amount) VALUES (?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET amount = excluded.amount",
            (telegram_id, amount),
        )


# ---------- Bonus kodlar ----------

def generate_bonus_code(amount: int, max_uses: int = 1) -> str:
    import random, string
    code = "B" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO bonus_codes (code, amount, created_at, max_uses) VALUES (?, ?, ?, ?)",
            (code, amount, datetime.utcnow().isoformat(), max_uses),
        )
    return code


def get_bonus_code(code: str):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM bonus_codes WHERE code=?", (code,)).fetchone()


def redeem_bonus_code(code: str, telegram_id: int):
    """Returns amount if successfully redeemed, 'ALREADY_USED' if this user already
    redeemed this exact code, or None if not found / limit reached."""
    with closing(db()) as conn, conn:
        row = conn.execute(
            "SELECT * FROM bonus_codes WHERE code=?", (code,)
        ).fetchone()
        if not row:
            return None
        max_uses = row["max_uses"] if row["max_uses"] is not None else 1

        already = conn.execute(
            "SELECT 1 FROM bonus_code_uses WHERE code=? AND telegram_id=?", (code, telegram_id)
        ).fetchone()
        if already:
            return "ALREADY_USED"

        if max_uses == 1:
            if row["used_by"] is not None:
                return None
        elif max_uses > 0:
            count = conn.execute(
                "SELECT COUNT(*) c FROM bonus_code_uses WHERE code=?", (code,)
            ).fetchone()["c"]
            if count >= max_uses:
                return None

        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO bonus_code_uses (code, telegram_id, used_at) VALUES (?, ?, ?)",
            (code, telegram_id, now),
        )
        conn.execute(
            "UPDATE bonus_codes SET used_by=?, used_at=? WHERE code=?",
            (telegram_id, now, code),
        )
        conn.execute(
            "INSERT INTO balances (telegram_id, amount) VALUES (?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET amount = amount + excluded.amount",
            (telegram_id, row["amount"]),
        )
        return row["amount"]


# ---------- Majburiy obuna ----------

def add_mandatory_channel(chat_id: int, link: str, title: str, threshold: int):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO mandatory_channels (chat_id, link, title, threshold, active) "
            "VALUES (?, ?, ?, ?, 1)",
            (chat_id, link, title, threshold),
        )


def list_mandatory_channels(active_only: bool = True):
    with closing(db()) as conn:
        if active_only:
            return conn.execute(
                "SELECT * FROM mandatory_channels WHERE active=1"
            ).fetchall()
        return conn.execute("SELECT * FROM mandatory_channels").fetchall()


def deactivate_mandatory_channel(channel_id: int):
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE mandatory_channels SET active=0 WHERE id=?", (channel_id,)
        )


def remove_mandatory_channel(channel_id: int):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM mandatory_channels WHERE id=?", (channel_id,))


async def autocheck_mandatory_thresholds():
    """Har bir faol majburiy kanal uchun obunachilar sonini tekshiradi;
    agar belgilangan chegaraga yetgan bo'lsa, kanalni avtomatik o'chiradi."""
    for ch in list_mandatory_channels(active_only=True):
        if not ch["threshold"]:
            continue
        try:
            count = await user_bot.get_chat_member_count(ch["chat_id"])
            if count >= ch["threshold"]:
                deactivate_mandatory_channel(ch["id"])
        except Exception as e:
            logger.warning(f"Obunachilar sonini olib bo'lmadi ({ch['chat_id']}): {e}")


async def get_missing_subscriptions(user_id: int):
    """Foydalanuvchi obuna bo'lmagan faol majburiy kanallar ro'yxatini qaytaradi."""
    await autocheck_mandatory_thresholds()
    missing = []
    for ch in list_mandatory_channels(active_only=True):
        try:
            member = await user_bot.get_chat_member(ch["chat_id"], user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            logger.warning(f"Obunani tekshirib bo'lmadi ({ch['chat_id']}): {e}")
    return missing


# ---------- Hamkorlik (partnyorlik) ----------

def create_partner_application(telegram_id: int, channel_link: str):
    with closing(db()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO partners (telegram_id, channel_link, created_at) VALUES (?, ?, ?)",
            (telegram_id, channel_link, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_pending_partners():
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM partners WHERE status='pending' ORDER BY id"
        ).fetchall()


def has_pending_partner_application(telegram_id: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT 1 FROM partners WHERE telegram_id=? AND status='pending'", (telegram_id,)
        ).fetchone()
        return row is not None


def get_partner(partner_id: int):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM partners WHERE id=?", (partner_id,)).fetchone()


def approve_partner(partner_id: int, letter_prefix: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE partners SET status='approved', letter_prefix=? WHERE id=?",
            (letter_prefix.upper(), partner_id),
        )


def reject_partner(partner_id: int):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE partners SET status='rejected' WHERE id=?", (partner_id,))


def get_approved_partner_by_uid(telegram_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM partners WHERE telegram_id=? AND status='approved' "
            "AND (banned IS NULL OR banned=0)",
            (telegram_id,),
        ).fetchone()


def next_available_partner_letter() -> str:
    """M va R harflari o'z (admin) ishlatishi uchun ajratilgan — hamkorlarga berilmaydi."""
    with closing(db()) as conn:
        used = {r["letter_prefix"] for r in conn.execute(
            "SELECT letter_prefix FROM partners WHERE status='approved' AND letter_prefix IS NOT NULL"
        )}
    reserved = {"M", "R"}
    import string
    for letter in string.ascii_uppercase:
        if letter not in used and letter not in reserved:
            return letter
    return "Z"  # zaxira, agar barcha harflar tugab qolsa


def next_partner_code(prefix: str) -> str:
    """Hamkorning harfi asosida keyingi bo'sh kodni topadi (masalan A001, A002...)."""
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT code FROM movies WHERE code LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{prefix}%",),
        ).fetchone()
    if not row:
        n = 1
    else:
        digits = "".join(ch for ch in row["code"][len(prefix):] if ch.isdigit())
        n = (int(digits) + 1) if digits else 1
    return f"{prefix}{n:03d}"


# ---------- Hisobni to'ldirish so'rovlari ----------

def create_topup_request(telegram_id: int, amount: int, receipt_file_id: str):
    with closing(db()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO topup_requests (telegram_id, amount, receipt_file_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (telegram_id, amount, receipt_file_id, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_pending_topups():
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM topup_requests WHERE status='pending' ORDER BY id"
        ).fetchall()


def get_topup(topup_id: int):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM topup_requests WHERE id=?", (topup_id,)).fetchone()


def approve_topup(topup_id: int):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE topup_requests SET status='approved' WHERE id=?", (topup_id,))


def reject_topup(topup_id: int):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE topup_requests SET status='rejected' WHERE id=?", (topup_id,))


# ---------- TUSHUM (admin uchun umumiy to'lovlar hisoboti) ----------

def record_revenue(source: str, telegram_id: int, amount: int, note: str = ""):
    """Har bir tasdiqlangan to'lov (hisob to'ldirish, VIP, hamkorlik, reklama)
    shu jadvalga yoziladi — admin panelda 'qancha pul tushgani' shundan hisoblanadi."""
    if not amount:
        return
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO revenue (source, telegram_id, amount, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (source, telegram_id, amount, note, datetime.utcnow().isoformat()),
        )


def get_revenue_total() -> int:
    with closing(db()) as conn:
        row = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM revenue").fetchone()
        return row["s"]


def get_revenue_breakdown():
    with closing(db()) as conn:
        return conn.execute(
            "SELECT source, COUNT(*) cnt, COALESCE(SUM(amount),0) total FROM revenue GROUP BY source ORDER BY total DESC"
        ).fetchall()


def get_recent_revenue(limit: int = 10):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM revenue ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


# ---------- Hamkorlar ro'yxati (admin: taqiqlash/ruxsat berish/o'chirish) ----------

def list_all_partners():
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM partners ORDER BY id DESC").fetchall()


def clear_membership(telegram_id: int, tier: str):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM memberships WHERE telegram_id=? AND tier=?", (telegram_id, tier))


def ban_partner(partner_id: int):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE partners SET banned=1 WHERE id=?", (partner_id,))


def unban_partner(partner_id: int):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE partners SET banned=0 WHERE id=?", (partner_id,))


def delete_partner_record(partner_id: int):
    partner = get_partner(partner_id)
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM partners WHERE id=?", (partner_id,))
    if partner:
        # Hamkor o'chirilganda uning "hamkor" tarifi/obunasi ham faolsizlantiriladi —
        # aks holda memberships jadvalida eski muddat qolib, "obunasi faol" ko'rsatib turardi.
        clear_membership(partner["telegram_id"], "hamkor")


def count_partner_movies(prefix: str) -> int:
    if not prefix:
        return 0
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM movies WHERE code LIKE ?", (f"{prefix}%",)
        ).fetchone()
        return row["c"]


def get_all_user_ids():
    with closing(db()) as conn:
        return [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM users")]


# ---------- Chat bot (admin <-> foydalanuvchi) ----------

def touch_chat_thread(telegram_id: int, username: str, full_name: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO chat_threads (telegram_id, username, full_name, last_message_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, "
            "full_name=excluded.full_name, last_message_at=excluded.last_message_at",
            (telegram_id, username or "", full_name or "", datetime.utcnow().isoformat()),
        )


def add_chat_message(telegram_id: int, sender: str, text: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO chat_messages (telegram_id, sender, text, created_at) VALUES (?, ?, ?, ?)",
            (telegram_id, sender, text, datetime.utcnow().isoformat()),
        )


def list_chat_threads():
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM chat_threads ORDER BY last_message_at DESC LIMIT 50"
        ).fetchall()


def get_chat_history(telegram_id: int, limit: int = 15):
    with closing(db()) as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE telegram_id=? ORDER BY id DESC LIMIT ?",
            (telegram_id, limit),
        ).fetchall()
        return list(reversed(rows))


# ============================================================
# FSM HOLATLARI
# ============================================================

class Onboarding(StatesGroup):
    waiting_name = State()
    waiting_phone = State()


class UploadMovie(StatesGroup):
    waiting_video = State()
    waiting_name = State()
    waiting_video2 = State()  # 2-til tanlanganda, shu bitta kod uchun 2-video
    waiting_code = State()


class SearchByCode(StatesGroup):
    waiting_code = State()


class SearchByName(StatesGroup):
    waiting_name = State()


class VipApplication(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_birthdate = State()


class VipCodeSearch(StatesGroup):
    waiting_code = State()


class ProCodeSearch(StatesGroup):
    waiting_code = State()


class TariffRedeem(StatesGroup):
    waiting_code = State()


class AdminGiveCode(StatesGroup):
    waiting_code = State()


class SettingsEdit(StatesGroup):
    waiting_text = State()


class AdminManage(StatesGroup):
    waiting_admin_id = State()


class BonusRedeem(StatesGroup):
    waiting_code = State()


class TopupRequest(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()


class AdminTopupDecision(StatesGroup):
    waiting_note = State()


class AdminBonusGenerate(StatesGroup):
    waiting_amount = State()
    waiting_max_uses = State()


class AdminTariffBonusGenerate(StatesGroup):
    waiting_max_uses = State()


class HamkorlikApply(StatesGroup):
    waiting_link = State()


class PartnerApprove(StatesGroup):
    waiting_letter = State()


class PartnerUpload(StatesGroup):
    waiting_video = State()
    waiting_name = State()
    waiting_video2 = State()  # 2-til tanlanganda, shu bitta kod uchun 2-video


class TaxonomyAdd(StatesGroup):
    waiting_name = State()


class ReklamaOrder(StatesGroup):
    waiting_content = State()


class ChatSession(StatesGroup):
    active = State()


class AdminChatReply(StatesGroup):
    waiting_text = State()


class MandatoryChannelAdd(StatesGroup):
    waiting_chat_id = State()
    waiting_link = State()
    waiting_title = State()
    waiting_threshold = State()


class MandatorySelfService(StatesGroup):
    """Oddiy foydalanuvchi o'z kanalini pullik majburiy obunaga qo'shishi uchun."""
    waiting_chat = State()
    waiting_count = State()


class HamkorLetterPick(StatesGroup):
    """Bonus/tarif kodi orqali YANGI hamkor bo'lgan odam o'zi uchun harf tanlashi uchun."""
    waiting_letter = State()


class SequelLink(StatesGroup):
    """Kino qo'shilgandan keyin 'davomi' yoki 'til varianti'ni KOD orqali qo'lda bog'lash uchun
    (agar kerakli kino so'nggi 8 talik ro'yxatda ko'rinmasa)."""
    waiting_seq_code = State()
    waiting_langlink_code = State()


class SeriesPartUpload(StatesGroup):
    """'Kinolarni boshqarish' kartasidan to'g'ridan-to'g'ri YANGI qism (video) yuklash uchun
    — 'Keyingi qism' / 'Oldingi qism' tugmalari orqali."""
    waiting_video = State()
    waiting_code = State()


class SeriesJoin(StatesGroup):
    """Allaqachon mavjud (alohida kodli) kinoni BOSHQA seriyaga NOM yoki KOD orqali
    qidirib qo'shish uchun — 'Qo'shish (boshqa seriyaga)' tugmasi orqali."""
    waiting_query = State()


class AdEdit(StatesGroup):
    """Segmentlashtirilgan reklamalar (VIP/PRO/HAMMAGA/ODDIYLARGA/KOD KANALGA):
    kontent (matn/rasm/video) + ixtiyoriy inline tugma/link."""
    waiting_content = State()
    waiting_btn_text = State()
    waiting_url = State()


class BroadcastMsg(StatesGroup):
    waiting_content = State()


class MovieManage(StatesGroup):
    waiting_search = State()
    waiting_new_value = State()
    waiting_trailer = State()


class MovieLangEdit(StatesGroup):
    waiting_new_video = State()
    waiting_pick_code = State()


# ============================================================
# KLAVIATURALAR
# ============================================================

def main_menu_kb(admin: bool = False, partner: bool = False, telegram_id: int = None) -> ReplyKeyboardMarkup:
    L = lambda k: menu_label(k, telegram_id)
    rows = [
        [KeyboardButton(text=L("search")), KeyboardButton(text=L("codes"))],
        [KeyboardButton(text=L("genres")), KeyboardButton(text=L("wallet"))],
        [KeyboardButton(text=L("favorites")), KeyboardButton(text=L("top"))],
        [KeyboardButton(text=L("recommend")), KeyboardButton(text=L("search_history"))],
        [KeyboardButton(text=L("random_movie")), KeyboardButton(text=L("coming_soon"))],
        [KeyboardButton(text="🚀 MINI APP", web_app=WebAppInfo(url=MINIAPP_URL))],
        [KeyboardButton(text=L("services")), KeyboardButton(text=L("invite"))],
    ]
    if partner:
        rows.append([KeyboardButton(text=L("partner_upload"))])
    # Diqqat: "🛠 ADMIN PANEL" tugmasi endi bu yerda ko'rsatilmaydi — admin panel
    # butunlay alohida ADMIN botga (ADMIN_BOT_TOKEN) ko'chirildi. Admin shu (ODDIY)
    # botda oddiy foydalanuvchi sifatida ishlaydi, boshqaruv esa ADMIN botda amalga oshiriladi.
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def user_menu_kb(telegram_id: int) -> ReplyKeyboardMarkup:
    """Foydalanuvchi turiga (admin/hamkor/oddiy) qarab to'g'ri asosiy menyuni qaytaradi."""
    admin = is_admin(telegram_id)
    partner = get_approved_partner_by_uid(telegram_id) is not None
    return main_menu_kb(admin, partner, telegram_id)


def services_kb(telegram_id: int = None) -> ReplyKeyboardMarkup:
    L = lambda k: menu_label(k, telegram_id)
    rows = [
        [KeyboardButton(text=L("vip")), KeyboardButton(text=L("pro"))],
        [KeyboardButton(text=L("contact"))],
        [KeyboardButton(text=L("ads"))],
        [KeyboardButton(text=L("mandatory_sub"))],
        [KeyboardButton(text=L("partnership")), KeyboardButton(text=L("chatbot"))],
        [KeyboardButton(text=L("back_normal"))],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def hisobim_kb(telegram_id: int = None) -> ReplyKeyboardMarkup:
    L = lambda k: menu_label(k, telegram_id)
    rows = [
        [KeyboardButton(text=L("topup"))],
        [KeyboardButton(text=L("bonus_code"))],
        [KeyboardButton(text=L("back_normal"))],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def chat_kb(telegram_id: int = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=menu_label("back_normal", telegram_id))]],
        resize_keyboard=True,
    )


def category_kb() -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=c, callback_data=f"cat:{c}", style="primary")] for c in list_genres()]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def select_kb(items, selected, flow: str, kind: str, done_text="➡️ Tayyor") -> InlineKeyboardMarkup:
    """Ko'p/bitta tanlov uchun umumiy inline klaviatura. flow: 'adm'/'ptn', kind: 'g'/'c'/'l'."""
    kb = []
    for it in items:
        mark = "✅ " if it in selected else "☐ "
        kb.append([InlineKeyboardButton(text=f"{mark}{it}", callback_data=f"pick:{flow}:{kind}:{it}", style="primary")])
    kb.append([InlineKeyboardButton(text=done_text, callback_data=f"pickdone:{flow}:{kind}", style="success")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def taxonomy_admin_kb(items, kind: str) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text="➕ Qo'shish", callback_data=f"tax_add:{kind}", style="success")]]
    for it in items:
        kb.append([InlineKeyboardButton(text=f"🗑 {it}", callback_data=f"tax_del:{kind}:{it}", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def sequel_pick_kb(movies, flow: str) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"seq:{flow}:{m['code']}", style="primary")]
          for m in movies]
    kb.append([InlineKeyboardButton(text="🔎 Boshqa kod kiriting", callback_data=f"seq:{flow}:custom", style="primary")])
    kb.append([InlineKeyboardButton(text="🔴 Yo'q, bu yangi kino", callback_data=f"seq:{flow}:none", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def langlink_pick_kb(movies, flow: str) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=f"{m['name']} ({m['code']}, {m['language']})", callback_data=f"langlink:{flow}:{m['code']}", style="primary")]
          for m in movies]
    kb.append([InlineKeyboardButton(text="🔎 Boshqa kod kiriting", callback_data=f"langlink:{flow}:custom", style="primary")])
    kb.append([InlineKeyboardButton(text="🔴 Yo'q, alohida kino", callback_data=f"langlink:{flow}:none", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def movie_list_kb(movies) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"mv_open:{m['id']}", style="primary")]
          for m in movies]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def movie_card_kb(movie) -> InlineKeyboardMarkup:
    mid = movie["id"]
    kb = [
        [InlineKeyboardButton(text="✏️ Nomi", callback_data=f"mv_edit:{mid}:name", style="primary"),
         InlineKeyboardButton(text="🔑 Kodi", callback_data=f"mv_edit:{mid}:code", style="primary")],
        [InlineKeyboardButton(text="🏷 Janri", callback_data=f"mv_edit:{mid}:genre", style="primary"),
         InlineKeyboardButton(text="🌍 Davlati", callback_data=f"mv_edit:{mid}:country", style="primary")],
        [InlineKeyboardButton(text="🗣 Tili", callback_data=f"mv_edit:{mid}:language", style="primary")],
        [InlineKeyboardButton(text="➡️ Keyingi qism", callback_data=f"mv_edit:{mid}:nextpart", style="primary"),
         InlineKeyboardButton(text="⬅️ Oldingi qism", callback_data=f"mv_edit:{mid}:prevpart", style="primary")],
        [InlineKeyboardButton(text="➕ Qo'shish (boshqa seriyaga)", callback_data=f"mv_edit:{mid}:joinseries", style="success"),
         InlineKeyboardButton(text="🌐 Boshqa til varianti", callback_data=f"mv_edit:{mid}:langvariant", style="primary")],
        [InlineKeyboardButton(text="🎞 Treyler qo'shish/almashtirish", callback_data=f"mv_edit:{mid}:trailer", style="primary")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"mv_del:{mid}", style="danger")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def vip_menu_kb(telegram_id: int = None) -> ReplyKeyboardMarkup:
    L = lambda k: menu_label(k, telegram_id)
    rows = [
        [KeyboardButton(text=L("vip_codes"))],
        [KeyboardButton(text=L("vip_search_code"))],
        [KeyboardButton(text=L("vip_enter_code"))],
    ]
    already_applied = False
    if telegram_id is not None:
        already_applied = (
            has_active_membership(telegram_id, "vip")
            or has_pending_vip_application(telegram_id)
        )
    if not already_applied:
        rows.append([KeyboardButton(text=L("vip_apply")), KeyboardButton(text=L("vip_pay_confirm"))])
    if telegram_id is not None and trial_available(telegram_id, "vip"):
        rows.append([KeyboardButton(text=L("vip_trial"))])
    rows.append([KeyboardButton(text=L("back_normal"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def pro_menu_kb(telegram_id: int = None) -> ReplyKeyboardMarkup:
    L = lambda k: menu_label(k, telegram_id)
    rows = [
        [KeyboardButton(text=L("pro_codes"))],
        [KeyboardButton(text=L("pro_search_code"))],
        [KeyboardButton(text=L("pro_enter_code"))],
    ]
    already_applied = False
    if telegram_id is not None:
        already_applied = (
            has_active_membership(telegram_id, "pro")
            or has_pending_tier_application(telegram_id, "pro")
        )
    if not already_applied:
        rows.append([KeyboardButton(text=L("pro_apply")), KeyboardButton(text=L("pro_pay_confirm"))])
    if telegram_id is not None and trial_available(telegram_id, "pro"):
        rows.append([KeyboardButton(text=L("pro_trial"))])
    rows.append([KeyboardButton(text=L("back_normal"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="⬆️ KINO YUKLASH")],
        [KeyboardButton(text="🎞 KINOLARNI BOSHQARISH")],
        [KeyboardButton(text="👤 FOYDALANUVCHI BOSHQARUVI")],
        [KeyboardButton(text="📅 TEZ ORADA BOSHQARUVI")],
        [KeyboardButton(text="💬 CHAT BOT"), KeyboardButton(text="📣 REKLAMA TARQATISH")],
        [KeyboardButton(text="⚙️ SOZLAMALAR")],
    ]
    # Diqqat: "⬅️ ODDIY REJIMGA QAYTISH" tugmasi endi shart emas — bu ADMIN bot
    # faqat boshqaruv uchun, "oddiy rejim" esa alohida (ODDIY) botda joylashgan.
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb(telegram_id: int = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=menu_label("cancel", telegram_id))]], resize_keyboard=True
    )


def skip_kb(telegram_id: int = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=menu_label("skip", telegram_id))], [KeyboardButton(text=menu_label("cancel", telegram_id))]],
        resize_keyboard=True,
    )


def sozlamalar_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📝 Matnlar (reklama/hamkorlik/bog'lanish)")],
        [KeyboardButton(text="📢 ADS")],
        [KeyboardButton(text="💵 Narxlar")],
        [KeyboardButton(text="🏷 Janrlar"), KeyboardButton(text="🌍 Davlatlar")],
        [KeyboardButton(text="🗣 Tillar"), KeyboardButton(text="📡 Majburiy obuna kanallari")],
        [KeyboardButton(text="👤 Adminlar")],
        [KeyboardButton(text="💰 Balans bonus kodi"), KeyboardButton(text="🎁 Tarif bonus kodi (VIP/PRO/Hamkor)")],
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📈 Tushum")],
        [KeyboardButton(text="📊 Kengaytirilgan statistika")],
        [KeyboardButton(text="📋 Ro'yxat"), KeyboardButton(text="📥 Arizalar")],
        [KeyboardButton(text="📬 Push xabarlar")],
        [KeyboardButton(text="🧾 Admin logi")],
        [KeyboardButton(text="⬅️ Orqaga")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def settings_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="Reklama matni", callback_data="set:reklama_info", style="primary")],
        [InlineKeyboardButton(text="Hamkorlik matni", callback_data="set:hamkorlik_info", style="primary")],
        [InlineKeyboardButton(text="Bog'lanish matni", callback_data="set:boglanish_info", style="primary")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def ads_kb() -> InlineKeyboardMarkup:
    kb = []
    for slot, label in AD_SLOTS.items():
        ad = get_ad(slot)
        status = "🟢" if ad else "⚪️"
        style = "success" if ad else "primary"
        kb.append([InlineKeyboardButton(text=f"{status} {label}", callback_data=f"ad_edit:{slot}", style=style)])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def prices_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(
            text=f"Hamkorlik narxi ({get_setting('price_hamkorlik')})",
            callback_data="set:price_hamkorlik", style="primary")],
        [InlineKeyboardButton(
            text=f"Reklama narxi ({get_setting('price_reklama')})",
            callback_data="set:price_reklama", style="primary")],
        [InlineKeyboardButton(
            text=f"Majburiy obuna narxi ({get_setting('price_majburiy_obuna')})",
            callback_data="set:price_majburiy_obuna", style="primary")],
    ]
    for plan in TIER_PLANS["vip"]:
        key = f"price_vip_{plan}"
        kb.append([InlineKeyboardButton(
            text=f"VIP {PLAN_LABELS[plan]} narxi ({get_setting(key)})",
            callback_data=f"set:{key}", style="primary")])
    for plan in TIER_PLANS["pro"]:
        key = f"price_pro_{plan}"
        kb.append([InlineKeyboardButton(
            text=f"PRO {PLAN_LABELS[plan]} narxi ({get_setting(key)})",
            callback_data=f"set:{key}", style="primary")])
    for plan in TIER_PLANS["hamkor"]:
        key = f"price_hamkor_{plan}"
        kb.append([InlineKeyboardButton(
            text=f"Hamkor {PLAN_LABELS[plan]} narxi ({get_setting(key)})",
            callback_data=f"set:{key}", style="primary")])
    kb.append([InlineKeyboardButton(
        text=f"Referral bonus ({get_setting('referral_bonus')})",
        callback_data="set:referral_bonus", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def mandatory_admin_kb() -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="maj_add", style="success")]]
    for ch in list_mandatory_channels(active_only=False):
        status = "🟢" if ch["active"] else "🔴"
        kb.append([InlineKeyboardButton(
            text=f"{status} {ch['title'] or ch['link']}",
            callback_data=f"maj_del:{ch['id']}",
        style="success" if ch["active"] else "danger")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def application_decision_kb(app_id: int) -> InlineKeyboardMarkup:
    kb = [[
        InlineKeyboardButton(text="🟢 Tasdiqlash", callback_data=f"appr:{app_id}", style="success"),
        InlineKeyboardButton(text="🔴 Rad etish", callback_data=f"rej:{app_id}", style="danger"),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

async def send_movie_ad(chat_id: int):
    """Har bir kino yuborilgandan keyin reklama(lar)ni yuboradi.

    - Faol VIP yoki PRO obunachiga — REKLAMA UMUMAN CHIQMAYDI (bu tarifning
      afzalligi sifatida).
    - Obuna muddati tugagan/mavjud bo'lmagan ODDIY foydalanuvchiga esa
      'hammaga' (doimiy) va 'oddiylarga' reklamalari ketma-ket yuboriladi
      (agar sozlangan bo'lsa). Bu tekshiruv har safar QAYTA hisoblanadi —
      demak VIP/PRO tugashi bilan foydalanuvchiga avtomatik ravishda yana
      reklama chiqa boshlaydi, alohida kod yozish shart emas."""
    if has_active_membership(chat_id, "vip") or has_active_membership(chat_id, "pro"):
        return  # VIP/PRO faol — reklamasiz

    for slot in ("hammaga", "oddiylarga"):
        ad = get_ad(slot)
        if ad:
            await deliver_ad(chat_id, ad)


async def send_movie(chat_id: int, movie: sqlite3.Row, variant: int = 1):
    """variant=1..5 -> shu bitta kod ostida saqlangan tegishli til-slot fayli."""
    increment_views(movie["id"])

    if variant not in movie_filled_slots(movie):
        variant = 1
    slot = movie_slot_data(movie, variant)
    language = slot["language"] or movie["language"]
    file_id = slot["file_id"]
    channel_chat_id = slot["channel_chat_id"]
    channel_message_id = slot["channel_message_id"]

    rating = get_rating_summary(movie["id"])
    rating_line = ""
    if rating and rating["cnt"]:
        rating_line = f"\n⭐️ Reyting: {rating['avg_stars']:.1f}/5 ({rating['cnt']} baho)"

    caption = (
        f"🎬 <b>{movie['name']}</b>\n"
        f"🏷 Janr: {movie['genre']}\n"
        f"🌍 Davlat: {movie['country']}\n"
        f"🗣 Til: {language}\n"
        f"🔑 Kod: <code>{movie['code']}</code>\n"
        f"📥 Yuklab olingan: {movie['views'] + 1} marta"
        f"{rating_line}"
    )

    fav = is_favorite(chat_id, movie["id"])
    fav_btn = InlineKeyboardButton(
        text="💔 Sevimlilardan olib tashlash" if fav else "⭐️ Sevimlilarga qo'shish",
        callback_data=f"fav:{movie['id']}",
    style="danger" if fav else "success")
    kb_rows = [[fav_btn]]
    is_oddiy = not movie["is_vip"] and not movie["is_pro"]
    protect = is_oddiy  # Oddiy (VIP/PRO bo'lmagan) kinolar galareyaga saqlash/forward qilishdan himoyalangan
    if is_oddiy:
        share_link = f"https://t.me/{BOT_USERNAME}?start=code_{movie['code']}"
        share_text = f"🎬 {movie['name']} kinosini {BOT_USERNAME} botida bepul tomosha qiling!"
        share_url = f"https://t.me/share/url?url={quote(share_link, safe='')}&text={quote(share_text, safe='')}"
        kb_rows.append([InlineKeyboardButton(text="🤝 Do'stlarga ulashish", url=share_url, style="primary")])
    if movie["trailer_file_id"]:
        kb_rows.append([InlineKeyboardButton(text="🎞 Treyler ko'rish", callback_data=f"trailer:{movie['id']}", style="primary")])
    has_download_privilege = (
        has_active_membership(chat_id, "vip")
        or has_active_membership(chat_id, "pro")
        or has_active_membership(chat_id, "hamkor")
    )
    if has_download_privilege:
        kb_rows.append([InlineKeyboardButton(
            text="📥 Yuklab olish", callback_data=f"dl:{movie['id']}:{variant}", style="primary",
        )])
    if movie["series_id"]:
        nxt = get_next_part(movie["series_id"], movie["part_number"])
        if nxt:
            kb_rows.append([InlineKeyboardButton(
                text=f"➡️ Keyingi qism ({nxt['code']})",
                callback_data=f"code:{nxt['code']}",
            style="primary")])
        kb_rows.append([InlineKeyboardButton(text="📺 Barcha qismlar", callback_data=f"parts:{movie['series_id']}", style="primary")])
    kb_rows.append([
        InlineKeyboardButton(text=str(s) + "⭐️", callback_data=f"rate:{movie['id']}:{s}", style="primary")
        for s in range(1, 6)
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    # Kanalga bog'langan bo'lsa — kanaldagi asl postdan nusxa ko'chiriladi
    if channel_chat_id and channel_message_id:
        try:
            await user_bot.copy_message(
                chat_id=chat_id,
                from_chat_id=channel_chat_id,
                message_id=channel_message_id,
                caption=caption,
                reply_markup=kb,
                protect_content=protect,
            )
            await send_movie_ad(chat_id)
            return
        except Exception as e:
            logger.warning(f"Kanaldan nusxa ko'chirib bo'lmadi, file_id fallback: {e}")
    if not file_id:
        await user_bot.send_message(chat_id, "⚠️ Bu til varianti uchun video topilmadi.")
        return
    await user_bot.send_video(chat_id, file_id, caption=caption, reply_markup=kb, protect_content=protect)
    await send_movie_ad(chat_id)


@user_router.callback_query(F.data.startswith("fav:"))
async def cb_toggle_favorite(call: CallbackQuery):
    movie_id = int(call.data.split(":", 1)[1])
    added = toggle_favorite(call.from_user.id, movie_id)
    await call.answer("⭐️ Sevimlilarga qo'shildi!" if added else "💔 Sevimlilardan olib tashlandi.")
    try:
        kb = call.message.reply_markup
        new_rows = []
        for row in kb.inline_keyboard:
            new_row = []
            for btn in row:
                if btn.callback_data == f"fav:{movie_id}":
                    text = "💔 Sevimlilardan olib tashlash" if added else "⭐️ Sevimlilarga qo'shish"
                    new_row.append(InlineKeyboardButton(text=text, callback_data=btn.callback_data, style="primary"))
                else:
                    new_row.append(btn)
            new_rows.append(new_row)
        await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_rows))
    except Exception:
        pass


@user_router.callback_query(F.data.startswith("rate:"))
async def cb_rate_movie(call: CallbackQuery):
    _, movie_id, stars = call.data.split(":", 2)
    set_rating(call.from_user.id, int(movie_id), int(stars))
    await call.answer(f"✅ Bahoyingiz qabul qilindi: {stars}⭐️. Rahmat!")


@user_router.callback_query(F.data.startswith("trailer:"))
async def cb_show_trailer(call: CallbackQuery):
    movie_id = int(call.data.split(":", 1)[1])
    movie = get_movie_by_id(movie_id)
    if not movie or not movie["trailer_file_id"]:
        await call.answer("Treyler topilmadi.", show_alert=True)
        return
    await call.answer()
    await user_bot.send_video(call.message.chat.id, movie["trailer_file_id"], caption=f"🎞 <b>{movie['name']}</b> — treyler")


@user_router.callback_query(F.data.startswith("dl:"))
async def cb_download_movie(call: CallbackQuery):
    tid = call.from_user.id
    has_privilege = (
        has_active_membership(tid, "vip")
        or has_active_membership(tid, "pro")
        or has_active_membership(tid, "hamkor")
    )
    if not has_privilege:
        await call.answer("⚠️ Yuklab olish faqat VIP/PRO/Hamkor a'zolar uchun mavjud.", show_alert=True)
        return
    _, movie_id_s, variant_s = call.data.split(":", 2)
    movie = get_movie_by_id(int(movie_id_s))
    if not movie:
        await call.answer("Kino topilmadi.", show_alert=True)
        return
    variant = int(variant_s)
    if variant not in movie_filled_slots(movie):
        variant = 1
    slot = movie_slot_data(movie, variant)
    file_id = slot["file_id"]
    if not file_id:
        await call.answer("⚠️ Fayl topilmadi.", show_alert=True)
        return
    await call.answer("📥 Yuklanmoqda...")
    try:
        await user_bot.send_document(call.message.chat.id, file_id, caption=f"📥 <b>{movie['name']}</b>")
    except Exception as e:
        logger.warning(f"Yuklab olish uchun document sifatida yuborib bo'lmadi: {e}")
        await user_bot.send_video(call.message.chat.id, file_id, caption=f"📥 <b>{movie['name']}</b>")


@user_router.callback_query(F.data.startswith("parts:"))
async def cb_series_parts(call: CallbackQuery):
    series_id = int(call.data.split(":", 1)[1])
    parts = get_series_parts(series_id)
    await call.answer()
    if not parts:
        await call.message.answer("Qismlar topilmadi.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{p['part_number']}-qism ({p['code']})", callback_data=f"code:{p['code']}", style="primary")]
        for p in parts
    ])
    await call.message.answer(f"📺 <b>{parts[0]['name']}</b> — barcha qismlar:", reply_markup=kb)


async def open_movie(chat_id: int, movie: sqlite3.Row):
    """Kino ochilishidan oldin — agar bir nechta til varianti mavjud bo'lsa,
    avval 'Tilni tanlang' tugmalarini ko'rsatadi; aks holda to'g'ridan-to'g'ri yuboradi.

    Ikki xil holat bor:
    1) BITTA KOD ostida ko'p tilli kino (2..5-slotlardan biri to'ldirilgan) — shu yerda
       barcha tillar xuddi shu movie yozuvi ichida saqlanadi.
    2) Turli kodlar bilan yuklangan, lang_group orqali bog'langan variantlar
       (masalan K0001 va K0002 — ikkalasi ham alohida kod, lekin bir xil kino)."""
    if movie["is_vip"] and not has_active_membership(chat_id, "vip"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐️ VIP obuna bo'lish", callback_data="vip_subscribe", style="primary")]
        ])
        await user_bot.send_message(
            chat_id,
            "⭐️ Bu kino VIP da mavjud. VIP obuna bo'ling.",
            reply_markup=kb,
        )
        return
    if movie["is_pro"] and not has_active_membership(chat_id, "pro"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 PRO obuna bo'lish", callback_data="pro_subscribe", style="primary")]
        ])
        await user_bot.send_message(
            chat_id,
            "💎 Bu kino PRO da mavjud. PRO obuna bo'ling.",
            reply_markup=kb,
        )
        return

    slots = movie_filled_slots(movie)
    if len(slots) > 1:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"🗣 {movie_slot_data(movie, n)['language']}",
                callback_data=f"langvar2:{movie['id']}:{n}",
            style="primary")]
            for n in slots
        ])
        await user_bot.send_message(
            chat_id,
            f"🎬 <b>{movie['name']}</b>\n\nTilni tanlang:",
            reply_markup=kb,
        )
        return

    group_id = movie["lang_group"] or movie["id"]
    variants = get_lang_variants(group_id)
    if len(variants) > 1:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗣 {v['language']}", callback_data=f"langvar:{v['id']}", style="primary")]
            for v in variants
        ])
        await user_bot.send_message(
            chat_id,
            f"🎬 <b>{movie['name']}</b>\n\nTilni tanlang:",
            reply_markup=kb,
        )
        return
    await send_movie(chat_id, movie)


@user_router.callback_query(F.data == "vip_subscribe")
async def cb_vip_subscribe(call: CallbackQuery):
    await call.answer()
    if all(tariff_price("vip", p) <= 0 for p in TIER_PLANS["vip"]):
        await call.message.answer("Bu xizmat hozircha faol emas.", reply_markup=vip_menu_kb(call.from_user.id))
        return
    await call.message.answer("Tarifni tanlang:", reply_markup=tariff_plan_kb("vip", "vippay"))


@user_router.callback_query(F.data == "pro_subscribe")
async def cb_pro_subscribe(call: CallbackQuery):
    await call.answer()
    if all(tariff_price("pro", p) <= 0 for p in TIER_PLANS["pro"]):
        await call.message.answer("Bu xizmat hozircha faol emas.", reply_markup=pro_menu_kb(call.from_user.id))
        return
    await call.message.answer("Tarifni tanlang:", reply_markup=tariff_plan_kb("pro", "propay"))


@user_router.callback_query(F.data.startswith("langvar2:"))
async def cb_langvar2(call: CallbackQuery):
    """Bitta kod ostidagi 2-til variantini tanlash (add_movie'dagi file_id2)."""
    _, movie_id, variant = call.data.split(":", 2)
    movie = get_movie_by_id(int(movie_id))
    if not movie:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    await send_movie(call.message.chat.id, movie, variant=int(variant))


@user_router.callback_query(F.data.startswith("langvar:"))
async def cb_langvar(call: CallbackQuery):
    movie_id = int(call.data.split(":", 1)[1])
    movie = get_movie_by_id(movie_id)
    if not movie:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    await send_movie(call.message.chat.id, movie)


# ============================================================
# /start
# ============================================================

@admin_router.message(CommandStart())
async def admin_cmd_start(message: Message):
    """ADMIN botning kirish nuqtasi. Faqat adminlar uchun ochiladi — oddiy
    foydalanuvchilar bu botga /start bosishi mumkin, lekin hech qanday
    funksionallikka ega bo'lmaydi (ADMIN PANEL faqat shu yerda joylashgan)."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Bu bot faqat administratorlar uchun mo'ljallangan.")
        return
    register_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    await message.answer("🛠 Admin panelga xush kelibsiz!", reply_markup=admin_menu_kb())


@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    is_new = not user_exists(message.from_user.id)
    register_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")

    parts = (message.text or "").split(maxsplit=1)
    start_payload = parts[1] if len(parts) > 1 else None

    if is_new:
        if start_payload and start_payload.startswith("ref_"):
            try:
                referrer_id = int(start_payload[4:])
            except ValueError:
                referrer_id = None
            if referrer_id and referrer_id != message.from_user.id:
                set_referrer(message.from_user.id, referrer_id)
                bonus = int(get_setting("referral_bonus") or "0")
                if bonus > 0:
                    add_balance(referrer_id, bonus)
                    try:
                        await user_bot.send_message(
                            referrer_id,
                            f"🎁 Sizning taklifingiz bo'yicha yangi foydalanuvchi qo'shildi! "
                            f"Balansingizga {bonus} so'm qo'shildi.",
                        )
                    except Exception:
                        pass

    pending_code = None
    if start_payload and start_payload.startswith("code_"):
        pending_code = start_payload[5:].upper()

    pending_bonus = None
    pending_tier = None
    pending_tier_code = None
    if start_payload and start_payload.startswith("bonus_"):
        pending_bonus = start_payload[6:].upper()
    elif start_payload and start_payload.startswith("vipcode_"):
        pending_tier, pending_tier_code = "vip", start_payload[8:].upper()
    elif start_payload and start_payload.startswith("procode_"):
        pending_tier, pending_tier_code = "pro", start_payload[8:].upper()

    if not has_chosen_lang(message.from_user.id):
        if pending_code or pending_bonus or pending_tier_code:
            await state.update_data(
                pending_code=pending_code, pending_bonus=pending_bonus,
                pending_tier=pending_tier, pending_tier_code=pending_tier_code,
            )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"startlang:{code}", style="primary")]
            for code, label in UI_LANGS.items()
        ])
        await message.answer(
            "🌐 Tilni tanlang / Choose language / Выберите язык / Dil seçin:",
            reply_markup=kb,
        )
        return

    if not has_onboarded(message.from_user.id):
        if pending_code or pending_bonus or pending_tier_code:
            await state.update_data(
                pending_code=pending_code, pending_bonus=pending_bonus,
                pending_tier=pending_tier, pending_tier_code=pending_tier_code,
            )
        await state.set_state(Onboarding.waiting_name)
        await message.answer(t("ask_name", message.from_user.id))
        return

    await send_post_lang_start(message, message.from_user.id, pending_code, pending_bonus, pending_tier, pending_tier_code)


async def send_post_lang_start(
    message: Message, telegram_id: int, pending_code: str = None,
    pending_bonus: str = None, pending_tier: str = None, pending_tier_code: str = None,
):
    """/start dagi til tanlangandan (yoki allaqachon tanlangan bo'lsa) keyingi qadam:
    majburiy obunani tekshirish va xush kelibsiz xabarini yuborish. Agar Mini App'dan
    kino kodi bilan kelingan bo'lsa ('/start code_XXXX'), oxirida o'sha kinoni ochadi."""
    admin = is_admin(telegram_id)

    if not admin:
        try:
            missing = await get_missing_subscriptions(telegram_id)
        except Exception as e:
            logger.warning(f"Majburiy obunani tekshirishda xato, o'tkazib yuboramiz: {e}")
            missing = []

        if missing:
            kb_rows = []
            for c in missing:
                link = (c["link"] or "").strip()
                if not link.startswith("http"):
                    link = f"https://t.me/{link.lstrip('@')}" if link else None
                if link:
                    kb_rows.append([InlineKeyboardButton(text=f"➡️ {c['title'] or link}", url=link, style="primary")])
            kb_rows.append([InlineKeyboardButton(text="🟢 Tekshirdim", callback_data="check_subs", style="success")])
            try:
                await message.answer(
                    "📡 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
                )
                return
            except Exception as e:
                logger.warning(f"Majburiy obuna xabarini yuborib bo'lmadi, o'tkazib yuboramiz: {e}")

    await message.answer(
        welcome_text(telegram_id),
        reply_markup=user_menu_kb(telegram_id),
    )

    if pending_code:
        movie = get_movie_by_code(pending_code)
        if movie:
            await open_movie(message.chat.id, movie)

    if pending_bonus:
        amount = redeem_bonus_code(pending_bonus, telegram_id)
        if isinstance(amount, int):
            new_balance = get_balance(telegram_id)
            await message.answer(
                f"✅ Bonus kod orqali {amount} so'm hisobingizga qo'shildi!\n💰 Yangi balans: {new_balance} so'm"
            )
        elif amount == "ALREADY_USED":
            await message.answer("⚠️ Siz bu koddan allaqachon foydalangansiz.")
        else:
            await message.answer("⚠️ Havoladagi bonus kod topilmadi yoki limiti tugagan.")

    if pending_tier and pending_tier_code:
        row = redeem_tariff_code(pending_tier_code, telegram_id, expected_tier=pending_tier)
        kb_map = {"vip": vip_menu_kb, "pro": pro_menu_kb}
        kb = kb_map.get(pending_tier, lambda uid: user_menu_kb(uid))(telegram_id)
        if row == "EXPIRED":
            await message.answer(
                "⌛ Havoladagi tarif kodining muddati allaqachon tugagan.", reply_markup=kb,
            )
        elif not row:
            await message.answer("⚠️ Havoladagi tarif kodi topilmadi yoki band.", reply_markup=kb)
        else:
            await message.answer(
                f"✅ Kod qabul qilindi! {TIER_TITLES.get(pending_tier, pending_tier)} tarifi faollashtirildi "
                f"({PLAN_LABELS.get(row['plan'], row['plan'])}).\n\n{membership_status_text(telegram_id, pending_tier)}",
                reply_markup=kb,
            )


@user_router.callback_query(F.data.startswith("startlang:"))
async def cb_start_lang(call: CallbackQuery, state: FSMContext):
    lang = call.data.split(":", 1)[1]
    if lang not in UI_LANGS:
        await call.answer()
        return
    set_user_lang(call.from_user.id, lang)
    await call.answer("✅")
    data = await state.get_data()
    pending_code = data.get("pending_code")
    pending_bonus = data.get("pending_bonus")
    pending_tier = data.get("pending_tier")
    pending_tier_code = data.get("pending_tier_code")

    if not has_onboarded(call.from_user.id):
        await state.set_state(Onboarding.waiting_name)
        await call.message.answer(t("ask_name", call.from_user.id))
        return

    await state.clear()
    await send_post_lang_start(call.message, call.from_user.id, pending_code, pending_bonus, pending_tier, pending_tier_code)


@user_router.message(Onboarding.waiting_name)
async def onboarding_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 100:
        await message.answer(t("ask_name_invalid", message.from_user.id))
        return
    set_user_full_name(message.from_user.id, name)
    await state.set_state(Onboarding.waiting_phone)
    phone_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text=t("share_phone_btn", message.from_user.id), request_contact=True
        )]],
        resize_keyboard=True,
    )
    await message.answer(t("ask_phone", message.from_user.id), reply_markup=phone_kb)


@user_router.message(Onboarding.waiting_phone, F.contact)
async def onboarding_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number or ""
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    set_user_phone(message.from_user.id, phone)
    data = await state.get_data()
    pending_code = data.get("pending_code")
    pending_bonus = data.get("pending_bonus")
    pending_tier = data.get("pending_tier")
    pending_tier_code = data.get("pending_tier_code")
    await state.clear()
    await message.answer(t("onboard_done", message.from_user.id), reply_markup=ReplyKeyboardRemove())
    await send_post_lang_start(message, message.from_user.id, pending_code, pending_bonus, pending_tier, pending_tier_code)


@user_router.message(Onboarding.waiting_phone)
async def onboarding_phone_invalid(message: Message):
    await message.answer(t("phone_invalid", message.from_user.id))


@user_router.message(Command("lang"))
async def cmd_lang(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"setlang:{code}", style="primary")]
        for code, label in UI_LANGS.items()
    ])
    await message.answer("🌐 Interfeys tilini tanlang / Choose language / Выберите язык:", reply_markup=kb)


@user_router.callback_query(F.data.startswith("setlang:"))
async def cb_set_lang(call: CallbackQuery):
    lang = call.data.split(":", 1)[1]
    if lang not in UI_LANGS:
        await call.answer()
        return
    set_user_lang(call.from_user.id, lang)
    await call.answer("✅")
    await call.message.answer(
        welcome_text(call.from_user.id),
        reply_markup=user_menu_kb(call.from_user.id),
    )


@user_router.callback_query(F.data == "check_subs")
async def cb_check_subs(call: CallbackQuery):
    try:
        missing = await get_missing_subscriptions(call.from_user.id)
    except Exception as e:
        logger.warning(f"Majburiy obunani tekshirishda xato: {e}")
        missing = []
    if missing:
        await call.answer("❌ Hali barcha kanallarga obuna bo'lmagansiz.", show_alert=True)
        return
    await call.answer("✅ Rahmat!")
    await call.message.answer(
        welcome_text(call.from_user.id),
        reply_markup=user_menu_kb(call.from_user.id),
    )


@user_router.message(btn("cancel"))
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=user_menu_kb(message.from_user.id))


@user_router.message(btn("back_normal"))
async def back_to_normal(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Oddiy menyu.", reply_markup=user_menu_kb(message.from_user.id))


# ============================================================
# ODDIY FOYDALANUVCHI: KINO KODLARI / QIDIRISH / KATEGORIYA
# ============================================================

@user_router.message(btn("codes"))
async def movie_codes_channel(message: Message):
    await message.answer(f"🎬 Kinolar kodlari kanali:\n{CODES_CHANNEL}")


@user_router.message(btn("search"))
async def ask_search(message: Message, state: FSMContext):
    await state.set_state(SearchByName.waiting_name)
    await message.answer(t("search_prompt", message.from_user.id), reply_markup=cancel_kb(message.from_user.id))


@user_router.message(SearchByName.waiting_name)
async def process_search(message: Message, state: FSMContext):
    query = message.text.strip()
    await state.clear()
    log_search_history(message.from_user.id, query)

    # Avval kod sifatida qidiramiz
    movie = get_movie_by_code(query.upper())
    if movie and not movie["is_vip"]:
        await message.answer("✅ Topildi!", reply_markup=user_menu_kb(message.from_user.id))
        await open_movie(message.chat.id, movie)
        return

    # Topilmasa, nom bo'yicha qidiramiz
    results = search_movies_by_name(query, vip=False)
    is_fuzzy = False
    if not results:
        results = fuzzy_search_movies_by_name(query, vip=False)
        is_fuzzy = bool(results)
    if not results:
        await message.answer(t("search_not_found", message.from_user.id), reply_markup=user_menu_kb(message.from_user.id))
        return
    kb_rows = []
    seen_series = set()
    for m in results:
        sid = m["series_id"] or m["id"]
        total_parts = series_part_count(sid)
        if total_parts > 1:
            if sid in seen_series:
                continue
            seen_series.add(sid)
            kb_rows.append([InlineKeyboardButton(text=f"📺 {m['name']} ({total_parts} qism)", callback_data=f"parts:{sid}", style="primary")])
        else:
            kb_rows.append([InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"code:{m['code']}", style="primary")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    header = "🔎 Ehtimol shularni qidiryapsiz:" if is_fuzzy else "Natijalar:"
    await message.answer(header, reply_markup=kb)
    await message.answer(t("menu_label", message.from_user.id), reply_markup=user_menu_kb(message.from_user.id))


@user_router.callback_query(F.data.startswith("code:"))
async def cb_open_code(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    movie = get_movie_by_code(code)
    if not movie:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    await open_movie(call.message.chat.id, movie)


@user_router.message(btn("genres"))
async def category_menu(message: Message):
    await message.answer("Janrni tanlang:", reply_markup=category_kb())


@user_router.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery):
    genre = call.data.split(":", 1)[1]
    movies = get_movies_by_genre(genre)
    await call.answer()
    if not movies:
        await call.message.answer(f"«{genre}» boʻyicha hozircha kino yoʻq.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"code:{m['code']}", style="primary")]
        for m in movies
    ])
    await call.message.answer(f"🗂 {genre}:", reply_markup=kb)


# ============================================================
# XIZMATLAR
# ============================================================

@user_router.message(btn("services"))
async def services_menu(message: Message):
    await message.answer("Xizmatlar:", reply_markup=services_kb(message.from_user.id))


@user_router.message(btn("ads"))
async def reklama_info(message: Message):
    price = get_setting("price_reklama")
    text = get_setting("reklama_info")
    extra = f"\n\n💵 Narxi: {price} so'm" if price and price != "0" else ""
    kb = None
    if price and price != "0":
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"💳 Pulga joylashtirish ({price} so'm)", callback_data="reklama_pay", style="success")
        ]])
    await message.answer(text + extra, reply_markup=kb)


@user_router.callback_query(F.data == "reklama_pay")
async def reklama_pay_start(call: CallbackQuery, state: FSMContext):
    price = int(get_setting("price_reklama") or "0")
    if get_balance(call.from_user.id) < price:
        await call.answer("❌ Balansingiz yetarli emas.", show_alert=True)
        return
    await call.answer()
    await state.set_state(ReklamaOrder.waiting_content)
    await call.message.answer(
        f"💳 Balansingizdan {price} so'm yechiladi.\n\nReklama matni yoki rasmini yuboring:",
        reply_markup=cancel_kb(),
    )


@user_router.message(ReklamaOrder.waiting_content)
async def reklama_pay_content(message: Message, state: FSMContext):
    price = int(get_setting("price_reklama") or "0")
    if get_balance(message.from_user.id) < price:
        await state.clear()
        await message.answer("❌ Balansingiz yetarli emas.", reply_markup=user_menu_kb(message.from_user.id))
        return
    add_balance(message.from_user.id, -price)
    record_revenue("reklama", message.from_user.id, price, "Reklama joylashtirish")
    await state.clear()
    await message.answer(
        "✅ To'lov qabul qilindi. Reklamangiz admin tomonidan tez orada joylanadi.",
        reply_markup=user_menu_kb(message.from_user.id),
    )
    caption = (
        f"📢 <b>To'langan reklama so'rovi</b>\n"
        f"🆔 {message.from_user.id} (@{message.from_user.username or '-'})\n"
        f"💵 To'landi: {price} so'm"
    )
    with closing(db()) as conn:
        admin_ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM admins")]
    for aid in admin_ids:
        try:
            await admin_bot.forward_message(aid, message.chat.id, message.message_id)
            await admin_bot.send_message(aid, caption)
        except Exception as e:
            logger.warning(f"Adminga yuborilmadi {aid}: {e}")


@user_router.message(btn("contact"))
async def boglanish_info(message: Message):
    await message.answer(get_setting("boglanish_info"))


@user_router.message(btn("mandatory_sub"))
async def mandatory_list_info(message: Message):
    channels = list_mandatory_channels(active_only=True)
    if channels:
        text = t("mandatory_header", message.from_user.id) + "\n\n" + "\n".join(
            f"• {c['title'] or c['link']}\n{c['link']}" for c in channels
        )
    else:
        text = t("mandatory_none", message.from_user.id)
    price = get_setting("price_majburiy_obuna") or "0"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="➕ Mening kanalimni qo'shish (pullik)", callback_data="mand_self_start", style="success"),
    ]])
    text += f"\n\n💡 O'z kanalingizni ham majburiy obunaga qo'shishingiz mumkin ({price} so'm / 1 obunachi, min. 100 ta)."
    await message.answer(text, reply_markup=kb)


@user_router.callback_query(F.data == "mand_self_start")
async def mandatory_self_start(call: CallbackQuery, state: FSMContext):
    price = get_setting("price_majburiy_obuna") or "0"
    await state.set_state(MandatorySelfService.waiting_chat)
    await call.answer()
    await call.message.answer(
        "📡 O'z kanalingizni majburiy obunaga (pullik) qo'shish:\n\n"
        "1️⃣ Avval BOTNI kanalingizga ADMIN qilib qo'shing.\n"
        f"2️⃣ Narx: {price} so'm / 1 obunachi (minimal buyurtma: 100 ta obunachi).\n\n"
        "Endi kanalingizdagi istalgan postni shu yerga FORWARD (uzatib) yuboring, "
        "yoki kanalning raqamli chat_id'sini kiriting (masalan -1001234567890):",
        reply_markup=cancel_kb(call.from_user.id),
    )


@user_router.message(MandatorySelfService.waiting_chat)
async def mandatory_self_chat(message: Message, state: FSMContext):
    chat_id = None
    title = None
    link = None

    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
        title = message.forward_from_chat.title
        if message.forward_from_chat.username:
            link = f"https://t.me/{message.forward_from_chat.username}"
    elif message.text:
        try:
            chat_id = int(message.text.strip())
        except ValueError:
            chat_id = None

    if chat_id is None:
        await message.answer(
            "❌ Tushunmadim. Kanaldagi postni FORWARD qiling, "
            "yoki raqamli chat_id kiriting (masalan -1001234567890):"
        )
        return

    try:
        chat = await user_bot.get_chat(chat_id)
        title = title or chat.title
        if not link and chat.username:
            link = f"https://t.me/{chat.username}"
    except Exception as e:
        await message.answer(
            f"⚠️ Botni shu kanaldan topa olmadim ({e}).\n"
            "Bot kanalga ADMIN qilib qo'shilganiga ishonch hosil qiling va qaytadan urinib ko'ring, "
            "yoki \"❌ BEKOR QILISH\" bosing."
        )
        return

    try:
        member = await user_bot.get_chat_member(chat_id, user_bot.id)
        if member.status not in ("administrator", "creator"):
            raise ValueError("bot admin emas")
    except Exception:
        await message.answer(
            "❌ Bot ushbu kanalda ADMIN emas. Avval botni o'sha kanalga ADMIN qilib qo'shing, "
            "so'ng qaytadan urinib ko'ring."
        )
        return

    if not link:
        await state.update_data(ms_chat_id=chat_id, ms_title=title)
        await message.answer("Kanal linkini kiriting (masalan https://t.me/kanalim):")
        return

    price = float(get_setting("price_majburiy_obuna") or 0)
    await state.update_data(ms_chat_id=chat_id, ms_title=title, ms_link=link)
    await state.set_state(MandatorySelfService.waiting_count)
    await message.answer(
        f"✅ Kanal topildi: <b>{title}</b>\n\n"
        f"Necha nafar obunachiga yetguncha majburiy bo'lib tursin? (minimal: 100)\n"
        f"Narx: {price:g} so'm / 1 obunachi"
    )


@user_router.message(MandatorySelfService.waiting_count)
async def mandatory_self_count(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("ms_link"):
        # Link hali kiritilmagan (forward orqali username topilmagan holat)
        await state.update_data(ms_link=message.text.strip())
        price = float(get_setting("price_majburiy_obuna") or 0)
        await state.set_state(MandatorySelfService.waiting_count)
        await message.answer(
            f"Necha nafar obunachiga yetguncha majburiy bo'lib tursin? (minimal: 100)\n"
            f"Narx: {price:g} so'm / 1 obunachi"
        )
        return

    try:
        count = int(message.text.strip())
    except ValueError:
        await message.answer("Iltimos, faqat butun son kiriting:")
        return
    if count < 100:
        await message.answer("⚠️ Minimal miqdor: 100. Qaytadan kiriting:")
        return

    price_per_sub = float(get_setting("price_majburiy_obuna") or 0)
    total_price = int(round(count * price_per_sub))
    uid = message.from_user.id
    balance = get_balance(uid)
    if balance < total_price:
        await message.answer(
            f"❌ Balansingiz yetarli emas. Kerak: {total_price} so'm, mavjud: {balance} so'm.\n"
            "Avval hisobingizni to'ldiring.",
            reply_markup=hisobim_kb(uid),
        )
        await state.clear()
        return

    add_balance(uid, -total_price)
    record_revenue(
        "majburiy_obuna_self",
        uid,
        total_price,
        f"O'z kanalini majburiy obunaga qo'shish ({data['ms_link']}, {count} ta obunachi)",
    )
    add_mandatory_channel(data["ms_chat_id"], data["ms_link"], data.get("ms_title") or data["ms_link"], count)
    await state.clear()
    await message.answer(
        f"✅ Kanalingiz majburiy obuna ro'yxatiga qo'shildi!\n"
        f"🎯 Maqsad: {count} ta obunachi\n"
        f"💳 {total_price} so'm hisobingizdan yechildi.\n\n"
        "Obunachilar soni shu miqdorga yetganda, kanal ro'yxatdan avtomatik olib tashlanadi.",
        reply_markup=user_menu_kb(uid),
    )


@user_router.message(btn("partnership"))
async def hamkorlik_info(message: Message):
    uid = message.from_user.id
    price_note = "" if all(tariff_price("hamkor", p) <= 0 for p in TIER_PLANS["hamkor"]) else "\n💵 Narxlar: Sozlamalarda ko'rsatilgan"
    text = get_setting("hamkorlik_info")
    status = membership_status_text(uid, "hamkor")
    already_applied = has_active_membership(uid, "hamkor") or has_pending_partner_application(uid)

    kb_rows = [[InlineKeyboardButton(text="🔑 KODNI KIRITING", callback_data="hamkor_redeem", style="primary")]]
    if not already_applied:
        kb_rows.insert(0, [InlineKeyboardButton(text="📝 Hamkorlikka ariza berish", callback_data="hamkorlik_apply", style="primary")])
    await message.answer(
        text + price_note + f"\n\nHolatingiz: {status}\n\n"
        "Hamkor bo'lish uchun avval kanalingizga botni ADMIN qilib qo'shing, "
        "so'ngra pastdagi tugma orqali ariza yuboring.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@user_router.callback_query(F.data == "hamkor_redeem")
async def hamkor_redeem_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(TariffRedeem.waiting_code)
    await state.update_data(redeem_tier="hamkor")
    await call.answer()
    await call.message.answer("🤝 Hamkor tarif kodini kiriting:", reply_markup=cancel_kb())


@user_router.callback_query(F.data == "hamkorlik_apply")
async def hamkorlik_apply_cb(call: CallbackQuery, state: FSMContext):
    await state.set_state(HamkorlikApply.waiting_link)
    await call.answer()
    await call.message.answer(
        "Kanalingizga botni ADMIN qilib qo'shganingizga ishonch hosil qiling, "
        "so'ng kanal linkini yuboring:",
        reply_markup=cancel_kb(),
    )


@user_router.message(HamkorlikApply.waiting_link)
async def hamkorlik_apply_link(message: Message, state: FSMContext):
    link = message.text.strip()
    partner_id = create_partner_application(message.from_user.id, link)
    await state.clear()

    if not all(tariff_price("hamkor", p) <= 0 for p in TIER_PLANS["hamkor"]):
        await message.answer(
            "✅ Arizangiz yuborildi.\n\nIstasangiz, kutmasdan darhol tasdiqlanishi uchun "
            "balansingizdan to'lab qo'yishingiz mumkin:",
            reply_markup=tariff_plan_kb("hamkor", f"ptrpay:{partner_id}"),
        )
    else:
        await message.answer(
            "✅ Arizangiz yuborildi. Admin tekshirib chiqqach xabar beriladi.",
            reply_markup=user_menu_kb(message.from_user.id),
        )

    text = (
        f"🤝 <b>Yangi hamkorlik arizasi</b> (#{partner_id})\n"
        f"🆔 {message.from_user.id} (@{message.from_user.username or '-'})\n"
        f"🔗 {link}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 Tasdiqlash", callback_data=f"papr:{partner_id}", style="success"),
        InlineKeyboardButton(text="🔴 Rad etish", callback_data=f"prej:{partner_id}", style="danger"),
    ]])
    with closing(db()) as conn:
        admin_ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM admins")]
    for aid in admin_ids:
        try:
            await admin_bot.send_message(aid, text, reply_markup=kb)
        except Exception as e:
            logger.warning(f"Adminga yuborilmadi {aid}: {e}")


@user_router.callback_query(F.data.startswith("ptrpay:"))
async def cb_partner_pay(call: CallbackQuery):
    _, partner_id, plan = call.data.split(":", 2)
    partner_id = int(partner_id)
    partner = get_partner(partner_id)
    if not partner or partner["status"] != "pending":
        await call.answer("Bu ariza allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    price = tariff_price("hamkor", plan)
    uid = call.from_user.id
    if get_balance(uid) < price:
        await call.answer("❌ Balansingiz yetarli emas. Avval hisobingizni to'ldiring.", show_alert=True)
        return
    letter = next_available_partner_letter()
    add_balance(uid, -price)
    record_revenue("hamkorlik", uid, price, f"Hamkorlik ariza #{partner_id} ({PLAN_LABELS[plan]})")
    approve_partner(partner_id, letter)
    code = issue_and_activate_code("hamkor", plan, uid)
    await call.answer("✅ Tasdiqlandi!")
    await call.message.edit_text(
        f"✅ Balansingizdan {price} so'm yechildi va hamkorlik darhol tasdiqlandi!\n"
        f"Sizning kod harfingiz: <b>{letter}</b> (masalan {letter}001, {letter}002...)\n"
        f"🎯 Tarif: {PLAN_LABELS[plan]}\n🔑 Kodingiz: <code>{code}</code>"
    )


@admin_router.callback_query(F.data.startswith("papr:"))
async def cb_partner_approve(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    partner_id = int(call.data.split(":", 1)[1])
    await state.set_state(PartnerApprove.waiting_letter)
    await state.update_data(partner_id=partner_id)
    await call.answer()
    await call.message.answer(
        f"Ariza #{partner_id} uchun harf kiriting (masalan A) — "
        "hamkorning kodlari shu harf bilan boshlanadi (A001, A002...):",
        reply_markup=cancel_kb(),
    )


@user_router.message(PartnerApprove.waiting_letter)
async def process_partner_letter(message: Message, state: FSMContext):
    data = await state.get_data()
    partner_id = data["partner_id"]
    letter = message.text.strip()[:1].upper()
    approve_partner(partner_id, letter)
    await state.update_data(letter=letter)
    await message.answer(
        "Endi tarifni tanlang (kod avtomatik yaratilib yuboriladi):",
        reply_markup=tariff_plan_kb("hamkor", f"hpappr:{partner_id}"),
    )


@admin_router.callback_query(F.data.startswith("hpappr:"))
async def cb_partner_approve_plan_chosen(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, partner_id, plan = call.data.split(":", 2)
    partner_id = int(partner_id)
    partner = get_partner(partner_id)
    if not partner:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    await state.clear()
    code = issue_and_activate_code("hamkor", plan, partner["telegram_id"])
    log_admin_action(call.from_user.id, "Hamkor tasdiqladi", f"#{partner_id} -> {partner['telegram_id']} ({PLAN_LABELS[plan]})")
    await call.message.answer(
        f"✅ Hamkor tasdiqlandi, harfi: {partner['letter_prefix']}, tarifi: {PLAN_LABELS[plan]}",
        reply_markup=admin_menu_kb(),
    )
    try:
        await user_bot.send_message(
            partner["telegram_id"],
            f"✅ Hamkorlik arizangiz tasdiqlandi!\nSizning kod harfingiz: <b>{partner['letter_prefix']}</b>\n"
            f"(masalan {partner['letter_prefix']}001, {partner['letter_prefix']}002...)\n"
            f"🎯 Tarif: {PLAN_LABELS[plan]}\n🔑 Kodingiz: <code>{code}</code>\n\n"
            f"{membership_status_text(partner['telegram_id'], 'hamkor')}",
        )
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("prej:"))
async def cb_partner_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    partner_id = int(call.data.split(":", 1)[1])
    reject_partner(partner_id)
    partner = get_partner(partner_id)
    log_admin_action(call.from_user.id, "Hamkor rad etdi", f"#{partner_id} -> {partner['telegram_id'] if partner else '?'}")
    await call.answer("Rad etildi.")
    await call.message.answer(f"❌ Hamkorlik arizasi #{partner_id} rad etildi.")
    try:
        await user_bot.send_message(partner["telegram_id"], "❌ Kechirasiz, hamkorlik arizangiz rad etildi.")
    except Exception:
        pass


# ------------------------------------------------------------
# HAMKOR: KINO YUKLASH (tasdiqlangan hamkor o'z harfi bilan kino yuklaydi)
# ------------------------------------------------------------

@user_router.message(btn("partner_upload"))
async def partner_upload_start(message: Message, state: FSMContext):
    partner = get_approved_partner_by_uid(message.from_user.id)
    if not partner:
        return
    if not partner["can_upload"]:
        await message.answer("⚠️ Sizga hozircha kino yuklash ruxsati berilmagan.")
        return
    if not has_active_membership(message.from_user.id, "hamkor"):
        await message.answer("⚠️ Hamkorlik tarifingiz muddati tugagan. Yangilash uchun \"🤝 HAMKORLIK\" bo'limiga o'ting.")
        return
    await state.update_data(partner_prefix=partner["letter_prefix"])

    options = []
    if partner["can_upload_vip"]:
        options.append([InlineKeyboardButton(text="⭐️ VIP", callback_data="puplcat:vip", style="primary")])
    if partner["can_upload_pro"]:
        options.append([InlineKeyboardButton(text="💎 PRO", callback_data="puplcat:pro", style="primary")])
    options.append([InlineKeyboardButton(text="🎬 Oddiy", callback_data="puplcat:oddiy", style="primary")])

    if len(options) == 1:
        await state.update_data(is_vip=False, is_pro=False)
        await state.set_state(PartnerUpload.waiting_video)
        await message.answer("Yuklamoqchi bo'lgan kino videosini yuboring:", reply_markup=cancel_kb())
        return
    await message.answer("Kino qaysi toifaga yuklanadi?", reply_markup=InlineKeyboardMarkup(inline_keyboard=options))


@user_router.callback_query(F.data.startswith("puplcat:"))
async def partner_upload_category_chosen(call: CallbackQuery, state: FSMContext):
    partner = get_approved_partner_by_uid(call.from_user.id)
    if not partner:
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    cat = call.data.split(":", 1)[1]
    if cat == "vip" and not partner["can_upload_vip"]:
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    if cat == "pro" and not partner["can_upload_pro"]:
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    await state.update_data(is_vip=(cat == "vip"), is_pro=(cat == "pro"))
    await state.set_state(PartnerUpload.waiting_video)
    await call.answer()
    await call.message.answer("Yuklamoqchi bo'lgan kino videosini yuboring:", reply_markup=cancel_kb())


@user_router.message(PartnerUpload.waiting_video, F.video)
async def partner_upload_video(message: Message, state: FSMContext):
    await state.update_data(file_id=message.video.file_id)
    await state.set_state(PartnerUpload.waiting_name)
    await message.answer("Kino nomini kiriting:")


@user_router.message(PartnerUpload.waiting_video)
async def partner_upload_video_invalid(message: Message):
    await message.answer("Iltimos, video fayl yuboring.")


@user_router.message(PartnerUpload.waiting_name)
async def partner_upload_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip(), sel_genres=[], sel_country=None, sel_languages=[])
    await message.answer(
        "Janrni tanlang (bitta yoki bir nechta), so'ng \"Tayyor\" bosing:",
        reply_markup=select_kb(list_genres(), [], "ptn", "g"),
    )


# ------------------------------------------------------------
# UMUMIY: Janr / Davlat / Til tanlash (admin va hamkor uchun)
# flow: "adm" — admin kino yuklash, "ptn" — hamkor kino yuklash
# ------------------------------------------------------------

@user_router.callback_query(F.data.startswith("pick:"))
async def cb_pick(call: CallbackQuery, state: FSMContext):
    _, flow, kind, value = call.data.split(":", 3)
    data = await state.get_data()

    if kind == "g":
        sel = list(data.get("sel_genres", []))
        sel = [x for x in sel if x != value] if value in sel else sel + [value]
        await state.update_data(sel_genres=sel)
        await call.answer()
        await call.message.edit_reply_markup(reply_markup=select_kb(list_genres(), sel, flow, "g"))

    elif kind == "c":
        await state.update_data(sel_country=value)
        await call.answer(f"✅ {value} tanlandi")
        await call.message.edit_text(f"🌍 Davlat: {value}")
        await call.message.answer(
            "Tilni tanlang (1 dan 5 tagacha), so'ng \"Tayyor\" bosing:",
            reply_markup=select_kb(list_languages(), [], flow, "l"),
        )

    elif kind == "l":
        sel = list(data.get("sel_languages", []))
        if value in sel:
            sel = [x for x in sel if x != value]
        elif len(sel) >= MAX_LANG_SLOTS:
            await call.answer(f"⚠️ Ko'pi bilan {MAX_LANG_SLOTS} ta til tanlash mumkin.", show_alert=True)
            return
        else:
            sel = sel + [value]
        await state.update_data(sel_languages=sel)
        await call.answer()
        await call.message.edit_reply_markup(reply_markup=select_kb(list_languages(), sel, flow, "l"))


@user_router.callback_query(F.data.startswith("pickdone:"))
async def cb_pickdone(call: CallbackQuery, state: FSMContext):
    _, flow, kind = call.data.split(":", 2)
    data = await state.get_data()

    if kind == "g":
        sel = data.get("sel_genres", [])
        if not sel:
            await call.answer("⚠️ Kamida bitta janr tanlang.", show_alert=True)
            return
        await call.answer()
        await call.message.edit_text(f"🏷 Janr(lar): {', '.join(sel)}")
        await call.message.answer(
            "Davlatni tanlang (faqat bitta):",
            reply_markup=select_kb(list_countries(), [], flow, "c"),
        )

    elif kind == "l":
        sel = data.get("sel_languages", [])
        if not sel:
            await call.answer("⚠️ Kamida bitta til tanlang.", show_alert=True)
            return
        await call.answer()
        await call.message.edit_text(f"🗣 Til(lar): {', '.join(sel)}")

        if flow == "mvlang":
            await mv_lang_ask_video_source(call.message, state, slot=1, lang_name=sel[0])
        elif len(sel) > 1:
            # 2 yoki undan ko'p til tanlangan — bitta kod ostida har bir qo'shimcha til
            # uchun ALOHIDA video so'raymiz (2, 3, 4, 5-slotlar), aks holda faqat 1 ta
            # fayl saqlanib, boshqa tillar hech qachon ishlamas edi.
            await state.update_data(lang_video_slot=2, extra_videos={})
            await call.message.answer(
                f"🎬 Endi \"{sel[1]}\" tilidagi videoni yuboring "
                f"(1-video \"{sel[0]}\" tili sifatida saqlanadi):"
            )
            if flow == "adm":
                await state.set_state(UploadMovie.waiting_video2)
            else:
                await state.set_state(PartnerUpload.waiting_video2)
        elif flow == "adm":
            await call.message.answer("Ushbu kino uchun kodni kiriting (masalan K0001 yoki H0001):")
            await state.set_state(UploadMovie.waiting_code)
        else:
            await finalize_partner_upload(call.message, state)

    elif kind == "c":
        await call.answer("⚠️ Ro'yxatdan bitta davlatni tanlang.", show_alert=True)


@user_router.message(PartnerUpload.waiting_video2, F.video)
async def partner_upload_video2(message: Message, state: FSMContext):
    data = await state.get_data()
    sel = data.get("sel_languages", [])
    slot = data.get("lang_video_slot", 2)
    videos = dict(data.get("extra_videos", {}))
    videos[str(slot)] = message.video.file_id
    next_slot = slot + 1
    if next_slot <= len(sel):
        await state.update_data(extra_videos=videos, lang_video_slot=next_slot)
        await message.answer(
            f"🎬 Endi \"{sel[next_slot - 1]}\" tilidagi videoni yuboring "
            f"({next_slot}-video sifatida saqlanadi):"
        )
    else:
        await state.update_data(extra_videos=videos)
        await finalize_partner_upload(message, state)


@user_router.message(PartnerUpload.waiting_video2)
async def partner_upload_video2_invalid(message: Message):
    await message.answer("Iltimos, 2-til uchun video fayl yuboring.")


async def upload_extra_lang_slots(sel_languages, extra_videos, target_channel_id, name, genre, country, code):
    """2..5-slotlar (qo'shimcha tillar) uchun videolarni kanalga joylaydi va
    add_movie'ga uzatiladigan qo'shimcha maydonlarni (kwargs) qaytaradi."""
    slot_kwargs = {}
    for slot_num in LANG_SLOT_NUMS[1:]:
        if slot_num > len(sel_languages):
            break
        lang_name = sel_languages[slot_num - 1]
        fid = (extra_videos or {}).get(str(slot_num))
        if not fid:
            continue
        chat_id, msg_id = None, None
        try:
            sent = await user_bot.send_video(
                target_channel_id, fid,
                caption=(
                    f"🎬 {name} ({lang_name})\n🏷 Janr: {genre}\n🌍 Davlat: {country}\n"
                    f"🗣 Til: {lang_name}\n🔑 Kod: {code}"
                ),
            )
            chat_id = target_channel_id
            msg_id = sent.message_id
        except Exception as e:
            logger.warning(f"{slot_num}-til videosini kanalga joylab bo'lmadi: {e}")
        suf = str(slot_num)
        slot_kwargs[f"language{suf}"] = lang_name
        slot_kwargs[f"file_id{suf}"] = fid
        slot_kwargs[f"channel_chat_id{suf}"] = chat_id
        slot_kwargs[f"channel_message_id{suf}"] = msg_id
    return slot_kwargs


async def finalize_partner_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    prefix = data["partner_prefix"]
    code = next_partner_code(prefix)
    is_vip = bool(data.get("is_vip"))
    is_pro = bool(data.get("is_pro"))
    genre = ", ".join(data.get("sel_genres", []))
    country = data.get("sel_country") or "-"
    sel_languages = data.get("sel_languages", [])
    language = sel_languages[0] if sel_languages else ""
    extra_videos = data.get("extra_videos", {})
    lang_caption = ", ".join(sel_languages) if sel_languages else language
    if is_vip:
        target_channel_id = VIP_CHANNEL_ID
    elif is_pro:
        target_channel_id = PRO_CHANNEL_ID
    else:
        target_channel_id = BASE_CHANNEL_ID

    channel_chat_id = None
    channel_message_id = None
    try:
        sent = await user_bot.send_video(
            target_channel_id, data["file_id"],
            caption=(
                f"🎬 {data['name']}\n🏷 Janr: {genre}\n🌍 Davlat: {country}\n"
                f"🗣 Til: {language}\n🔑 Kod: {code}"
            ),
        )
        channel_chat_id = target_channel_id
        channel_message_id = sent.message_id
    except Exception as e:
        logger.warning(f"Kanalga joylab bo'lmadi: {e}")

    slot_kwargs = await upload_extra_lang_slots(
        sel_languages, extra_videos, target_channel_id, data["name"], genre, country, code
    )

    movie_id = add_movie(
        code=code, name=data["name"], genre=genre, country=country,
        language=language, file_id=data["file_id"], channel_chat_id=channel_chat_id,
        channel_message_id=channel_message_id, is_vip=1 if is_vip else 0,
        is_pro=1 if is_pro else 0,
        **slot_kwargs,
    )
    with closing(db()) as conn, conn:
        conn.execute("UPDATE movies SET series_id=? WHERE id=?", (movie_id, movie_id))
        conn.execute("UPDATE movies SET lang_group=? WHERE id=?", (movie_id, movie_id))

    await state.update_data(new_movie_id=movie_id)
    recent = [m for m in get_recent_movies(limit=8, is_vip=1 if is_vip else 0) if m["id"] != movie_id]
    lang_summary = lang_caption + (f" ({len(sel_languages)} ta video)" if len(sel_languages) > 1 else "")
    await message.answer(
        f"✅ Kino qo'shildi!\nKod: <code>{code}</code>\nNomi: {data['name']}\n"
        f"🗣 Til: {lang_summary}\n\n"
        "Bu kino boshqa kinoning KEYINGI QISMImi?",
        reply_markup=sequel_pick_kb(recent, "ptn"),
    )


async def apply_seq_link(new_movie_id: int, code: str) -> str:
    """Kino kodini SERIYA (davomi) sifatida bog'laydi, natija matnini qaytaradi."""
    parent = get_movie_by_code(code)
    if not parent:
        return f"⚠️ \"{code}\" kodli kino topilmadi. Kodni tekshirib qaytadan yozing:"
    series_id = parent["series_id"] or parent["id"]
    next_part_number = get_max_part_number(series_id) + 1
    link_movie_to_series(new_movie_id, series_id, next_part_number)
    return f"✅ Bog'landi! Bu — {next_part_number}-qism (\"{parent['name']}\" seriyasida)."


async def show_langlink_step(message: Message, data: dict, new_movie_id: int, flow: str):
    is_vip = bool(data.get("is_vip"))
    recent = [m for m in get_recent_movies(limit=8, is_vip=1 if is_vip else 0) if m["id"] != new_movie_id]
    await message.answer(
        "Bu kino boshqa TIL variantimi (bir xil kino/qism, boshqa tilda ovozlangan)?",
        reply_markup=langlink_pick_kb(recent, flow),
    )


@user_router.callback_query(F.data.startswith("seq:"))
async def cb_seq(call: CallbackQuery, state: FSMContext):
    _, flow, value = call.data.split(":", 2)
    data = await state.get_data()
    new_movie_id = data.get("new_movie_id")
    await call.answer()

    if not new_movie_id:
        return

    if value == "custom":
        await state.update_data(seq_flow=flow)
        await state.set_state(SequelLink.waiting_seq_code)
        await call.message.answer("Qaysi kino kodining DAVOMI ekanini yozing (masalan 21):")
        return

    if value == "none":
        with closing(db()) as conn, conn:
            conn.execute(
                "UPDATE movies SET series_id=?, part_number=1 WHERE id=?", (new_movie_id, new_movie_id)
            )
        await call.message.edit_text("✅ Tayyor. Bu — mustaqil kino.")
    else:
        result_text = await apply_seq_link(new_movie_id, value)
        await call.message.edit_text(result_text)

    await show_langlink_step(call.message, data, new_movie_id, flow)


@user_router.message(SequelLink.waiting_seq_code)
async def seq_code_manual(message: Message, state: FSMContext):
    data = await state.get_data()
    new_movie_id = data.get("new_movie_id")
    flow = data.get("seq_flow", "adm")
    if not new_movie_id:
        await state.clear()
        return
    code = message.text.strip().upper()
    result_text = await apply_seq_link(new_movie_id, code)
    await message.answer(result_text)
    if result_text.startswith("⚠️"):
        return  # kod topilmasa, qayta kod kiritishga imkon beramiz
    await state.set_state(None)
    await show_langlink_step(message, data, new_movie_id, flow)


async def apply_langlink(new_movie_id: int, code: str) -> str:
    """Kino kodini bir xil TIL-guruhiga bog'laydi, natija matnini qaytaradi."""
    sibling = get_movie_by_code(code)
    if not sibling:
        return f"⚠️ \"{code}\" kodli kino topilmadi. Kodni tekshirib qaytadan yozing:"
    group_id = sibling["lang_group"] or sibling["id"]
    set_lang_group(new_movie_id, group_id)
    return f"✅ Til varianti sifatida bog'landi (\"{sibling['name']}\" bilan bir guruhda)."


async def finish_langlink_step(message: Message, state: FSMContext, flow: str, telegram_id: int):
    await state.clear()
    if flow == "adm":
        await message.answer("Menyu:", reply_markup=admin_menu_kb())
    else:
        await message.answer("Menyu:", reply_markup=user_menu_kb(telegram_id))


@user_router.callback_query(F.data.startswith("langlink:"))
async def cb_langlink(call: CallbackQuery, state: FSMContext):
    _, flow, value = call.data.split(":", 2)
    data = await state.get_data()
    new_movie_id = data.get("new_movie_id")
    await call.answer()

    if not new_movie_id:
        return

    if value == "custom":
        await state.update_data(langlink_flow=flow)
        await state.set_state(SequelLink.waiting_langlink_code)
        await call.message.answer("Qaysi kino kodi bilan bir TIL-guruhida bog'lansin? Kodni yozing:")
        return

    if value == "none":
        with closing(db()) as conn, conn:
            conn.execute("UPDATE movies SET lang_group=? WHERE id=?", (new_movie_id, new_movie_id))
        await call.message.edit_text("✅ Tayyor. Alohida til-guruhida qoladi.")
    else:
        result_text = await apply_langlink(new_movie_id, value)
        await call.message.edit_text(result_text)

    await finish_langlink_step(call.message, state, flow, call.from_user.id)


@user_router.message(SequelLink.waiting_langlink_code)
async def langlink_code_manual(message: Message, state: FSMContext):
    data = await state.get_data()
    new_movie_id = data.get("new_movie_id")
    flow = data.get("langlink_flow", "adm")
    if not new_movie_id:
        await state.clear()
        return
    code = message.text.strip().upper()
    result_text = await apply_langlink(new_movie_id, code)
    await message.answer(result_text)
    if result_text.startswith("⚠️"):
        return
    await finish_langlink_step(message, state, flow, message.from_user.id)


# ---------- Qism (davomi) to'g'ridan-to'g'ri yuklash / boshqa seriyaga qo'shish ----------

def suggest_part_name(name: str, part_number: int) -> str:
    """'Qasoskorlar 3' -> 'Qasoskorlar 4' kabi, oxiridagi raqamni almashtirib nom taklif qiladi."""
    base = re.sub(r"\s*\d+\s*$", "", name or "").strip() or (name or "").strip()
    return f"{base} {part_number}".strip()


def admin_search_movies(query: str):
    """Admin uchun nom YOKI kod bo'yicha qidiruv (VIP/PRO farqisiz, hammasi ichida)."""
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE name LIKE ? OR code LIKE ? ORDER BY id DESC LIMIT 20",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()


@user_router.message(SeriesPartUpload.waiting_video, F.video)
async def seriespart_video(message: Message, state: FSMContext):
    await state.update_data(part_file_id=message.video.file_id)
    await message.answer(
        "Ushbu qism uchun kodni kiriting (masalan K0005):",
        reply_markup=cancel_kb(message.from_user.id),
    )
    await state.set_state(SeriesPartUpload.waiting_code)


@user_router.message(SeriesPartUpload.waiting_video)
async def seriespart_video_invalid(message: Message):
    await message.answer("Iltimos, video fayl yuboring.")


@user_router.message(SeriesPartUpload.waiting_code)
async def seriespart_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    if get_movie_by_code(code):
        await message.answer("⚠️ Bu kod band. Boshqa kod kiriting:")
        return

    data = await state.get_data()
    base_movie = get_movie_by_id(data["part_base_movie_id"])
    direction = data["part_direction"]
    file_id = data["part_file_id"]
    await state.clear()

    if not base_movie:
        await message.answer("⚠️ Xatolik: asosiy kino topilmadi.", reply_markup=admin_menu_kb())
        return

    series_id = base_movie["series_id"] or base_movie["id"]

    if direction == "next":
        new_part_number = get_max_part_number(series_id) + 1
    else:
        with closing(db()) as conn, conn:
            conn.execute("UPDATE movies SET part_number = COALESCE(part_number, 1) + 1 WHERE series_id=?", (series_id,))
        new_part_number = 1

    new_name = suggest_part_name(base_movie["name"], new_part_number)
    target_channel_id = (
        VIP_CHANNEL_ID if base_movie["is_vip"] else (PRO_CHANNEL_ID if base_movie["is_pro"] else BASE_CHANNEL_ID)
    )
    channel_chat_id, channel_message_id = None, None
    try:
        sent = await user_bot.send_video(
            target_channel_id, file_id,
            caption=(
                f"🎬 {new_name}\n🏷 Janr: {base_movie['genre']}\n🌍 Davlat: {base_movie['country']}\n"
                f"🗣 Til: {base_movie['language']}\n🔑 Kod: {code}"
            ),
        )
        channel_chat_id = target_channel_id
        channel_message_id = sent.message_id
    except Exception as e:
        logger.warning(f"Kanalga joylab bo'lmadi: {e}")

    new_id = add_movie(
        code=code, name=new_name, genre=base_movie["genre"], country=base_movie["country"],
        language=base_movie["language"], file_id=file_id,
        channel_chat_id=channel_chat_id, channel_message_id=channel_message_id,
        is_vip=base_movie["is_vip"], is_pro=base_movie["is_pro"],
        series_id=series_id, part_number=new_part_number,
    )
    with closing(db()) as conn, conn:
        # Agar asosiy kino hali seriya-ildizi sifatida belgilanmagan bo'lsa, o'zini belgilaymiz.
        conn.execute(
            "UPDATE movies SET series_id=? WHERE id=? AND (series_id IS NULL OR series_id=0)",
            (series_id, series_id),
        )
        conn.execute("UPDATE movies SET lang_group=COALESCE(lang_group, id) WHERE id=?", (new_id,))

    await message.answer(
        f"✅ Yangi qism qo'shildi!\nKod: <code>{code}</code>\nNomi: {new_name}\n"
        f"📍 {new_part_number}-qism sifatida saqlandi.",
        reply_markup=admin_menu_kb(),
    )


async def finalize_series_join(message: Message, join_movie_id: int, target):
    series_id = target["series_id"] or target["id"]
    next_part_number = get_max_part_number(series_id) + 1
    link_movie_to_series(join_movie_id, series_id, next_part_number)
    with closing(db()) as conn, conn:
        conn.execute(
            "UPDATE movies SET series_id=? WHERE id=? AND (series_id IS NULL OR series_id=0)",
            (series_id, series_id),
        )
    await message.answer(
        f"✅ Bog'landi! Bu — {next_part_number}-qism (\"{target['name']}\" seriyasida).",
        reply_markup=admin_menu_kb(),
    )


@user_router.message(SeriesJoin.waiting_query)
async def seriesjoin_query(message: Message, state: FSMContext):
    data = await state.get_data()
    join_movie_id = data.get("join_movie_id")
    if not join_movie_id:
        await state.clear()
        return
    query = message.text.strip()
    exact = get_movie_by_code(query.upper())
    if exact and exact["id"] != join_movie_id:
        await state.clear()
        await finalize_series_join(message, join_movie_id, exact)
        return

    results = [m for m in admin_search_movies(query) if m["id"] != join_movie_id]
    if not results:
        await message.answer("❌ Hech narsa topilmadi. Qaytadan nomi yoki kodini kiriting:")
        return
    if len(results) == 1:
        await state.clear()
        await finalize_series_join(message, join_movie_id, results[0])
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"joinpick:{join_movie_id}:{m['id']}", style="primary")]
        for m in results[:15]
    ])
    await message.answer("Bir nechta natija topildi, birini tanlang:", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("joinpick:"))
async def cb_joinpick(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    _, join_movie_id_s, target_id_s = call.data.split(":")
    target = get_movie_by_id(int(target_id_s))
    await call.answer()
    if not target:
        await call.message.answer("Topilmadi.")
        return
    await state.clear()
    await finalize_series_join(call.message, int(join_movie_id_s), target)




# ============================================================
# SEVIMLILARIM / TOP KINOLAR / DO'STNI TAKLIF QILISH
# ============================================================

_bot_username_cache = None


async def get_bot_username() -> str:
    global _bot_username_cache
    if _bot_username_cache is None:
        me = await user_bot.get_me()
        _bot_username_cache = me.username
    return _bot_username_cache


@user_router.message(btn("favorites"))
async def favorites_list(message: Message):
    favs = list_favorites(message.from_user.id)
    if not favs:
        await message.answer(t("favorites_empty", message.from_user.id))
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"code:{m['code']}", style="primary")]
        for m in favs
    ])
    await message.answer(t("favorites_header", message.from_user.id, n=len(favs)), reply_markup=kb)


@user_router.message(btn("top"))
async def top_movies_list(message: Message):
    top = get_top_movies(limit=10, is_vip=0, is_pro=0)
    if not top:
        await message.answer("Hozircha kinolar yo'q.")
        return
    lines = [f"{i+1}. {m['name']} ({m['code']}) — 👁 {m['views']}" for i, m in enumerate(top)]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"code:{m['code']}", style="primary")]
        for m in top
    ])
    await message.answer("🔥 <b>TOP 10 kinolar:</b>\n\n" + "\n".join(lines), reply_markup=kb)


@user_router.message(btn("invite"))
async def referral_info(message: Message):
    username = await get_bot_username()
    link = f"https://t.me/{username}?start=ref_{message.from_user.id}"
    count = get_referral_count(message.from_user.id)
    bonus = int(get_setting("referral_bonus") or "0")
    bonus_note = f"\n💵 Har bir taklif uchun: {bonus} so'm bonus" if bonus > 0 else ""
    await message.answer(
        "🎁 <b>Do'stlarni taklif qilish</b>\n\n"
        f"Sizning taklif havolangiz:\n{link}\n\n"
        f"👥 Siz orqali qo'shilganlar: {count} kishi{bonus_note}",
    )


@user_router.message(btn("wallet"))
async def hisobim_menu(message: Message):
    balance = get_balance(message.from_user.id)
    await message.answer(t("balance_line", message.from_user.id, balance=balance), reply_markup=hisobim_kb(message.from_user.id))


@user_router.message(btn("bonus_code"))
async def bonus_ask(message: Message, state: FSMContext):
    await state.set_state(BonusRedeem.waiting_code)
    await message.answer("Bonus kodni kiriting:", reply_markup=cancel_kb(message.from_user.id))


@user_router.message(BonusRedeem.waiting_code)
async def bonus_process(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    amount = redeem_bonus_code(code, message.from_user.id)
    await state.clear()
    if amount == "ALREADY_USED":
        await message.answer("⚠️ Siz bu koddan allaqachon foydalangansiz.", reply_markup=hisobim_kb(message.from_user.id))
        return
    if amount is None:
        await message.answer(t("code_not_found_generic", message.from_user.id), reply_markup=hisobim_kb(message.from_user.id))
        return
    new_balance = get_balance(message.from_user.id)
    await message.answer(
        f"✅ {amount} so'm hisobingizga qo'shildi!\n💰 Yangi balans: {new_balance} so'm",
        reply_markup=hisobim_kb(message.from_user.id),
    )


@user_router.message(btn("topup"))
async def topup_ask_amount(message: Message, state: FSMContext):
    await state.set_state(TopupRequest.waiting_amount)
    await message.answer("To'ldirmoqchi bo'lgan summani kiriting (raqamda):", reply_markup=cancel_kb(message.from_user.id))


@user_router.message(TopupRequest.waiting_amount)
async def topup_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting:")
        return
    await state.update_data(amount=amount)
    await state.set_state(TopupRequest.waiting_receipt)
    await message.answer("Endi to'lov chekini (screenshot/rasm) yuboring:")


@user_router.message(TopupRequest.waiting_receipt, F.photo)
async def topup_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data["amount"]
    receipt_file_id = message.photo[-1].file_id
    topup_id = create_topup_request(message.from_user.id, amount, receipt_file_id)
    await state.clear()
    await message.answer(
        "✅ So'rovingiz yuborildi. Admin tasdiqlagach hisobingiz to'ldiriladi.",
        reply_markup=hisobim_kb(message.from_user.id),
    )
    caption = (
        f"💳 <b>Hisob to'ldirish so'rovi</b> (#{topup_id})\n"
        f"🆔 {message.from_user.id} (@{message.from_user.username or '-'})\n"
        f"💵 Summa: {amount} so'm"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 Tasdiqlash", callback_data=f"tapr:{topup_id}", style="success"),
        InlineKeyboardButton(text="🔴 Rad etish", callback_data=f"trej:{topup_id}", style="danger"),
    ]])
    with closing(db()) as conn:
        admin_ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM admins")]
    for aid in admin_ids:
        try:
            await admin_bot.send_photo(aid, receipt_file_id, caption=caption, reply_markup=kb)
        except Exception as e:
            logger.warning(f"Adminga yuborilmadi {aid}: {e}")


@user_router.message(TopupRequest.waiting_receipt)
async def topup_receipt_invalid(message: Message):
    await message.answer("Iltimos, chek rasmini (screenshot) yuboring.")


@admin_router.callback_query(F.data.startswith("tapr:"))
async def cb_topup_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    topup_id = int(call.data.split(":", 1)[1])
    topup = get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await call.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    approve_topup(topup_id)
    add_balance(topup["telegram_id"], topup["amount"])
    record_revenue("topup", topup["telegram_id"], topup["amount"], f"Hisob to'ldirish #{topup_id}")
    await call.answer("Tasdiqlandi.")
    await call.message.answer(f"✅ To'ldirish #{topup_id} tasdiqlandi, hisobga {topup['amount']} so'm qo'shildi.")
    try:
        await user_bot.send_message(
            topup["telegram_id"],
            f"✅ Hisobingiz {topup['amount']} so'mga to'ldirildi!\n💰 Yangi balans: {get_balance(topup['telegram_id'])} so'm",
        )
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("trej:"))
async def cb_topup_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    topup_id = int(call.data.split(":", 1)[1])
    reject_topup(topup_id)
    topup = get_topup(topup_id)
    await call.answer("Rad etildi.")
    await call.message.answer(f"❌ To'ldirish so'rovi #{topup_id} rad etildi.")
    try:
        await user_bot.send_message(topup["telegram_id"], "❌ Hisob to'ldirish so'rovingiz rad etildi.")
    except Exception:
        pass


# ============================================================
# VIP MENYU (qo'rqinchli kinolar, ariza asosida)
# ============================================================

@user_router.message(btn("vip"))
async def vip_menu(message: Message):
    status = membership_status_text(message.from_user.id, "vip")
    text = (
        "⭐️ <b>VIP</b>\n\n"
        "Bu bo'limda qo'shimcha (qo'rqinchli janr) kontent joylashgan.\n"
        f"\nHolatingiz: {status}"
    )
    await message.answer(text, reply_markup=vip_menu_kb(message.from_user.id))


@user_router.message(btn("vip_codes"))
async def vip_codes_channel(message: Message):
    if not has_active_membership(message.from_user.id, "vip"):
        await message.answer("⚠️ Avval VIP obuna oling (ariza yuboring, pulga tasdiqlang yoki kod kiriting).")
        return
    await message.answer(f"⭐️ VIP kanal:\n{VIP_CHANNEL}")


@user_router.message(btn("vip_search_code"))
async def vip_ask_code(message: Message, state: FSMContext):
    if not has_active_membership(message.from_user.id, "vip"):
        await message.answer("⚠️ Avval VIP obuna oling (ariza yuboring, pulga tasdiqlang yoki kod kiriting).")
        return
    await state.set_state(VipCodeSearch.waiting_code)
    await message.answer("VIP kino kodini kiriting:", reply_markup=cancel_kb(message.from_user.id))


@user_router.message(VipCodeSearch.waiting_code)
async def vip_process_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    movie = get_movie_by_code(code)
    await state.clear()
    if not movie or not movie["is_vip"]:
        await message.answer(t("vip_code_not_found", message.from_user.id), reply_markup=vip_menu_kb(message.from_user.id))
        return
    await message.answer("✅ Topildi!", reply_markup=vip_menu_kb(message.from_user.id))
    await open_movie(message.chat.id, movie)


@user_router.message(btn("vip_enter_code"))
async def vip_redeem_start(message: Message, state: FSMContext):
    await state.set_state(TariffRedeem.waiting_code)
    await state.update_data(redeem_tier="vip")
    await message.answer("⭐️ VIP tarif kodini kiriting:", reply_markup=cancel_kb(message.from_user.id))


@user_router.message(TariffRedeem.waiting_code)
async def tariff_redeem_process(message: Message, state: FSMContext):
    data = await state.get_data()
    tier = data.get("redeem_tier", "vip")
    code = message.text.strip().upper()
    await state.clear()
    row = redeem_tariff_code(code, message.from_user.id, expected_tier=tier)
    kb_map = {"vip": vip_menu_kb, "pro": pro_menu_kb}
    kb = kb_map.get(tier, lambda uid: user_menu_kb(uid))(message.from_user.id)
    if row == "EXPIRED":
        await message.answer(
            "⌛ Bu kodning muddati allaqachon tugagan. Yangi tarif sotib olishingiz yoki "
            "yangi ariza yuborishingiz kerak.",
            reply_markup=kb,
        )
        return
    if not row:
        await message.answer(t("tariff_code_not_found", message.from_user.id), reply_markup=kb)
        return

    if tier == "hamkor":
        # Hamkor tarifi kod orqali faollashtirilganda, foydalanuvchi PARTNERS jadvaliga
        # ham kiritilishi shart — aks holda "Hamkorlar ro'yxati"da ko'rinmaydi va
        # "HAMKOR KINO YUKLASH" tugmasidan foydalana olmaydi.
        await finalize_hamkor_code_redeem(message, state)
        return

    await message.answer(
        f"✅ Kod qabul qilindi! {TIER_TITLES.get(tier, tier)} tarifi faollashtirildi "
        f"({PLAN_LABELS.get(row['plan'], row['plan'])}).\n\n{membership_status_text(message.from_user.id, tier)}",
        reply_markup=kb,
    )


async def finalize_hamkor_code_redeem(message: Message, state: FSMContext):
    uid = message.from_user.id
    existing = get_approved_partner_by_uid(uid)
    if existing:
        await message.answer(
            f"✅ Kod qabul qilindi! Hamkorlik tarifingiz yangilandi.\n\n"
            f"🔠 Sizning harfingiz: <b>{existing['letter_prefix'] or '-'}</b>\n"
            f"{membership_status_text(uid, 'hamkor')}",
            reply_markup=user_menu_kb(uid),
        )
        return
    suggestion = next_available_partner_letter()
    await state.set_state(HamkorLetterPick.waiting_letter)
    await message.answer(
        f"✅ Kod qabul qilindi! Hamkorlik tarifi faollashtirildi.\n{membership_status_text(uid, 'hamkor')}\n\n"
        "Endi o'zingiz uchun BITTA lotin harfi tanlang — kino kodlaringiz shu harf bilan "
        f"boshlanadi (masalan {suggestion}001, {suggestion}002...).\n\n"
        f"Bo'sh harf: <b>{suggestion}</b> (yoki boshqasini yozing, bitta harf yuboring):"
    )


@user_router.message(HamkorLetterPick.waiting_letter)
async def hamkor_letter_pick(message: Message, state: FSMContext):
    letter = (message.text or "").strip()[:1].upper()
    if not letter.isalpha():
        await message.answer("Iltimos, faqat bitta lotin harfi yuboring (masalan A):")
        return
    if letter in ("M", "R"):
        await message.answer(f"❌ \"{letter}\" harfi tizim uchun ajratilgan. Boshqa harf tanlang:")
        return
    with closing(db()) as conn:
        taken = conn.execute(
            "SELECT 1 FROM partners WHERE letter_prefix=? AND status='approved'", (letter,)
        ).fetchone()
    if taken:
        await message.answer(f"❌ \"{letter}\" harfi band. Boshqa harf tanlang:")
        return
    uid = message.from_user.id
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO partners (telegram_id, channel_link, letter_prefix, status, created_at) "
            "VALUES (?, '-', ?, 'approved', ?)",
            (uid, letter, datetime.utcnow().isoformat()),
        )
    await state.clear()
    await message.answer(
        f"✅ Tayyor! Sizning harfingiz: <b>{letter}</b>\n"
        f"Kino kodlaringiz shu harf bilan boshlanadi (masalan {letter}001, {letter}002...).\n\n"
        "Endi asosiy menyudan \"⬆️ HAMKOR KINO YUKLASH\" tugmasi orqali kino yuklashingiz mumkin.",
        reply_markup=user_menu_kb(uid),
    )


@user_router.message(btn("vip_apply"))
async def vip_apply_start(message: Message, state: FSMContext):
    await state.update_data(vip_paid=False)
    await state.set_state(VipApplication.waiting_name)
    await message.answer("Ismingizni kiriting:", reply_markup=cancel_kb(message.from_user.id))


@user_router.message(btn("vip_pay_confirm"))
async def vip_pay_start(message: Message, state: FSMContext):
    if all(tariff_price("vip", p) <= 0 for p in TIER_PLANS["vip"]):
        await message.answer("Bu xizmat hozircha faol emas.", reply_markup=vip_menu_kb(message.from_user.id))
        return
    await message.answer(
        "Tarifni tanlang:",
        reply_markup=tariff_plan_kb("vip", "vippay"),
    )


@user_router.callback_query(F.data.startswith("vippay:"))
async def vip_pay_plan_chosen(call: CallbackQuery):
    plan = call.data.split(":", 1)[1]
    price = tariff_price("vip", plan)
    uid = call.from_user.id
    await call.answer()
    if price <= 0:
        await call.message.answer("Bu tarif hozircha faol emas.")
        return
    if get_balance(uid) < price:
        await call.message.answer(
            f"❌ Balansingiz yetarli emas (kerak: {price} so'm). "
            "Avval \"💰 HISOBIM\" bo'limidan hisobingizni to'ldiring.",
            reply_markup=vip_menu_kb(uid),
        )
        return
    add_balance(uid, -price)
    record_revenue("vip", uid, price, f"VIP {PLAN_LABELS[plan]} (pulga tasdiqlash)")
    code = issue_and_activate_code("vip", plan, uid)
    await call.message.answer(
        f"✅ Balansingizdan {price} so'm yechildi va VIP darhol ochildi!\n"
        f"🔑 Kodingiz: <code>{code}</code>\n"
        f"⭐️ VIP kanal: {VIP_CHANNEL}\n\n{membership_status_text(uid, 'vip')}",
        reply_markup=vip_menu_kb(uid),
    )


@user_router.message(VipApplication.waiting_name)
async def vip_apply_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await state.set_state(VipApplication.waiting_phone)
    await message.answer("Telefon raqamingizni kiriting:")


@user_router.message(VipApplication.waiting_phone)
async def vip_apply_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await state.set_state(VipApplication.waiting_birthdate)
    await message.answer("Tug'ilgan yilingizni kiriting (masalan: 01.01.2001):")


@user_router.message(VipApplication.waiting_birthdate)
async def vip_apply_birthdate(message: Message, state: FSMContext):
    data = await state.get_data()
    full_name = data["full_name"]
    phone = data["phone"]
    birthdate = message.text.strip()
    app_id = create_vip_application(message.from_user.id, full_name, phone, birthdate)
    await state.clear()

    await message.answer(
        "✅ Arizangiz yuborildi. Admin ko'rib chiqqach, tarifni tanlab kod yuboradi.",
        reply_markup=vip_menu_kb(message.from_user.id),
    )
    admin_text = (
        f"📥 <b>Yangi VIP ariza</b> (#{app_id})\n"
        f"👤 Ism: {full_name}\n"
        f"📞 Tel: {phone}\n"
        f"🎂 Sana: {birthdate}\n"
        f"🆔 User ID: {message.from_user.id}\n"
        f"Username: @{message.from_user.username or '-'}"
    )
    with closing(db()) as conn:
        admin_ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM admins")]
    for aid in admin_ids:
        try:
            await admin_bot.send_message(aid, admin_text, reply_markup=application_decision_kb(app_id))
        except Exception as e:
            logger.warning(f"Adminga yuborilmadi {aid}: {e}")


@admin_router.callback_query(F.data.startswith("appr:"))
async def cb_approve(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    app_id = int(call.data.split(":", 1)[1])
    await call.answer()
    await call.message.answer(
        f"Ariza #{app_id} uchun tarifni tanlang (kod avtomatik yaratilib yuboriladi):",
        reply_markup=tariff_plan_kb("vip", f"vappr:{app_id}"),
    )


@admin_router.callback_query(F.data.startswith("vappr:"))
async def cb_approve_plan_chosen(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, app_id, plan = call.data.split(":", 2)
    app_id = int(app_id)
    app = get_application(app_id)
    if not app:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    code = issue_and_activate_code("vip", plan, app["telegram_id"])
    approve_application(app_id, code)
    log_admin_action(call.from_user.id, "VIP ariza tasdiqladi", f"#{app_id} -> {app['telegram_id']} ({PLAN_LABELS[plan]})")
    await call.message.answer(
        f"✅ Ariza tasdiqlandi ({PLAN_LABELS[plan]}) va kod avtomatik yuborildi.",
        reply_markup=admin_menu_kb(),
    )
    try:
        await user_bot.send_message(
            app["telegram_id"],
            f"✅ Arizangiz tasdiqlandi!\n🎯 Tarif: {PLAN_LABELS[plan]}\n"
            f"🔑 Sizning VIP kodingiz: <code>{code}</code>\n"
            f"Kanal: {VIP_CHANNEL}\n\n{membership_status_text(app['telegram_id'], 'vip')}",
        )
    except Exception as e:
        logger.warning(f"Foydalanuvchiga yuborilmadi: {e}")


@admin_router.callback_query(F.data.startswith("rej:"))
async def cb_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    app_id = int(call.data.split(":", 1)[1])
    reject_application(app_id)
    app = get_application(app_id)
    log_admin_action(call.from_user.id, "VIP ariza rad etdi", f"#{app_id} -> {app['telegram_id'] if app else '?'}")
    await call.answer("Rad etildi.")
    await call.message.answer(f"❌ Ariza #{app_id} rad etildi.")
    try:
        await user_bot.send_message(app["telegram_id"], "❌ Kechirasiz, arizangiz rad etildi.")
    except Exception:
        pass


# ============================================================
# PRO (hammadan oldin yuklangan kinolar) — VIP bilan bir xil tuzilma
# ============================================================

@user_router.message(btn("pro"))
async def pro_menu(message: Message):
    status = membership_status_text(message.from_user.id, "pro")
    text = (
        "💎 <b>PRO</b>\n\n"
        "PRO obunachilar yangi yuklangan kinolarni HAMMADAN OLDIN ko'radi.\n"
        f"\nHolatingiz: {status}"
    )
    await message.answer(text, reply_markup=pro_menu_kb(message.from_user.id))


@user_router.message(btn("pro_codes"))
async def pro_codes_channel(message: Message):
    if not has_active_membership(message.from_user.id, "pro"):
        await message.answer("⚠️ Avval PRO obuna oling (ariza yuboring, pulga tasdiqlang yoki kod kiriting).")
        return
    await message.answer(f"💎 PRO kanal:\n{PRO_CHANNEL}")


@user_router.message(btn("pro_search_code"))
async def pro_ask_code(message: Message, state: FSMContext):
    if not has_active_membership(message.from_user.id, "pro"):
        await message.answer("⚠️ Avval PRO obuna oling (ariza yuboring, pulga tasdiqlang yoki kod kiriting).")
        return
    await state.set_state(ProCodeSearch.waiting_code)
    await message.answer("PRO kino kodini kiriting:", reply_markup=cancel_kb(message.from_user.id))


@user_router.message(ProCodeSearch.waiting_code)
async def pro_process_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    movie = get_movie_by_code(code)
    await state.clear()
    if not movie or not movie["is_pro"]:
        await message.answer(t("pro_code_not_found", message.from_user.id), reply_markup=pro_menu_kb(message.from_user.id))
        return
    await message.answer("✅ Topildi!", reply_markup=pro_menu_kb(message.from_user.id))
    await open_movie(message.chat.id, movie)


@user_router.message(btn("pro_enter_code"))
async def pro_redeem_start(message: Message, state: FSMContext):
    await state.set_state(TariffRedeem.waiting_code)
    await state.update_data(redeem_tier="pro")
    await message.answer("💎 PRO tarif kodini kiriting:", reply_markup=cancel_kb(message.from_user.id))


@user_router.message(btn("pro_apply"))
async def pro_apply_start(message: Message):
    app_id = create_tier_application(message.from_user.id, "pro")
    await message.answer(
        "✅ Arizangiz yuborildi. Admin ko'rib chiqqach, tarifni tanlab kod yuboradi.",
        reply_markup=pro_menu_kb(message.from_user.id),
    )
    admin_text = (
        f"📥 <b>Yangi PRO ariza</b> (#{app_id})\n"
        f"🆔 User ID: {message.from_user.id}\n"
        f"Username: @{message.from_user.username or '-'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 Tasdiqlash", callback_data=f"pappr:{app_id}", style="success"),
        InlineKeyboardButton(text="🔴 Rad etish", callback_data=f"prorej:{app_id}", style="danger"),
    ]])
    with closing(db()) as conn:
        admin_ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM admins")]
    for aid in admin_ids:
        try:
            await admin_bot.send_message(aid, admin_text, reply_markup=kb)
        except Exception as e:
            logger.warning(f"Adminga yuborilmadi {aid}: {e}")


@user_router.message(btn("pro_pay_confirm"))
async def pro_pay_start(message: Message):
    if all(tariff_price("pro", p) <= 0 for p in TIER_PLANS["pro"]):
        await message.answer("Bu xizmat hozircha faol emas.", reply_markup=pro_menu_kb(message.from_user.id))
        return
    await message.answer("Tarifni tanlang:", reply_markup=tariff_plan_kb("pro", "propay"))


@user_router.callback_query(F.data.startswith("propay:"))
async def pro_pay_plan_chosen(call: CallbackQuery):
    plan = call.data.split(":", 1)[1]
    price = tariff_price("pro", plan)
    uid = call.from_user.id
    await call.answer()
    if price <= 0:
        await call.message.answer("Bu tarif hozircha faol emas.")
        return
    if get_balance(uid) < price:
        await call.message.answer(
            f"❌ Balansingiz yetarli emas (kerak: {price} so'm). "
            "Avval \"💰 HISOBIM\" bo'limidan hisobingizni to'ldiring.",
            reply_markup=pro_menu_kb(uid),
        )
        return
    add_balance(uid, -price)
    record_revenue("pro", uid, price, f"PRO {PLAN_LABELS[plan]} (pulga tasdiqlash)")
    code = issue_and_activate_code("pro", plan, uid)
    await call.message.answer(
        f"✅ Balansingizdan {price} so'm yechildi va PRO darhol ochildi!\n"
        f"🔑 Kodingiz: <code>{code}</code>\n"
        f"💎 PRO kanal: {PRO_CHANNEL}\n\n{membership_status_text(uid, 'pro')}",
        reply_markup=pro_menu_kb(uid),
    )


@admin_router.callback_query(F.data.startswith("pappr:"))
async def cb_pro_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    app_id = int(call.data.split(":", 1)[1])
    await call.answer()
    await call.message.answer(
        f"PRO ariza #{app_id} uchun tarifni tanlang (kod avtomatik yaratilib yuboriladi):",
        reply_markup=tariff_plan_kb("pro", f"pappr2:{app_id}"),
    )


@admin_router.callback_query(F.data.startswith("pappr2:"))
async def cb_pro_approve_plan_chosen(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, app_id, plan = call.data.split(":", 2)
    app_id = int(app_id)
    app = get_tier_application(app_id)
    if not app:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    code = issue_and_activate_code("pro", plan, app["telegram_id"])
    set_tier_application_status(app_id, "approved")
    log_admin_action(call.from_user.id, "PRO ariza tasdiqladi", f"#{app_id} -> {app['telegram_id']} ({PLAN_LABELS[plan]})")
    await call.message.answer(
        f"✅ PRO ariza tasdiqlandi ({PLAN_LABELS[plan]}) va kod avtomatik yuborildi.",
        reply_markup=admin_menu_kb(),
    )
    try:
        await user_bot.send_message(
            app["telegram_id"],
            f"✅ PRO arizangiz tasdiqlandi!\n🎯 Tarif: {PLAN_LABELS[plan]}\n"
            f"🔑 Sizning PRO kodingiz: <code>{code}</code>\n"
            f"Kanal: {PRO_CHANNEL}\n\n{membership_status_text(app['telegram_id'], 'pro')}",
        )
    except Exception as e:
        logger.warning(f"Foydalanuvchiga yuborilmadi: {e}")


@admin_router.callback_query(F.data.startswith("prorej:"))
async def cb_pro_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    app_id = int(call.data.split(":", 1)[1])
    set_tier_application_status(app_id, "rejected")
    app = get_tier_application(app_id)
    log_admin_action(call.from_user.id, "PRO ariza rad etdi", f"#{app_id} -> {app['telegram_id'] if app else '?'}")
    await call.answer("Rad etildi.")
    await call.message.answer(f"❌ PRO ariza #{app_id} rad etildi.")
    try:
        await user_bot.send_message(app["telegram_id"], "❌ Kechirasiz, PRO arizangiz rad etildi.")
    except Exception:
        pass


# ============================================================
# ADMIN PANEL
# ============================================================

@admin_router.message(F.text == "🛠 ADMIN PANEL")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 Admin panel:", reply_markup=admin_menu_kb())


@admin_router.message(F.text == "⬆️ KINO YUKLASH")
async def upload_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(csoon_link_id=None, csoon_link_name=None)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ VIP", callback_data="uplcat:vip", style="primary")],
        [InlineKeyboardButton(text="💎 PRO", callback_data="uplcat:pro", style="primary")],
        [InlineKeyboardButton(text="🎬 Oddiy", callback_data="uplcat:oddiy", style="primary")],
    ])
    await message.answer("Kino qaysi toifaga yuklanadi?", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("uplcat:"))
async def upload_category_chosen(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    cat = call.data.split(":", 1)[1]
    is_vip = cat == "vip"
    is_pro = cat == "pro"
    await state.update_data(is_vip=is_vip, is_pro=is_pro)
    await state.set_state(UploadMovie.waiting_video)
    await call.answer()
    data = await state.get_data()
    linked_name = data.get("csoon_link_name")
    prompt = f"🎬 \"{linked_name}\" uchun videoni yuboring:" if linked_name else "Videoni yuboring:"
    await call.message.answer(prompt, reply_markup=cancel_kb())


async def _proceed_after_movie_name(message: Message, state: FSMContext, name: str):
    await state.update_data(name=name, sel_genres=[], sel_country=None, sel_languages=[])
    data = await state.get_data()
    if data.get("is_vip"):
        await state.update_data(sel_genres=["Qo'rqinchli"])
        await message.answer(
            "Davlatni tanlang (faqat bitta):",
            reply_markup=select_kb(list_countries(), [], "adm", "c"),
        )
    else:
        await message.answer(
            "Janrni tanlang (bitta yoki bir nechta), so'ng \"Tayyor\" bosing:",
            reply_markup=select_kb(list_genres(), [], "adm", "g"),
        )


@admin_router.message(UploadMovie.waiting_video, F.video)
async def upload_video(message: Message, state: FSMContext):
    await state.update_data(file_id=message.video.file_id)
    data = await state.get_data()
    linked_name = data.get("csoon_link_name")
    if linked_name:
        linked_id = data.get("csoon_link_id")
        if linked_id:
            delete_coming_soon(linked_id)
        await message.answer(f"✅ \"{linked_name}\" nomi 'Tez orada' ro'yxatidan avtomatik olindi.")
        await _proceed_after_movie_name(message, state, linked_name)
        return
    await state.set_state(UploadMovie.waiting_name)
    await message.answer("Kino nomini kiriting:")


@admin_router.message(UploadMovie.waiting_video)
async def upload_video_invalid(message: Message):
    await message.answer("Iltimos, video fayl yuboring.")


@admin_router.message(UploadMovie.waiting_name)
async def upload_name(message: Message, state: FSMContext):
    await _proceed_after_movie_name(message, state, message.text.strip())


@admin_router.message(UploadMovie.waiting_video2, F.video)
async def upload_video2(message: Message, state: FSMContext):
    data = await state.get_data()
    sel = data.get("sel_languages", [])
    slot = data.get("lang_video_slot", 2)
    videos = dict(data.get("extra_videos", {}))
    videos[str(slot)] = message.video.file_id
    next_slot = slot + 1
    if next_slot <= len(sel):
        await state.update_data(extra_videos=videos, lang_video_slot=next_slot)
        await message.answer(
            f"🎬 Endi \"{sel[next_slot - 1]}\" tilidagi videoni yuboring "
            f"({next_slot}-video sifatida saqlanadi):"
        )
    else:
        await state.update_data(extra_videos=videos)
        await message.answer("Ushbu kino uchun kodni kiriting (masalan K0001 yoki H0001):")
        await state.set_state(UploadMovie.waiting_code)


@admin_router.message(UploadMovie.waiting_video2)
async def upload_video2_invalid(message: Message):
    await message.answer("Iltimos, 2-til uchun video fayl yuboring.")


@admin_router.message(UploadMovie.waiting_code)
async def upload_code(message: Message, state: FSMContext):
    data = await state.get_data()
    code = message.text.strip().upper()
    if get_movie_by_code(code):
        await message.answer("⚠️ Bu kod band. Boshqa kod kiriting:")
        return

    is_vip = bool(data.get("is_vip"))
    is_pro = bool(data.get("is_pro"))
    genre = ", ".join(data.get("sel_genres", []))
    country = data.get("sel_country") or "-"
    sel_languages = data.get("sel_languages", [])
    language = sel_languages[0] if sel_languages else ""
    extra_videos = data.get("extra_videos", {})
    if is_vip:
        target_channel_id = VIP_CHANNEL_ID
    elif is_pro:
        target_channel_id = PRO_CHANNEL_ID
    else:
        target_channel_id = BASE_CHANNEL_ID
    lang_caption = ", ".join(sel_languages) if sel_languages else language

    channel_chat_id = None
    channel_message_id = None
    try:
        sent = await user_bot.send_video(
            target_channel_id, data["file_id"],
            caption=(
                f"🎬 {data['name']}\n🏷 Janr: {genre}\n🌍 Davlat: {country}\n"
                f"🗣 Til: {language}\n🔑 Kod: {code}"
            ),
        )
        channel_chat_id = target_channel_id
        channel_message_id = sent.message_id
    except Exception as e:
        logger.warning(f"Kanalga joylab bo'lmadi ({target_channel_id}): {e}")
        await message.answer(
            "⚠️ Kanalga avtomatik joylab bo'lmadi (bot kanalda admin emas yoki "
            "BASE_CHANNEL_ID/VIP_CHANNEL_ID noto'g'ri). Kino baza ichida saqlanadi, "
            "lekin kanalga qo'lda joylashingiz kerak bo'ladi."
        )

    slot_kwargs = await upload_extra_lang_slots(
        sel_languages, extra_videos, target_channel_id, data["name"], genre, country, code
    )

    movie_id = add_movie(
        code=code,
        name=data["name"],
        genre=genre,
        country=country,
        language=language,
        file_id=data["file_id"],
        channel_chat_id=channel_chat_id,
        channel_message_id=channel_message_id,
        is_vip=1 if is_vip else 0,
        series_id=None,
        is_pro=1 if is_pro else 0,
        **slot_kwargs,
    )
    with closing(db()) as conn, conn:
        conn.execute("UPDATE movies SET series_id=? WHERE id=?", (movie_id, movie_id))
        conn.execute("UPDATE movies SET lang_group=? WHERE id=?", (movie_id, movie_id))

    await state.update_data(new_movie_id=movie_id)
    recent = [m for m in get_recent_movies(limit=8, is_vip=1 if is_vip else 0) if m["id"] != movie_id]
    lang_summary = lang_caption + (f" ({len(sel_languages)} ta video)" if len(sel_languages) > 1 else "")
    await message.answer(
        f"✅ Kino qo'shildi va kanalga joylandi!\nKod: <code>{code}</code>\nNomi: {data['name']}\n"
        f"🗣 Til: {lang_summary}\n\n"
        "Bu kino boshqa kinoning KEYINGI QISMImi?",
        reply_markup=sequel_pick_kb(recent, "adm"),
    )


@admin_router.message(F.text == "⚙️ SOZLAMALAR")
async def settings_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⚙️ Sozlamalar:", reply_markup=sozlamalar_kb())


@admin_router.message(F.text == "⬅️ Orqaga")
async def settings_back(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 Admin panel:", reply_markup=admin_menu_kb())


@admin_router.message(F.text == "📝 Matnlar (reklama/hamkorlik/bog'lanish)")
async def soz_matnlar(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Qaysi matnni tahrirlashni xohlaysiz?", reply_markup=settings_kb())


@admin_router.message(F.text == "💵 Narxlar")
async def soz_narxlar(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Narxni tanlang va yangisini kiriting:", reply_markup=prices_kb())


@admin_router.message(F.text == "👤 Adminlar")
async def soz_adminlar(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admin_add", style="success")],
        [InlineKeyboardButton(text="➖ Admin o'chirish", callback_data="admin_del", style="danger")],
    ])
    await message.answer("Admin boshqaruvi:", reply_markup=kb)


@admin_router.message(F.text == "💰 Balans bonus kodi")
async def soz_bonus(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminBonusGenerate.waiting_amount)
    await message.answer("Bonus kod uchun summani kiriting:", reply_markup=cancel_kb(message.from_user.id))


@admin_router.message(AdminBonusGenerate.waiting_amount)
async def process_bonus_generate(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting:")
        return
    await state.update_data(bonus_amount=amount)
    await state.set_state(AdminBonusGenerate.waiting_max_uses)
    await message.answer(
        "Bu kod necha marta ishlatilishi mumkin?\n"
        "• Bitta marta uchun: 1\n"
        "• Cheksiz (istalgancha foydalanuvchi) uchun: 0\n"
        "• Ma'lum sonli foydalanuvchi uchun: masalan 50",
        reply_markup=cancel_kb(message.from_user.id),
    )


@admin_router.message(AdminBonusGenerate.waiting_max_uses)
async def process_bonus_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text.strip())
        if max_uses < 0:
            raise ValueError
    except ValueError:
        await message.answer("Iltimos, 0 yoki musbat butun son kiriting:")
        return
    data = await state.get_data()
    amount = data["bonus_amount"]
    await state.clear()
    code = generate_bonus_code(amount, max_uses)
    link = f"https://t.me/{BOT_USERNAME}?start=bonus_{code}"
    uses_label = "♾ Cheksiz" if max_uses == 0 else f"{max_uses} marta"
    await message.answer(
        f"✅ Bonus kod yaratildi:\n<code>{code}</code>\n💵 Summasi: {amount} so'm\n🔁 Foydalanish soni: {uses_label}\n\n"
        "Bu kodni xohlagan foydalanuvchingizga bering — u \"HISOBIM\" → \"BONUS KOD KIRITISH\" "
        f"orqali hisobiga qo'shib oladi.\n\n🔗 Yoki to'g'ridan-to'g'ri havola:\n{link}",
        reply_markup=admin_menu_kb(),
    )
    await message.answer(
        "📢 Bu kod KODLAR kanaliga yuborilsinmi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha", callback_data=f"bonuschan:{code}", style="success"),
             InlineKeyboardButton(text="❌ Yo'q", callback_data="bonuschan_no", style="danger")],
        ]),
    )


@admin_router.callback_query(F.data == "bonuschan_no")
async def cb_bonuschan_no(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer("Bekor qilindi.")
    await call.message.delete()


@admin_router.callback_query(F.data.startswith("bonuschan:"))
async def cb_bonuschan_yes(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    code = call.data.split(":", 1)[1]
    row = get_bonus_code(code)
    if not row:
        await call.answer("⚠️ Kod topilmadi.", show_alert=True)
        return
    max_uses = row["max_uses"] if row["max_uses"] is not None else 1
    uses_label = "♾ Cheksiz" if max_uses == 0 else f"{max_uses} marta"
    text = (
        f"🎁 <b>BONUS KOD</b>\n\n💵 Summasi: {row['amount']} so'm\n🔁 Foydalanish soni: {uses_label}\n\n"
        "Pastdagi tugmani bosib darhol faollashtiring!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Faollashtirish", callback_data=f"actbonus:{code}", style="success")],
    ])
    await user_bot.send_message(CODES_CHANNEL_ID, text, reply_markup=kb)
    await call.answer("✅ Kanalga yuborildi.")
    await call.message.delete()


@user_router.callback_query(F.data.startswith("actbonus:"))
async def cb_activate_bonus(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    if not user_exists(call.from_user.id):
        register_user(call.from_user.id, call.from_user.username, call.from_user.first_name or "")
    amount = redeem_bonus_code(code, call.from_user.id)
    if isinstance(amount, int):
        new_balance = get_balance(call.from_user.id)
        await call.answer(f"✅ {amount} so'm hisobingizga qo'shildi! Balans: {new_balance} so'm", show_alert=True)
    elif amount == "ALREADY_USED":
        await call.answer("⚠️ Siz bu koddan allaqachon foydalangansiz.", show_alert=True)
    else:
        await call.answer("⚠️ Bu kodning foydalanish limiti tugagan.", show_alert=True)


TAXONOMY_CONFIG = {
    "janr": {"title": "Janrlar", "list": list_genres, "add": add_genre, "remove": remove_genre},
    "davlat": {"title": "Davlatlar", "list": list_countries, "add": add_country, "remove": remove_country},
    "til": {"title": "Tillar", "list": list_languages, "add": add_language, "remove": remove_language},
}


@admin_router.message(F.text.in_(["🏷 Janrlar", "🌍 Davlatlar", "🗣 Tillar"]))
async def soz_taxonomy(message: Message):
    if not is_admin(message.from_user.id):
        return
    kind = {"🏷 Janrlar": "janr", "🌍 Davlatlar": "davlat", "🗣 Tillar": "til"}[message.text]
    cfg = TAXONOMY_CONFIG[kind]
    await message.answer(f"{cfg['title']}:", reply_markup=taxonomy_admin_kb(cfg["list"](), kind))


@admin_router.callback_query(F.data.startswith("tax_add:"))
async def tax_add_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    kind = call.data.split(":", 1)[1]
    await state.set_state(TaxonomyAdd.waiting_name)
    await state.update_data(tax_kind=kind)
    await call.answer()
    await call.message.answer(f"Yangi {TAXONOMY_CONFIG[kind]['title'].lower()} nomini kiriting:", reply_markup=cancel_kb())


@admin_router.message(TaxonomyAdd.waiting_name)
async def tax_add_process(message: Message, state: FSMContext):
    data = await state.get_data()
    kind = data["tax_kind"]
    cfg = TAXONOMY_CONFIG[kind]
    cfg["add"](message.text.strip())
    await state.clear()
    await message.answer(
        f"✅ Qo'shildi.",
        reply_markup=admin_menu_kb(),
    )
    await message.answer(f"{cfg['title']}:", reply_markup=taxonomy_admin_kb(cfg["list"](), kind))


@admin_router.callback_query(F.data.startswith("tax_del:"))
async def tax_del(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    _, kind, name = call.data.split(":", 2)
    cfg = TAXONOMY_CONFIG[kind]
    cfg["remove"](name)
    await call.answer("O'chirildi.")
    await call.message.edit_reply_markup(reply_markup=taxonomy_admin_kb(cfg["list"](), kind))


@admin_router.message(F.text == "📡 Majburiy obuna kanallari")
async def soz_majburiy(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("📡 Majburiy obuna kanallari:", reply_markup=mandatory_admin_kb())


@admin_router.callback_query(F.data == "maj_add")
async def maj_add_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(MandatoryChannelAdd.waiting_chat_id)
    await call.answer()
    await call.message.answer(
        "Kanalni qo'shishning eng oson yo'li:\n"
        "1️⃣ O'sha kanaldagi istalgan postni shu yerga FORWARD (uzatib) yuboring\n\n"
        "Yoki:\n"
        "2️⃣ Kanalning raqamli chat_id'sini qo'lda kiriting (masalan -1001234567890)\n\n"
        "(Bot shu kanalga avval ADMIN qilib qo'shilgan bo'lishi shart)",
        reply_markup=cancel_kb(),
    )


@admin_router.message(MandatoryChannelAdd.waiting_chat_id)
async def maj_add_chat_id(message: Message, state: FSMContext):
    chat_id = None
    title = None

    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
        title = message.forward_from_chat.title
    elif message.text:
        try:
            chat_id = int(message.text.strip())
        except ValueError:
            chat_id = None

    if chat_id is None:
        await message.answer(
            "❌ Tushunmadim. Kanaldagi postni FORWARD qiling, "
            "yoki raqamli chat_id kiriting (masalan -1001234567890):"
        )
        return

    # Bot shu kanalda ishlay oladimi, tekshirib ko'ramiz
    try:
        chat = await user_bot.get_chat(chat_id)
        title = title or chat.title
    except Exception as e:
        await message.answer(
            f"⚠️ Botni shu kanaldan topa olmadim ({e}).\n"
            "Bot kanalga ADMIN qilib qo'shilganiga ishonch hosil qiling va qaytadan urinib ko'ring, "
            "yoki \"❌ BEKOR QILISH\" bosing."
        )
        return

    await state.update_data(chat_id=chat_id, title=title)
    if title:
        await state.set_state(MandatoryChannelAdd.waiting_link)
        await message.answer(f"✅ Kanal topildi: <b>{title}</b>\n\nEndi kanal linkini (https://t.me/...) kiriting:")
    else:
        await state.set_state(MandatoryChannelAdd.waiting_link)
        await message.answer("Kanal linkini (https://t.me/...) kiriting:")


@admin_router.message(MandatoryChannelAdd.waiting_link)
async def maj_add_link(message: Message, state: FSMContext):
    await state.update_data(link=message.text.strip())
    data = await state.get_data()
    if data.get("title"):
        # Forward orqali nom allaqachon aniqlangan — nom so'rash bosqichini o'tkazib yuboramiz
        await state.set_state(MandatoryChannelAdd.waiting_threshold)
        await message.answer(
            "Nechta obunachida avtomatik o'chirilsin? (0 — cheksiz, hech qachon o'chmaydi):"
        )
    else:
        await state.set_state(MandatoryChannelAdd.waiting_title)
        await message.answer("Kanal nomini kiriting:")


@admin_router.message(MandatoryChannelAdd.waiting_title)
async def maj_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(MandatoryChannelAdd.waiting_threshold)
    await message.answer(
        "Nechta obunachida avtomatik o'chirilsin? (0 — cheksiz, hech qachon o'chmaydi):"
    )


@admin_router.message(MandatoryChannelAdd.waiting_threshold)
async def maj_add_threshold(message: Message, state: FSMContext):
    try:
        threshold = int(message.text.strip())
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting:")
        return
    data = await state.get_data()
    add_mandatory_channel(data["chat_id"], data["link"], data["title"], threshold)
    await state.clear()
    await message.answer("✅ Majburiy obuna kanali qo'shildi.", reply_markup=admin_menu_kb())


@admin_router.callback_query(F.data.startswith("maj_del:"))
async def maj_del(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    ch_id = int(call.data.split(":", 1)[1])
    remove_mandatory_channel(ch_id)
    await call.answer("O'chirildi.")
    await call.message.answer("📡 Majburiy obuna kanallari:", reply_markup=mandatory_admin_kb())


@admin_router.callback_query(F.data.startswith("set:"))
async def cb_settings(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    key = call.data.split(":", 1)[1]
    await state.set_state(SettingsEdit.waiting_text)
    await state.update_data(key=key)
    await call.answer()
    await call.message.answer(f"Yangi qiymatni kiriting (joriy: {get_setting(key)}):", reply_markup=cancel_kb())


@admin_router.message(SettingsEdit.waiting_text)
async def process_settings_text(message: Message, state: FSMContext):
    data = await state.get_data()
    set_setting(data["key"], message.text.strip())
    await state.clear()
    await message.answer("✅ Yangilandi.", reply_markup=admin_menu_kb())


@admin_router.message(F.text == "📢 ADS")
async def ads_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "📢 <b>Reklamalar (ADS)</b>\n\n"
        "📢 HAMMAGA (doimiy) va 👤 ODDIYLARGA — kino topilgandan keyin FAQAT "
        "oddiy (VIP/PRO tarifi bo'lmagan yoki muddati tugagan) foydalanuvchiga yuboriladi.\n"
        "⭐️ Faol VIP va 💎 faol PRO obunachilarga — reklama umuman chiqmaydi. "
        "Obunasi tugagan zahoti (avtomatik) yana reklama ko'rina boshlaydi.\n"
        "⭐️ VIP REKLAMA / 💎 PRO REKLAMA — hozircha avtomatik yuborilmaydi, "
        "kelajakda kerak bo'lsa ishlatish uchun tayyor turadi.\n"
        "🎬 KOD KANALGA — kod kanaliga o'zingiz xohlagan vaqtda \"📤 Hozir joylash\" "
        "tugmasi orqali joylanadi.\n\n"
        "✅ — sozlangan, ⬜️ — hali bo'sh.",
        reply_markup=ads_kb(),
    )


@admin_router.callback_query(F.data.startswith("ad_edit:"))
async def ad_edit_open(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    slot = call.data.split(":", 1)[1]
    if slot not in AD_SLOTS:
        await call.answer()
        return
    ad = get_ad(slot)
    await state.set_state(AdEdit.waiting_content)
    await state.update_data(slot=slot)
    await call.answer()

    if ad:
        kind = {"text": "matn", "photo": "rasm", "video": "video"}.get(ad["content_type"], ad["content_type"])
        info = f"turi: {kind}\nmatn: {ad['text'] or '-'}\ntugma: {ad['btn_text'] or '-'}\nlink: {ad['btn_url'] or '-'}"
        actions = [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"ad_delete:{slot}", style="danger")]
        if slot == "kod_kanal":
            actions.append(InlineKeyboardButton(text="📤 Hozir joylash", callback_data=f"ad_post_now:{slot}", style="primary"))
        await call.message.answer(
            f"{AD_SLOTS[slot]}\n\nJoriy holat:\n{info}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[actions]),
        )
    else:
        await call.message.answer(f"{AD_SLOTS[slot]}\n\nHozircha sozlanmagan.")

    await call.message.answer(
        "Yangi reklama uchun MATN, RASM (izoh bilan) yoki VIDEO (izoh bilan) yuboring:",
        reply_markup=cancel_kb(),
    )


@admin_router.callback_query(F.data.startswith("ad_delete:"))
async def ad_delete_cb(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    slot = call.data.split(":", 1)[1]
    clear_ad(slot)
    await call.answer("O'chirildi.")
    await call.message.answer(f"🗑 {AD_SLOTS.get(slot, slot)} reklamasi o'chirildi.", reply_markup=admin_menu_kb())


@admin_router.callback_query(F.data.startswith("ad_post_now:"))
async def ad_post_now_cb(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    slot = call.data.split(":", 1)[1]
    ad = get_ad(slot)
    if not ad:
        await call.answer("Reklama topilmadi.", show_alert=True)
        return
    target = CODES_CHANNEL_ID if slot == "kod_kanal" else None
    if not target:
        await call.answer("Bu reklama uchun kanal belgilanmagan.", show_alert=True)
        return
    ok = await deliver_ad(target, ad)
    await call.answer("✅ Kanalga joylandi." if ok else "⚠️ Joylab bo'lmadi.", show_alert=True)


@admin_router.message(AdEdit.waiting_content)
async def ad_edit_content(message: Message, state: FSMContext):
    data = await state.get_data()
    slot = data["slot"]
    content_type = None
    text = None
    file_id = None
    if message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
        text = message.caption or ""
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
        text = message.caption or ""
    elif message.text:
        content_type = "text"
        text = message.text.strip()
    else:
        await message.answer("Iltimos, matn, rasm yoki video yuboring:")
        return
    await state.update_data(content_type=content_type, text=text, file_id=file_id)
    await state.set_state(AdEdit.waiting_btn_text)
    await message.answer(
        "✅ Kontent qabul qilindi.\n\n"
        "Endi tugma matnini yuboring (masalan: \"👇 Obuna bo'lish\").\n"
        "Tugma kerak bo'lmasa — \"⏭ OʻTKAZIB YUBORISH\" tugmasini bosing:",
        reply_markup=skip_kb(),
    )


@admin_router.message(AdEdit.waiting_btn_text)
async def ad_edit_btn_text(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text in MENU_LABELS["skip"].values():
        set_ad(data["slot"], data["content_type"], data["text"], data["file_id"], "", "")
        await state.clear()
        await message.answer(f"✅ {AD_SLOTS.get(data['slot'])} saqlandi (tugmasiz).", reply_markup=admin_menu_kb())
        return
    if not message.text:
        await message.answer("Iltimos, faqat matn yuboring:")
        return
    await state.update_data(btn_text=message.text.strip())
    await state.set_state(AdEdit.waiting_url)
    await message.answer(
        "Endi tugma bosilganda ochiladigan LINKni yuboring (https://... yoki https://t.me/...):",
        reply_markup=cancel_kb(),
    )


@admin_router.message(AdEdit.waiting_url)
async def ad_edit_url(message: Message, state: FSMContext):
    url = (message.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("⚠️ Link \"http://\" yoki \"https://\" bilan boshlanishi kerak. Qaytadan yuboring:")
        return
    data = await state.get_data()
    set_ad(data["slot"], data["content_type"], data["text"], data["file_id"], data["btn_text"], url)
    await state.clear()
    await message.answer(f"✅ {AD_SLOTS.get(data['slot'])} saqlandi (tugma bilan).", reply_markup=admin_menu_kb())


@admin_router.message(F.text == "📥 Arizalar")
async def list_applications(message: Message):
    if not is_admin(message.from_user.id):
        return
    vip_apps = get_pending_applications()
    partner_apps = get_pending_partners()
    topups = get_pending_topups()
    pro_apps = get_pending_tier_applications("pro")

    if not vip_apps and not partner_apps and not topups and not pro_apps:
        await message.answer("Hozircha kutilayotgan arizalar yo'q.")
        return

    for a in vip_apps:
        text = (
            f"⭐️ VIP ariza #{a['id']}\n"
            f"👤 {a['full_name']}\n📞 {a['phone']}\n🎂 {a['birthdate']}\n"
            f"🆔 {a['telegram_id']}"
        )
        await message.answer(text, reply_markup=application_decision_kb(a["id"]))

    for a in pro_apps:
        text = f"💎 PRO ariza #{a['id']}\n🆔 {a['telegram_id']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🟢 Tasdiqlash", callback_data=f"pappr:{a['id']}", style="success"),
            InlineKeyboardButton(text="🔴 Rad etish", callback_data=f"prorej:{a['id']}", style="danger"),
        ]])
        await message.answer(text, reply_markup=kb)

    for p in partner_apps:
        text = (
            f"🤝 Hamkorlik arizasi #{p['id']}\n"
            f"🆔 {p['telegram_id']}\n🔗 {p['channel_link']}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🟢 Tasdiqlash", callback_data=f"papr:{p['id']}", style="success"),
            InlineKeyboardButton(text="🔴 Rad etish", callback_data=f"prej:{p['id']}", style="danger"),
        ]])
        await message.answer(text, reply_markup=kb)

    for t in topups:
        caption = (
            f"💳 Hisob to'ldirish #{t['id']}\n"
            f"🆔 {t['telegram_id']}\n💵 {t['amount']} so'm"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🟢 Tasdiqlash", callback_data=f"tapr:{t['id']}", style="success"),
            InlineKeyboardButton(text="🔴 Rad etish", callback_data=f"trej:{t['id']}", style="danger"),
        ]])
        if t["receipt_file_id"]:
            await message.answer_photo(t["receipt_file_id"], caption=caption, reply_markup=kb)
        else:
            await message.answer(caption, reply_markup=kb)


@admin_router.callback_query(F.data.in_(["admin_add", "admin_del"]))
async def cb_admin_manage(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    await state.update_data(action=call.data)
    await state.set_state(AdminManage.waiting_admin_id)
    await call.answer()
    await call.message.answer("Foydalanuvchi ID raqamini kiriting:", reply_markup=cancel_kb())


@admin_router.message(AdminManage.waiting_admin_id)
async def process_admin_manage(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("Noto'g'ri ID. Raqam kiriting:")
        return
    if data["action"] == "admin_add":
        add_admin(uid)
        log_admin_action(message.from_user.id, "Admin qo'shdi", str(uid))
        await message.answer(f"✅ {uid} admin qilib qo'shildi.", reply_markup=admin_menu_kb())
    else:
        remove_admin(uid)
        log_admin_action(message.from_user.id, "Adminlikdan olib tashladi", str(uid))
        await message.answer(f"✅ {uid} adminlikdan olib tashlandi.", reply_markup=admin_menu_kb())
    await state.clear()


# ============================================================
# TUSHUM (admin: qancha to'lov tushgani)
# ============================================================

@admin_router.message(F.text == "📈 Tushum")
async def admin_revenue_view(message: Message):
    if not is_admin(message.from_user.id):
        return
    total = get_revenue_total()
    breakdown = get_revenue_breakdown()
    recent = get_recent_revenue(10)

    lines = [f"📊 <b>Umumiy tushum: {total} so'm</b>\n"]
    if breakdown:
        lines.append("📂 <b>Manbalar bo'yicha:</b>")
        source_names = {
            "topup": "💳 Hisob to'ldirish",
            "reklama": "📢 Reklama",
            "hamkorlik": "🤝 Hamkorlik",
            "vip": "⭐️ VIP",
        }
        for b in breakdown:
            name = source_names.get(b["source"], b["source"])
            lines.append(f"• {name}: {b['total']} so'm ({b['cnt']} ta to'lov)")
        lines.append("")
    if recent:
        lines.append("🕐 <b>So'nggi to'lovlar:</b>")
        for r in recent:
            lines.append(f"• {r['amount']} so'm — {r['note'] or r['source']} (ID: {r['telegram_id']})")
    else:
        lines.append("Hozircha hech qanday to'lov qayd etilmagan.")

    await message.answer("\n".join(lines))


@admin_router.message(F.text == "📊 Statistika")
async def admin_statistika_view(message: Message):
    if not is_admin(message.from_user.id):
        return
    top10 = stats_top10()
    top_text = "\n".join(
        f"{i+1}. {m['name']} — {m['views']} ko'rish ({m['code']})"
        for i, m in enumerate(top10)
    ) or "—"
    active_vip = len(list_active_memberships("vip"))
    active_pro = len(list_active_memberships("pro"))
    active_hamkor = len(list_active_memberships("hamkor"))
    text = (
        f"📈 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {stats_users_count()}\n"
        f"🎬 Jami kinolar: {stats_movies_count()}\n\n"
        f"⭐️ Faol VIP: {active_vip}\n"
        f"💎 Faol PRO: {active_pro}\n"
        f"🤝 Faol Hamkor: {active_hamkor}\n\n"
        f"🏆 <b>TOP 10 ko'rilgan:</b>\n{top_text}"
    )
    await message.answer(text)


@admin_router.message(F.text == "🧾 Admin logi")
async def admin_logs_view(message: Message):
    if not is_admin(message.from_user.id):
        return
    logs = get_recent_admin_logs(20)
    if not logs:
        await message.answer("Hozircha loglar yo'q.")
        return
    lines = [
        f"🕐 {l['created_at'][:16].replace('T', ' ')} — 👤{l['admin_id']} — {l['action']}"
        + (f" ({l['detail']})" if l["detail"] else "")
        for l in logs
    ]
    await message.answer("🧾 <b>So'nggi admin harakatlari:</b>\n\n" + "\n".join(lines))


# ============================================================
# HAMKORLAR RO'YXATI (admin: taqiqlash / ruxsat berish / o'chirish)
# ============================================================

def partner_row_kb(p) -> InlineKeyboardMarkup:
    row = []
    if p["status"] == "approved":
        if p["banned"]:
            row.append(InlineKeyboardButton(text="🟢 Ruxsat berish", callback_data=f"phb_un:{p['id']}", style="success"))
        else:
            row.append(InlineKeyboardButton(text="🔴 Taqiqlash", callback_data=f"phb_ban:{p['id']}", style="danger"))
    row.append(InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"phb_del:{p['id']}", style="danger"))

    def toggle_btn(flag_key, on_label, off_label):
        on = p[flag_key]
        text = f"🟢 {on_label}" if on else f"🔴 {off_label}"
        style = "success" if on else "danger"
        return InlineKeyboardButton(text=text, callback_data=f"pperm:{flag_key}:{p['id']}", style=style)

    perm_rows = [
        [toggle_btn("can_upload", "Kino yuklash: yoqilgan", "Kino yuklash: o'chirilgan")],
        [toggle_btn("can_upload_vip", "VIP kino yuklash: yoqilgan", "VIP kino yuklash: o'chirilgan")],
        [toggle_btn("can_upload_pro", "PRO kino yuklash: yoqilgan", "PRO kino yuklash: o'chirilgan")],
        [toggle_btn("can_send_ads", "Reklama yuborish: yoqilgan", "Reklama yuborish: o'chirilgan")],
        [toggle_btn("bypass_majburiy", "Majburiy obunadan ozod: ha", "Majburiy obunadan ozod: yo'q")],
        [toggle_btn("can_view_stats", "Statistika: yoqilgan", "Statistika: o'chirilgan")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row] + perm_rows)


@admin_router.callback_query(F.data.startswith("pperm:"))
async def cb_partner_toggle_perm(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, flag_key, partner_id = call.data.split(":", 2)
    if flag_key not in ("can_upload", "can_upload_vip", "can_upload_pro", "bypass_majburiy",
                         "can_send_ads", "can_view_stats"):
        await call.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    partner_id = int(partner_id)
    p = get_partner(partner_id)
    if not p:
        await call.answer("Topilmadi.", show_alert=True)
        return
    new_value = 0 if p[flag_key] else 1
    with closing(db()) as conn, conn:
        conn.execute(f"UPDATE partners SET {flag_key}=? WHERE id=?", (new_value, partner_id))
    p = get_partner(partner_id)
    await call.answer("✅ Yangilandi.")
    await call.message.edit_reply_markup(reply_markup=partner_row_kb(p))


@admin_router.message(F.text == "📋 Ro'yxat")
async def admin_roster_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Foydalanuvchilar ro'yxati", callback_data="roster:users:0", style="primary")],
        [InlineKeyboardButton(text="🤝 Hamkorlar ro'yxati", callback_data="roster:hamkor", style="primary")],
        [InlineKeyboardButton(text="⭐️ Viplar ro'yxati", callback_data="roster:vip", style="primary")],
        [InlineKeyboardButton(text="💎 Prolar ro'yxati", callback_data="roster:pro", style="primary")],
        [InlineKeyboardButton(text="👤 Adminlar ro'yxati", callback_data="roster:admin", style="primary")],
    ])
    await message.answer("📋 Ro'yxatlardan birini tanlang:", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("roster:users:"))
async def admin_users_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    page = int(call.data.split(":", 2)[2])
    per_page = 50
    with closing(db()) as conn:
        total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        rows = conn.execute(
            "SELECT telegram_id, username, first_name FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        ).fetchall()
    if not rows:
        await call.message.answer("Foydalanuvchilar topilmadi.")
        return
    lines = []
    for r in rows:
        name = f"@{r['username']}" if r["username"] else (r["first_name"] or "Noma'lum")
        lines.append(f"{name} — {r['telegram_id']}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"roster:users:{page-1}", style="primary"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"roster:users:{page+1}", style="primary"))
    kb = InlineKeyboardMarkup(inline_keyboard=[nav]) if nav else None
    await call.message.answer(
        f"👥 Jami foydalanuvchilar: {total} ({page+1}-sahifa)\n\n" + "\n".join(lines),
        reply_markup=kb,
    )


@admin_router.callback_query(F.data == "roster:hamkor")
async def admin_partners_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    try:
        partners = list_all_partners()
    except Exception as e:
        logger.exception("Hamkorlar ro'yxatini o'qishda xato")
        await call.message.answer(f"⚠️ Hamkorlar ro'yxatini o'qishda xato: {e}")
        return
    if not partners:
        await call.message.answer("Hozircha hamkorlar yo'q.")
        return
    status_names = {"approved": "✅ Tasdiqlangan", "pending": "⏳ Kutilmoqda", "rejected": "❌ Rad etilgan"}
    await call.message.answer(f"🤝 Jami hamkorlar: {len(partners)}")
    shown = 0
    for p in partners:
        try:
            status = status_names.get(p["status"], p["status"])
            if p["status"] == "approved" and p["banned"]:
                status = "🚫 Taqiqlangan"
            movies_count = count_partner_movies(p["letter_prefix"]) if p["letter_prefix"] else 0
            text = (
                f"👤 Hamkor #{p['id']}\n"
                f"🆔 {p['telegram_id']}\n"
                f"🔗 {p['channel_link']}\n"
                f"🔠 Harf: {p['letter_prefix'] or '-'}\n"
                f"🎬 Yuklangan kinolar: {movies_count}\n"
                f"📌 Holat: {status}\n"
                f"🎯 Tarif: {membership_status_text(p['telegram_id'], 'hamkor')}"
            )
            await call.message.answer(text, reply_markup=partner_row_kb(p))
            shown += 1
        except Exception as e:
            logger.exception(f"Hamkor #{p['id']}ni ko'rsatishda xato")
            await call.message.answer(f"⚠️ Hamkor #{p['id']}ni ko'rsatib bo'lmadi: {e}")
    if shown == 0:
        await call.message.answer(
            "⚠️ Hamkorlar bazada bor, lekin birortasini ham ko'rsatib bo'lmadi. "
            "Yuqoridagi xato xabarlariga qarang."
        )


def membership_row_kb(m) -> InlineKeyboardMarkup:
    tier = m["tier"]
    tid = m["telegram_id"]
    row = []
    if m["banned"]:
        row.append(InlineKeyboardButton(text="🟢 Yoqish", callback_data=f"mhb_un:{tier}:{tid}", style="success"))
    else:
        row.append(InlineKeyboardButton(text="🔴 Taqiqlash", callback_data=f"mhb_ban:{tier}:{tid}", style="danger"))
    row.append(InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"mhb_del:{tier}:{tid}", style="danger"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


@admin_router.callback_query(F.data.startswith("mhb_ban:"))
async def cb_membership_ban(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, tier, tid = call.data.split(":", 2)
    tid = int(tid)
    set_membership_banned(tid, tier, True)
    m = get_membership(tid, tier)
    await call.answer("🚫 Taqiqlandi.")
    try:
        await call.message.edit_reply_markup(reply_markup=membership_row_kb(m))
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("mhb_un:"))
async def cb_membership_unban(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, tier, tid = call.data.split(":", 2)
    tid = int(tid)
    set_membership_banned(tid, tier, False)
    m = get_membership(tid, tier)
    await call.answer("✅ Ruxsat berildi.")
    try:
        await call.message.edit_reply_markup(reply_markup=membership_row_kb(m))
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("mhb_del:"))
async def cb_membership_delete(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, tier, tid = call.data.split(":", 2)
    tid = int(tid)
    delete_membership(tid, tier)
    await call.answer("🗑 O'chirildi.")
    try:
        await call.message.edit_text(f"🗑 {TIER_TITLES.get(tier, tier)} tarifi o'chirildi — 🆔 {tid}")
    except Exception:
        pass


@admin_router.callback_query(F.data == "roster:vip")
async def admin_vip_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    members = list_active_memberships("vip")
    if not members:
        await call.message.answer("Hozircha faol VIP obunachilar yo'q.")
        return
    await call.message.answer(f"⭐️ Faol VIP obunachilar ({len(members)}):")
    for m in members:
        status = " 🚫 (taqiqlangan)" if m["banned"] else ""
        text = (
            f"🆔 {m['telegram_id']} — {PLAN_LABELS.get(m['plan'], m['plan'])}"
            + (f" ({m['expires_at'][:10]} gacha)" if m["expires_at"] else " (♾ doimiy)")
            + status
        )
        await call.message.answer(text, reply_markup=membership_row_kb(m))


@admin_router.callback_query(F.data == "roster:pro")
async def admin_pro_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    members = list_active_memberships("pro")
    if not members:
        await call.message.answer("Hozircha faol PRO obunachilar yo'q.")
        return
    await call.message.answer(f"💎 Faol PRO obunachilar ({len(members)}):")
    for m in members:
        status = " 🚫 (taqiqlangan)" if m["banned"] else ""
        text = (
            f"🆔 {m['telegram_id']} — {PLAN_LABELS.get(m['plan'], m['plan'])}"
            + (f" ({m['expires_at'][:10]} gacha)" if m["expires_at"] else " (♾ doimiy)")
            + status
        )
        await call.message.answer(text, reply_markup=membership_row_kb(m))



@admin_router.callback_query(F.data == "roster:admin")
async def admin_admins_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    admin_ids = list_admins()
    lines = [f"🆔 {aid}" + (" 👑 (egasi)" if aid == OWNER_ID else "") for aid in admin_ids]
    kb = None
    if call.from_user.id == OWNER_ID:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admin_add", style="success")],
            [InlineKeyboardButton(text="➖ Admin o'chirish", callback_data="admin_del", style="danger")],
        ])
    await call.message.answer(f"👤 Adminlar ({len(admin_ids)}):\n\n" + "\n".join(lines), reply_markup=kb)


# ============================================================
# BONUS YARATISH — PRO / VIP / HAMKOR uchun BEPUL (hech kimga bog'lanmagan) tarif kodi
# ============================================================

@admin_router.message(F.text == "🎁 Tarif bonus kodi (VIP/PRO/Hamkor)")
async def bonus_create_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 PRO BONUS KOD", callback_data="bonuscat:pro", style="primary")],
        [InlineKeyboardButton(text="⭐️ VIP BONUS KOD", callback_data="bonuscat:vip", style="primary")],
        [InlineKeyboardButton(text="🤝 HAMKOR BONUS KOD", callback_data="bonuscat:hamkor", style="primary")],
    ])
    await message.answer(
        "Qaysi tarif uchun BEPUL (bonus) kod yaratamiz? "
        "Bu kodni istalgan foydalanuvchiga berishingiz mumkin — u \"KODNI KIRITISH\" orqali faollashtiradi:",
        reply_markup=kb,
    )


@admin_router.callback_query(F.data.startswith("bonuscat:"))
async def bonus_tier_chosen(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    tier = call.data.split(":", 1)[1]
    await call.answer()
    await call.message.answer(
        f"{TIER_TITLES.get(tier, tier)} bonus kod uchun tarifni tanlang:",
        reply_markup=tariff_plan_kb(tier, f"bonusgen:{tier}"),
    )


@admin_router.callback_query(F.data.startswith("bonusgen:"))
async def bonus_generate(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    _, tier, plan = call.data.split(":", 2)
    await call.answer()
    await state.update_data(tariff_bonus_tier=tier, tariff_bonus_plan=plan)
    await state.set_state(AdminTariffBonusGenerate.waiting_max_uses)
    await call.message.answer(
        "Bu kod necha marta ishlatilishi mumkin?\n"
        "• Bitta marta uchun: 1\n"
        "• Cheksiz (istalgancha foydalanuvchi) uchun: 0\n"
        "• Ma'lum sonli foydalanuvchi uchun: masalan 50",
        reply_markup=cancel_kb(call.from_user.id),
    )


@admin_router.message(AdminTariffBonusGenerate.waiting_max_uses)
async def process_tariff_bonus_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text.strip())
        if max_uses < 0:
            raise ValueError
    except ValueError:
        await message.answer("Iltimos, 0 yoki musbat butun son kiriting:")
        return
    data = await state.get_data()
    tier = data["tariff_bonus_tier"]
    plan = data["tariff_bonus_plan"]
    await state.clear()
    code = issue_tariff_code(tier, plan, telegram_id=None, max_uses=max_uses)
    uses_label = "♾ Cheksiz" if max_uses == 0 else f"{max_uses} marta"
    link_line = ""
    if tier in ("vip", "pro"):
        link = f"https://t.me/{BOT_USERNAME}?start={tier}code_{code}"
        link_line = f"\n🔗 Yoki to'g'ridan-to'g'ri havola:\n{link}"
    await message.answer(
        f"✅ Bonus kod yaratildi!\n\n"
        f"{TIER_TITLES.get(tier, tier)} — {PLAN_LABELS[plan]}\n"
        f"🔑 Kod: <code>{code}</code>\n🔁 Foydalanish soni: {uses_label}\n\n"
        "Bu kodni xohlagan foydalanuvchingizga bering — u mos bo'limdagi "
        f"\"KODNI KIRITISH\" tugmasi orqali faollashtiradi.{link_line}",
        reply_markup=admin_menu_kb(),
    )
    await message.answer(
        "📢 Bu kod KODLAR kanaliga yuborilsinmi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha", callback_data=f"tariffchan:{tier}:{code}", style="success"),
             InlineKeyboardButton(text="❌ Yo'q", callback_data="tariffchan_no", style="danger")],
        ]),
    )


@admin_router.callback_query(F.data == "tariffchan_no")
async def cb_tariffchan_no(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await call.answer("Bekor qilindi.")
    await call.message.delete()


@admin_router.callback_query(F.data.startswith("tariffchan:"))
async def cb_tariffchan_yes(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    _, tier, code = call.data.split(":", 2)
    row = get_tariff_code(code)
    if not row:
        await call.answer("⚠️ Kod topilmadi.", show_alert=True)
        return
    max_uses = row["max_uses"] if row["max_uses"] is not None else 1
    uses_label = "♾ Cheksiz" if max_uses == 0 else f"{max_uses} marta"
    text = (
        f"{TIER_TITLES.get(tier, tier)} <b>BONUS KOD</b>\n\n"
        f"🗓 Muddat: {PLAN_LABELS.get(row['plan'], row['plan'])}\n🔁 Foydalanish soni: {uses_label}\n\n"
        "Pastdagi tugmani bosib darhol faollashtiring!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Faollashtirish", callback_data=f"acttariff:{tier}:{code}", style="success")],
    ])
    await user_bot.send_message(CODES_CHANNEL_ID, text, reply_markup=kb)
    await call.answer("✅ Kanalga yuborildi.")
    await call.message.delete()


@user_router.callback_query(F.data.startswith("acttariff:"))
async def cb_activate_tariff(call: CallbackQuery, state: FSMContext):
    _, tier, code = call.data.split(":", 2)
    tid = call.from_user.id
    if not user_exists(tid):
        register_user(tid, call.from_user.username, call.from_user.first_name or "")
    row = redeem_tariff_code(code, tid, expected_tier=tier)
    if row == "EXPIRED":
        await call.answer("⌛ Bu kodning muddati tugagan.", show_alert=True)
        return
    if not row:
        await call.answer("⚠️ Kod topilmadi yoki foydalanish limiti tugagan.", show_alert=True)
        return
    await call.answer(f"✅ {TIER_TITLES.get(tier, tier)} tarifi faollashtirildi!", show_alert=True)
    if tier == "hamkor":
        try:
            existing = get_approved_partner_by_uid(tid)
            if existing:
                await user_bot.send_message(
                    tid,
                    f"✅ Kod qabul qilindi! Hamkorlik tarifingiz yangilandi.\n\n"
                    f"🔠 Sizning harfingiz: <b>{existing['letter_prefix'] or '-'}</b>\n"
                    f"{membership_status_text(tid, 'hamkor')}",
                )
            else:
                await user_bot.send_message(
                    tid,
                    f"✅ Kod qabul qilindi! Hamkorlik tarifi faollashtirildi.\n{membership_status_text(tid, 'hamkor')}\n\n"
                    "Endi lotin harfingizni tanlash uchun botga o'ting va \"🤝 Hamkorlik\" bo'limidan davom eting.",
                )
        except Exception:
            pass
    else:
        try:
            kb_map = {"vip": vip_menu_kb, "pro": pro_menu_kb}
            await user_bot.send_message(
                tid,
                f"✅ Kod qabul qilindi! {TIER_TITLES.get(tier, tier)} tarifi faollashtirildi "
                f"({PLAN_LABELS.get(row['plan'], row['plan'])}).\n\n{membership_status_text(tid, tier)}",
                reply_markup=kb_map.get(tier, lambda uid: None)(tid),
            )
        except Exception:
            pass


@admin_router.callback_query(F.data.startswith("phb_ban:"))
async def cb_partner_ban(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    partner_id = int(call.data.split(":", 1)[1])
    ban_partner(partner_id)
    p = get_partner(partner_id)
    log_admin_action(call.from_user.id, "Hamkorni taqiqladi", f"#{partner_id} -> {p['telegram_id'] if p else '?'}")
    await call.answer("🚫 Taqiqlandi.")
    await call.message.edit_reply_markup(reply_markup=partner_row_kb(p))
    try:
        await user_bot.send_message(
            p["telegram_id"],
            "🚫 Sizning hamkorlik huquqingiz vaqtincha taqiqlandi. Kino yuklash imkoniyatingiz o'chirildi.",
        )
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("phb_un:"))
async def cb_partner_unban(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    partner_id = int(call.data.split(":", 1)[1])
    unban_partner(partner_id)
    p = get_partner(partner_id)
    log_admin_action(call.from_user.id, "Hamkorga ruxsat berdi", f"#{partner_id} -> {p['telegram_id'] if p else '?'}")
    await call.answer("✅ Ruxsat berildi.")
    await call.message.edit_reply_markup(reply_markup=partner_row_kb(p))
    try:
        await user_bot.send_message(
            p["telegram_id"],
            "✅ Hamkorlik huquqingiz qayta tiklandi. Kino yuklashingiz mumkin.",
        )
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("phb_del:"))
async def cb_partner_delete(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    partner_id = int(call.data.split(":", 1)[1])
    partner_before = get_partner(partner_id)
    delete_partner_record(partner_id)
    log_admin_action(call.from_user.id, "Hamkorni o'chirdi", f"#{partner_id} -> {partner_before['telegram_id'] if partner_before else '?'}")
    await call.answer("🗑 O'chirildi.")
    await call.message.edit_text("🗑 Hamkor ro'yxatdan o'chirildi.")


# ============================================================
# KINOLARNI BOSHQARISH (tahrirlash / o'chirish)
# ============================================================

@admin_router.message(F.text == "🎞 KINOLARNI BOSHQARISH")
async def movie_manage_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    recent = get_recent_movies(limit=10, is_vip=0) + get_recent_movies(limit=10, is_vip=1)
    if recent:
        await message.answer(
            "Oxirgi yuklangan kinolar (yoki nom/kod bo'yicha qidiring):",
            reply_markup=movie_list_kb(recent[:15]),
        )
    await state.set_state(MovieManage.waiting_search)
    await message.answer("Kino nomi yoki kodini kiriting:", reply_markup=cancel_kb())


@admin_router.message(MovieManage.waiting_search)
async def movie_manage_search(message: Message, state: FSMContext):
    results = search_movies_any(message.text.strip())
    await state.clear()
    admin_kb_ref = admin_menu_kb()
    if not results:
        await message.answer("❌ Hech narsa topilmadi.", reply_markup=admin_kb_ref)
        return
    await message.answer("Natijalar:", reply_markup=movie_list_kb(results))
    await message.answer("Menyu:", reply_markup=admin_kb_ref)


@admin_router.callback_query(F.data.startswith("mv_open:"))
async def mv_open(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    movie_id = int(call.data.split(":", 1)[1])
    movie = get_movie_by_id(movie_id)
    if not movie:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    slots = movie_filled_slots(movie)
    lang_line = " / ".join(movie_slot_data(movie, n)["language"] or "" for n in slots)
    if len(slots) > 1:
        lang_line += f" ({len(slots)} ta video)"

    series_line = ""
    if movie["series_id"] and movie["series_id"] != movie["id"] or (movie["part_number"] or 1) > 1:
        series_line = f"\n🎞 Qism: {movie['part_number']}-qism"

    variants = get_lang_variants(movie["lang_group"] or movie["id"])
    other_variants = [v for v in variants if v["id"] != movie["id"]]
    variant_line = ""
    if other_variants:
        variant_line = "\n🌐 Boshqa til varianti: " + ", ".join(f"{v['name']} ({v['language']})" for v in other_variants)

    text = (
        f"🎬 <b>{movie['name']}</b>\n"
        f"🔑 Kod: {movie['code']}\n"
        f"🏷 Janr: {movie['genre']}\n"
        f"🌍 Davlat: {movie['country']}\n"
        f"🗣 Til: {lang_line}"
        f"{series_line}"
        f"{variant_line}\n"
        f"👁 Ko'rishlar: {movie['views']}\n"
        f"{'⭐️ VIP' if movie['is_vip'] else ''}"
    )
    await call.message.answer(text, reply_markup=movie_card_kb(movie))


@admin_router.callback_query(F.data.startswith("mv_edit:"))
async def mv_edit_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    _, movie_id_s, field = call.data.split(":", 2)
    movie = get_movie_by_id(int(movie_id_s))
    if not movie:
        await call.answer("Topilmadi.", show_alert=True)
        return

    if field == "language":
        await state.update_data(mv_movie_id=movie["id"], sel_languages=[])
        cur_slots = movie_filled_slots(movie)
        cur_langs = " / ".join(movie_slot_data(movie, n)["language"] or "" for n in cur_slots)
        await call.answer()
        await call.message.answer(
            f"🗣 Hozirgi til(lar): {cur_langs}"
            + "\n\nYangi til(lar)ni tanlang (1 dan 5 tagacha), so'ng \"Tayyor\" bosing:",
            reply_markup=select_kb(list_languages(), [], "mvlang", "l"),
        )
        return

    if field == "nextpart":
        await state.update_data(part_base_movie_id=movie["id"], part_direction="next")
        await call.answer()
        cur = ""
        if (movie["part_number"] or 1) > 1 or movie["series_id"]:
            cur = f"\n\nHozirgi qism: {movie['part_number'] or 1}-qism."
        await call.message.answer(
            f"🎬 \"{movie['name']}\" kinosining KEYINGI qismi videosini yuboring:{cur}",
            reply_markup=cancel_kb(call.from_user.id),
        )
        await state.set_state(SeriesPartUpload.waiting_video)
        return

    if field == "prevpart":
        await state.update_data(part_base_movie_id=movie["id"], part_direction="prev")
        await call.answer()
        cur = ""
        if (movie["part_number"] or 1) > 1 or movie["series_id"]:
            cur = f"\n\nHozirgi qism: {movie['part_number'] or 1}-qism."
        await call.message.answer(
            f"🎬 \"{movie['name']}\" kinosining OLDINGI qismi videosini yuboring:{cur}",
            reply_markup=cancel_kb(call.from_user.id),
        )
        await state.set_state(SeriesPartUpload.waiting_video)
        return

    if field == "joinseries":
        await state.update_data(join_movie_id=movie["id"])
        await call.answer()
        await call.message.answer(
            f"🔎 \"{movie['name']}\" qaysi kino/serialga qo'shilsin? Nomi yoki kodini kiriting:",
            reply_markup=cancel_kb(call.from_user.id),
        )
        await state.set_state(SeriesJoin.waiting_query)
        return

    if field == "langvariant":
        await state.update_data(new_movie_id=movie["id"], is_vip=movie["is_vip"])
        await call.answer()
        variants = get_lang_variants(movie["lang_group"] or movie["id"])
        other = [v for v in variants if v["id"] != movie["id"]]
        cur = ""
        if other:
            cur = "\n\nHozirgi variantlar: " + ", ".join(f"{v['name']} ({v['language']})" for v in other)
        recent = [m for m in get_recent_movies(limit=8, is_vip=movie["is_vip"]) if m["id"] != movie["id"]]
        await call.message.answer(
            f"🌐 Bu kino boshqa TIL varianti bormi (bir xil kino/qism, boshqa tilda ovozlangan)?{cur}",
            reply_markup=langlink_pick_kb(recent, "adm"),
        )
        return

    if field == "trailer":
        await state.update_data(trailer_movie_id=movie["id"])
        await state.set_state(MovieManage.waiting_trailer)
        await call.answer()
        cur = "\n\n(Hozircha treyler yo'q.)" if not movie["trailer_file_id"] else "\n\n(Joriy treyler almashtiriladi.)"
        await call.message.answer(
            f"🎞 \"{movie['name']}\" uchun treyler videoni yuboring:{cur}",
            reply_markup=cancel_kb(call.from_user.id),
        )
        return

    field_labels = {"name": "Nomi", "code": "Kodi", "genre": "Janri", "country": "Davlati"}
    await state.set_state(MovieManage.waiting_new_value)
    await state.update_data(movie_id=movie["id"], field=field)
    await call.answer()
    await call.message.answer(
        f"{field_labels[field]} uchun yangi qiymatni kiriting (joriy: {movie[field]}):",
        reply_markup=cancel_kb(),
    )


def mv_lang_video_source_kb(slot: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kinolar ichidan tanlash", callback_data=f"mvlangsrc:pick:{slot}", style="primary")],
        [InlineKeyboardButton(text="📤 Yangi video yuklash", callback_data=f"mvlangsrc:upload:{slot}", style="primary")],
    ])


async def mv_lang_ask_video_source(message: Message, state: FSMContext, slot: int, lang_name: str):
    await message.answer(
        f"\"{lang_name}\" tili uchun videoni qayerdan olamiz?",
        reply_markup=mv_lang_video_source_kb(slot),
    )


@admin_router.callback_query(F.data.startswith("mvlangsrc:"))
async def mv_lang_source_chosen(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    _, mode, slot = call.data.split(":", 2)
    slot = int(slot)
    await state.update_data(mv_slot=slot)
    await call.answer()
    if mode == "upload":
        await state.set_state(MovieLangEdit.waiting_new_video)
        await call.message.answer(f"{slot}-til uchun videoni yuboring:", reply_markup=cancel_kb())
    else:
        await state.set_state(MovieLangEdit.waiting_pick_code)
        await call.message.answer(
            f"{slot}-til uchun qaysi kino videosidan foydalanamiz? Kinoning KODINI kiriting:",
            reply_markup=cancel_kb(),
        )


async def mv_lang_after_slot_filled(message: Message, state: FSMContext):
    data = await state.get_data()
    sel = data.get("sel_languages", [])
    slot = data.get("mv_slot", 1)
    next_slot = slot + 1
    if next_slot <= len(sel):
        await mv_lang_ask_video_source(message, state, slot=next_slot, lang_name=sel[next_slot - 1])
    else:
        await mv_lang_finalize(message, state)


@admin_router.message(MovieLangEdit.waiting_new_video, F.video)
async def mv_lang_new_video(message: Message, state: FSMContext):
    data = await state.get_data()
    slot = data.get("mv_slot", 1)
    suf = _slot_suffix(slot)
    await state.update_data(**{
        f"mv_file_id{suf}": message.video.file_id,
        f"mv_chat_id{suf}": None,
        f"mv_msg_id{suf}": None,
    })
    await mv_lang_after_slot_filled(message, state)


@admin_router.message(MovieLangEdit.waiting_new_video)
async def mv_lang_new_video_invalid(message: Message):
    await message.answer("Iltimos, video fayl yuboring.")


@admin_router.message(MovieLangEdit.waiting_pick_code)
async def mv_lang_pick_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    source = get_movie_by_code(code)
    if not source:
        await message.answer("❌ Bunday kod topilmadi. Qaytadan kiriting:")
        return
    data = await state.get_data()
    slot = data.get("mv_slot", 1)
    suf = _slot_suffix(slot)
    await state.update_data(**{
        f"mv_file_id{suf}": source["file_id"],
        f"mv_chat_id{suf}": source["channel_chat_id"],
        f"mv_msg_id{suf}": source["channel_message_id"],
    })
    await mv_lang_after_slot_filled(message, state)


async def mv_lang_finalize(message: Message, state: FSMContext):
    data = await state.get_data()
    movie_id = data["mv_movie_id"]
    sel = data.get("sel_languages", [])
    set_parts = []
    params = []
    for n in LANG_SLOT_NUMS:
        suf = _slot_suffix(n)
        if n <= len(sel):
            lang_val = sel[n - 1]
            file_val = data.get(f"mv_file_id{suf}")
            chat_val = data.get(f"mv_chat_id{suf}")
            msg_val = data.get(f"mv_msg_id{suf}")
        else:
            lang_val = "" if n == 1 else None
            file_val, chat_val, msg_val = None, None, None
        set_parts += [f"language{suf}=?", f"file_id{suf}=?", f"channel_chat_id{suf}=?", f"channel_message_id{suf}=?"]
        params += [lang_val, file_val, chat_val, msg_val]
    params.append(movie_id)
    with closing(db()) as conn, conn:
        conn.execute(f"UPDATE movies SET {', '.join(set_parts)} WHERE id=?", params)
    await state.clear()
    movie = get_movie_by_id(movie_id)
    slots = movie_filled_slots(movie)
    lang_line = " / ".join(movie_slot_data(movie, n)["language"] or "" for n in slots)
    if len(slots) > 1:
        lang_line += f" ({len(slots)} ta video)"
    await message.answer(
        f"✅ Til(lar) yangilandi: {lang_line}", reply_markup=admin_menu_kb(),
    )
    text = (
        f"🎬 <b>{movie['name']}</b>\n"
        f"🔑 Kod: {movie['code']}\n"
        f"🏷 Janr: {movie['genre']}\n"
        f"🌍 Davlat: {movie['country']}\n"
        f"🗣 Til: {lang_line}\n"
        f"👁 Ko'rishlar: {movie['views']}\n"
        f"{'⭐️ VIP' if movie['is_vip'] else ''}"
    )
    await message.answer(text, reply_markup=movie_card_kb(movie))


@admin_router.message(MovieManage.waiting_new_value)
async def mv_edit_apply(message: Message, state: FSMContext):
    data = await state.get_data()
    movie_id = data["movie_id"]
    field = data["field"]
    new_value = message.text.strip()

    if field == "code":
        new_value = new_value.upper()
        existing = get_movie_by_code(new_value)
        if existing and existing["id"] != movie_id:
            await message.answer("⚠️ Bu kod band. Boshqa kod kiriting:")
            return

    update_movie_field(movie_id, field, new_value)
    await state.clear()
    movie = get_movie_by_id(movie_id)
    await message.answer("✅ Yangilandi.", reply_markup=admin_menu_kb())
    text = (
        f"🎬 <b>{movie['name']}</b>\n"
        f"🔑 Kod: {movie['code']}\n"
        f"🏷 Janr: {movie['genre']}\n"
        f"🌍 Davlat: {movie['country']}\n"
        f"🗣 Til: {movie['language']}\n"
        f"👁 Ko'rishlar: {movie['views']}\n"
        f"{'⭐️ VIP' if movie['is_vip'] else ''}"
    )
    await message.answer(text, reply_markup=movie_card_kb(movie))


@admin_router.message(MovieManage.waiting_trailer, F.video)
async def mv_trailer_apply(message: Message, state: FSMContext):
    data = await state.get_data()
    movie_id = data.get("trailer_movie_id")
    if not movie_id:
        await state.clear()
        return
    update_movie_field(movie_id, "trailer_file_id", message.video.file_id)
    await state.clear()
    movie = get_movie_by_id(movie_id)
    await message.answer("✅ Treyler saqlandi.", reply_markup=admin_menu_kb())
    await message.answer(f"🎬 <b>{movie['name']}</b> uchun treyler yangilandi.", reply_markup=movie_card_kb(movie))


@admin_router.message(MovieManage.waiting_trailer)
async def mv_trailer_invalid(message: Message):
    await message.answer("Iltimos, treyler uchun video fayl yuboring.")


@admin_router.callback_query(F.data.startswith("mv_del:"))
async def mv_del_confirm(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    movie_id = int(call.data.split(":", 1)[1])
    movie = get_movie_by_id(movie_id)
    if not movie:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔴 Ha, o'chirish", callback_data=f"mv_delyes:{movie_id}", style="danger"),
        InlineKeyboardButton(text="⚪️ Bekor qilish", callback_data=f"mv_delno:{movie_id}", style="primary"),
    ]])
    await call.message.answer(
        f"⚠️ \"{movie['name']}\" ({movie['code']}) rostdan ham o'chirilsinmi?\n"
        "Bu amalni orqaga qaytarib bo'lmaydi.",
        reply_markup=kb,
    )


@admin_router.callback_query(F.data.startswith("mv_delyes:"))
async def mv_del_yes(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    movie_id = int(call.data.split(":", 1)[1])
    movie = get_movie_by_id(movie_id)
    if not movie:
        await call.answer("Allaqachon o'chirilgan.", show_alert=True)
        return

    if movie["channel_chat_id"] and movie["channel_message_id"]:
        try:
            await user_bot.delete_message(movie["channel_chat_id"], movie["channel_message_id"])
        except Exception as e:
            logger.warning(f"Kanaldagi postni o'chirib bo'lmadi: {e}")

    delete_movie(movie_id)
    log_admin_action(call.from_user.id, "Kino o'chirdi", f"{movie['name']} ({movie['code']})")
    await call.answer("🗑 O'chirildi.")
    await call.message.edit_text(f"🗑 \"{movie['name']}\" ({movie['code']}) o'chirildi.")


@admin_router.callback_query(F.data.startswith("mv_delno:"))
async def mv_del_no(call: CallbackQuery):
    await call.answer("Bekor qilindi.")
    await call.message.edit_text("Bekor qilindi — kino o'chirilmadi.")


# ============================================================
# REKLAMA TARQATISH (admin: barcha foydalanuvchilarga xabar yuborish)
# ============================================================

@admin_router.message(F.text == "📣 REKLAMA TARQATISH")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastMsg.waiting_content)
    await message.answer(
        "📣 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring "
        "(matn, rasm, video — istalgani bo'lishi mumkin):",
        reply_markup=cancel_kb(),
    )


@admin_router.message(BroadcastMsg.waiting_content)
async def broadcast_send(message: Message, state: FSMContext):
    await state.clear()
    user_ids = get_all_user_ids()
    await message.answer(f"📤 Yuborilmoqda... Jami: {len(user_ids)} foydalanuvchi.")

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await user_bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Reklama yuborilmadi {uid}: {e}")
        await asyncio.sleep(0.05)  # Telegram flood-limitiga tushmaslik uchun

    await message.answer(
        f"✅ Tarqatish tugadi.\n📬 Yuborildi: {sent}\n⚠️ Yuborilmadi: {failed}",
        reply_markup=admin_menu_kb(),
    )


# ============================================================
# CHAT BOT (admin <-> foydalanuvchi yozishmasi)
# ============================================================

@admin_router.message(btn("chatbot"))
async def admin_chatbot_entry(message: Message):
    """Admin bot tomonida: 'chatbot' tugmasi yozishmalar ro'yxatini ochadi."""
    if not is_admin(message.from_user.id):
        return
    threads = list_chat_threads()
    if not threads:
        await message.answer("Hozircha hech kim yozmagan.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{t['full_name'] or t['username'] or t['telegram_id']}",
            callback_data=f"chat_open:{t['telegram_id']}",
        style="primary")]
        for t in threads
    ])
    await message.answer("💬 Yozishmalar:", reply_markup=kb)


@user_router.message(btn("chatbot"))
async def user_chatbot_entry(message: Message, state: FSMContext):
    """Oddiy bot tomonida: 'chatbot' tugmasi foydalanuvchini chat rejimiga o'tkazadi."""
    await state.set_state(ChatSession.active)
    await message.answer(
        "💬 Admin bilan chat rejimidasiz. Xabaringizni yozing.\n"
        "Chiqish uchun \"⬅️ ODDIY REJIMGA QAYTISH\" tugmasini bosing.",
        reply_markup=chat_kb(message.from_user.id),
    )


@user_router.message(ChatSession.active)
async def chat_user_message(message: Message, state: FSMContext):
    if message.text in MENU_LABELS["back_normal"].values():
        await state.clear()
        await message.answer("Oddiy menyu.", reply_markup=user_menu_kb(message.from_user.id))
        return
    if not message.text:
        await message.answer("Faqat matnli xabar yuboring.")
        return
    touch_chat_thread(message.from_user.id, message.from_user.username or "", message.from_user.full_name or "")
    add_chat_message(message.from_user.id, "user", message.text)
    with closing(db()) as conn:
        admin_ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM admins")]
    text = (
        f"💬 <b>{message.from_user.full_name}</b> (@{message.from_user.username or '-'}, "
        f"{message.from_user.id}):\n{message.text}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Javob yozish", callback_data=f"chat_reply:{message.from_user.id}", style="primary")
    ]])
    for aid in admin_ids:
        try:
            await admin_bot.send_message(aid, text, reply_markup=kb)
        except Exception as e:
            logger.warning(f"Adminga chat xabari yuborilmadi {aid}: {e}")
    await message.answer("✅ Yuborildi.")


@admin_router.callback_query(F.data.startswith("chat_open:"))
async def chat_open(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    uid = int(call.data.split(":", 1)[1])
    history = get_chat_history(uid)
    if not history:
        text = "Xabarlar yo'q."
    else:
        lines = []
        for h in history:
            who = "👤 Foydalanuvchi" if h["sender"] == "user" else "👨‍💼 Admin"
            lines.append(f"{who}: {h['text']}")
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✍️ Yozish", callback_data=f"chat_reply:{uid}", style="primary")
    ]])
    await call.answer()
    await call.message.answer(text, reply_markup=kb)


@admin_router.callback_query(F.data.startswith("chat_reply:"))
async def chat_reply_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    uid = int(call.data.split(":", 1)[1])
    await state.set_state(AdminChatReply.waiting_text)
    await state.update_data(uid=uid)
    await call.answer()
    await call.message.answer("Javobingizni yozing:", reply_markup=cancel_kb())


@admin_router.message(AdminChatReply.waiting_text)
async def chat_reply_send(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data["uid"]
    add_chat_message(uid, "admin", message.text)
    await state.clear()
    try:
        await user_bot.send_message(uid, f"👨‍💼 <b>Admin:</b>\n{message.text}")
        await message.answer("✅ Yuborildi.", reply_markup=admin_menu_kb())
    except Exception as e:
        await message.answer(f"⚠️ Yuborilmadi: {e}", reply_markup=admin_menu_kb())


# ============================================================
# TUGMASIZ KOD KIRITISH (hech qanday menyu bosilmasa ham ishlaydi)
# ============================================================

class AdminUserManage(StatesGroup):
    waiting_id = State()
    waiting_hamkor_link = State()


class ComingSoonAdd(StatesGroup):
    waiting_name = State()
    waiting_note = State()
    waiting_poster = State()


# ---------- TAVSIYA (recommendations) ----------

@user_router.message(btn("recommend"))
async def show_recommendations(message: Message):
    tid = message.from_user.id
    movies = get_recommendations(tid, limit=10)
    if not movies:
        await message.answer("Hozircha tavsiya qilish uchun kino topilmadi.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"code:{m['code']}", style="primary")]
        for m in movies
    ])
    await message.answer("🎯 Siz uchun tavsiyalar:", reply_markup=kb)


# ---------- TASODIFIY KINO ----------

@user_router.message(btn("random_movie"))
async def handle_random_movie(message: Message):
    tid = message.from_user.id
    movie = get_random_movie(tid)
    if not movie:
        await message.answer("Hozircha kinolar mavjud emas.")
        return
    await message.answer("🎲 Tasodifiy tanlangan kino:")
    await open_movie(message.chat.id, movie)


# ---------- TEZ ORADA (foydalanuvchilar uchun) ----------

@user_router.message(btn("coming_soon"))
async def show_coming_soon(message: Message):
    items = list_coming_soon()
    if not items:
        await message.answer("Hozircha 'Tez orada' ro'yxati bo'sh.")
        return
    await message.answer("📅 <b>Tez orada tomosha qilish mumkin bo'ladigan kinolar:</b>")
    for it in items:
        caption = f"🎬 <b>{it['name']}</b>"
        if it["note"]:
            caption += f"\n📝 {it['note']}"
        if it["poster_file_id"]:
            await user_bot.send_photo(message.chat.id, it["poster_file_id"], caption=caption)
        else:
            await message.answer(caption)


# ---------- TEZ ORADA (admin boshqaruvi) ----------

@admin_router.message(F.text == "📅 TEZ ORADA BOSHQARUVI")
async def admin_coming_soon_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qo'shish", callback_data="csoon:add", style="success")],
        [InlineKeyboardButton(text="📋 Ro'yxat / O'chirish", callback_data="csoon:list", style="primary")],
    ])
    await message.answer("📅 'Tez orada' bo'limini boshqarish:", reply_markup=kb)


@admin_router.callback_query(F.data == "csoon:add")
async def cb_csoon_add(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(ComingSoonAdd.waiting_name)
    await call.answer()
    await call.message.answer("Yangi kino nomini kiriting:", reply_markup=cancel_kb(call.from_user.id))


@admin_router.message(ComingSoonAdd.waiting_name)
async def csoon_name_entered(message: Message, state: FSMContext):
    await state.update_data(csoon_name=message.text.strip())
    await state.set_state(ComingSoonAdd.waiting_note)
    await message.answer(
        "Qo'shimcha izoh kiriting (masalan chiqish sanasi). Kerak bo'lmasa - (chiziqcha) yuboring:"
    )


@admin_router.message(ComingSoonAdd.waiting_note)
async def csoon_note_entered(message: Message, state: FSMContext):
    note = message.text.strip()
    if note == "-":
        note = None
    await state.update_data(csoon_note=note)
    await state.set_state(ComingSoonAdd.waiting_poster)
    await message.answer("Poster rasm yuboring (ixtiyoriy). Kerak bo'lmasa - (chiziqcha) yuboring:")


@admin_router.message(ComingSoonAdd.waiting_poster, F.photo)
async def csoon_poster_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    add_coming_soon(data["csoon_name"], data.get("csoon_note"), message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ 'Tez orada' ro'yxatiga qo'shildi.", reply_markup=admin_menu_kb())


@admin_router.message(ComingSoonAdd.waiting_poster)
async def csoon_poster_skip(message: Message, state: FSMContext):
    if message.text and message.text.strip() == "-":
        data = await state.get_data()
        add_coming_soon(data["csoon_name"], data.get("csoon_note"), None)
        await state.clear()
        await message.answer("✅ 'Tez orada' ro'yxatiga qo'shildi.", reply_markup=admin_menu_kb())
        return
    await message.answer("Iltimos, rasm yuboring yoki o'tkazib yuborish uchun - yuboring:")


@admin_router.callback_query(F.data == "csoon:list")
async def cb_csoon_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    items = list_coming_soon()
    await call.answer()
    if not items:
        await call.message.answer("Ro'yxat bo'sh.")
        return
    for it in items:
        caption = f"🎬 <b>{it['name']}</b>"
        if it["note"]:
            caption += f"\n📝 {it['note']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬆️ Shu nomga video yuklash", callback_data=f"csoon_upload:{it['id']}", style="success")],
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"csoon_del:{it['id']}", style="danger")],
        ])
        if it["poster_file_id"]:
            await user_bot.send_photo(call.message.chat.id, it["poster_file_id"], caption=caption, reply_markup=kb)
        else:
            await call.message.answer(caption, reply_markup=kb)


@admin_router.callback_query(F.data.startswith("csoon_upload:"))
async def cb_csoon_upload(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    entry_id = int(call.data.split(":", 1)[1])
    entry = get_coming_soon_by_id(entry_id)
    if not entry:
        await call.answer("⚠️ Yozuv topilmadi (allaqachon o'chirilgan bo'lishi mumkin).", show_alert=True)
        return
    await state.update_data(csoon_link_id=entry_id, csoon_link_name=entry["name"])
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ VIP", callback_data="uplcat:vip", style="primary")],
        [InlineKeyboardButton(text="💎 PRO", callback_data="uplcat:pro", style="primary")],
        [InlineKeyboardButton(text="🎬 Oddiy", callback_data="uplcat:oddiy", style="primary")],
    ])
    await call.message.answer(f"🎬 \"{entry['name']}\" uchun kino qaysi toifaga yuklanadi?", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("csoon_del:"))
async def cb_csoon_delete(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    entry_id = int(call.data.split(":", 1)[1])
    delete_coming_soon(entry_id)
    await call.answer("🗑 O'chirildi.")
    try:
        await call.message.delete()
    except Exception:
        pass


# ---------- QIDIRUV TARIXI ----------

@user_router.message(btn("search_history"))
async def show_search_history(message: Message):
    tid = message.from_user.id
    rows = get_search_history(tid, limit=10)
    if not rows:
        await message.answer("Sizda hali qidiruv tarixi yo'q.")
        return
    lines = [f"🔎 {r['query']}" for r in rows]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔎 {r['query']}", callback_data=f"research:{r['query'][:20]}", style="primary")]
        for r in rows
    ])
    await message.answer("🕘 So'nggi qidiruvlaringiz:\n\n" + "\n".join(lines), reply_markup=kb)


@user_router.callback_query(F.data.startswith("research:"))
async def cb_research(call: CallbackQuery):
    query = call.data.split(":", 1)[1]
    await call.answer()
    movie = get_movie_by_code(query.upper())
    if movie and not movie["is_vip"]:
        await open_movie(call.message.chat.id, movie)
        return
    results = search_movies_by_name(query, vip=False)
    if not results:
        results = fuzzy_search_movies_by_name(query, vip=False)
    if not results:
        await call.message.answer(t("search_not_found", call.from_user.id))
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{m['name']} ({m['code']})", callback_data=f"code:{m['code']}", style="primary")]
        for m in results
    ])
    await call.message.answer("Natijalar:", reply_markup=kb)


# ---------- VIP/PRO 3 KUNLIK SINOV ----------

@user_router.message(btn("vip_trial"))
async def handle_vip_trial(message: Message):
    tid = message.from_user.id
    if not trial_available(tid, "vip"):
        await message.answer("⚠️ Siz allaqachon sinov muddatidan foydalangansiz yoki faol obunangiz bor.")
        return
    give_trial(tid, "vip")
    await message.answer(
        "🎁 Tabriklaymiz! Sizga 3 kunlik BEPUL VIP obuna faollashtirildi.",
        reply_markup=vip_menu_kb(tid),
    )


@user_router.message(btn("pro_trial"))
async def handle_pro_trial(message: Message):
    tid = message.from_user.id
    if not trial_available(tid, "pro"):
        await message.answer("⚠️ Siz allaqachon sinov muddatidan foydalangansiz yoki faol obunangiz bor.")
        return
    give_trial(tid, "pro")
    await message.answer(
        "🎁 Tabriklaymiz! Sizga 3 kunlik BEPUL PRO obuna faollashtirildi.",
        reply_markup=pro_menu_kb(tid),
    )


# ---------- ADMIN: FOYDALANUVCHI BOSHQARUVI ----------

async def show_user_manage_panel(chat_id: int, tid: int):
    with closing(db()) as conn:
        u = conn.execute("SELECT * FROM users WHERE telegram_id=?", (tid,)).fetchone()
    if not u:
        await admin_bot.send_message(chat_id, f"⚠️ {tid} — bu foydalanuvchi bazada topilmadi (hali botga /start bosmagan).")
        return
    banned = bool(u["banned"])
    name = f"@{u['username']}" if u["username"] else (u["first_name"] or "Noma'lum")
    text = (
        f"👤 <b>{name}</b>\n🆔 <code>{tid}</code>\n\n"
        f"🚦 Holat: {'🚫 Bloklangan' if banned else '✅ Faol'}\n"
        f"⭐️ VIP: {membership_status_text(tid, 'vip')}\n"
        f"💎 PRO: {membership_status_text(tid, 'pro')}\n"
        f"🤝 Hamkor: {membership_status_text(tid, 'hamkor')}"
    )
    kb_rows = [
        [InlineKeyboardButton(
            text=("✅ Blokdan chiqarish" if banned else "🚫 Bloklash"),
            callback_data=f"umanage:{'unban' if banned else 'ban'}:{tid}",
            style=("success" if banned else "danger"),
        )],
        [InlineKeyboardButton(text="⭐️ VIP qilish", callback_data=f"umanage:vip:{tid}", style="primary"),
         InlineKeyboardButton(text="💎 PRO qilish", callback_data=f"umanage:pro:{tid}", style="primary")],
        [InlineKeyboardButton(text="🤝 Hamkor qilish", callback_data=f"umanage:hamkor:{tid}", style="primary")],
    ]
    await admin_bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@admin_router.message(F.text == "👤 FOYDALANUVCHI BOSHQARUVI")
async def admin_user_manage_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminUserManage.waiting_id)
    await message.answer("Foydalanuvchi Telegram ID raqamini kiriting:", reply_markup=cancel_kb())


@admin_router.message(AdminUserManage.waiting_id)
async def admin_user_manage_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        tid = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Iltimos, to'g'ri Telegram ID (faqat raqam) kiriting:")
        return
    await state.clear()
    await message.answer("🛠 Admin panel:", reply_markup=admin_menu_kb())
    await show_user_manage_panel(message.chat.id, tid)


@admin_router.callback_query(F.data.startswith("umanage:ban:"))
async def cb_umanage_ban(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    tid = int(call.data.split(":", 2)[2])
    set_user_banned(tid, True)
    await call.answer("🚫 Bloklandi.")
    await show_user_manage_panel(call.message.chat.id, tid)
    try:
        await user_bot.send_message(tid, "🚫 Sizga botdan foydalanish vaqtincha taqiqlandi.")
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("umanage:unban:"))
async def cb_umanage_unban(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    tid = int(call.data.split(":", 2)[2])
    set_user_banned(tid, False)
    await call.answer("✅ Blokdan chiqarildi.")
    await show_user_manage_panel(call.message.chat.id, tid)
    try:
        await user_bot.send_message(tid, "✅ Sizga botdan foydalanish uchun ruxsat qayta berildi.")
    except Exception:
        pass


def umanage_plan_kb(tier: str, tid: int) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=PLAN_LABELS[plan], callback_data=f"umanagedo:{tier}:{tid}:{plan}", style="primary")]
          for plan in TIER_PLANS[tier]]
    return InlineKeyboardMarkup(inline_keyboard=kb)


@admin_router.callback_query(F.data.startswith("umanage:vip:"))
async def cb_umanage_vip_pick(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    tid = int(call.data.split(":", 2)[2])
    await call.answer()
    await call.message.answer("⭐️ VIP muddatini tanlang:", reply_markup=umanage_plan_kb("vip", tid))


@admin_router.callback_query(F.data.startswith("umanage:pro:"))
async def cb_umanage_pro_pick(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    tid = int(call.data.split(":", 2)[2])
    await call.answer()
    await call.message.answer("💎 PRO muddatini tanlang:", reply_markup=umanage_plan_kb("pro", tid))


@admin_router.callback_query(F.data.startswith("umanagedo:"))
async def cb_umanage_do(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    _, tier, tid_s, plan = call.data.split(":", 3)
    tid = int(tid_s)
    code = issue_and_activate_code(tier, plan, tid)
    await call.answer("✅ Bajarildi.")
    await call.message.answer(
        f"✅ {TIER_TITLES.get(tier, tier)} ({PLAN_LABELS.get(plan, plan)}) {tid} uchun faollashtirildi.\n"
        f"🔑 Kod: <code>{code}</code>"
    )
    try:
        await user_bot.send_message(
            tid,
            f"🎉 Administrator sizga {TIER_TITLES.get(tier, tier)} ({PLAN_LABELS.get(plan, plan)}) obunasini "
            f"faollashtirdi!\n🔑 Kodingiz: <code>{code}</code>",
        )
    except Exception:
        pass
    await show_user_manage_panel(call.message.chat.id, tid)


@admin_router.callback_query(F.data.startswith("umanage:hamkor:"))
async def cb_umanage_hamkor(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    tid = int(call.data.split(":", 2)[2])
    await state.update_data(hamkor_target_id=tid)
    await state.set_state(AdminUserManage.waiting_hamkor_link)
    await call.answer()
    await call.message.answer(
        f"🤝 {tid} uchun kanal havolasini kiriting (hamkor sifatida darhol tasdiqlanadi):",
        reply_markup=cancel_kb(),
    )


@admin_router.message(AdminUserManage.waiting_hamkor_link)
async def admin_make_hamkor(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    tid = data.get("hamkor_target_id")
    link = message.text.strip()
    await state.clear()
    partner_id = create_partner_application(tid, link)
    letter = next_available_partner_letter()
    approve_partner(partner_id, letter)
    code = issue_and_activate_code("hamkor", "12m", tid)
    await message.answer(
        f"✅ {tid} hamkor sifatida tasdiqlandi. Harf: {letter}\n🔑 Kod: <code>{code}</code>",
        reply_markup=admin_menu_kb(),
    )
    try:
        await user_bot.send_message(
            tid,
            f"🎉 Siz hamkor sifatida tasdiqlandingiz! Harfingiz: {letter}\n🔑 Kodingiz: <code>{code}</code>",
        )
    except Exception:
        pass


# ---------- KENGAYTIRILGAN STATISTIKA ----------

@admin_router.message(F.text == "📊 Kengaytirilgan statistika")
async def admin_extended_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    s = stats_extended()
    text = (
        f"📊 <b>Kengaytirilgan statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {s['total_users']}\n"
        f"🆕 Bugun qo'shilgan: {s['new_today']}\n"
        f"🆕 Shu hafta qo'shilgan: {s['new_week']}\n"
        f"🚫 Bloklangan foydalanuvchilar: {s['banned_users']}\n\n"
        f"🎬 Jami kinolar: {s['total_movies']}\n"
        f"🎬 Bugun qo'shilgan kinolar: {s['movies_today']}\n"
        f"🎬 Shu hafta qo'shilgan kinolar: {s['movies_week']}\n\n"
        f"⭐️ Faol VIP: {s['active_vip']}\n"
        f"💎 Faol PRO: {s['active_pro']}\n"
        f"🤝 Faol Hamkor: {s['active_hamkor']}\n\n"
        f"🎁 VIP sinovdan foydalanganlar: {s['vip_trials']}\n"
        f"🎁 PRO sinovdan foydalanganlar: {s['pro_trials']}\n\n"
        f"🔎 Jami qidiruvlar: {s['total_searches']}\n"
        f"💰 Jami tushum: {s['total_revenue']} so'm"
    )
    await message.answer(text)


# ---------- PUSH XABARLAR SOZLAMALARI ----------

def push_settings_kb() -> InlineKeyboardMarkup:
    daily_on = get_setting("daily_push_enabled") == "1"
    weekly_on = get_setting("weekly_push_enabled") == "1"
    hour = get_setting("push_hour") or "10"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📅 Kunlik push: {'✅ Yoqilgan' if daily_on else '❌ O\'chirilgan'}",
            callback_data="pushcfg:daily", style="primary")],
        [InlineKeyboardButton(
            text=f"🗓 Haftalik push: {'✅ Yoqilgan' if weekly_on else '❌ O\'chirilgan'}",
            callback_data="pushcfg:weekly", style="primary")],
        [InlineKeyboardButton(text=f"⏰ Yuborish soati: {hour}:00", callback_data="pushcfg:hour", style="primary")],
    ])


@admin_router.message(F.text == "📬 Push xabarlar")
async def admin_push_settings(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "📬 Kunlik/haftalik avtomatik yangi kinolar haqida push xabar sozlamalari:",
        reply_markup=push_settings_kb(),
    )


@admin_router.callback_query(F.data == "pushcfg:daily")
async def cb_pushcfg_daily(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    cur = get_setting("daily_push_enabled") == "1"
    set_setting("daily_push_enabled", "0" if cur else "1")
    await call.answer("✅ Yangilandi.")
    await call.message.edit_reply_markup(reply_markup=push_settings_kb())


@admin_router.callback_query(F.data == "pushcfg:weekly")
async def cb_pushcfg_weekly(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    cur = get_setting("weekly_push_enabled") == "1"
    set_setting("weekly_push_enabled", "0" if cur else "1")
    await call.answer("✅ Yangilandi.")
    await call.message.edit_reply_markup(reply_markup=push_settings_kb())


class PushHourEdit(StatesGroup):
    waiting_hour = State()


@admin_router.callback_query(F.data == "pushcfg:hour")
async def cb_pushcfg_hour(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer()
        return
    await state.set_state(PushHourEdit.waiting_hour)
    await call.answer()
    await call.message.answer("Push xabarlar yuboriladigan soatni kiriting (0-23):", reply_markup=cancel_kb())


@admin_router.message(PushHourEdit.waiting_hour)
async def apply_push_hour(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        hour = int(message.text.strip())
        if not (0 <= hour <= 23):
            raise ValueError
    except ValueError:
        await message.answer("⚠️ 0 dan 23 gacha butun son kiriting:")
        return
    set_setting("push_hour", str(hour))
    await state.clear()
    await message.answer("✅ Saqlandi.", reply_markup=admin_menu_kb())


@user_router.message(StateFilter(None), F.text)
async def catch_plain_code(message: Message):
    """Foydalanuvchi \"🔎 KINO QIDIRISH\" tugmasini bosmasdan, to'g'ridan-to'g'ri kino kodini
    yozib yuborsa ham — bo'sh turgan (hech qanday jarayon boshlanmagan) holatda kodni tekshirib,
    topilsa kinoni ochib beradi. Bu boshqa hech qanday matn-asosidagi handlerga to'sqinlik qilmasligi
    uchun eng oxirida, faqat FSM holati bo'sh bo'lganda ishlaydi."""
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return
    # Agar bu matn biror menyu tugmasi bo'lsa (biror tilda), aralashmaymiz —
    # tegishli handler allaqachon yuqorida ishlab bo'lgan bo'lardi, demak bu kod emas.
    code = text.upper()
    movie = get_movie_by_code(code)
    if not movie:
        return
    await open_movie(message.chat.id, movie)



# ============================================================
# ISHGA TUSHIRISH
# ============================================================

# ============================================================
# YANGI FUNKSIYALAR: bloklash, sinov, tavsiya, qidiruv tarixi,
# kengaytirilgan statistika, flood himoyasi
# ============================================================

TIER_CHANNEL_MAP = {"vip": VIP_CHANNEL, "pro": PRO_CHANNEL}

def is_user_banned(telegram_id: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute("SELECT banned FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    return bool(row["banned"]) if row else False


def set_user_banned(telegram_id: int, banned: bool):
    with closing(db()) as conn, conn:
        conn.execute("UPDATE users SET banned=? WHERE telegram_id=?", (1 if banned else 0, telegram_id))


def log_search_history(telegram_id: int, query: str):
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO search_history (telegram_id, query, created_at) VALUES (?, ?, ?)",
            (telegram_id, query, datetime.utcnow().isoformat()),
        )
        conn.execute(
            "DELETE FROM search_history WHERE telegram_id=? AND id NOT IN "
            "(SELECT id FROM search_history WHERE telegram_id=? ORDER BY id DESC LIMIT 50)",
            (telegram_id, telegram_id),
        )


def get_search_history(telegram_id: int, limit: int = 10):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT query, created_at FROM search_history WHERE telegram_id=? ORDER BY id DESC LIMIT ?",
            (telegram_id, limit),
        ).fetchall()


def get_recommendations(telegram_id: int, limit: int = 10):
    with closing(db()) as conn:
        fav_genres = [r["genre"] for r in conn.execute(
            "SELECT DISTINCT m.genre AS genre FROM favorites f JOIN movies m ON m.id=f.movie_id "
            "WHERE f.telegram_id=? AND m.genre IS NOT NULL",
            (telegram_id,),
        )]
        rated_genres = [r["genre"] for r in conn.execute(
            "SELECT DISTINCT m.genre AS genre FROM ratings r JOIN movies m ON m.id=r.movie_id "
            "WHERE r.telegram_id=? AND r.stars>=4 AND m.genre IS NOT NULL",
            (telegram_id,),
        )]
        favorited_ids = [r["movie_id"] for r in conn.execute(
            "SELECT movie_id FROM favorites WHERE telegram_id=?", (telegram_id,)
        )]
        genres = list({g for g in (fav_genres + rated_genres) if g})
        rows = []
        if genres:
            placeholders = ",".join("?" * len(genres))
            query = f"SELECT * FROM movies WHERE genre IN ({placeholders}) AND is_vip=0 AND is_pro=0"
            params = list(genres)
            if favorited_ids:
                query += f" AND id NOT IN ({','.join('?' * len(favorited_ids))})"
                params += favorited_ids
            query += " ORDER BY views DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT * FROM movies WHERE is_vip=0 AND is_pro=0 ORDER BY views DESC LIMIT ?", (limit,)
            ).fetchall()
        return rows


def add_coming_soon(name: str, note: str = None, poster_file_id: str = None) -> int:
    with closing(db()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO coming_soon (name, note, poster_file_id, created_at) VALUES (?, ?, ?, ?)",
            (name, note, poster_file_id, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_coming_soon_by_id(entry_id: int):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM coming_soon WHERE id=?", (entry_id,)).fetchone()


def list_coming_soon():
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM coming_soon ORDER BY id DESC").fetchall()


def delete_coming_soon(entry_id: int):
    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM coming_soon WHERE id=?", (entry_id,))


def get_random_movie(telegram_id: int):
    vip_ok = has_active_membership(telegram_id, "vip")
    pro_ok = has_active_membership(telegram_id, "pro")
    conditions = []
    if not vip_ok:
        conditions.append("is_vip=0")
    if not pro_ok:
        conditions.append("is_pro=0")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    with closing(db()) as conn:
        return conn.execute(f"SELECT * FROM movies{where} ORDER BY RANDOM() LIMIT 1").fetchone()


def trial_available(telegram_id: int, tier: str) -> bool:
    if tier not in ("vip", "pro"):
        return False
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT vip_trial_used, pro_trial_used FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
    used = bool(row[f"{tier}_trial_used"]) if row else False
    if used:
        return False
    return not has_active_membership(telegram_id, tier)


def give_trial(telegram_id: int, tier: str) -> bool:
    if not trial_available(telegram_id, tier):
        return False
    expires_at = (datetime.utcnow() + timedelta(days=3)).isoformat()
    flag_col = f"{tier}_trial_used"
    with closing(db()) as conn, conn:
        conn.execute(f"UPDATE users SET {flag_col}=1 WHERE telegram_id=?", (telegram_id,))
        conn.execute(
            "INSERT INTO memberships (telegram_id, tier, plan, expires_at, reminded) VALUES (?, ?, 'trial', ?, 0) "
            "ON CONFLICT(telegram_id, tier) DO UPDATE SET plan=excluded.plan, expires_at=excluded.expires_at, reminded=0",
            (telegram_id, tier, expires_at),
        )
    return True


def stats_extended() -> dict:
    with closing(db()) as conn:
        total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        banned_users = conn.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"]
        vip_trials = conn.execute("SELECT COUNT(*) c FROM users WHERE vip_trial_used=1").fetchone()["c"]
        pro_trials = conn.execute("SELECT COUNT(*) c FROM users WHERE pro_trial_used=1").fetchone()["c"]
        total_movies = conn.execute("SELECT COUNT(*) c FROM movies").fetchone()["c"]
        total_searches = conn.execute("SELECT COUNT(*) c FROM search_history").fetchone()["c"]

        today_str = datetime.utcnow().date().isoformat()
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

        new_today = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE joined_at LIKE ?", (f"{today_str}%",)
        ).fetchone()["c"]
        new_week = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE joined_at >= ?", (week_ago,)
        ).fetchone()["c"]
        movies_today = conn.execute(
            "SELECT COUNT(*) c FROM movies WHERE created_at LIKE ?", (f"{today_str}%",)
        ).fetchone()["c"]
        movies_week = conn.execute(
            "SELECT COUNT(*) c FROM movies WHERE created_at >= ?", (week_ago,)
        ).fetchone()["c"]
        total_revenue = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM revenue").fetchone()["s"]

    return {
        "total_users": total_users,
        "banned_users": banned_users,
        "vip_trials": vip_trials,
        "pro_trials": pro_trials,
        "total_movies": total_movies,
        "total_searches": total_searches,
        "new_today": new_today,
        "new_week": new_week,
        "movies_today": movies_today,
        "movies_week": movies_week,
        "active_vip": len(list_active_memberships("vip")),
        "active_pro": len(list_active_memberships("pro")),
        "active_hamkor": len(list_active_memberships("hamkor")),
        "total_revenue": total_revenue,
    }


# ---------- Flood himoyasi (oddiy in-memory darcha oynasi) ----------

_flood_history: dict = {}
_flood_warn_cooldown: dict = {}
FLOOD_MAX_MESSAGES = 6
FLOOD_WINDOW_SECONDS = 3.0
FLOOD_WARN_COOLDOWN_SECONDS = 10.0


def check_flood(telegram_id: int) -> bool:
    """True qaytarsa — bu foydalanuvchi hozir flood qilyapti, xabar e'tiborsiz qoldirilishi kerak."""
    now = time.time()
    hist = _flood_history.setdefault(telegram_id, [])
    hist.append(now)
    cutoff = now - FLOOD_WINDOW_SECONDS
    while hist and hist[0] < cutoff:
        hist.pop(0)
    return len(hist) > FLOOD_MAX_MESSAGES


async def ban_and_flood_middleware(handler, event: Message, data):
    tid = event.from_user.id if event.from_user else None
    if tid and not is_admin(tid):
        if is_user_banned(tid):
            return
        if check_flood(tid):
            now = time.time()
            warned_until = _flood_warn_cooldown.get(tid, 0)
            if now > warned_until:
                _flood_warn_cooldown[tid] = now + FLOOD_WARN_COOLDOWN_SECONDS
                try:
                    await event.answer("⚠️ Juda tez-tez xabar yuboryapsiz. Iltimos, biroz kutib qayta urinib ko'ring.")
                except Exception:
                    pass
            return
    return await handler(event, data)


# Ban/flood himoyasi ikkala botga ham ulanadi (admin uchun is_admin() tekshiruvi
# tufayli baribir chetlab o'tiladi, lekin agar admin bot havolasi tasodifan
# oddiy foydalanuvchi qo'liga tushib qolsa ham himoya ishlab turadi).
user_router.message.outer_middleware()(ban_and_flood_middleware)
admin_router.message.outer_middleware()(ban_and_flood_middleware)


async def expiry_reminder_loop():
    """Muddati 24 soatdan kam qolgan VIP/PRO/Hamkor obunachilarga bir martalik eslatma yuboradi."""
    while True:
        try:
            for m in get_memberships_needing_reminder(hours_ahead=24):
                tier = m["tier"]
                text = (
                    f"⏰ Diqqat! Sizning {TIER_TITLES.get(tier, tier)} obunangiz "
                    f"muddati tez orada ({m['expires_at'][:16].replace('T', ' ')}) tugaydi.\n"
                    "Muddatni uzaytirish uchun tegishli bo'limga o'ting."
                )
                try:
                    await user_bot.send_message(m["telegram_id"], text)
                except Exception as e:
                    logger.warning(f"Eslatma yuborilmadi ({m['telegram_id']}): {e}")
                mark_membership_reminded(m["telegram_id"], tier)
        except Exception as e:
            logger.warning(f"expiry_reminder_loop xatosi: {e}")
        await asyncio.sleep(3600)  # har soatda tekshiradi


async def push_notification_loop():
    """Kunlik/haftalik yangi kinolar haqida avtomatik push xabar yuboradi (admin sozlamalari asosida)."""
    while True:
        try:
            now = datetime.utcnow()
            hour = int(get_setting("push_hour") or "10")
            today_str = now.date().isoformat()

            if now.hour == hour and get_setting("daily_push_enabled") == "1" \
                    and get_setting("last_daily_push_date") != today_str:
                since = (now - timedelta(hours=24)).isoformat()
                with closing(db()) as conn:
                    new_movies = conn.execute(
                        "SELECT * FROM movies WHERE created_at >= ? AND is_vip=0 AND is_pro=0 ORDER BY id DESC LIMIT 15",
                        (since,),
                    ).fetchall()
                    user_ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM users WHERE banned=0 OR banned IS NULL")]
                if new_movies:
                    lines = "\n".join(f"• {m['name']} ({m['code']})" for m in new_movies)
                    text = f"📅 Bugungi yangi kinolar:\n\n{lines}"
                    for uid in user_ids:
                        try:
                            await user_bot.send_message(uid, text)
                        except Exception:
                            pass
                        await asyncio.sleep(0.05)
                set_setting("last_daily_push_date", today_str)

            if now.hour == hour and now.weekday() == 0 and get_setting("weekly_push_enabled") == "1" \
                    and get_setting("last_weekly_push_date") != today_str:
                since = (now - timedelta(days=7)).isoformat()
                with closing(db()) as conn:
                    new_movies = conn.execute(
                        "SELECT * FROM movies WHERE created_at >= ? AND is_vip=0 AND is_pro=0 ORDER BY id DESC LIMIT 25",
                        (since,),
                    ).fetchall()
                    user_ids = [r["telegram_id"] for r in conn.execute("SELECT telegram_id FROM users WHERE banned=0 OR banned IS NULL")]
                if new_movies:
                    lines = "\n".join(f"• {m['name']} ({m['code']})" for m in new_movies)
                    text = f"🗓 Shu haftaning yangi kinolari:\n\n{lines}"
                    for uid in user_ids:
                        try:
                            await user_bot.send_message(uid, text)
                        except Exception:
                            pass
                        await asyncio.sleep(0.05)
                set_setting("last_weekly_push_date", today_str)
        except Exception as e:
            logger.warning(f"push_notification_loop xatosi: {e}")
        await asyncio.sleep(600)  # har 10 daqiqada tekshiradi


AUTO_RESTART_HOURS = 12  # PythonAnywhere kabi bepul hostinglarda uzoq muddat ishlashdan
                          # kelib chiqishi mumkin bo'lgan muammolarning oldini olish uchun,
                          # bot shu necha soatda bir marta o'zini avtomatik qayta ishga tushiradi.


async def auto_restart_loop():
    """Har AUTO_RESTART_HOURS soatda butun jarayonni (bot.py'ni) qaytadan
    ishga tushiradi — alohida bash skript yoki tashqi nazoratchi shart emas."""
    await asyncio.sleep(AUTO_RESTART_HOURS * 3600)
    logger.info(f"⏰ {AUTO_RESTART_HOURS} soat o'tdi — bot avtomatik qayta ishga tushirilmoqda...")
    try:
        await user_bot.session.close()
    except Exception as e:
        logger.warning(f"Oddiy bot sessiyasini yopishda xato (baribir qayta ishga tushamiz): {e}")
    try:
        await admin_bot.session.close()
    except Exception as e:
        logger.warning(f"Admin bot sessiyasini yopishda xato (baribir qayta ishga tushamiz): {e}")
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def _run_bot_polling(dp_obj: Dispatcher, bot_obj: Bot, label: str):
    """Bitta botni (oddiy yoki admin) uzluksiz poll qiladi, ulanish uzilsa
    avtomatik qayta urinadi — ikkala bot bir-biridan mustaqil ishlaydi."""
    retry_delay = 5
    while True:
        try:
            await bot_obj.delete_webhook(drop_pending_updates=True)
            await dp_obj.start_polling(bot_obj)
            break  # start_polling faqat maxsus to'xtatilganda (Ctrl+C) qaytadi
        except Exception as e:
            logger.error(
                f"[{label}] Ulanishda xatolik (proxy vaqtincha ishlamayotgan bo'lishi mumkin): {e}. "
                f"{retry_delay} soniyadan keyin qayta urinamiz..."
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # asta-sekin oshiramiz, 60 sondan oshmaydi


async def main():
    init_db()
    logger.info("uzkinox7 bot (ODDIY + ADMIN, ikkita alohida token) ishga tushdi")
    try:
        await user_bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🚀 Mini App", web_app=WebAppInfo(url=MINIAPP_URL))
        )
    except Exception as e:
        logger.warning(f"Mini App menu tugmasi o'rnatilmadi (MINIAPP_URL to'g'ri HTTPS manzilmi?): {e}")

    asyncio.create_task(expiry_reminder_loop())
    asyncio.create_task(auto_restart_loop())
    asyncio.create_task(push_notification_loop())

    # Ikkala bot (ODDIY va ADMIN) bir jarayonda, bir-biridan mustaqil ravishda
    # parallel poll qilinadi. Biri to'xtab qolsa ham ikkinchisi ishlashda davom etadi
    # (har biri o'z retry-loopiga ega).
    await asyncio.gather(
        _run_bot_polling(user_dp, user_bot, "ODDIY BOT"),
        _run_bot_polling(admin_dp, admin_bot, "ADMIN BOT"),
    )


if __name__ == "__main__":
    asyncio.run(main())