import os
import sys
import traceback
import asyncio
import sqlite3
import io
import re
import time
import tempfile
import calendar
from urllib.parse import urljoin, urlparse, quote, unquote, parse_qs

from baleio import Bot, Dispatcher, F
from baleio.filters import CommandStart, Command
from baleio.types import Message, ReplyKeyboardRemove, CallbackQuery
from baleio.utils import InlineKeyboardBuilder

def log(*args):
    print(*args, flush=True)

log("🚀 شروع برنامه بله...")

# =========================================================
# تنظیمات و کلیدها
# =========================================================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
AI_API_KEY = os.getenv("AI_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.avalai.ir/v1")
AI_CHAT_MODEL = os.getenv("AI_CHAT_MODEL", "gpt-4o-mini")
AI_STT_MODEL = os.getenv("AI_STT_MODEL", "whisper-1")   # تبدیل ویس به متن
AI_TTS_MODEL = os.getenv("AI_TTS_MODEL", "tts-1")       # تبدیل متن به ویس
AI_TTS_VOICE = os.getenv("AI_TTS_VOICE", "nova")
# --- سرویس دوم هوش مصنوعی (پشتیبان): اگر سرویس اول قطع بود خودکار استفاده می‌شود ---
AI2_API_KEY = os.getenv("AI2_API_KEY")
AI2_BASE_URL = os.getenv("AI2_BASE_URL", "")
AI2_CHAT_MODEL = os.getenv("AI2_CHAT_MODEL", AI_CHAT_MODEL)
AI2_STT_MODEL = os.getenv("AI2_STT_MODEL", AI_STT_MODEL)
AI2_TTS_MODEL = os.getenv("AI2_TTS_MODEL", AI_TTS_MODEL)
AI2_TTS_VOICE = os.getenv("AI2_TTS_VOICE", AI_TTS_VOICE)
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "25"))                  # حداکثر انتظار برای هر سرویس (ثانیه)
AI_FAIL_COOLDOWN = int(os.getenv("AI_FAIL_COOLDOWN", "120"))       # سرویس خراب تا این مدت (ثانیه) در اولویت آخر می‌رود
JFT_URL = os.getenv("JFT_URL", "https://jft.nairan1.org/")
JFT_SELECTOR = os.getenv("JFT_SELECTOR", "")   # اختیاری: سلکتور CSS بخش متن در سایت
JFT_CACHE_SECONDS = int(os.getenv("JFT_CACHE_SECONDS", "1800"))
ONLINE_URL = os.getenv("ONLINE_URL", "https://nairan1.org/onlinemeeting/")
ONLINE_SELECTOR = os.getenv("ONLINE_SELECTOR", "")   # اختیاری: سلکتور CSS بخش لیست جلسات
ONLINE_CACHE_SECONDS = int(os.getenv("ONLINE_CACHE_SECONDS", "600"))
ONLINE_MAX_CHARS = int(os.getenv("ONLINE_MAX_CHARS", "8000"))
MAX_VOICE_SECONDS = int(os.getenv("MAX_VOICE_SECONDS", "60"))
MAX_VOICE_BYTES = int(os.getenv("MAX_VOICE_BYTES", str(2 * 1024 * 1024)))

# --- جلسات حضوری خارج از ایران ---
NA_WORLD_SEARCH_URL = os.getenv("NA_WORLD_SEARCH_URL", "https://na.org/meetingsearch/find-na/")
GOOGLE_CSE_KEY = os.getenv("GOOGLE_CSE_KEY", "")     # اختیاری: کلید Google Programmable Search
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")       # اختیاری: شناسه موتور جستجو (cx)
LOCAL_SITE_MAX_PAGES = int(os.getenv("LOCAL_SITE_MAX_PAGES", "3"))   # حداکثر تعداد سایت محلی که بررسی می‌شود
_BLOCK_DOMAINS = ("facebook.com", "instagram.com", "youtube.com", "wikipedia.org", "reddit.com",
                  "twitter.com", "x.com", "tiktok.com", "pinterest.com", "na.org")

