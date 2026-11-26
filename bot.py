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
    "روی هر دکمه بزنید تا مستقیماً برای آن بخش ایمیل بفرستید.\n\n"
    "🇮🇷 برای ارتباط با خدمات جهانی NA ایران از دکمه اول (info@wsoiran.org) استفاده کنید."
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
    # دکمه‌های عملیاتی
    kb.button(text="💻 اطلاع از جلسات آنلاین", callback_data="menu_online")
    kb.button(text="🔍 جستجوی جلسات حضوری", callback_data="menu_inperson")
    kb.button(text="📊 روزشمار پاکی", callback_data="menu_clean")
    kb.button(text="🌿 پیام امید امروز", callback_data="menu_jft")
    # سه دکمه لینک‌دار شوراهای فرامنطقه: مستقیم لینک را باز می‌کنند
    kb.button(text="🌐 شورای فرامنطقه ایران", url="https://nairan.org/fa")
    kb.button(text="🌐 شورای فرامنطقه APF", url="https://fa.apfna.org/farsi-home")
    kb.button(text="🌐 شورای فرامنطقه EDM", url="https://edmna.org/")
    # بقیه دکمه‌ها
    kb.button(text="✉️ ارتباط با کنفرانس خدمات جهانی NA", callback_data="menu_email")
    kb.button(text="🤫 ارسال پیام به سازنده", callback_data="menu_admin_msg")
    kb.button(text="🤖 گفتگوی هوشمند", callback_data="menu_ai")
    kb.adjust(1)
    return kb

def email_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    # دکمه ارتباط با خدمات جهانی NA ایران (ایمیل فارسی)
    kb.button(text="🌐 ارتباط با خدمات جهانی NA ایران", url="mailto:info@wsoiran.org")
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
    # چیدمان: دکمه اصلی ایران در ردیف اول به تنهایی، بقیه ۲ تایی
    kb.adjust(1, 2, 2, 2, 2, 2, 1, 1)
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
            root = soup.select