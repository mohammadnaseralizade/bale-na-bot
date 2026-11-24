import os
import sys
import traceback
import asyncio
import sqlite3
import io
import re
import time
import tempfile

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
JFT_URL = os.getenv("JFT_URL", "https://jft.nairan1.org/")
JFT_SELECTOR = os.getenv("JFT_SELECTOR", "")   # اختیاری: سلکتور CSS بخش متن در سایت
JFT_CACHE_SECONDS = int(os.getenv("JFT_CACHE_SECONDS", "1800"))
ONLINE_URL = os.getenv("ONLINE_URL", "https://nairan1.org/onlinemeeting/")
ONLINE_SELECTOR = os.getenv("ONLINE_SELECTOR", "")   # اختیاری: سلکتور CSS بخش لیست جلسات
ONLINE_CACHE_SECONDS = int(os.getenv("ONLINE_CACHE_SECONDS", "600"))
ONLINE_MAX_CHARS = int(os.getenv("ONLINE_MAX_CHARS", "8000"))
MAX_VOICE_SECONDS = int(os.getenv("MAX_VOICE_SECONDS", "60"))
MAX_VOICE_BYTES = int(os.getenv("MAX_VOICE_BYTES", str(2 * 1024 * 1024)))

if not TOKEN:
    log("❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    sys.exit(1)

dp = Dispatcher()
bot = Bot(token=TOKEN)

# =========================================================
# راه‌اندازی کلاینت هوش مصنوعی (ایمن)
# =========================================================
ai_client = None
if AI_API_KEY:
    try:
        from openai import AsyncOpenAI
        ai_client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        log("✅ کلاینت هوش مصنوعی آماده شد.")
    except Exception:
        log("⚠️ راه‌اندازی هوش مصنوعی ناموفق بود (پکیج openai نصب است؟):")
        traceback.print_exc()
else:
    log("⚠️ AI_API_KEY تنظیم نشده؛ گفتگوی هوشمند غیرفعال است.")

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

# =========================================================
# متن‌ها و پرامپت هوش مصنوعی
# =========================================================
WELCOME_TEXT = (
    "مرکز جامع خدمات و منابع انجمن معتادان گمنام (NA) 🌐🤝\n\n"
    "دریافت اطلاعات درباره NA 📚، جلسات مجازی 💻🌍، جلسات حضوری 🏢📍 و ارتباط مستقیم با کنفرانس خدمات جهانی(NA) 📞🌐. "
    "راهنمای همراه شما در مسیر بهبودی 🌱✨، بدون پیچیدگی و کاملاً سریع ⚡👌\n\n"
    "💡 شما می‌توانید سوالات خود را درباره NA بپرسید یا از منوی زیر استفاده کنید:"
)

EMAIL_TEXT = (
    "بخش‌های ارتباطی خدمات جهانی NA\n"
    "روی هر دکمه بزنید تا مستقیماً برای آن بخش ایمیل بفرستید."
)

SYSTEM_PROMPT = (
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

# =========================================================
# کیبوردهای شیشه‌ای (Inline)
# =========================================================
def main_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    # دکمه‌های لینک‌دار: مستقیم لینک را باز می‌کنند
    kb.button(text="💻 اطلاع از جلسات آنلاین", callback_data="menu_online")
    kb.button(text="🔍 جستجوی جلسات حضوری", url="https://nairan.org/fa/meetings")
    kb.button(text="📊 روزشمار پاکی", url="https://nairan.org/fa/cleanlinesscalendar")
    kb.button(text="🌿 پیام امید امروز", callback_data="menu_jft")
    # دکمه‌های عملیاتی
    kb.button(text="✉️ ارتباط با کنفرانس خدمات جهانی NA", callback_data="menu_email")
    kb.button(text="🤫 ارسال پیام به سازنده", callback_data="menu_admin_msg")
    kb.button(text="🤖 گفتگوی هوشمند", callback_data="menu_ai")
    kb.adjust(1)
    return kb

def email_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="اطلاعات عمومی و فلووشیپ", url="mailto:fsmail@na.org")
    kb.button(text="خدمات مشتری (سفارشات)", url="mailto:customer_service@na.org")
    kb.button(text="هیئت جهانی", url="mailto:worldboard@na.org")
    kb.button(text="منابع انسانی", url="mailto:hrp@na.org")
    kb.button(text="روابط عمومی", url="mailto:pr@na.org")
    kb.button(text="بیمارستان‌ها و موسسات", url="mailto:handi@na.org")
    kb.button(text="وب‌سایت", url="mailto:webmaster@na.org")
    kb.button(text="رویدادها و کنوانسیون‌ها", url="mailto:events@na.org")
    kb.button(text="مجله The NA Way", url="mailto:naway@na.org")
    kb.button(text="کمک‌های مالی", url="mailto:contributions@na.org")
    kb.button(text="فرصت‌های شغلی", url="mailto:jobs@na.org")
    kb.button(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
    kb.adjust(2, 2, 2, 2, 2, 1, 1)
    return kb

def main_markup():
    return main_inline_keyboard().as_markup()

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

        await message.answer(WELCOME_TEXT, reply_markup=main_markup())
    except Exception:
        traceback.print_exc()
        await message.answer("❌ خطا در نمایش منو. لطفاً دوباره /start را بزنید.")

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
        await bot.send_message(chat_id=target_id, text=f"✉️ **پاسخ سازنده:**\n\n{parts[2]}")
        await message.answer("✅ پاسخ با موفقیت ارسال شد.")
    except Exception as e:
        log(f"Reply error: {e}")
        await message.answer(f"❌ خطا در ارسال: {e}")

# ----- پیام امید امروز (دریافت مستقیم از سایت) -----
_jft_cache = {"text": None, "time": 0.0}

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

def jft_markup():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
    kb.adjust(1)
    return kb.as_markup()

@dp.callback_query(F.data == "menu_jft")
async def jft_handler(callback: CallbackQuery):
    await callback.answer()
    try:
        text = await fetch_jft()
        await callback.message.answer("🌿 پیام امید امروز\n\n" + text, reply_markup=jft_markup())
    except Exception as e:
        log(f"JFT error: {e!r}")
        traceback.print_exc()
        # گزارش علت خطا برای ادمین
        if ADMIN_ID:
            try:
                await bot.send_message(chat_id=int(ADMIN_ID), text=f"🛠 خطای پیام امید امروز:\n{type(e).__name__}: {e}"[:3500])
            except Exception:
                pass
        await callback.message.answer(
            "⚠️ الان نتوانستم پیام امروز را دریافت کنم. لطفاً چند دقیقه بعد دوباره تلاش کنید.",
            reply_markup=jft_markup()
        )

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

from urllib.parse import urljoin, urlparse

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
    await callback.answer()
    try:
        text = await fetch_online()
        truncated = len(text) > ONLINE_MAX_CHARS
        if truncated:
            text = text[:ONLINE_MAX_CHARS].rsplit("\n", 1)[0]
        chunks = split_text("💻 جلسات آنلاین\n\n" + text)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            if is_last and truncated and ONLINE_SHOW_FULL_LIST_BUTTON:
                kb = InlineKeyboardBuilder()
                kb.button(text="🌐 مشاهده لیست کامل", url=ONLINE_URL)
                kb.button(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
                kb.adjust(1)
                await callback.message.answer(chunk, reply_markup=kb.as_markup())
            elif is_last:
                await callback.message.answer(chunk, reply_markup=jft_markup())
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
        await callback.message.answer(
            "⚠️ الان نتوانستم لیست جلسات آنلاین را دریافت کنم. لطفاً چند دقیقه بعد دوباره تلاش کنید.",
            reply_markup=jft_markup()
        )

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
    user_states.pop(callback.from_user.id, None)
    try:
        await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_markup())
    except Exception:
        await callback.message.answer(WELCOME_TEXT, reply_markup=main_markup())
    await callback.answer()

@dp.callback_query(F.data == "menu_email")
async def email_menu_handler(callback: CallbackQuery):
    try:
        await callback.message.edit_text(EMAIL_TEXT, reply_markup=email_inline_keyboard().as_markup())
    except Exception:
        await callback.message.answer(EMAIL_TEXT, reply_markup=email_inline_keyboard().as_markup())
    await callback.answer()

@dp.callback_query(F.data == "menu_admin_msg")
async def admin_msg_menu_handler(callback: CallbackQuery):
    user_states[callback.from_user.id] = "waiting_for_admin_msg"
    await callback.message.answer("📝 لطفاً متن پیام خود را برای سازنده بنویسید.")
    await callback.answer()

@dp.callback_query(F.data == "menu_ai")
async def ai_menu_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_states[user_id] = "waiting_for_ai"
    ai_chat_history[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await callback.message.answer(
        "🤖 **دستیار هوشمند NA در خدمت شماست.**\n\n"
        "می‌توانید سوالات خود را درباره انجمن، مسیر بهبودی یا جلسات بپرسید. من اینجا هستم تا با هم صحبت کنیم.\n\n"
        "🎙 هم می‌توانید متن بنویسید و هم ویس بفرستید؛ اگر ویس بفرستید، به صورت صوتی هم جواب می‌دهم.\n\n"
        "⚠️ **توجه:** برای حفظ حریم خصوصی، لطفاً نام، شماره تماس یا آدرس خود را برای من نفرستید.\n"
        "برای خروج از این بخش، دستور /start را بزنید."
    )
    await callback.answer()

# ----- توابع کمکی هوش مصنوعی و صوت -----
async def ask_ai(user_id: int, text: str) -> str:
    history = ai_chat_history.setdefault(user_id, [{"role": "system", "content": SYSTEM_PROMPT}])
    history.append({"role": "user", "content": text})
    if len(history) > 11:
        history[:] = [history[0]] + history[-10:]
    response = await ai_client.chat.completions.create(
        model=AI_CHAT_MODEL,
        messages=history,
        max_tokens=500,
        temperature=0.7
    )
    reply = response.choices[0].message.content
    history.append({"role": "assistant", "content": reply})
    return reply

async def voice_to_text(file_bytes: bytes) -> str:
    result = await ai_client.audio.transcriptions.create(
        model=AI_STT_MODEL,
        file=("voice.ogg", file_bytes),
        language="fa",
    )
    return (result.text or "").strip()

async def text_to_voice(text: str) -> bytes:
    response = await ai_client.audio.speech.create(
        model=AI_TTS_MODEL,
        voice=AI_TTS_VOICE,
        input=text[:1500],
        response_format="opus",   # ogg/opus، مناسب برای ویس
    )
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
    if user_states.get(user.id) != "waiting_for_ai":
        await message.answer("🎙 برای گفتگوی صوتی، اول از منو دکمه «🤖 گفتگوی هوشمند» را بزنید.", reply_markup=main_markup())
        return
    if ai_client is None:
        await message.answer("⚠️ سرویس هوش مصنوعی در حال حاضر غیرفعال است.")
        return
    # در بله duration ممکن است به میلی‌ثانیه باشد؛ پس نرمال‌سازی می‌کنیم
    raw_duration = getattr(message.voice, "duration", 0) or 0
    duration_sec = raw_duration / 1000 if raw_duration > 1000 else raw_duration
    file_size = getattr(message.voice, "file_size", 0) or 0
    log(f"Voice received: duration_raw={raw_duration}, duration_sec={duration_sec}, size={file_size}")
    if duration_sec > MAX_VOICE_SECONDS or file_size > MAX_VOICE_BYTES:
        await message.answer(f"⚠️ لطفاً ویس کوتاه‌تر از {MAX_VOICE_SECONDS} ثانیه بفرستید.")
        return

    try:
        # 1) دانلود ویس
        file = await bot.get_file(message.voice.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)

        # 2) ویس -> متن
        user_text = await voice_to_text(buf.getvalue())
        if not user_text:
            await message.answer("🎙 متوجه صدا نشدم، لطفاً دوباره و واضح‌تر بفرستید.")
            return

        # 3) پاسخ هوش مصنوعی
        ai_reply = await ask_ai(user.id, user_text)
    except Exception as e:
        log(f"Voice AI Error: {e}")
        traceback.print_exc()
        await message.answer("❌ متاسفانه نتوانستم ویس را پردازش کنم. لطفاً بعداً تلاش کنید یا پیام متنی بفرستید.")
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
    state = user_states.get(user_id)

    # 1. ارسال پیام به ادمین
    if state == "waiting_for_admin_msg":
        user_states.pop(user_id, None)
        try:
            save_message(user.id, user.first_name, user.username, message.text)
        except Exception as e:
            log(f"Error saving message: {e}")
        if not ADMIN_ID:
            await message.answer("⚠️ متاسفانه ارسال پیام به سازنده در حال حاضر غیرفعال است.", reply_markup=main_markup())
            return
        try:
            sender_info = (
                f"📩 **پیام جدید از طرف کاربر:**\n\n"
                f"👤 نام: {user.first_name}\n"
                f"🔗 نام کاربری: @{user.username if user.username else 'ندارد'}\n"
                f"🆔 آیدی عددی: `{user.id}`\n\n"
                f"📝 **متن پیام:**\n{message.text}\n\n"
                f"---\n"
                f"💡 برای پاسخ به این کاربر، از دستور زیر استفاده کنید:\n"
                f"`/reply {user.id} متن پاسخ شما`"
            )
            await bot.send_message(chat_id=int(ADMIN_ID), text=sender_info)
            await message.answer("✅ پیام شما با موفقیت برای سازنده ارسال شد.", reply_markup=main_markup())
        except Exception as e:
            log(f"Error sending msg to admin: {e}")
            await message.answer("❌ خطا در ارسال پیام. لطفاً بعداً تلاش کنید.", reply_markup=main_markup())
        return

    # 2. گفتگو با هوش مصنوعی (متنی)
    if state == "waiting_for_ai":
        if ai_client is None:
            await message.answer("⚠️ سرویس هوش مصنوعی در حال حاضر غیرفعال است.")
            return
        try:
            ai_reply = await ask_ai(user_id, message.text)
            await message.answer(ai_reply)
        except Exception as e:
            log(f"AI Error: {e}")
            await message.answer("❌ متاسفانه در حال حاضر نمی‌توانم پاسخ دهم. لطفاً بعداً تلاش کنید یا /start را بزنید.")
        return

    # 3. پیام‌های متفرقه
    await message.answer(
        "لطفاً از دکمه‌های منوی زیر استفاده کنید:",
        reply_markup=main_markup()
    )

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