if not TOKEN:
    log("❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    sys.exit(1)

dp = Dispatcher()
bot = Bot(token=TOKEN)

# =========================================================
# راه‌اندازی کلاینت هوش مصنوعی (ایمن)
# =========================================================
AI_PROVIDERS = []   # فهرست سرویس‌ها به ترتیب اولویت
try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None
    log("⚠️ پکیج openai نصب نیست:")
    traceback.print_exc()

def _add_provider(name, key, base, chat, stt, tts, voice):
    if not key or not base or AsyncOpenAI is None:
        return
    try:
        client = AsyncOpenAI(api_key=key, base_url=base, timeout=AI_TIMEOUT, max_retries=0)
        AI_PROVIDERS.append({"name": name, "client": client, "chat": chat, "stt": stt, "tts": tts, "voice": voice})
        log(f"✅ سرویس هوش مصنوعی «{name}» آماده شد ({base}).")
    except Exception:
        log(f"⚠️ راه‌اندازی سرویس «{name}» ناموفق بود:")
        traceback.print_exc()

_add_provider("اصلی", AI_API_KEY, AI_BASE_URL, AI_CHAT_MODEL, AI_STT_MODEL, AI_TTS_MODEL, AI_TTS_VOICE)
_add_provider("پشتیبان", AI2_API_KEY, AI2_BASE_URL, AI2_CHAT_MODEL, AI2_STT_MODEL, AI2_TTS_MODEL, AI2_TTS_VOICE)

# برای سازگاری با بقیه کد: اگر حداقل یک سرویس فعال باشد، ai_client خالی نیست
ai_client = AI_PROVIDERS[0]["client"] if AI_PROVIDERS else None
if not AI_PROVIDERS:
    log("⚠️ هیچ سرویس هوش مصنوعی تنظیم نشده (AI_API_KEY / AI2_API_KEY)؛ گفتگوی هوشمند غیرفعال است.")

_ai_fail_until = {}

async def ai_call(call):
    """call(provider) را روی سرویس‌ها به ترتیب اجرا می‌کند؛ اگر یکی خطا داد، سراغ بعدی می‌رود."""
    now = time.time()
    ready = [p for p in AI_PROVIDERS if _ai_fail_until.get(p["name"], 0) <= now]
    waiting = [p for p in AI_PROVIDERS if p not in ready]
    last_err = None
    for p in ready + waiting:
        try:
            result = await call(p)
            _ai_fail_until.pop(p["name"], None)
            return result
        except Exception as e:
            last_err = e
            log(f"AI provider «{p['name']}» failed: {e!r}")
            newly_failed = _ai_fail_until.get(p["name"], 0) <= time.time()
            _ai_fail_until[p["name"]] = time.time() + AI_FAIL_COOLDOWN
            if newly_failed and len(AI_PROVIDERS) > 1:
                try:
                    await report_admin(f"⚠️ سرویس هوش مصنوعی «{p['name']}» خطا داد و موقتاً کنار گذاشته شد:\n{type(e).__name__}: {e}")
                except Exception:
                    pass
    raise last_err if last_err else RuntimeError("no AI provider configured")

# =========================================================
# بخش دیتابیس
# =========================================================
DB_PATH = os.getenv("DB_PATH", "bot_database.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            first_name TEXT,
            username TEXT,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_langs (
            user_id INTEGER PRIMARY KEY,
            lang TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_user(user_id, first_name, username):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, first_name, username) VALUES (?, ?, ?)', (user_id, first_name, username))
    conn.commit()
    conn.close()

def get_user_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def save_message(user_id, first_name, username, text):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO messages (user_id, first_name, username, text) VALUES (?, ?, ?, ?)',
        (user_id, first_name, username, text)
    )
    conn.commit()
    conn.close()

def get_message_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM messages')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_last_messages(limit=5):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, user_id, first_name, username, text, created_at '
        'FROM messages ORDER BY id DESC LIMIT ?', (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

init_db()

# ----- زبان کاربر -----
DEFAULT_LANG = "fa"
_lang_cache = {}

def get_lang(user_id) -> str:
    if user_id in _lang_cache:
        return _lang_cache[user_id]
    lang = DEFAULT_LANG
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute('SELECT lang FROM user_langs WHERE user_id = ?', (user_id,)).fetchone()
        conn.close()
        if row and row[0] in ("fa", "en"):
            lang = row[0]
    except Exception as e:
        log(f"get_lang error: {e!r}")
    _lang_cache[user_id] = lang
    return lang

def set_lang(user_id, lang: str):
    if lang not in ("fa", "en"):
        lang = DEFAULT_LANG
    _lang_cache[user_id] = lang
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('INSERT OR REPLACE INTO user_langs (user_id, lang) VALUES (?, ?)', (user_id, lang))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"set_lang error: {e!r}")

# =========================================================
# متن‌ها (فارسی / English)
# =========================================================
STR = {
    "fa": {
        "lang_prompt": "🌐 Select Language\nانتخاب زبان",
        "btn_lang": "🌐 زبان / Language",
        "welcome": (
            "مرکز جامع خدمات و منابع انجمن معتادان گمنام (NA) 🌐🤝\n\n"
            "دریافت اطلاعات درباره NA 📚، جلسات مجازی 💻🌍، جلسات حضوری 🏢📍 و ارتباط مستقیم با کنفرانس خدمات جهانی(NA) 📞🌐. "
            "راهنمای همراه شما در مسیر بهبودی 🌱✨، بدون پیچیدگی و کاملاً سریع ⚡👌\n\n"
            "💡 شما می‌توانید سوالات خود را درباره NA بپرسید یا از منوی زیر استفاده کنید:"
        ),
        "email_text": (
            "بخش‌های ارتباطی خدمات جهانی NA\n"
            "روی هر دکمه بزنید تا مستقیماً برای آن بخش ایمیل بفرستید."
        ),
        "btn_online": "💻 اطلاع از جلسات آنلاین",
        "btn_inperson": "🔍 جستجوی جلسات حضوری",
        "btn_clean": "📊 روزشمار پاکی",
        "btn_jft": "🌿 پیام امید امروز",
        "btn_iran_council": "🌐 شورای فرامنطقه ایران",
        "btn_apf": "🌐 شورای فرامنطقه APF",
        "btn_edm": "🌐 شورای فرامنطقه EDM",
        "btn_email": "✉️ ارتباط با کنفرانس خدمات جهانی NA",
        "btn_wso_iran": "📧 دفتر خدمات جهانی NA ایران",
        "btn_admin_msg": "🤫 ارسال پیام به سازنده",
        "btn_ai": "🤖 گفتگوی هوشمند",
        "back": "🔙 بازگشت به منوی اصلی",
        "em_general": "اطلاعات عمومی و فلووشیپ",
        "em_customer": "خدمات مشتری (سفارشات)",
        "em_board": "هیئت جهانی",
        "em_hr": "منابع انسانی",
        "em_pr": "روابط عمومی",
        "em_hospitals": "بیمارستان‌ها و موسسات",
        "em_web": "وب‌سایت",
        "em_events": "رویدادها و کنوانسیون‌ها",
        "em_naway": "مجله The NA Way",
        "em_contrib": "کمک‌های مالی",
        "em_jobs": "فرصت‌های شغلی",
        "start_err": "❌ خطا در نمایش منو. لطفاً دوباره /start را بزنید.",
        "dev_reply": "✉️ **پاسخ سازنده:**\n\n{text}",
        "jft_title": "🌿 پیام امید امروز\n\n",
        "jft_fail": "⚠️ الان نتوانستم پیام امروز را دریافت کنم. لطفاً چند دقیقه بعد دوباره تلاش کنید.",
        "online_title": "💻 جلسات آنلاین\n\n",
        "online_fail": "⚠️ الان نتوانستم لیست جلسات آنلاین را دریافت کنم. لطفاً چند دقیقه بعد دوباره تلاش کنید.",
        "view_full_list": "🌐 مشاهده لیست کامل",
        "admin_msg_prompt": "📝 لطفاً متن پیام خود را برای سازنده بنویسید.",
        "admin_msg_disabled": "⚠️ متاسفانه ارسال پیام به سازنده در حال حاضر غیرفعال است.",
        "admin_msg_sent": "✅ پیام شما با موفقیت برای سازنده ارسال شد.",
        "admin_msg_err": "❌ خطا در ارسال پیام. لطفاً بعداً تلاش کنید.",
        "ai_intro": (
            "🤖 **دستیار هوشمند NA در خدمت شماست.**\n\n"
            "می‌توانید سوالات خود را درباره انجمن، مسیر بهبودی یا جلسات بپرسید. من اینجا هستم تا با هم صحبت کنیم.\n\n"
            "🎙 هم می‌توانید متن بنویسید و هم ویس بفرستید؛ اگر ویس بفرستید، به صورت صوتی هم جواب می‌دهم.\n\n"
            "⚠️ **توجه:** برای حفظ حریم خصوصی، لطفاً نام، شماره تماس یا آدرس خود را برای من نفرستید.\n"
            "برای خروج از این بخش، دستور /start را بزنید."
        ),
        "ai_disabled": "⚠️ سرویس هوش مصنوعی در حال حاضر غیرفعال است.",
        "ai_err": "❌ متاسفانه در حال حاضر نمی‌توانم پاسخ دهم. لطفاً بعداً تلاش کنید یا /start را بزنید.",
        "voice_need_ai": "🎙 برای گفتگوی صوتی، اول از منو دکمه «🤖 گفتگوی هوشمند» را بزنید.",
        "voice_too_long": "⚠️ لطفاً ویس کوتاه‌تر از {sec} ثانیه بفرستید.",
        "voice_no_audio": "🎙 متوجه صدا نشدم، لطفاً دوباره و واضح‌تر بفرستید.",
        "voice_fail": "❌ متاسفانه نتوانستم ویس را پردازش کنم. لطفاً بعداً تلاش کنید یا پیام متنی بفرستید.",
        "use_menu": "لطفاً از دکمه‌های منوی زیر استفاده کنید:",
        "inperson_intro": (
            "🏢 جستجوی جلسات حضوری\n\n"
            "📍 لوکیشن خود را بفرستید (از دکمه پایین، یا از منوی پیوست 📎 گزینه «موقعیت مکانی»)\n"
            "یا ✍️ نام شهر یا روستای خود را بنویسید.\n\n"
            "برای خروج، دستور /start را بزنید."
        ),
        "btn_send_location": "📍 ارسال موقعیت من",
        "inperson_need_menu": "📍 برای جستجوی جلسات حضوری، اول از منو دکمه «🔍 جستجوی جلسات حضوری» را بزنید.",
        "type_short": "لطفاً نام شهر یا روستا را کوتاه و واضح بنویسید، یا لوکیشن خود را بفرستید.",
        "searching": "🔎 در حال جستجو…",
        "searching_near": "🔎 در حال جستجوی جلسات نزدیک شما…",
        "no_place": "ℹ️ مکانی با این نام پیدا نشد. نام شهر را کامل‌تر بنویسید یا لوکیشن خود را بفرستید.",
        "inperson_fail": "❌ الان نتوانستم لیست جلسات حضوری را دریافت کنم. لطفاً چند دقیقه بعد دوباره تلاش کنید.",
        "nearby_header": "🏢 جلسات حضوری نزدیک شما{where} — تا {r} کیلومتر",
        "nearby_none_header": "ℹ️ در شعاع {r} کیلومتری{where} جلسه‌ای پیدا نشد. نزدیک‌ترین جلسات:",
        "no_meetings": "ℹ️ جلسه‌ای برای این محدوده پیدا نشد.",
        "text_results_header": "🏢 جلسات حضوری «{q}»",
        "global_header": "🌍 نزدیک‌ترین جلسات حضوری NA{where}",
        "global_none": (
            "ℹ️ برای این محدوده جلسه حضوری ثبت‌شده‌ای پیدا نشد.\n"
            "می‌توانید نزدیک‌ترین انجمن محلی NA را از سایت رسمی پیدا کنید:\n{url}"
        ),
        "global_footer": (
            "ℹ️ اطلاعات از پایگاه داده جهانی جلسات NA (BMLT) گرفته شده است. قبل از رفتن، با گروه هماهنگ کنید.\n"
            "🌍 لیست کامل‌تر: " + NA_WORLD_SEARCH_URL
        ),
        "local_header": "🌍 جلسات حضوری NA از سایت محلی{where}",
        "local_footer": (
            "ℹ️ این اطلاعات از سایت محلی NA گرفته شده و ممکن است قدیمی باشد. قبل از رفتن با گروه هماهنگ کنید.\n"
            "🔗 منبع: {src}"
        ),
        "km": "کیلومتر",
        "meeting": "جلسه",
        "open_sessions": "🟢 جلسات باز:",
        "closed_sessions": "🔒 جلسات بسته:",
        "neshan": "🧭 مسیریابی (نشان): ",
        "source": "🌐 منبع: {src}",
        "sep": "، ",
        "clean_title": "📊 روزشمار پاکی\n\nسال شروع پاکی خود را انتخاب کنید:",
        "clean_year_title": "📅 سال {y}\n\nماه شروع پاکی را انتخاب کنید:",
        "clean_month_title": "📅 {m} {y}\n\nروز شروع پاکی را انتخاب کنید:",
        "older": "⬅️ قدیمی‌تر",
        "newer": "جدیدتر ➡️",
        "back_year": "🔙 انتخاب سال",
        "back_month": "🔙 انتخاب ماه",
        "recalc": "🔄 محاسبه مجدد",
        "clean_future": "⚠️ تاریخ انتخاب‌شده در آینده است. لطفاً دوباره انتخاب کنید.",
        "clean_result": (
            "📊 روزشمار پاکی\n\n"
            "📅 تاریخ شروع پاکی: {start}\n"
            "🗓 امروز: {today}\n\n"
            "🌿 مدت پاکی شما:\n{duration}\n"
            "🔢 مجموع: {total} روز\n\n"
            "هر روز پاکی یک پیروزی است. 🌱🙏"
        ),
        "first_day": "امروز اولین روز شماست",
        "clean_err": "❌ خطایی رخ داد. لطفاً دوباره از منو «📊 روزشمار پاکی» را بزنید.",
    },
    "en": {
        "lang_prompt": "🌐 Select Language\nانتخاب زبان",
        "btn_lang": "🌐 زبان / Language",
        "welcome": (
            "The Comprehensive Services & Resources Hub of Narcotics Anonymous (NA) 🌐🤝\n\n"
            "Get information about NA 📚, online meetings 💻🌍, in-person meetings 🏢📍, and direct contact with the NA World Services conference 📞🌐. "
            "Your companion on the path of recovery 🌱✨ — simple and fast ⚡👌\n\n"
            "💡 You can ask your questions about NA or use the menu below:"
        ),
        "email_text": (
            "NA World Services contact departments\n"
            "Tap a button to email that department directly."
        ),
        "btn_online": "💻 Online meetings",
        "btn_inperson": "🔍 Find in-person meetings",
        "btn_clean": "📊 Clean time counter",
        "btn_jft": "🌿 Today's message of hope",
        "btn_iran_council": "🌐 NA Iran Regional Council",
        "btn_apf": "🌐 APF Regional Council",
        "btn_edm": "🌐 EDM Regional Council",
        "btn_email": "✉️ Contact NA World Services",
        "btn_wso_iran": "📧 NA Iran Service Office",
        "btn_admin_msg": "🤫 Message the developer",
        "btn_ai": "🤖 Smart assistant",
        "back": "🔙 Back to main menu",
        "em_general": "General info & Fellowship",
        "em_customer": "Customer service (orders)",
        "em_board": "World Board",
        "em_hr": "Human Resources",
        "em_pr": "Public Relations",
        "em_hospitals": "Hospitals & Institutions",
        "em_web": "Website",
        "em_events": "Events & Conventions",
        "em_naway": "The NA Way Magazine",
        "em_contrib": "Contributions",
        "em_jobs": "Job opportunities",
        "start_err": "❌ Couldn't show the menu. Please send /start again.",
        "dev_reply": "✉️ **Reply from the developer:**\n\n{text}",
        "jft_title": "🌿 Today's message of hope\n\n",
        "jft_fail": "⚠️ I couldn't get today's message right now. Please try again in a few minutes.",
        "online_title": "💻 Online meetings\n\nℹ️ These meetings are published in Persian by NA Iran.\n\n",
        "online_fail": "⚠️ I couldn't get the online meetings list right now. Please try again in a few minutes.",
        "view_full_list": "🌐 View full list",
        "admin_msg_prompt": "📝 Please write your message to the developer.",
        "admin_msg_disabled": "⚠️ Sending messages to the developer is currently disabled.",
        "admin_msg_sent": "✅ Your message was sent to the developer.",
        "admin_msg_err": "❌ Couldn't send the message. Please try again later.",
        "ai_intro": (
            "🤖 **The NA smart assistant is here for you.**\n\n"
            "You can ask about the fellowship, the path of recovery, or meetings. I'm here to talk with you.\n\n"
            "🎙 You can type or send a voice message; if you send a voice message, I'll answer with voice too.\n\n"
            "⚠️ **Note:** To protect your privacy, please don't send me your name, phone number, or address.\n"
            "To leave this section, send /start."
        ),
        "ai_disabled": "⚠️ The AI service is currently disabled.",
        "ai_err": "❌ Sorry, I can't answer right now. Please try again later or send /start.",
        "voice_need_ai": "🎙 For voice chat, first tap the “🤖 Smart assistant” button in the menu.",
        "voice_too_long": "⚠️ Please send a voice message shorter than {sec} seconds.",
        "voice_no_audio": "🎙 I couldn't make out the audio. Please send it again, more clearly.",
        "voice_fail": "❌ Sorry, I couldn't process the voice message. Please try again later or send a text message.",
        "use_menu": "Please use the menu buttons below:",
        "inperson_intro": (
            "🏢 Find in-person meetings\n\n"
            "📍 Send your location (use the button below, or the attachment menu 📎 → “Location”)\n"
            "or ✍️ type the name of your city or town.\n\n"
            "To exit, send /start."
        ),
        "btn_send_location": "📍 Send my location",
        "inperson_need_menu": "📍 To find in-person meetings, first tap “🔍 Find in-person meetings” in the menu.",
        "type_short": "Please type the name of your city or town briefly and clearly, or send your location.",
        "searching": "🔎 Searching…",
        "searching_near": "🔎 Searching for meetings near you…",
        "no_place": "ℹ️ No place with that name was found. Try a more complete name or send your location.",
        "inperson_fail": "❌ I couldn't get the in-person meetings list right now. Please try again in a few minutes.",
        "nearby_header": "🏢 In-person meetings near you{where} — within {r} km",
        "nearby_none_header": "ℹ️ No meetings found within {r} km{where}. Nearest meetings:",
        "no_meetings": "ℹ️ No meetings were found for this area.",
        "text_results_header": "🏢 In-person meetings for “{q}”",
        "global_header": "🌍 Nearest in-person NA meetings{where}",
        "global_none": (
            "ℹ️ No registered in-person meetings were found for this area.\n"
            "You can find your nearest local NA community on the official site:\n{url}"
        ),
        "global_footer": (
            "ℹ️ Data comes from the worldwide NA meeting database (BMLT). Please confirm with the group before going.\n"
            "🌍 More: " + NA_WORLD_SEARCH_URL
        ),
        "local_header": "🌍 In-person NA meetings from the local site{where}",
        "local_footer": (
            "ℹ️ Taken from the local NA website and may be out of date. Please confirm with the group before going.\n"
            "🔗 Source: {src}"
        ),
        "km": "km",
        "meeting": "Meeting",
        "open_sessions": "🟢 Open meetings:",
        "closed_sessions": "🔒 Closed meetings:",
        "neshan": "🧭 Navigation (Neshan): ",
        "source": "🌐 Source: {src}",
        "sep": ", ",
        "clean_title": "📊 Clean time counter\n\nChoose the year your clean time started:",
        "clean_year_title": "📅 Year {y}\n\nChoose the month your clean time started:",
        "clean_month_title": "📅 {m} {y}\n\nChoose the day your clean time started:",
        "older": "⬅️ Older",
        "newer": "Newer ➡️",
        "back_year": "🔙 Choose year",
        "back_month": "🔙 Choose month",
        "recalc": "🔄 Recalculate",
        "clean_future": "⚠️ The selected date is in the future. Please choose again.",
        "clean_result": (
            "📊 Clean time counter\n\n"
            "📅 Clean date: {start}\n"
            "🗓 Today: {today}\n\n"
            "🌿 Your clean time:\n{duration}\n"
            "🔢 Total: {total} days\n\n"
            "Every clean day is a victory. 🌱🙏"
        ),
        "first_day": "Today is your first day",
        "clean_err": "❌ Something went wrong. Please tap “📊 Clean time counter” in the menu again.",
    },
}

def T(lang: str, key: str, **kw) -> str:
    s = STR.get(lang, STR[DEFAULT_LANG]).get(key)
    if s is None:
        s = STR[DEFAULT_LANG].get(key, key)
    return s.format(**kw) if kw else s

SYSTEM_PROMPT_FA = (
    "شما یک دستیار هوشمند و همدل هستید که منحصراً برای «انجمن معتادان گمنام (NA)» طراحی شده‌اید. "
    "وظیفه شما ارائه اطلاعات دقیق، همدلانه و بدون قضاوت درباره مسیر بهبودی، ۱۲ قدم، ۱۲ سنت، جلسات NA، مفاهیم روحانی و متون این انجمن است. "
    "لحن شما باید بسیار مهربان، پر از امید، آرامش‌بخش و کاملاً همدلانه باشد.\n\n"
    "⚠️ **قوانین بسیار مهم و سخت‌گیرانه (باید دقیقاً رعایت شوند):**\n"
    "۱. **محدودیت موضوعی:** شما فقط مجاز هستید به سوالاتی پاسخ دهید که مستقیماً به انجمن NA، اعتیاد، بهبودی و سلامت روان مرتبط باشند. "
    "اگر کاربر سوالی بی‌ربط پرسید، با احترام بگویید: «من فقط برای کمک در مسیر بهبودی و پاسخ به سوالات مربوط به انجمن NA طراحی شده‌ام و نمی‌توانم در این مورد کمکی کنم.»\n"
    "۲. **ایمنی و بحران:** اگر کاربر صحبت از خودکشی، تمایل شدید به مصرف مجدد، یا افسردگی شدید کرد، فوراً با لحنی دلسوزانه او را به کمک‌های انسانی ارجاع دهید. بگویید: «شنیدن این حرف‌ها برای من مهم است. لطفاً همین حالا با یک راهنما، یک دوست مورد اعتماد یا اورژانس اجتماعی (شماره ۱۲۳) و صدای مشاور (شماره ۱۴۸۰) تماس بگیرید. شما تنها نیستید.»\n"
    "۳. **اصل ناشناسی (Anonymity):** هرگز از کاربر اسم، شماره تلفن، آدرس یا اطلاعات هویتی نخواهید. همچنین هرگز ادعا نکنید که شما یک انسان هستید؛ شما یک هوش مصنوعی هستید.\n"
    "۴. **عدم جایگزینی:** گاهی به کاربر یادآوری کنید که گفتگو با هوش مصنوعی جایگزین شرکت در جلسات واقعی NA و صحبت با یک راهنما (Sponsor) نیست.\n"
    "۵. پاسخ‌ها باید کوتاه، کاربردی و به زبان فارسی روان و صمیمی نوشته شوند."
)

SYSTEM_PROMPT_EN = (
    "You are a smart, compassionate assistant designed exclusively for Narcotics Anonymous (NA). "
    "Your job is to give accurate, empathetic, non-judgmental information about the path of recovery, the 12 Steps, the 12 Traditions, "
    "NA meetings, spiritual principles, and NA literature. Your tone must be very kind, hopeful, calming, and fully empathetic.\n\n"
    "⚠️ **Very important, strict rules (follow them exactly):**\n"
    "1. **Topic limit:** Only answer questions directly related to NA, addiction, recovery, and mental health. "
    "If the user asks something unrelated, politely say: \"I'm designed only to help with recovery and questions about the NA fellowship, so I can't help with that.\"\n"
    "2. **Safety and crisis:** If the user talks about suicide, a strong urge to use again, or severe depression, immediately and compassionately refer them to human help. "
    "Say: \"I'm glad you told me. Please reach out right now to a sponsor, a trusted friend, or your local emergency services or crisis line. You are not alone.\"\n"
    "3. **Anonymity:** Never ask the user for their name, phone number, address, or identifying information. Never claim to be human; you are an AI.\n"
    "4. **Not a replacement:** Occasionally remind the user that chatting with an AI is not a substitute for attending real NA meetings and talking with a sponsor.\n"
    "5. Replies must be short, practical, and written in warm, natural English."
)

def system_prompt(lang: str) -> str:
    return SYSTEM_PROMPT_EN if lang == "en" else SYSTEM_PROMPT_FA

# =========================================================
# کیبوردهای شیشه‌ای (Inline)
# =========================================================
def lang_markup():
    kb = InlineKeyboardBuilder()
    kb.button(text="English", callback_data="lang_en")
    kb.button(text="فارسی", callback_data="lang_fa")
    kb.adjust(2)
    return kb.as_markup()

def main_inline_keyboard(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    # دکمه‌های عملیاتی
    kb.button(text=T(lang, "btn_online"), callback_data="menu_online")
    kb.button(text=T(lang, "btn_inperson"), callback_data="menu_inperson")
    kb.button(text=T(lang, "btn_clean"), callback_data="menu_clean")
    kb.button(text=T(lang, "btn_jft"), callback_data="menu_jft")
    # سه دکمه لینک‌دار شوراهای فرامنطقه: مستقیم لینک را باز می‌کنند
    kb.button(text=T(lang, "btn_iran_council"), url="https://nairan.org/fa")
    kb.button(text=T(lang, "btn_apf"), url="https://fa.apfna.org/farsi-home")
    kb.button(text=T(lang, "btn_edm"), url="https://edmna.org/")
    # بقیه دکمه‌ها
    kb.button(text=T(lang, "btn_email"), callback_data="menu_email")
    kb.button(text=T(lang, "btn_wso_iran"), url="mailto:info@wsoiran.org")
    kb.button(text=T(lang, "btn_admin_msg"), callback_data="menu_admin_msg")
    kb.button(text=T(lang, "btn_ai"), callback_data="menu_ai")
    kb.button(text=T(lang, "btn_lang"), callback_data="menu_lang")
    kb.adjust(1)
    return kb

def email_inline_keyboard(lang: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=T(lang, "em_general"), url="mailto:fsmail@na.org")
    kb.button(text=T(lang, "em_customer"), url="mailto:customer_service@na.org")
    kb.button(text=T(lang, "em_board"), url="mailto:worldboard@na.org")
    kb.button(text=T(lang, "em_hr"), url="mailto:hrp@na.org")
    kb.button(text=T(lang, "em_pr"), url="mailto:pr@na.org")
    kb.button(text=T(lang, "em_hospitals"), url="mailto:handi@na.org")
    kb.button(text=T(lang, "em_web"), url="mailto:webmaster@na.org")
    kb.button(text=T(lang, "em_events"), url="mailto:events@na.org")
    kb.button(text=T(lang, "em_naway"), url="mailto:naway@na.org")
    kb.button(text=T(lang, "em_contrib"), url="mailto:contributions@na.org")
    kb.button(text=T(lang, "em_jobs"), url="mailto:jobs@na.org")
    kb.button(text=T(lang, "back"), callback_data="back_to_main")
    kb.adjust(2, 2, 2, 2, 2, 1, 1)
    return kb

def main_markup(lang: str = DEFAULT_LANG):
    return main_inline_keyboard(lang).as_markup()

# =========================================================
# وضعیت‌های موقت کاربر
# =========================================================
user_states = {}
ai_chat_history = {}

# =========================================================
# هندلرها
# =========================================================
@dp.message(CommandStart())
async def start_handler(message: Message):
    user = message.from_user
    if not user:
        return
    lang = get_lang(user.id)
    try:
        add_user(user.id, user.first_name, user.username)
        user_states.pop(user.id, None)
        ai_chat_history.pop(user.id, None)

        # حذف کیبورد قدیمی پایین صفحه (برای کاربرانی که قبلاً داشتند)
        tmp = await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
        try:
            await tmp.delete()
        except Exception:
            pass

        # انتخاب زبان
        await message.answer(STR["fa"]["lang_prompt"], reply_markup=lang_markup())
    except Exception:
        traceback.print_exc()
        await message.answer(T(lang, "start_err"))

@dp.callback_query(F.data.in_({"lang_en", "lang_fa"}))
async def lang_choice_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = "en" if callback.data == "lang_en" else "fa"
    set_lang(user_id, lang)
    user_states.pop(user_id, None)
    ai_chat_history.pop(user_id, None)
    await callback.answer()
    try:
        await callback.message.edit_text(T(lang, "welcome"), reply_markup=main_markup(lang))
    except Exception:
        await callback.message.answer(T(lang, "welcome"), reply_markup=main_markup(lang))

@dp.callback_query(F.data == "menu_lang")
async def lang_menu_handler(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text(STR["fa"]["lang_prompt"], reply_markup=lang_markup())
    except Exception:
        await callback.message.answer(STR["fa"]["lang_prompt"], reply_markup=lang_markup())

@dp.message(Command("stats"))
async def stats_handler(message: Message):
    user = message.from_user
    if user and str(user.id) == str(ADMIN_ID):
        count = get_user_count()
        msg_count = get_message_count()
        await message.answer(
            f"📊 آمار ربات:\n\n"
            f"👥 تعداد کل اعضای ربات: **{count}** نفر\n"
            f"📩 تعداد پیام‌های دریافتی: **{msg_count}**"
        )

@dp.message(Command("messages"))
async def messages_handler(message: Message):
    user = message.from_user
    if not user or str(user.id) != str(ADMIN_ID):
        return
    rows = get_last_messages(5)
    if not rows:
        await message.answer("هنوز پیامی ثبت نشده است.")
        return
    parts = []
    for r in rows:
        _id, uid, fname, uname, text, created = r
        parts.append(
            f"#{_id} | {created}\n"
            f"👤 {fname} (@{uname if uname else 'ندارد'}) | 🆔 {uid}\n"
            f"{text}"
        )
    await message.answer("📩 آخرین پیام‌ها:\n\n" + "\n\n------\n\n".join(parts))

@dp.message(Command("reply"))
async def admin_reply_handler(message: Message):
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("فرمت: /reply USER_ID TEXT\nمثال: /reply 123456789 سلام")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ آیدی باید فقط عدد باشد.")
        return
    try:
        await bot.send_message(chat_id=target_id, text=T(get_lang(target_id), "dev_reply", text=parts[2]))
        await message.answer("✅ پاسخ با موفقیت ارسال شد.")
    except Exception as e:
        log(f"Reply error: {e}")
        await message.answer(f"❌ خطا در ارسال: {e}")

# ----- پیام امید امروز (دریافت مستقیم از سایت) -----
_jft_cache = {"text": None, "time": 0.0}
_jft_en_cache = {"src": None, "text": None}

def _clean_text(text: str) -> str:
    # حذف کاراکترهایی که ممکن است فرمت‌بندی پیام را خراب کنند
    text = re.sub(r"[*_`\[\]]", "", text)
    lines = [ln.strip() for ln in text.splitlines()]
    out = []
    for ln in lines:
        if ln:
            out.append(ln)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()

def extract_jft(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        BeautifulSoup = None

    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "button", "svg", "table", "select"]):
            tag.decompose()

        # 1) اگر سلکتور مشخص شده باشد، فقط همان بخش
        if JFT_SELECTOR:
            node = soup.select_one(JFT_SELECTOR)
            if node is not None:
                paras = [x.get_text(" ", strip=True) for x in node.find_all(["p", "h1", "h2", "h3", "h4", "li"])]
                joined = "\n\n".join(x for x in paras if x) or node.get_text(" ", strip=True)
                return _clean_text(joined)

        # 2) استخراج هوشمند: فقط پاراگراف‌های متنی بلند (بدون تقویم، شماره‌ها و منو)
        def is_noise(t: str) -> bool:
            letters = sum(ch.isalpha() for ch in t)
            return len(t) < 20 or letters < len(t) * 0.5

        long_ps = []
        seen = set()
        first_p = None
        for el in soup.find_all(["p", "div", "li"]):
            # فقط عناصری که خودشان زیرمجموعه بلاک دیگر ندارند
            if el.find(["p", "div", "li", "h1", "h2", "h3", "h4"]):
                continue
            t = el.get_text(" ", strip=True)
            if is_noise(t) or t in seen:
                continue
            seen.add(t)
            long_ps.append(t)
            if first_p is None:
                first_p = el

        if long_ps:
            title = ""
            if first_p is not None:
                h = first_p.find_previous(["h1", "h2", "h3", "h4", "h5"])
                if h:
                    title = h.get_text(" ", strip=True)
            body = "\n\n".join(long_ps)
            text = (title + "\n\n" + body) if title and title not in body else body
        else:
            text = soup.get_text(" ", strip=True)
    else:
        text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "", html)
        text = re.sub(r"(?s)<br\s*/?>|</p>|</div>|</h\d>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", "", text)
        import html as _html
        text = _html.unescape(text)
        lines = [ln.strip() for ln in text.splitlines()]
        text = "\n\n".join(ln for ln in lines if len(ln) >= 20)
    return _clean_text(text)

def pick_jft(text: str) -> str:
    """فقط بخش پایانی «فقط برای امروز : ...» را برمی‌گرداند و حقوق سایت را حذف می‌کند."""
    t = text.replace("ي", "ی").replace("ك", "ک")
    matches = list(re.finditer(r"فقط\s*برای\s*امروز\s*[:：]", t))
    if not matches:
        return ""
    t = t[matches[-1].start():]
    # حذف بخش حقوق سایت و هر چیز بعد از آن
    for marker in ("©", "تمامی حقوق", "تمام حقوق", "حقوق این سایت", "حقوق اين سايت"):
        idx = t.find(marker)
        if idx != -1:
            t = t[:idx]
    t = re.sub(r"\s+", " ", t).strip()
    # حذف سال (مثل 2023 یا ۱۴۰۵) و نمادهای باقی‌مانده از انتهای متن
    t = re.sub(r"[\s©\-–—]*(?:19|20|14)\d{2}\s*$", "", t)
    t = re.sub(r"[\s©\-–—]*[۱۲]?[۰-۹]{3,4}\s*$", "", t)
    return t.strip()

async def fetch_jft() -> str:
    now = time.time()
    if _jft_cache["text"] and now - _jft_cache["time"] < JFT_CACHE_SECONDS:
        return _jft_cache["text"]
    import httpx
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(JFT_URL, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        html_text = resp.text
        text = pick_jft(extract_jft(html_text))
    if len(text) < 40:
        api_hints = sorted(set(re.findall(r"""["'](/?[\w\-./]*api[\w\-./?=&]*)["']""", html_text)))[:8]
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_text)[:6]
        raise ValueError(
            f"متن کافی استخراج نشد | status={resp.status_code} | html_len={len(html_text)} | "
            f"text_len={len(text)} | api_hints={api_hints} | scripts={scripts}"
        )
    text = text[:3500]
    _jft_cache["text"] = text
    _jft_cache["time"] = now
    return text

async def fetch_jft_localized(lang: str):
    """برای کاربر انگلیسی، متن فارسی با هوش مصنوعی ترجمه می‌شود. خروجی: (متن، ترجمه_شد؟)"""
    text = await fetch_jft()
    if lang != "en":
        return text, False
    if _jft_en_cache["src"] == text and _jft_en_cache["text"]:
        return _jft_en_cache["text"], True
    if ai_client is not None:
        try:
            resp = await ai_call(lambda p: p["client"].chat.completions.create(
                model=p["chat"],
                messages=[
                    {"role": "system", "content": (
                        "You are a faithful translator. Translate the following Persian Narcotics Anonymous "
                        "'Just For Today' daily reading into natural, clear English. Output only the translation."
                    )},
                    {"role": "user", "content": text},
                ],
                max_tokens=1200,
                temperature=0.2,
            ))
            out = (resp.choices[0].message.content or "").strip()
            if out:
                _jft_en_cache["src"], _jft_en_cache["text"] = text, out
                return out, True
        except Exception as e:
            log(f"JFT translate error: {e!r}")
    return text, False

def jft_markup(lang: str = DEFAULT_LANG):
    kb = InlineKeyboardBuilder()
    kb.button(text=T(lang, "back"), callback_data="back_to_main")
    kb.adjust(1)
    return kb.as_markup()

@dp.callback_query(F.data == "menu_jft")
async def jft_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    await callback.answer()
    try:
        text, translated = await fetch_jft_localized(lang)
        title = T(lang, "jft_title")
        if lang == "en":
            title = title.rstrip("\n") + (" (automatic translation)" if translated else " (Persian original)") + "\n\n"
        await callback.message.answer(title + text, reply_markup=jft_markup(lang))
    except Exception as e:
        log(f"JFT error: {e!r}")
        traceback.print_exc()
        # گزارش علت خطا برای ادمین
        if ADMIN_ID:
            try:
                await bot.send_message(chat_id=int(ADMIN_ID), text=f"🛠 خطای پیام امید امروز:\n{type(e).__name__}: {e}"[:3500])
            except Exception:
                pass
        await callback.message.answer(T(lang, "jft_fail"), reply_markup=jft_markup(lang))

@dp.message(Command("testjft"))
async def test_jft_handler(message: Message):
    # ویژه ادمین: برای بررسی اینکه متن درست استخراج می‌شود
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    _jft_cache["text"] = None
    try:
        text = await fetch_jft()
        await message.answer(f"✅ {len(text)} کاراکتر دریافت شد.\n\n{text[:1500]}")
    except Exception as e:
        await message.answer(f"❌ خطا: {type(e).__name__}: {e}"[:3500])

# ----- جلسات آنلاین (دریافت مستقیم از سایت) -----
_online_cache = {"text": None, "time": 0.0}

# فقط لینک‌های Zoom
ZOOM_RE = re.compile(r"zoom\.(us|com)", re.I)

# کلمات مربوط به روز برگزاری
DAY_WORDS = (
    "شنبه", "یکشنبه", "یک‌شنبه", "دوشنبه", "دو‌شنبه", "سه‌شنبه", "سه شنبه", "سهشنبه",
    "چهارشنبه", "چهار‌شنبه", "پنجشنبه", "پنج‌شنبه", "پنج شنبه", "جمعه",
    "هر روز", "همه روزه", "همه‌روزه", "روزانه", "ایام هفته",
)
# الگوی ساعت
TIME_RE = re.compile(r"\d{1,2}\s*[:٫.]\s*\d{2}|[۰-۹]{1,2}\s*[:٫]\s*[۰-۹]{2}|ساعت|صبح|ظهر|عصر|شب")

def _norm_fa(s: str) -> str:
    return s.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")

def extract_online(html: str) -> str:
    """متن خام صفحه (برای عیب‌یابی)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        BeautifulSoup = None
    if BeautifulSoup is None:
        text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "", html)
        text = re.sub(r"(?s)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        import html as _html
        return _clean_text(_html.unescape(text))

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "button", "svg", "select"]):
        tag.decompose()
    root = None
    if ONLINE_SELECTOR:
        root = soup.select_one(ONLINE_SELECTOR)
    if root is None:
        root = soup.find("main") or soup.body or soup

    # هر ردیف جدول -> یک خط
    for tr in root.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        tr.replace_with("\n• " + " | ".join(cells) + "\n")
    # هر آیتم لیست -> یک خط
    for li in root.find_all("li"):
        t = li.get_text(" ", strip=True)
        if t:
            li.replace_with("\n• " + t + "\n")
    text = root.get_text("\n", strip=True)
    return _clean_text(text)

FIELD_ICONS = (
    ("تلفن", "📞"), ("جنسیت", "👥"), ("ویژگی", "✨"), ("منطقه", "🏙"),
    ("تاریخ", "📅"), ("شهر", "📍"), ("آدرس", "🏠"), ("بستر", "💻"),
    ("رمز", "🔑"), ("ایمیل", "✉️"), ("لینک", "🔗"), ("روز", "🗓"), ("ساعت", "🕘"),
)
EMPTY_VALUES = {"", "0", "۰", "-", "—", "ندارد"}
LABEL_RE = re.compile(r"^([^:：\d]{1,30}?)\s*[:：]\s*(.*)$")

def _field_icon(label: str) -> str:
    for key, icon in FIELD_ICONS:
        if key in label:
            return icon
    return "▫️"

def extract_online_groups(html: str) -> str:
    """هر جلسه را به شکل «نام گروه + فیلدهای label : value + لینک Zoom» برمی‌گرداند."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg", "select"]):
        tag.decompose()
    root = None
    if ONLINE_SELECTOR:
        root = soup.select_one(ONLINE_SELECTOR)
    if root is None:
        root = soup.find("main") or soup.body or soup

    def is_zoom(h: str) -> bool:
        h = (h or "").strip()
        return h.lower().startswith(("http://", "https://")) and bool(ZOOM_RE.search(h))

    def zoom_links(node):
        return {a["href"].strip() for a in node.find_all("a", href=True) if is_zoom(a["href"])}

    def parse_label(line: str):
        m = LABEL_RE.match(line)
        if not m or m.group(2).startswith("//"):
            return None
        return m.group(1).strip(), m.group(2).strip()

    groups, seen = [], set()
    for a in root.find_all("a", href=True):
        href = a["href"].strip()
        if not is_zoom(href) or href in seen:
            continue

        # بالا رفتن تا کوچک‌ترین «کارت» که فقط یک لینک Zoom دارد
        card, node = a, a
        while node.parent is not None and node.parent.name not in ("body", "html", "[document]"):
            parent = node.parent
            if len(zoom_links(parent)) > 1 or len(parent.get_text(" ", strip=True)) > 1500:
                break
            card, node = parent, parent

        lines = [re.sub(r"\s+", " ", ln).strip()
                 for ln in card.get_text("\n", strip=True).splitlines() if ln.strip()]
        btn = a.get_text(" ", strip=True)
        if btn in lines and len(btn) <= 20:
            lines.remove(btn)
        lines = [ln for ln in lines if not ln.lower().startswith("http")]
        if not lines:
            continue

        name = None
        extra = []     # خط‌های بدون برچسب (مثل روز و ساعت)
        fields = []    # (label, value)
        i = 0
        while i < len(lines):
            ln = lines[i]
            parsed = parse_label(ln)
            if parsed:
                label, value = parsed
                # اگر مقدار در خط بعدی آمده باشد
                if not value and i + 1 < len(lines) and parse_label(lines[i + 1]) is None:
                    value = lines[i + 1]
                    i += 1
                fields.append((label, value))
            elif name is None:
                name = ln
            else:
                extra.append(ln)
            i += 1

        item = f"🔹 {name or 'جلسه آنلاین'}"
        for ln in extra:
            if ln != name:
                item += f"\n🗓 {ln[:120]}"
        for label, value in fields:
            if "لینک" in label:
                continue  # لینک را از href می‌گذاریم
            if _norm_fa(value).strip() in EMPTY_VALUES:
                continue
            item += f"\n{_field_icon(label)} {label} : {value}"
        item += f"\n🔗 لینک : {href}"

        seen.add(href)
        groups.append(item)
    return "\n\n".join(groups)

def split_text(text: str, limit: int = 3500):
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur.strip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur.strip())
    return chunks

ONLINE_LINK_SELECTOR = os.getenv("ONLINE_LINK_SELECTOR", "")   # اختیاری: سلکتور CSS لینک‌های جلسات در صفحه لیست
ONLINE_MAX_PAGES = int(os.getenv("ONLINE_MAX_PAGES", "60"))     # حداکثر تعداد صفحه جلسه که بررسی می‌شود

# فقط گروه‌های بهبودی: عنوان‌هایی که یکی از این کلمات را دارند حذف می‌شوند (با ویرگول جدا کنید)
ONLINE_EXCLUDE_WORDS = [w.strip() for w in os.getenv(
    "ONLINE_EXCLUDE_WORDS",
    "روابط عمومی,کمیته,معارفه,شورا,هیئت,هیات,کارگاه,همایش,کنوانسیون,سمینار,نشست,برگزار می,اطلاعیه,فراخوان,مراسم,جشن"
).split(",") if w.strip()]
# اختیاری: اگر پر شود، فقط عنوان‌هایی که یکی از این کلمات را دارند نمایش داده می‌شوند (مثلاً: گروه)
ONLINE_INCLUDE_WORDS = [w.strip() for w in os.getenv("ONLINE_INCLUDE_WORDS", "").split(",") if w.strip()]

def _squash(s: str) -> str:
    """حذف هر نوع فاصله و کاراکتر نامرئی (نیم‌فاصله، NBSP، اعراب و ...) برای مقایسه مطمئن."""
    s = (s or "").replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    return re.sub(r"[\s\u200b-\u200f\u202a-\u202e\u00a0\u064b-\u065f\u0640]+", "", s)

def is_recovery_group(title: str) -> bool:
    t = _squash(title)
    if any(_squash(w) in t for w in ONLINE_EXCLUDE_WORDS):
        return False
    if ONLINE_INCLUDE_WORDS and not any(_squash(w) in t for w in ONLINE_INCLUDE_WORDS):
        return False
    return True

_online_debug = {"excluded": []}

ZOOM_URL_RE = re.compile(r"https?://[^\s\"'<>]*zoom\.(?:us|com)[^\s\"'<>]*", re.I)
SKIP_PATH_PARTS = ("/category/", "/author/", "/tag/", "/page/", "/wp-", "/feed", "/search", "/comments")
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".zip", ".mp3", ".mp4")

def _host(u: str) -> str:
    return urlparse(u).netloc.lower().replace("www.", "")

def extract_detail_links(html: str):
    """لینک صفحه‌های تک‌تک جلسات را از صفحه لیست درمی‌آورد."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg", "select"]):
        tag.decompose()
    if ONLINE_LINK_SELECTOR:
        anchors = [x for x in soup.select(ONLINE_LINK_SELECTOR) if x.get("href")]
    else:
        root = None
        if ONLINE_SELECTOR:
            root = soup.select_one(ONLINE_SELECTOR)
        if root is None:
            root = soup.find("main") or soup.body or soup
        anchors = root.find_all("a", href=True)

    base_path = urlparse(ONLINE_URL).path.rstrip("/")
    out, seen = [], set()
    for a in anchors:
        href = (a["href"] or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(ONLINE_URL, href).split("#")[0]
        p = urlparse(full)
        if p.scheme not in ("http", "https") or _host(full) != _host(ONLINE_URL):
            continue
        path = p.path.lower()
        if path.rstrip("/") in ("", base_path.lower()):
            continue
        if any(s in path for s in SKIP_PATH_PARTS) or "?s=" in full or path.endswith(SKIP_EXT):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
    return out[:ONLINE_MAX_PAGES]

def parse_meeting_page(html: str, url: str):
    """از صفحه یک جلسه، متن آماده نمایش و لینک Zoom را برمی‌گرداند؛ اگر Zoom نداشت None."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # عنوان را قبل از حذف تگ‌ها برمی‌داریم
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title and soup.title:
        title = re.split(r"[|–—-]", soup.title.get_text(" ", strip=True))[0].strip()

    for tag in soup(["script", "style", "noscript", "nav", "form", "svg", "select", "aside", "footer"]):
        tag.decompose()
    root = soup.select_one(".entry-content, .post-content, article, main") or soup.body or soup

    zoom = ""
    for a in root.find_all("a", href=True):
        h = a["href"].strip()
        if h.lower().startswith(("http://", "https://")) and ZOOM_RE.search(h):
            zoom = h
            break
    if not zoom:
        m = ZOOM_URL_RE.search(root.get_text(" ", strip=True))
        if m:
            zoom = m.group(0)
    if not zoom:
        return None

    lines = [re.sub(r"\s+", " ", ln).strip() for ln in root.get_text("\n", strip=True).splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.lower().startswith("http")]

    def parse_label(line: str):
        m = LABEL_RE.match(line)
        if not m or m.group(2).startswith("//"):
            return None
        return m.group(1).strip(), m.group(2).strip()

    def is_schedule(line: str) -> bool:
        n = _norm_fa(line)
        return any(_norm_fa(d) in n for d in DAY_WORDS) or bool(TIME_RE.search(n))

    fields, extra = [], []
    i = 0
    while i < len(lines):
        parsed = parse_label(lines[i])
        if parsed:
            label, value = parsed
            if not value and i + 1 < len(lines) and parse_label(lines[i + 1]) is None:
                value = lines[i + 1]
                i += 1
            fields.append((label, value))
        elif is_schedule(lines[i]) and len(lines[i]) <= 80 and lines[i] != title and lines[i] not in extra:
            extra.append(lines[i])
        i += 1

    item = f"🔹 {title or 'جلسه آنلاین'}"
    for ln in extra:
        item += f"\n🗓 {ln}"
    for label, value in fields:
        if "لینک" in label or _norm_fa(value).strip() in EMPTY_VALUES:
            continue
        item += f"\n{_field_icon(label)} {label} : {value}"
    item += f"\n🔗 لینک : {zoom}"
    return item, zoom, (title or "")

ONLINE_SHOW_FULL_LIST_BUTTON = os.getenv("ONLINE_SHOW_FULL_LIST_BUTTON", "0") == "1"   # دکمه لینک سایت (پیش‌فرض خاموش)

def _build_meeting_item(lines, zoom, title=None):
    """از خط‌های متن یک جلسه، متن آماده نمایش می‌سازد. فقط نام، فیلدها و لینک Zoom."""
    def parse_label(line: str):
        m = LABEL_RE.match(line)
        if not m or m.group(2).startswith("//"):
            return None
        return m.group(1).strip(), m.group(2).strip()

    def is_schedule(line: str) -> bool:
        n = _norm_fa(line)
        return any(_norm_fa(d) in n for d in DAY_WORDS) or bool(TIME_RE.search(n))

    name, fields, extra = title, [], []
    i = 0
    while i < len(lines):
        parsed = parse_label(lines[i])
        if parsed:
            label, value = parsed
            if not value and i + 1 < len(lines) and parse_label(lines[i + 1]) is None:
                value = lines[i + 1]
                i += 1
            fields.append((label, value))
        elif name is None:
            name = lines[i]
        elif is_schedule(lines[i]) and len(lines[i]) <= 80 and lines[i] != name and lines[i] not in extra:
            extra.append(lines[i])
        i += 1

    item = f"🔹 {name or 'جلسه آنلاین'}"
    for ln in extra:
        item += f"\n🗓 {ln}"
    for label, value in fields:
        if "لینک" in label or _norm_fa(value).strip() in EMPTY_VALUES:
            continue
        item += f"\n{_field_icon(label)} {label} : {value}"
    item += f"\n🔗 لینک : {zoom}"
    return item, zoom, (name or "")

def extract_zoom_cards(html: str):
    """هر لینک Zoom را در صفحه پیدا می‌کند (در href، متن یا هر ویژگی تگ) و کارت اطراف آن را برمی‌گرداند."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "svg", "select"]):
        tag.decompose()
    root = None
    if ONLINE_SELECTOR:
        root = soup.select_one(ONLINE_SELECTOR)
    if root is None:
        root = soup.find("main") or soup.body or soup

    cands = {}   # url -> element
    def add(el, url):
        url = url.strip().rstrip(".,;)،")
        if url not in cands:
            cands[url] = el

    for el in root.find_all(True):
        for v in el.attrs.values():
            val = " ".join(v) if isinstance(v, list) else str(v)
            m = ZOOM_URL_RE.search(val)
            if m:
                add(el, m.group(0))
    for t in root.find_all(string=ZOOM_URL_RE):
        m = ZOOM_URL_RE.search(str(t))
        if m and t.parent is not None:
            add(t.parent, m.group(0))

    anc = {u: {id(x) for x in [el] + list(el.parents)} for u, el in cands.items()}
    results = []
    for url, el in cands.items():
        card, node = el, el
        while node.parent is not None and node.parent.name not in ("body", "html", "[document]"):
            parent = node.parent
            inside = sum(1 for u in cands if id(parent) in anc[u])
            if inside > 1 or len(parent.get_text(" ", strip=True)) > 1500:
                break
            card, node = parent, parent
        lines = [re.sub(r"\s+", " ", ln).strip()
                 for ln in card.get_text("\n", strip=True).splitlines() if ln.strip()]
        lines = [ln for ln in lines if not ln.lower().startswith("http")]
        if lines:
            results.append(_build_meeting_item(lines, url))
    return results

@dp.message(Command("debugonline"))
async def debug_online_handler(message: Message):
    """ویژه ادمین: گزارش ساختار صفحه جلسات آنلاین برای عیب‌یابی."""
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = await client.get(ONLINE_URL)
            html = resp.text
        low = html.lower()
        urls = ZOOM_URL_RE.findall(html) and [m.group(0) for m in ZOOM_URL_RE.finditer(html)]
        rep = [
            f"status={resp.status_code} html_len={len(html)}",
            f"zoom_word={low.count('zoom')} zoom_urls={len(urls or [])}",
            f"<a>={low.count('<a ')} <table>={low.count('<table')} <iframe>={low.count('<iframe')}",
            f"admin-ajax={low.count('admin-ajax')} wp-json={low.count('wp-json')} fetch(={low.count('fetch(')} json={low.count('application/json')}",
        ]
        for m in list(re.finditer(r"zoom", low))[:3]:
            ctx = html[max(0, m.start() - 150): m.start() + 150].replace("\n", " ")
            rep.append("… " + ctx + " …")
        rep.append("iframes: " + str(re.findall(r'<iframe[^>]+src=["\']([^"\']+)', html, re.I)[:5]))
        rep.append("detail_links: " + str(extract_detail_links(html)[:8]))
        rep.append("متن صفحه:\n" + extract_online(html)[:700])
        for chunk in split_text("\n\n".join(rep), 3500):
            await message.answer(chunk)
    except Exception as e:
        await message.answer(f"❌ خطا: {type(e).__name__}: {e}"[:3500])

def extract_table_meetings(html: str):
    """جدول جلسات را می‌خواند: هر ردیف = نام گروه + روز + ساعت + لینک Zoom (بدون هیچ متن اضافه)."""
    import html as _html
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        def cells_of(tr):
            return [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in tr.find_all(["th", "td"])]

        # ستون‌ها را از ردیف عنوان تشخیص می‌دهیم؛ اگر نبود، ترتیب پیش‌فرض: نام، روز، ساعت
        name_i, day_i, time_i = 0, 1, 2
        first = cells_of(rows[0])
        if first and not ZOOM_URL_RE.search(_html.unescape(str(rows[0]))):
            for idx, c in enumerate(first):
                n = _norm_fa(c)
                if "نام" in n or "گروه" in n:
                    name_i = idx
                    break
            for idx, c in enumerate(first):
                n = _norm_fa(c)
                if "روز" in n:
                    day_i = idx
                    break
            else:
                day_i = None
            for idx, c in enumerate(first):
                if "ساعت" in _norm_fa(c):
                    time_i = idx
                    break
            else:
                time_i = None
            if time_i is not None and time_i == day_i:
                time_i = None

        for tr in rows:
            m = ZOOM_URL_RE.search(_html.unescape(str(tr)))
            if not m:
                continue
            zoom = m.group(0).strip().rstrip(".,;)،")
            cells = cells_of(tr)

            def get(i):
                return cells[i] if i is not None and 0 <= i < len(cells) else ""

            name, day, tm = get(name_i), get(day_i), get(time_i)
            if not name:
                continue
            when = " | ".join(x for x in (day, tm) if x)
            item = f"🔹 {name}"
            if when:
                item += f"\n🗓 {when}"
            item += f"\n🔗 {zoom}"
            results.append((item, zoom, name))
    return results

async def fetch_online() -> str:
    now = time.time()
    if _online_cache["text"] and now - _online_cache["time"] < ONLINE_CACHE_SECONDS:
        return _online_cache["text"]
    import httpx
    links, fetched, no_zoom = [], 0, 0
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = await client.get(ONLINE_URL)
        resp.raise_for_status()
        html_text = resp.text
        status = resp.status_code

        # حالت ۱: لینک Zoom در خود صفحه لیست است (لینک، متن یا ویژگی تگ)
        _online_debug["excluded"] = []
        card_items, seen_z = [], set()
        for item, zoom, title in (extract_table_meetings(html_text) or extract_zoom_cards(html_text)):
            if not is_recovery_group(title):
                _online_debug["excluded"].append(title)
                continue
            if item in seen_z:
                continue
            seen_z.add(item)
            card_items.append(item)
        text = "\n\n".join(card_items)

        # حالت ۲: لینک Zoom داخل صفحه هر جلسه است
        if len(text) < 20:
            links = extract_detail_links(html_text)
            sem = asyncio.Semaphore(5)

            async def one(u):
                async with sem:
                    try:
                        r = await client.get(u)
                        r.raise_for_status()
                        return parse_meeting_page(r.text, u)
                    except Exception as e:
                        log(f"Meeting page error {u}: {e!r}")
                        return False

            results = await asyncio.gather(*(one(u) for u in links))
            items, seen_zoom = [], set()
            for r in results:
                if r is False:
                    continue
                fetched += 1
                if r is None:
                    no_zoom += 1
                    continue
                item, zoom, title = r
                if not is_recovery_group(title):
                    _online_debug["excluded"].append(title)
                    continue
                if zoom in seen_zoom:
                    continue
                seen_zoom.add(zoom)
                items.append(item)
            text = "\n\n".join(items)

    if len(text) < 20:
        raise ValueError(
            f"جلسه‌ای با لینک Zoom پیدا نشد | status={status} | html_len={len(html_text)} | "
            f"detail_links={len(links)} | pages_ok={fetched} | pages_without_zoom={no_zoom} | "
            f"excluded={_online_debug['excluded'][:5]} | "
            f"sample_links={links[:5]}"
        )
    _online_cache["text"] = text
    _online_cache["time"] = now
    return text

@dp.callback_query(F.data == "menu_online")
async def online_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    await callback.answer()
    try:
        text = await fetch_online()
        truncated = len(text) > ONLINE_MAX_CHARS
        if truncated:
            text = text[:ONLINE_MAX_CHARS].rsplit("\n", 1)[0]
        chunks = split_text(T(lang, "online_title") + text)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            if is_last and truncated and ONLINE_SHOW_FULL_LIST_BUTTON:
                kb = InlineKeyboardBuilder()
                kb.button(text=T(lang, "view_full_list"), url=ONLINE_URL)
                kb.button(text=T(lang, "back"), callback_data="back_to_main")
                kb.adjust(1)
                await callback.message.answer(chunk, reply_markup=kb.as_markup())
            elif is_last:
                await callback.message.answer(chunk, reply_markup=jft_markup(lang))
            else:
                await callback.message.answer(chunk)
    except Exception as e:
        log(f"Online meetings error: {e!r}")
        traceback.print_exc()
        if ADMIN_ID:
            try:
                await bot.send_message(chat_id=int(ADMIN_ID), text=f"🛠 خطای جلسات آنلاین:\n{type(e).__name__}: {e}"[:3500])
            except Exception:
                pass
        await callback.message.answer(T(lang, "online_fail"), reply_markup=jft_markup(lang))

@dp.message(Command("testonline"))
async def test_online_handler(message: Message):
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    _online_cache["text"] = None
    try:
        text = await fetch_online()
        ex = _online_debug["excluded"]
        ex_txt = ("\n\n🚫 حذف‌شده‌ها (" + str(len(ex)) + "):\n" + "\n".join("• " + x for x in ex[:15])) if ex else ""
        await message.answer(f"✅ {len(text)} کاراکتر دریافت شد.\n\n{text[:1500]}{ex_txt}"[:3500])
    except Exception as e:
        await message.answer(f"❌ خطا: {type(e).__name__}: {e}"[:3500])

# ----- هندلرهای دکمه‌های شیشه‌ای -----
@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    user_states.pop(callback.from_user.id, None)
    try:
        await callback.message.edit_text(T(lang, "welcome"), reply_markup=main_markup(lang))
    except Exception:
        await callback.message.answer(T(lang, "welcome"), reply_markup=main_markup(lang))
    await callback.answer()

@dp.callback_query(F.data == "menu_email")
async def email_menu_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    try:
        await callback.message.edit_text(T(lang, "email_text"), reply_markup=email_inline_keyboard(lang).as_markup())
    except Exception:
        await callback.message.answer(T(lang, "email_text"), reply_markup=email_inline_keyboard(lang).as_markup())
    await callback.answer()

@dp.callback_query(F.data == "menu_admin_msg")
async def admin_msg_menu_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    user_states[callback.from_user.id] = "waiting_for_admin_msg"
    await callback.message.answer(T(lang, "admin_msg_prompt"))
    await callback.answer()

@dp.callback_query(F.data == "menu_ai")
async def ai_menu_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_lang(user_id)
    user_states[user_id] = "waiting_for_ai"
    ai_chat_history[user_id] = [{"role": "system", "content": system_prompt(lang)}]
    await callback.message.answer(T(lang, "ai_intro"))
    await callback.answer()

# ----- توابع کمکی هوش مصنوعی و صوت -----
async def report_admin(text: str):
    """گزارش خطا برای ادمین (برای عیب‌یابی)."""
    if ADMIN_ID:
        try:
            await bot.send_message(chat_id=int(ADMIN_ID), text=text[:3500])
        except Exception:
            pass

async def download_bale_file(file_path: str) -> bytes:
    """دانلود فایل از بله: اول با کتابخانه، اگر نشد مستقیم از سرور بله."""
    try:
        buf = io.BytesIO()
        await bot.download_file(file_path, buf)
        data = buf.getvalue()
        if data:
            return data
    except Exception as e:
        log(f"download_file failed: {e!r}")
    import httpx
    url = file_path if file_path.startswith("http") else f"https://tapi.bale.ai/file/bot{TOKEN}/{file_path}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

async def ask_ai(user_id: int, text: str, lang: str = DEFAULT_LANG) -> str:
    history = ai_chat_history.setdefault(user_id, [{"role": "system", "content": system_prompt(lang)}])
    history.append({"role": "user", "content": text})
    if len(history) > 11:
        history[:] = [history[0]] + history[-10:]
    try:
        response = await ai_call(lambda p: p["client"].chat.completions.create(
            model=p["chat"],
            messages=history,
            max_tokens=500,
            temperature=0.7
        ))
    except Exception:
        history.pop()   # پیام بی‌پاسخ در تاریخچه نماند
        raise
    reply = response.choices[0].message.content
    history.append({"role": "assistant", "content": reply})
    return reply

async def voice_to_text(file_bytes: bytes, lang: str = DEFAULT_LANG) -> str:
    result = await ai_call(lambda p: p["client"].audio.transcriptions.create(
        model=p["stt"],
        file=("voice.ogg", file_bytes, "audio/ogg"),
        language=("en" if lang == "en" else "fa"),
    ))
    return (result.text or "").strip()

async def text_to_voice(text: str) -> bytes:
    response = await ai_call(lambda p: p["client"].audio.speech.create(
        model=p["tts"],
        voice=p["voice"],
        input=text[:1500],
        response_format="opus",   # ogg/opus، مناسب برای ویس
    ))
    return response.content

async def send_voice_reply(message: Message, audio_bytes: bytes):
    try:
        from baleio.types import BufferedInputFile
        await message.answer_voice(voice=BufferedInputFile(audio_bytes, filename="reply.ogg"))
    except ImportError:
        from baleio.types import FSInputFile
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_bytes)
            path = f.name
        try:
            await message.answer_voice(voice=FSInputFile(path))
        finally:
            os.remove(path)

@dp.message(F.voice)
async def handle_voice(message: Message):
    user = message.from_user
    if not user:
        return
    lang = get_lang(user.id)
    if user_states.get(user.id) != "waiting_for_ai":
        await message.answer(T(lang, "voice_need_ai"), reply_markup=main_markup(lang))
        return
    if ai_client is None:
        await message.answer(T(lang, "ai_disabled"))
        return
    # در بله duration ممکن است به میلی‌ثانیه باشد؛ پس نرمال‌سازی می‌کنیم
    raw_duration = getattr(message.voice, "duration", 0) or 0
    duration_sec = raw_duration / 1000 if raw_duration > 1000 else raw_duration
    file_size = getattr(message.voice, "file_size", 0) or 0
    log(f"Voice received: duration_raw={raw_duration}, duration_sec={duration_sec}, size={file_size}")
    if duration_sec > MAX_VOICE_SECONDS or file_size > MAX_VOICE_BYTES:
        await message.answer(T(lang, "voice_too_long", sec=MAX_VOICE_SECONDS))
        return

    stage = "download"
    try:
        # 1) دانلود ویس
        file = await bot.get_file(message.voice.file_id)
        audio_bytes = await download_bale_file(file.file_path)

        # 2) ویس -> متن
        stage = "stt"
        user_text = await voice_to_text(audio_bytes, lang)
        if not user_text:
            await message.answer(T(lang, "voice_no_audio"))
            return

        # 3) پاسخ هوش مصنوعی
        stage = "chat"
        ai_reply = await ask_ai(user.id, user_text, lang)
    except Exception as e:
        log(f"Voice AI Error [{stage}]: {e!r}")
        traceback.print_exc()
        await report_admin(f"🛠 خطای ویس (مرحله {stage}):\n{type(e).__name__}: {e}")
        await message.answer(T(lang, "voice_fail"))
        return

    # 4) متن پاسخ + ویس پاسخ
    await message.answer(ai_reply)
    try:
        audio = await text_to_voice(ai_reply)
        await send_voice_reply(message, audio)
    except Exception as e:
        log(f"TTS Error: {e}")
        traceback.print_exc()

# ----- هندلر اصلی برای دریافت متن‌ها (باید آخرین هندلر پیام باشد) -----
@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text_inputs(message: Message):
    user = message.from_user
    if not user:
        return

    user_id = user.id
    lang = get_lang(user_id)
    state = user_states.get(user_id)

    # 1. ارسال پیام به ادمین
    if state == "waiting_for_admin_msg":
        user_states.pop(user_id, None)
        try:
            save_message(user.id, user.first_name, user.username, message.text)
        except Exception as e:
            log(f"Error saving message: {e}")
        if not ADMIN_ID:
            await message.answer(T(lang, "admin_msg_disabled"), reply_markup=main_markup(lang))
            return
        try:
            sender_info = (
                f"📩 **پیام جدید از طرف کاربر:**\n\n"
                f"👤 نام: {user.first_name}\n"
                f"🔗 نام کاربری: @{user.username if user.username else 'ندارد'}\n"
                f"🆔 آیدی عددی: `{user.id}`\n"
                f"🌐 زبان: {lang}\n\n"
                f"📝 **متن پیام:**\n{message.text}\n\n"
                f"---\n"
                f"💡 برای پاسخ به این کاربر، از دستور زیر استفاده کنید:\n"
                f"`/reply {user.id} متن پاسخ شما`"
            )
            await bot.send_message(chat_id=int(ADMIN_ID), text=sender_info)
            await message.answer(T(lang, "admin_msg_sent"), reply_markup=main_markup(lang))
        except Exception as e:
            log(f"Error sending msg to admin: {e}")
            await message.answer(T(lang, "admin_msg_err"), reply_markup=main_markup(lang))
        return

    # 1.5 جستجوی جلسات حضوری با نام شهر/روستا
    if state == "waiting_for_location":
        await inperson_by_text(message, lang, message.text)
        return

    # 2. گفتگو با هوش مصنوعی (متنی)
    if state == "waiting_for_ai":
        if ai_client is None:
            await message.answer(T(lang, "ai_disabled"))
            return
        try:
            ai_reply = await ask_ai(user_id, message.text, lang)
            await message.answer(ai_reply)
        except Exception as e:
            log(f"AI Error: {e}")
            await report_admin(f"🛠 خطای گفتگوی هوشمند:\n{type(e).__name__}: {e}")
            await message.answer(T(lang, "ai_err"))
        return

    # 3. پیام‌های متفرقه
    await message.answer(T(lang, "use_menu"), reply_markup=main_markup(lang))

# ----- عیب‌یابی صفحه جلسات حضوری (ویژه ادمین) -----
INPERSON_URL = os.getenv("INPERSON_URL", "https://nairan.org/fa/meetings")

@dp.message(Command("debugmeetings"))
async def debug_meetings_handler(message: Message):
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    import httpx
    try:
        rep = []
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = await client.get(INPERSON_URL)
            html = resp.text
            low = html.lower()
            rep.append(f"status={resp.status_code} final_url={resp.url} html_len={len(html)}")
            keys = ("bmlt", "client_interface", "getsearchresults", "wp-json", "admin-ajax", "fetch(", "axios",
                    "leaflet", "google.maps", "mapbox", "__next_data__", "nuxt", "react", "vue", "angular", "graphql")
            rep.append("hints: " + " ".join(f"{k}={low.count(k)}" for k in keys if low.count(k)))
            rep.append(f"<table>={low.count('<table')} <form>={low.count('<form')} <select>={low.count('<select')} <a>={low.count('<a ')}")
            rep.append("fields: " + str(re.findall(r'<(?:input|select)[^>]+name=["\']([^"\']+)', html, re.I)[:20]))
            scripts = [urljoin(INPERSON_URL, s) for s in re.findall(r'<script[^>]+src=["\']([^"\']+)', html, re.I)]
            rep.append("scripts: " + str(scripts[:10]))
            pat = r'https?://[^\s"\'<>\\)]*(?:api|json|meeting|bmlt|graphql|search|geo)[^\s"\'<>\\)]*'
            urls = set(re.findall(pat, html, re.I))
            # داخل چند اسکریپت اول هم دنبال آدرس API می‌گردیم
            for sc in scripts[:6]:
                try:
                    r = await client.get(sc)
                    body = r.text[:1_500_000]
                    urls |= set(re.findall(pat, body, re.I))
                    for m in list(re.finditer(r"fetch\(|axios\.|\.ajax\(", body))[:3]:
                        rep.append("… " + body[max(0, m.start() - 60): m.start() + 140].replace("\n", " ") + " …")
                except Exception as e:
                    rep.append(f"script error {sc}: {type(e).__name__}")
            rep.append("api_urls:\n" + "\n".join(sorted(urls)[:25]))
        rep.append("متن صفحه:\n" + extract_online(html)[:600])
        for chunk in split_text("\n\n".join(rep), 3500):
            await message.answer(chunk)
    except Exception as e:
        await message.answer(f"❌ خطا: {type(e).__name__}: {e}"[:3500])

@dp.message(Command("debugmeetings2"))
async def debug_meetings2_handler(message: Message):
    """ویژه ادمین: بررسی فرم و آدرس‌های جست‌وجوی جلسات حضوری (آزمایش چند درخواست)."""
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    import httpx
    from bs4 import BeautifulSoup
    base = INPERSON_URL
    rep = []

    def table_info(html):
        soup = BeautifulSoup(html, "html.parser")
        trs = soup.find_all("tr")
        out = f"tr={len(trs)}"
        for tr in trs[:3]:
            cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))[:40] for c in tr.find_all(["th", "td"])]
            out += "\n  " + " | ".join(cells)
        return out

    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            r = await client.get(base)
            html = r.text
            soup = BeautifulSoup(html, "html.parser")
            rep.append("BASE " + table_info(html))

            for f in soup.find_all("form"):
                names = [x.get("name") for x in f.find_all(["input", "select"]) if x.get("name")]
                rep.append(f"FORM action={f.get('action')} method={f.get('method')} fields={names[:20]}")

            prov_id = None
            for sel in soup.find_all("select"):
                name = sel.get("name")
                opts = [(o.get("value"), o.get_text(" ", strip=True)) for o in sel.find_all("option")]
                rep.append(f"SELECT {name}: {len(opts)} options: " + ", ".join(f"{v}:{t}" for v, t in opts[:12]))
                if name == "province_id" and not prov_id:
                    for v, t in opts:
                        if "تهران" in t and v:
                            prov_id = v
                            break

            keys = ("byLocation", "byRegion", "$.ajax", "$.get", "$.post", "fetch(", "latitude", "lat", "lng", "province_id", "city_id")
            seen = 0
            for sc in soup.find_all("script"):
                if sc.get("src"):
                    continue
                body = sc.string or sc.get_text() or ""
                for k in keys:
                    for m in list(re.finditer(re.escape(k), body))[:2]:
                        rep.append(f"JS[{k}] … " + body[max(0, m.start() - 100): m.start() + 160].replace("\n", " ") + " …")
                        seen += 1
                    if seen >= 14:
                        break
                if seen >= 14:
                    break

            async def probe(label, url, params=None):
                try:
                    rr = await client.get(url, params=params)
                    ct = rr.headers.get("content-type", "")
                    body = rr.text
                    info = f"PROBE {label}: {rr.status_code} {ct[:30]} len={len(body)}"
                    if "json" in ct:
                        info += " JSON: " + body[:300].replace("\n", " ")
                    else:
                        info += " " + table_info(body).replace("\n", " // ")[:300]
                    rep.append(info)
                except Exception as e:
                    rep.append(f"PROBE {label}: error {type(e).__name__}")

            await probe("search=تهران", base, {"search": "تهران"})
            if prov_id:
                await probe(f"province_id={prov_id}", base, {"province_id": prov_id})
            loc = base.rstrip("/") + "/byLocation"
            for params in ({"lat": 35.7, "lng": 51.4}, {"lat": 35.7, "long": 51.4},
                           {"latitude": 35.7, "longitude": 51.4}, {"lat": 35.7, "lon": 51.4}):
                await probe("byLocation " + str(params), loc, params)
            await probe("byRegion", base.rstrip("/") + "/byRegion")

        for chunk in split_text("\n\n".join(rep), 3500):
            await message.answer(chunk)
    except Exception as e:
        await message.answer(f"❌ خطا: {type(e).__name__}: {e}"[:3500])

# =========================================================
# جلسات حضوری
#   - داخل ایران: از سایت شورای فرامنطقه ایران (لینک مسیریاب نشان)
#   - سایر کشورها: ۱) پایگاه داده جهانی جلسات NA (BMLT Aggregator) با لینک Google Maps
#                  ۲) اگر چیزی پیدا نشد: سایت محلی NA همان منطقه (جستجو + استخراج با هوش مصنوعی)
# =========================================================
import json
import math

INPERSON_RADIUS_KM = float(os.getenv("INPERSON_RADIUS_KM", "20"))   # شعاع جست‌وجو (ایران)
INPERSON_MAX = int(os.getenv("INPERSON_MAX", "8"))                  # حداکثر تعداد جلسه در پاسخ
GEOCODE_URL = os.getenv("GEOCODE_URL", "https://nominatim.openstreetmap.org/search")

# --- پایگاه داده جهانی جلسات NA ---
AGGREGATOR_URL = os.getenv("BMLT_AGGREGATOR_URL", "https://aggregator.bmltenabled.org/main_server/")
GLOBAL_FETCH_N = int(os.getenv("GLOBAL_FETCH_N", "40"))              # تعداد جلسه‌ای که برای گروه‌بندی از سرور خواسته می‌شود

# قالب لینک مسیریاب نشان (برای کاربران داخل ایران)؛ در صورت نیاز از طریق متغیر محیطی تغییر دهید
NESHAN_URL_TEMPLATE = os.getenv("NESHAN_URL_TEMPLATE", "https://nshn.ir/?lat={lat}&lng={lng}")

# چندضلعی تقریبی مرز ایران (عرض، طول) برای تشخیص اینکه لوکیشن داخل ایران است
_IRAN_POLY = [
    (39.4, 44.3), (38.95, 45.5), (38.85, 46.3), (39.2, 46.9), (39.8, 47.8), (39.3, 48.5), (38.4, 48.95),
    (37.6, 49.4), (37.0, 50.5), (36.9, 52.6), (37.5, 54.0), (37.35, 55.5), (37.6, 56.8), (38.2, 57.4),
    (37.65, 58.4), (37.3, 59.3), (36.6, 60.4), (36.5, 61.2), (35.6, 61.15), (34.5, 60.6), (33.3, 60.6),
    (31.5, 61.7), (30.8, 61.8), (29.9, 60.9), (29.0, 61.8), (27.2, 63.3), (26.0, 62.5), (25.2, 61.6),
    (25.2, 60.6), (25.5, 59.0), (25.5, 57.8), (26.9, 56.5), (26.4, 54.9), (26.4, 54.0), (27.3, 52.6),
    (28.8, 50.8), (29.9, 49.3), (30.1, 48.8), (30.4, 48.0), (31.0, 47.7), (32.0, 47.8), (32.7, 47.45),
    (33.1, 46.1), (33.8, 45.9), (34.45, 45.5), (35.1, 46.15), (35.6, 45.8), (36.2, 45.1), (37.0, 44.8),
    (37.4, 44.4), (38.3, 44.4),
]

def in_iran(lat: float, lon: float) -> bool:
    """تشخیص تقریبی (چندضلعی مرزی) اینکه نقطه داخل ایران است."""
    if not (24.8 <= lat <= 39.9 and 43.9 <= lon <= 63.4):
        return False
    inside = False
    j = len(_IRAN_POLY) - 1
    for i in range(len(_IRAN_POLY)):
        yi, xi = _IRAN_POLY[i]
        yj, xj = _IRAN_POLY[j]
        if (yi > lat) != (yj > lat):
            if lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside

def gmaps_link(lat, lng) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={float(lat):.6f},{float(lng):.6f}"

def nav_links(lat, lng, nav: str = "ir", lang: str = DEFAULT_LANG) -> list:
    """nav='ir' -> لینک نشان | nav='global' -> لینک Google Maps."""
    lat_s, lng_s = f"{float(lat):.6f}", f"{float(lng):.6f}"
    if nav == "ir":
        return [T(lang, "neshan") + NESHAN_URL_TEMPLATE.format(lat=lat_s, lng=lng_s)]
    return [f"🗺 Google Maps: {gmaps_link(lat, lng)}"]

_DAY_NAMES = {0: "شنبه", 1: "یک‌شنبه", 2: "دوشنبه", 3: "سه‌شنبه", 4: "چهارشنبه", 5: "پنج‌شنبه", 6: "جمعه"}
_SEX_NAMES = {0: "بانوان", 1: "آقایان", 2: "مختلط"}
_KNOWN_FIELDS = {
    "address": "📍", "addr": "📍", "full_address": "📍", "phone": "📞", "tel": "📞", "mobile": "📞",
    "feature": "✨", "features": "✨", "property": "✨", "properties": "✨",
}
_SKIP_KEYS = {"id", "lat", "lng", "latitude", "longitude", "name", "created_at", "updated_at", "deleted_at", "icon", "color"}

def _hav_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def _scalar(key: str, val) -> str:
    k = (key or "").lower()
    if isinstance(val, bool):
        return ""
    if k in ("day", "weekday", "day_id") and str(val).strip().isdigit() and int(val) in _DAY_NAMES:
        return _DAY_NAMES[int(val)]
    if k in ("sex", "gender") and str(val).strip().lstrip("-").isdigit() and int(val) in _SEX_NAMES:
        return _SEX_NAMES[int(val)]
    return re.sub(r"\s+", " ", str(val)).strip()

def _format_meeting_item(item: dict) -> str:
    def first(keys):
        for k in keys:
            if item.get(k) not in (None, ""):
                return _scalar(k, item[k])
        return ""
    name = first(("group_name", "name", "title"))
    day = first(("day", "day_name", "day_title", "weekday"))
    st, en = first(("start_time", "from", "start")), first(("end_time", "to", "end"))
    sex = first(("sex", "gender", "sex_title"))
    when = " ".join(x for x in (day, (f"{st}-{en}" if st and en else st)) if x)
    parts = [x for x in (name, when, sex) if x]
    if not parts:   # ساختار ناشناخته: همه مقدارهای ساده
        parts = [_scalar(k, v) for k, v in item.items()
                 if k not in _SKIP_KEYS and not k.endswith("_id") and isinstance(v, (str, int, float)) and str(v).strip()]
    return " | ".join(parts)

INPERSON_SHOW_TOPICS = os.getenv("INPERSON_SHOW_TOPICS", "0") == "1"   # نمایش موضوع هر جلسه (مثلاً «مشارکت»)

def _clean_html(s: str) -> str:
    import html as _html
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>", "\n", s or "")
    s = _html.unescape(re.sub(r"<[^>]+>", " ", s))
    parts = [re.sub(r"\s+", " ", p).strip() for p in s.splitlines()]
    return " | ".join(p for p in parts if p)

def _sessions_lines(label: str, sessions, lang: str = DEFAULT_LANG) -> list:
    """جلسه‌های هم‌ساعت را در یک خط جمع می‌کند: «شنبه، یک‌شنبه ⏰ 07:00 - 08:00»."""
    if not sessions:
        return []
    groups = {}
    for s in sessions:
        if not isinstance(s, dict):
            continue
        time_ = re.sub(r"\s+", " ", str(s.get("time") or "")).strip()
        day = re.sub(r"\s+", " ", str(s.get("day") or "")).strip()
        topic = re.sub(r"\s+", " ", str(s.get("topic") or "")).strip()
        if INPERSON_SHOW_TOPICS and topic:
            day = f"{day} ({topic})"
        if day or time_:
            groups.setdefault(time_, []).append(day)
    if not groups:
        return []
    sep = T(lang, "sep")
    out = [label]
    for time_, days in groups.items():
        out.append("   " + sep.join(d for d in days if d) + (f" ⏰ {time_}" if time_ else ""))
    return out

def format_location(rec: dict, dist_km=None, nav: str = "ir", lang: str = DEFAULT_LANG) -> str:
    """جلسه ایران. nav='ir' -> لینک نشان | nav='global' -> لینک Google Maps."""
    title = re.sub(r"\s+", " ", str(rec.get("name") or rec.get("group_name") or T(lang, "meeting"))).strip()
    head = f"🔹 {title}"
    if dist_km is not None:
        head += f"  ({dist_km:.1f} {T(lang, 'km')})"
    lines = [head]

    def txt(k):
        return re.sub(r"\s+", " ", str(rec.get(k) or "")).strip()

    # آدرس: استان، شهر (بدون تکرار)، بخش، آدرس
    parts = []
    for k in ("province", "city", "district", "address"):
        v = txt(k)
        if v and v not in parts:
            parts.append(v)
    if parts:
        lines.append("📍 " + T(lang, "sep").join(parts))
    if txt("phone"):
        lines.append(f"📞 {txt('phone')}")
    if txt("gender"):
        lines.append(f"👥 {txt('gender')}")
    if txt("feature"):
        lines.append(f"✨ {txt('feature')}")

    lines += _sessions_lines(T(lang, "open_sessions"), rec.get("openSessions"), lang)
    lines += _sessions_lines(T(lang, "closed_sessions"), rec.get("closedSessions"), lang)

    notes = _clean_html(str(rec.get("notes") or ""))
    if notes:
        lines.append("📝 " + notes[:200])
    try:
        lines += nav_links(rec["lat"], rec["lng"], nav, lang)
    except Exception:
        pass
    return "\n".join(lines)

_nearby_cache = {}
_all_loc_cache = {"t": 0.0, "recs": []}

def _recs_from(data):
    recs = data.get("locations") if isinstance(data, dict) else data
    return [x for x in (recs or []) if isinstance(x, dict)]

async def fetch_nearby(lat: float, lon: float):
    key = (round(lat, 2), round(lon, 2))
    now = time.time()
    c = _nearby_cache.get(key)
    if c and now - c[0] < 1800:
        return c[1]
    import httpx
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}) as client:
        r = await client.get(INPERSON_URL.rstrip("/") + "/byLocation", params={"latitude": lat, "longitude": lon})
        r.raise_for_status()
        recs = _recs_from(r.json())
    if len(_nearby_cache) > 40:
        _nearby_cache.clear()
    _nearby_cache[key] = (now, recs)
    return recs

async def fetch_all_locations():
    now = time.time()
    if _all_loc_cache["recs"] and now - _all_loc_cache["t"] < 6 * 3600:
        return _all_loc_cache["recs"]
    import httpx
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}) as client:
        r = await client.get(INPERSON_URL.rstrip("/") + "/byRegion")
        r.raise_for_status()
        recs = _recs_from(r.json())
    _all_loc_cache["t"], _all_loc_cache["recs"] = now, recs
    return recs

async def geocode_place(q: str, lang: str = DEFAULT_LANG, iran_only: bool = True):
    """نام شهر/روستا -> (lat, lon, نام یافت‌شده)؛ اگر پیدا نشد None."""
    import httpx
    params = {"q": q, "format": "json", "limit": 1, "accept-language": "fa" if lang == "fa" else "en"}
    if iran_only:
        params["countrycodes"] = "ir"
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "NA-Bale-Bot/1.0"}) as client:
        r = await client.get(GEOCODE_URL, params=params)
        r.raise_for_status()
        arr = r.json()
    if not arr:
        return None
    return float(arr[0]["lat"]), float(arr[0]["lon"]), (arr[0].get("display_name") or "")

def pick_nearest(recs, lat, lon):
    out = []
    for r in recs:
        try:
            out.append((_hav_km(lat, lon, float(r["lat"]), float(r["lng"])), r))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    near = [x for x in out if x[0] <= INPERSON_RADIUS_KM][:INPERSON_MAX]
    return near, out[:3]

# ----- جلسات سایر کشورها (BMLT Aggregator) -----
_global_cache = {}
_WEEKDAYS = {
    "en": {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday", 5: "Thursday", 6: "Friday", 7: "Saturday"},
    "fa": {1: "یک‌شنبه", 2: "دوشنبه", 3: "سه‌شنبه", 4: "چهارشنبه", 5: "پنج‌شنبه", 6: "جمعه", 7: "شنبه"},
}

async def fetch_global_nearby(lat: float, lon: float):
    """نزدیک‌ترین جلسات NA در سراسر جهان را از Aggregator می‌گیرد."""
    key = (round(lat, 2), round(lon, 2))
    now = time.time()
    c = _global_cache.get(key)
    if c and now - c[0] < 1800:
        return c[1]
    import httpx
    url = AGGREGATOR_URL.rstrip("/") + "/client_interface/json/"
    recs = []
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers={
        "User-Agent": "NA-Bale-Bot/1.0", "Accept": "application/json"}) as client:
        # اول شعاع خودکار (تعداد جلسه)، اگر نتیجه نداد شعاع‌های ثابت
        for width in (-GLOBAL_FETCH_N, 50, 300):
            params = {
                "switcher": "GetSearchResults",
                "lat_val": lat,
                "long_val": lon,
                "geo_width_km": width,
                "sort_results_by_distance": 1,
            }
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log(f"Global search error (width={width}): {e!r}")
                continue
            recs = [x for x in data if isinstance(x, dict)] if isinstance(data, list) else _recs_from(data)
            if recs:
                break
    if len(_global_cache) > 40:
        _global_cache.clear()
    _global_cache[key] = (now, recs)
    return recs

def group_global(recs, lat, lon):
    """جلسه‌های یک گروه (همان نام و مکان) را یکجا جمع می‌کند و بر اساس فاصله مرتب می‌کند."""
    groups = {}
    for r in recs:
        if str(r.get("venue_type", "")) == "2":   # فقط مجازی
            continue
        try:
            la, lo = float(r["latitude"]), float(r["longitude"])
        except Exception:
            continue
        if la == 0 and lo == 0:
            continue
        key = (str(r.get("meeting_name", "")).strip(), round(la, 5), round(lo, 5))
        g = groups.get(key)
        if g is None:
            g = {"rec": r, "dist": _hav_km(lat, lon, la, lo), "meetings": []}
            groups[key] = g
        g["meetings"].append(r)
    return sorted(groups.values(), key=lambda g: g["dist"])

def _hhmm(t: str) -> str:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(t or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""

def format_global(g: dict, lang: str = "en") -> str:
    r = g["rec"]
    sep = T(lang, "sep")
    name = re.sub(r"\s+", " ", str(r.get("meeting_name") or "NA")).strip()
    lines = [f"🔹 {name}  ({g['dist']:.1f} {T(lang, 'km')})"]

    parts = []
    for k in ("location_text", "location_street", "location_neighborhood", "location_municipality",
              "location_sub_province", "location_province", "location_postal_code_1", "location_nation"):
        v = re.sub(r"\s+", " ", str(r.get(k) or "")).strip()
        if v and v not in parts:
            parts.append(v)
    if parts:
        lines.append("📍 " + sep.join(parts))

    info = _clean_html(str(r.get("location_info") or ""))
    if info:
        lines.append("ℹ️ " + info[:150])

    # برنامه جلسات: روزهای هم‌ساعت در یک خط
    by_time = {}
    for m in g["meetings"]:
        try:
            wd = int(m.get("weekday_tinyint"))
        except Exception:
            continue
        by_time.setdefault(_hhmm(m.get("start_time")), set()).add(wd)
    names = _WEEKDAYS.get(lang, _WEEKDAYS["en"])
    for tm in sorted(by_time):
        days = sep.join(names[d] for d in sorted(by_time[tm]) if d in names)
        lines.append("🗓 " + days + (f" ⏰ {tm}" if tm else ""))

    comments = _clean_html(str(r.get("comments") or ""))
    if comments:
        lines.append("📝 " + comments[:150])
    try:
        lines += nav_links(r["latitude"], r["longitude"], "global", lang)
    except Exception:
        pass
    src = urlparse(str(r.get("root_server_uri") or "")).netloc.replace("www.", "")
    if src:
        lines.append(T(lang, "source", src=src))
    return "\n".join(lines)

# ----- جلسات سایت محلی NA (وقتی BMLT چیزی نداشت) -----
async def reverse_geocode(lat: float, lon: float):
    """مختصات -> (شهر، کشور) به انگلیسی."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "NA-Bale-Bot/1.0"}) as c:
            r = await c.get("https://nominatim.openstreetmap.org/reverse", params={
                "lat": lat, "lon": lon, "format": "json", "zoom": 10, "accept-language": "en"})
            a = r.json().get("address", {})
        city = a.get("city") or a.get("town") or a.get("village") or a.get("county") or a.get("state") or ""
        return city, a.get("country", "")
    except Exception as e:
        log(f"reverse_geocode error: {e!r}")
        return "", ""

def _ok_url(u: str) -> bool:
    h = _host(u)
    return u.startswith("http") and not any(h == d or h.endswith("." + d) for d in _BLOCK_DOMAINS)

async def search_local_sites(query: str):
    """سایت‌های محلی NA را از موتور جستجو پیدا می‌کند (Google API → Google → DuckDuckGo)."""
    import httpx
    from bs4 import BeautifulSoup
    urls = []
    hdr = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=hdr) as c:
        if GOOGLE_CSE_KEY and GOOGLE_CSE_CX:
            try:
                r = await c.get("https://www.googleapis.com/customsearch/v1",
                                params={"key": GOOGLE_CSE_KEY, "cx": GOOGLE_CSE_CX, "q": query, "num": 8})
                urls += [it["link"] for it in r.json().get("items", [])]
            except Exception as e:
                log(f"CSE error: {e!r}")
        if not urls:
            try:
                r = await c.get("https://www.google.com/search", params={"q": query, "num": 10})
                for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
                    if a["href"].startswith("/url?q="):
                        urls.append(unquote(a["href"][7:].split("&")[0]))
            except Exception as e:
                log(f"Google search error: {e!r}")
        if not urls:
            try:
                r = await c.post("https://html.duckduckgo.com/html/", data={"q": query})
                for a in BeautifulSoup(r.text, "html.parser").select("a.result__a"):
                    h = a.get("href", "")
                    if "uddg=" in h:
                        h = unquote(parse_qs(urlparse(h).query).get("uddg", [""])[0])
                    urls.append(h)
            except Exception as e:
                log(f"DDG error: {e!r}")
    out, seen = [], set()
    for u in urls:
        if _ok_url(u) and _host(u) not in seen:
            seen.add(_host(u))
            out.append(u)
    return out[:LOCAL_SITE_MAX_PAGES]

async def fetch_page_text(url: str, limit: int = 6000) -> str:
    """متن صفحه؛ اگر ساعت جلسه نداشت، یک لینک «meeting» داخل همان سایت را هم می‌خواند."""
    import httpx
    from bs4 import BeautifulSoup

    def text_of(soup):
        for t in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg"]):
            t.decompose()
        return _clean_text(soup.get_text("\n", strip=True))

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = await c.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        link = None
        for a in soup.find_all("a", href=True):
            if "meeting" in (a["href"] + a.get_text()).lower():
                full = urljoin(url, a["href"]).split("#")[0]
                if _host(full) == _host(url) and full != url:
                    link = full
                    break
        txt = text_of(soup)
        if link and not re.search(r"\d{1,2}[:.]\d{2}|\b[ap]\.?m\b", txt, re.I):
            try:
                r2 = await c.get(link)
                txt = text_of(BeautifulSoup(r2.text, "html.parser")) or txt
            except Exception:
                pass
    return txt[:limit]

async def extract_meetings_ai(page_text: str, place: str):
    """جلسات حضوری نوشته‌شده در متن صفحه را به JSON تبدیل می‌کند (بدون حدس)."""
    resp = await ai_call(lambda p: p["client"].chat.completions.create(
        model=p["chat"],
        messages=[
            {"role": "system", "content": (
                "Extract IN-PERSON Narcotics Anonymous meetings from the text. Use ONLY information that is explicitly "
                "in the text; never invent anything. Return ONLY a JSON array (max 8 items) of objects with keys: "
                "name, day_time, address. Use \"\" if unknown. Skip online-only meetings. If none, return [].")},
            {"role": "user", "content": f"Area: {place}\n\n{page_text}"},
        ],
        max_tokens=900, temperature=0,
    ))
    raw = re.sub(r"```(?:json)?", "", resp.choices[0].message.content or "").strip()
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict) and (m.get("name") or m.get("address"))][:8]

async def send_local_site_fallback(message, lang: str, lat: float, lon: float) -> bool:
    """سایت محلی NA همان منطقه را پیدا و جلسات را می‌فرستد. True یعنی نتیجه ارسال شد."""
    if not AI_PROVIDERS:
        return False
    city, country = await reverse_geocode(lat, lon)
    place = ", ".join(x for x in (city, country) if x)
    if not place:
        return False
    sites = await search_local_sites(f"Narcotics Anonymous NA meetings {place}")
    for site in sites:
        try:
            text = await fetch_page_text(site)
            meetings = await extract_meetings_ai(text, place)
        except Exception as e:
            log(f"Local site error {site}: {e!r}")
            continue
        if not meetings:
            continue
        items = []
        for m in meetings:
            name = str(m.get("name") or T(lang, "meeting")).strip()
            lines = [f"🔹 {name}"]
            if m.get("day_time"):
                lines.append(f"🗓 {m['day_time']}")
            if m.get("address"):
                addr = str(m["address"]).strip()
                lines.append(f"📍 {addr}")
                lines.append("🗺 Google Maps: https://www.google.com/maps/search/?api=1&query=" + quote(f"{addr}, {place}"))
            items.append("\n".join(lines))
        await send_results(message, lang, T(lang, "local_header", where=f" ({place})"), items,
                           footer=T(lang, "local_footer", src=site))
        return True
    return False

async def send_results(message, lang: str, header: str, items, footer: str = ""):
    text = header + "\n\n" + "\n\n".join(items)
    if footer:
        text += "\n\n" + footer
    chunks = split_text(text, 3500)
    for i, ch in enumerate(chunks):
        if i == len(chunks) - 1:
            await message.answer(ch, reply_markup=jft_markup(lang))
        else:
            await message.answer(ch)

async def send_global_nearby(message, lang: str, lat: float, lon: float, label: str = ""):
    recs = await fetch_global_nearby(lat, lon)
    groups = group_global(recs, lat, lon)[:INPERSON_MAX]
    where = f" ({label})" if label else ""
    if groups:
        await send_results(message, lang, T(lang, "global_header", where=where),
                           [format_global(g, lang) for g in groups], footer=T(lang, "global_footer"))
        return
    # BMLT جلسه‌ای نداشت: سایت محلی NA همان منطقه را بررسی می‌کنیم
    try:
        if await send_local_site_fallback(message, lang, lat, lon):
            return
    except Exception as e:
        log(f"Local fallback error: {e!r}")
    await message.answer(T(lang, "global_none", url=NA_WORLD_SEARCH_URL), reply_markup=jft_markup(lang))

async def send_nearby(message, lang: str, lat: float, lon: float, label: str = ""):
    # خارج از ایران: پایگاه داده جهانی NA + سایت محلی + لینک Google Maps
    if not in_iran(lat, lon):
        await send_global_nearby(message, lang, lat, lon, label)
        return
    # داخل ایران: سایت شورای فرامنطقه ایران + لینک نشان
    recs = await fetch_nearby(lat, lon)
    near, closest = pick_nearest(recs, lat, lon)
    where = f" ({label})" if label else ""
    r_km = f"{INPERSON_RADIUS_KM:g}"
    if near:
        await send_results(message, lang, T(lang, "nearby_header", where=where, r=r_km),
                           [format_location(r, d, "ir", lang) for d, r in near])
    elif closest:
        await send_results(message, lang, T(lang, "nearby_none_header", where=where, r=r_km),
                           [format_location(r, d, "ir", lang) for d, r in closest])
    else:
        await message.answer(T(lang, "no_meetings"), reply_markup=jft_markup(lang))

async def inperson_by_text(message, lang: str, query: str):
    q = (query or "").strip()
    if len(q) < 2 or len(q) > 60:
        await message.answer(T(lang, "type_short"))
        return
    tmp = await message.answer(T(lang, "searching"), reply_markup=ReplyKeyboardRemove())
    try:
        geo = None
        # کاربر فارسی: اول ایران، بعد سراسر جهان | کاربر انگلیسی: اول سراسر جهان
        order = [True, False] if lang == "fa" else [False, True]
        for n, iran_only in enumerate(order):
            try:
                geo = await geocode_place(q, lang, iran_only)
            except Exception as e:
                log(f"Geocode error: {e!r}")
            if geo:
                break
            if n == 0:
                await asyncio.sleep(1.1)   # محدودیت نرخ Nominatim
        if geo:
            label = re.split(r"[،,]", geo[2])[0].strip()[:50] if geo[2] else q
            await send_nearby(message, lang, geo[0], geo[1], label)
        else:
            # راه دوم: جست‌وجوی متنی در فهرست همه جلسات ایران
            recs = await fetch_all_locations()
            nq = _squash(q)
            hits = [r for r in recs if nq in _squash(json.dumps(r, ensure_ascii=False))][:INPERSON_MAX]
            if hits:
                await send_results(message, lang, T(lang, "text_results_header", q=q),
                                   [format_location(r, nav="ir", lang=lang) for r in hits])
            else:
                await message.answer(T(lang, "no_place"))
    except Exception as e:
        log(f"In-person search error: {e!r}")
        traceback.print_exc()
        await message.answer(T(lang, "inperson_fail"))
    finally:
        try:
            await tmp.delete()
        except Exception:
            pass

# ----- هندلرهای جلسات حضوری -----
@dp.callback_query(F.data == "menu_inperson")
async def inperson_menu_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    user_states[callback.from_user.id] = "waiting_for_location"
    await callback.answer()
    text = T(lang, "inperson_intro")
    try:
        from baleio.types import ReplyKeyboardMarkup, KeyboardButton
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=T(lang, "btn_send_location"), request_location=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        )
        await callback.message.answer(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text)

@dp.message(F.location)
async def handle_location(message: Message):
    user = message.from_user
    if not user:
        return
    lang = get_lang(user.id)
    if user_states.get(user.id) != "waiting_for_location":
        await message.answer(T(lang, "inperson_need_menu"), reply_markup=main_markup(lang))
        return
    loc = message.location
    tmp = await message.answer(T(lang, "searching_near"), reply_markup=ReplyKeyboardRemove())
    try:
        await send_nearby(message, lang, float(loc.latitude), float(loc.longitude))
    except Exception as e:
        log(f"Location search error: {e!r}")
        traceback.print_exc()
        await message.answer(T(lang, "inperson_fail"))
    finally:
        try:
            await tmp.delete()
        except Exception:
            pass

@dp.message(Command("debuglocation"))
async def debug_location_handler(message: Message):
    """ویژه ادمین: نمایش ساختار یک رکورد جلسه حضوری (نمونه: مرکز تهران) + نمونه جهانی (پاریس)."""
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    try:
        recs = await fetch_nearby(35.6892, 51.3890)
        near, _ = pick_nearest(recs, 35.6892, 51.3890)
        rep = [f"records={len(recs)} within_{INPERSON_RADIUS_KM:g}km={len(near)}"]
        if recs:
            rep.append("keys: " + str(list(recs[0].keys())))
            rep.append("RAW:\n" + json.dumps(recs[0], ensure_ascii=False)[:1500])
            rep.append("FORMATTED (ir/fa):\n" + format_location(recs[0], nav="ir", lang="fa"))
            rep.append("FORMATTED (global nav/en):\n" + format_location(recs[0], nav="global", lang="en"))
        try:
            g_recs = await fetch_global_nearby(48.8566, 2.3522)
            groups = group_global(g_recs, 48.8566, 2.3522)
            rep.append(f"GLOBAL (Paris) records={len(g_recs)} groups={len(groups)}")
            if g_recs:
                rep.append("global keys: " + str(list(g_recs[0].keys())))
            if groups:
                rep.append("GLOBAL FORMATTED:\n" + format_global(groups[0], "en"))
        except Exception as e:
            rep.append(f"GLOBAL error: {type(e).__name__}: {e}")
        for chunk in split_text("\n\n".join(rep), 3500):
            await message.answer(chunk)
    except Exception as e:
        await message.answer(f"❌ خطا: {type(e).__name__}: {e}"[:3500])

@dp.message(Command("testlocal"))
async def test_local_handler(message: Message):
    """ویژه ادمین: آزمایش جستجوی سایت محلی NA (نمونه: استانبول). برای مکان دیگر: /testlocal lat lon"""
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    lat, lon = 41.0082, 28.9784
    parts = (message.text or "").split()
    if len(parts) >= 3:
        try:
            lat, lon = float(parts[1]), float(parts[2])
        except ValueError:
            pass
    try:
        lang = get_lang(message.from_user.id)
        ok = await send_local_site_fallback(message, lang, lat, lon)
        if not ok:
            await message.answer("❌ جلسه‌ای از سایت محلی استخراج نشد (لاگ سرور را ببینید).")
    except Exception as e:
        await message.answer(f"❌ {type(e).__name__}: {e}"[:3500])

# =========================================================
# روزشمار پاکی (انتخاب سال/ماه/روز با دکمه‌های شیشه‌ای)
#   فارسی: تقویم شمسی | English: Gregorian calendar
# =========================================================
from datetime import date, datetime, timedelta, timezone

JMONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
           "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
GMONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]
CLEAN_MAX_YEARS_BACK = int(os.getenv("CLEAN_MAX_YEARS_BACK", "60"))
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

def fa_num(x) -> str:
    return str(x).translate(_FA_DIGITS)

def jalali_to_gregorian(jy: int, jm: int, jd: int):
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    sal_a = [0, 31, 29 if ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd

def gregorian_to_jalali(gy: int, gm: int, gd: int):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd

def jalali_month_len(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if gregorian_to_jalali(*jalali_to_gregorian(jy, 12, 30)) == (jy, 12, 30) else 29

def today_jalali():
    now = datetime.now(timezone(timedelta(hours=3, minutes=30)))   # وقت ایران
    return gregorian_to_jalali(now.year, now.month, now.day), date(now.year, now.month, now.day)

# --- توابع مستقل از نوع تقویم ---
def cal_today(lang: str):
    """(سال، ماه، روز) امروز در تقویم زبان کاربر + تاریخ میلادی معادل."""
    if lang == "fa":
        return today_jalali()
    now = datetime.now(timezone.utc)
    d = date(now.year, now.month, now.day)
    return (d.year, d.month, d.day), d

def cal_month_len(lang: str, y: int, m: int) -> int:
    return jalali_month_len(y, m) if lang == "fa" else calendar.monthrange(y, m)[1]

def cal_to_greg(lang: str, y: int, m: int, d: int):
    return jalali_to_gregorian(y, m, d) if lang == "fa" else (y, m, d)

def month_names(lang: str):
    return JMONTHS if lang == "fa" else GMONTHS

def num(lang: str, x) -> str:
    return fa_num(x) if lang == "fa" else str(x)

def fmt_date(lang: str, y: int, m: int, d: int) -> str:
    if lang == "fa":
        return f"{fa_num(d)} {JMONTHS[m - 1]} {fa_num(y)}"
    return f"{GMONTHS[m - 1]} {d}, {y}"

def clean_time(lang: str, sy: int, sm: int, sd: int):
    """مدت پاکی از تاریخ شروع تا امروز: (سال، ماه، روز، مجموع روز) یا None اگر تاریخ آینده باشد."""
    (ty, tm, td), today_g = cal_today(lang)
    start_g = date(*cal_to_greg(lang, sy, sm, sd))
    total = (today_g - start_g).days
    if total < 0:
        return None
    y, m, d = ty - sy, tm - sm, td - sd
    if d < 0:
        pm, py = (tm - 1, ty) if tm > 1 else (12, ty - 1)
        d += cal_month_len(lang, py, pm)
        m -= 1
    if m < 0:
        m += 12
        y -= 1
    return y, m, d, total

def _duration_text(lang: str, y: int, m: int, d: int) -> str:
    if lang == "fa":
        parts = [f"{fa_num(v)} {u}" for v, u in ((y, "سال"), (m, "ماه"), (d, "روز")) if v]
        return " و ".join(parts) if parts else T(lang, "first_day")

    def unit(v, s):
        return f"{v} {s}" + ("" if v == 1 else "s")
    parts = [unit(v, s) for v, s in ((y, "year"), (m, "month"), (d, "day")) if v]
    if not parts:
        return T(lang, "first_day")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]

def clean_result_text(lang: str, sy: int, sm: int, sd: int) -> str:
    res = clean_time(lang, sy, sm, sd)
    if res is None:
        return T(lang, "clean_future")
    y, m, d, total = res
    (ty, tm, td), _ = cal_today(lang)
    return T(
        lang, "clean_result",
        start=fmt_date(lang, sy, sm, sd),
        today=fmt_date(lang, ty, tm, td),
        duration=_duration_text(lang, y, m, d),
        total=num(lang, total),
    )

def _clean_years_markup(lang: str, page: int):
    (ty, _, _), _ = cal_today(lang)
    min_year = ty - CLEAN_MAX_YEARS_BACK
    years = [ty - page * 12 - i for i in range(12) if ty - page * 12 - i >= min_year]
    kb = InlineKeyboardBuilder()
    for y in years:
        kb.button(text=num(lang, y), callback_data=f"cc_y_{y}")
    sizes = [4] * (len(years) // 4) + ([len(years) % 4] if len(years) % 4 else [])
    nav = 0
    if page > 0:
        kb.button(text=T(lang, "newer"), callback_data=f"cc_yp_{page - 1}")
        nav += 1
    if ty - (page + 1) * 12 >= min_year:
        kb.button(text=T(lang, "older"), callback_data=f"cc_yp_{page + 1}")
        nav += 1
    if nav:
        sizes.append(nav)
    kb.button(text=T(lang, "back"), callback_data="back_to_main")
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()

def _clean_months_markup(lang: str, year: int):
    (ty, tm, _), _ = cal_today(lang)
    last = tm if year == ty else 12
    names = month_names(lang)
    kb = InlineKeyboardBuilder()
    for m in range(1, last + 1):
        kb.button(text=names[m - 1], callback_data=f"cc_m_{year}_{m}")
    sizes = [3] * (last // 3) + ([last % 3] if last % 3 else [])
    kb.button(text=T(lang, "back_year"), callback_data="cc_yp_0")
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()

def _clean_days_markup(lang: str, year: int, month: int):
    (ty, tm, td), _ = cal_today(lang)
    last = cal_month_len(lang, year, month)
    if (year, month) == (ty, tm):
        last = min(last, td)
    kb = InlineKeyboardBuilder()
    for d in range(1, last + 1):
        kb.button(text=num(lang, d), callback_data=f"cc_d_{year}_{month}_{d}")
    sizes = [7] * (last // 7) + ([last % 7] if last % 7 else [])
    kb.button(text=T(lang, "back_month"), callback_data=f"cc_y_{year}")
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()

async def _clean_show(callback: CallbackQuery, text: str, markup):
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)

@dp.callback_query(F.data == "menu_clean")
async def clean_menu_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    await callback.answer()
    await _clean_show(callback, T(lang, "clean_title"), _clean_years_markup(lang, 0))

@dp.callback_query(F.data.startswith("cc_"))
async def clean_callback_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    await callback.answer()
    try:
        p = callback.data.split("_")
        kind = p[1]
        if kind == "yp":
            await _clean_show(callback, T(lang, "clean_title"), _clean_years_markup(lang, int(p[2])))
        elif kind == "y":
            y = int(p[2])
            await _clean_show(callback, T(lang, "clean_year_title", y=num(lang, y)), _clean_months_markup(lang, y))
        elif kind == "m":
            y, m = int(p[2]), int(p[3])
            await _clean_show(callback,
                              T(lang, "clean_month_title", m=month_names(lang)[m - 1], y=num(lang, y)),
                              _clean_days_markup(lang, y, m))
        elif kind == "d":
            y, m, d = int(p[2]), int(p[3]), int(p[4])
            kb = InlineKeyboardBuilder()
            kb.button(text=T(lang, "recalc"), callback_data="cc_yp_0")
            kb.button(text=T(lang, "back"), callback_data="back_to_main")
            kb.adjust(1)
            await _clean_show(callback, clean_result_text(lang, y, m, d), kb.as_markup())
    except Exception:
        traceback.print_exc()
        await callback.message.answer(T(lang, "clean_err"), reply_markup=main_markup(lang))

@dp.message(Command("testai"))
async def test_ai_handler(message: Message):
    """ویژه ادمین: آزمایش جداگانه هر سرویس (گفتگو، متن به ویس، ویس به متن)."""
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    if not AI_PROVIDERS:
        await message.answer("❌ هیچ سرویس هوش مصنوعی ساخته نشده (AI_API_KEY / AI2_API_KEY و AI2_BASE_URL و پکیج openai را بررسی کنید).")
        return
    for p in AI_PROVIDERS:
        c = p["client"]
        rep = [f"🔧 سرویس «{p['name']}»\nbase_url={c.base_url}\nchat={p['chat']} stt={p['stt']} tts={p['tts']} voice={p['voice']}"]
        try:
            r = await c.chat.completions.create(
                model=p["chat"], messages=[{"role": "user", "content": "سلام"}], max_tokens=20)
            rep.append("✅ chat: " + (r.choices[0].message.content or "")[:60])
        except Exception as e:
            rep.append(f"❌ chat: {type(e).__name__}: {e}")
        audio = None
        try:
            resp = await c.audio.speech.create(model=p["tts"], voice=p["voice"],
                                               input="سلام، حال شما چطور است؟", response_format="opus")
            audio = resp.content
            rep.append(f"✅ tts: {len(audio)} bytes")
        except Exception as e:
            rep.append(f"❌ tts: {type(e).__name__}: {e}")
        if audio:
            try:
                res = await c.audio.transcriptions.create(
                    model=p["stt"], file=("voice.ogg", audio, "audio/ogg"), language="fa")
                rep.append(f"✅ stt: {(res.text or '')[:80]}")
            except Exception as e:
                rep.append(f"❌ stt: {type(e).__name__}: {e}")
        await message.answer("\n\n".join(rep)[:3500])

# =========================================================
# اجرا
# =========================================================
async def main():
    log("✅ ربات بله با موفقیت اجرا شد.")
    try:
        await dp.start_polling(bot)
    except Exception:
        log("❌ خطا در اجرای ربات بله:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
