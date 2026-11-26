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
    kb.button(text="دفتر خدمات جهانی NA ایران", url="mailto:info@wsoiran.org")
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
    kb.adjust(1, 2, 2, 2, 2, 1, 1, 1)
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
        file=("voice.ogg", file_bytes, "audio/ogg"),
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

    stage = "download"
    try:
        # 1) دانلود ویس
        file = await bot.get_file(message.voice.file_id)
        audio_bytes = await download_bale_file(file.file_path)

        # 2) ویس -> متن
        stage = "stt"
        user_text = await voice_to_text(audio_bytes)
        if not user_text:
            await message.answer("🎙 متوجه صدا نشدم، لطفاً دوباره و واضح‌تر بفرستید.")
            return

        # 3) پاسخ هوش مصنوعی
        stage = "chat"
        ai_reply = await ask_ai(user.id, user_text)
    except Exception as e:
        log(f"Voice AI Error [{stage}]: {e!r}")
        traceback.print_exc()
        await report_admin(f"🛠 خطای ویس (مرحله {stage}):\n{type(e).__name__}: {e}")
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

    # 1.5 جستجوی جلسات حضوری با نام شهر/روستا
    if state == "waiting_for_location":
        await inperson_by_text(message, message.text)
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
            await report_admin(f"🛠 خطای گفتگوی هوشمند:\n{type(e).__name__}: {e}")
            await message.answer("❌ متاسفانه در حال حاضر نمی‌توانم پاسخ دهم. لطفاً بعداً تلاش کنید یا /start را بزنید.")
        return

    # 3. پیام‌های متفرقه
    await message.answer(
        "لطفاً از دکمه‌های منوی زیر استفاده کنید:",
        reply_markup=main_markup()
    )

# ----- عیب‌یابی صفحه جلسات حضوری (ویژه ادمین) -----
INPERSON_URL = os.getenv("INPERSON_URL", "https://nairan.org/fa/meetings")

@dp.message(Command("debugmeetings"))
async def debug_meetings_handler(message: Message):
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    import httpx
    from urllib.parse import urljoin
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
# جلسات حضوری (لوکیشن یا نام شهر/روستا)
# =========================================================
import json
import math

INPERSON_RADIUS_KM = float(os.getenv("INPERSON_RADIUS_KM", "20"))   # شعاع جست‌وجو
INPERSON_MAX = int(os.getenv("INPERSON_MAX", "8"))                  # حداکثر تعداد جلسه در پاسخ
GEOCODE_URL = os.getenv("GEOCODE_URL", "https://nominatim.openstreetmap.org/search")

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

def _sessions_lines(label: str, sessions) -> list:
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
    out = [label]
    for time_, days in groups.items():
        out.append("   " + "، ".join(d for d in days if d) + (f" ⏰ {time_}" if time_ else ""))
    return out

def format_location(rec: dict, dist_km=None) -> str:
    title = re.sub(r"\s+", " ", str(rec.get("name") or rec.get("group_name") or "جلسه")).strip()
    head = f"🔹 {title}"
    if dist_km is not None:
        head += f"  ({dist_km:.1f} کیلومتر)"
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
        lines.append("📍 " + "، ".join(parts))
    if txt("phone"):
        lines.append(f"📞 {txt('phone')}")
    if txt("gender"):
        lines.append(f"👥 {txt('gender')}")
    if txt("feature"):
        lines.append(f"✨ {txt('feature')}")

    lines += _sessions_lines("🟢 جلسات باز:", rec.get("openSessions"))
    lines += _sessions_lines("🔒 جلسات بسته:", rec.get("closedSessions"))

    notes = _clean_html(str(rec.get("notes") or ""))
    if notes:
        lines.append("📝 " + notes[:200])
    try:
        lines.append(f"🗺 https://maps.google.com/?q={float(rec['lat']):.6f},{float(rec['lng']):.6f}")
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

async def geocode_place(q: str):
    """نام شهر/روستا -> (lat, lon, نام یافت‌شده)؛ اگر پیدا نشد None."""
    import httpx
    params = {"q": q, "format": "json", "limit": 1, "countrycodes": "ir", "accept-language": "fa"}
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

async def send_results(message, header: str, items):
    text = header + "\n\n" + "\n\n".join(items)
    chunks = split_text(text, 3500)
    for i, ch in enumerate(chunks):
        if i == len(chunks) - 1:
            await message.answer(ch, reply_markup=jft_markup())
        else:
            await message.answer(ch)

async def send_nearby(message, lat: float, lon: float, label: str = ""):
    recs = await fetch_nearby(lat, lon)
    near, closest = pick_nearest(recs, lat, lon)
    where = f" ({label})" if label else ""
    if near:
        await send_results(message, f"🏢 جلسات حضوری نزدیک شما{where} — تا {INPERSON_RADIUS_KM:g} کیلومتر",
                           [format_location(r, d) for d, r in near])
    elif closest:
        await send_results(message, f"ℹ️ در شعاع {INPERSON_RADIUS_KM:g} کیلومتری{where} جلسه‌ای پیدا نشد. نزدیک‌ترین جلسات:",
                           [format_location(r, d) for d, r in closest])
    else:
        await message.answer("ℹ️ جلسه‌ای برای این محدوده پیدا نشد.", reply_markup=jft_markup())

async def inperson_by_text(message, query: str):
    q = (query or "").strip()
    if len(q) < 2 or len(q) > 60:
        await message.answer("لطفاً نام شهر یا روستا را کوتاه و واضح بنویسید، یا لوکیشن خود را بفرستید.")
        return
    tmp = await message.answer("🔎 در حال جستجو…", reply_markup=ReplyKeyboardRemove())
    try:
        geo = None
        try:
            geo = await geocode_place(q)
        except Exception as e:
            log(f"Geocode error: {e!r}")
        if geo:
            label = geo[2].split("،")[0][:50] if geo[2] else q
            await send_nearby(message, geo[0], geo[1], label)
        else:
            # راه دوم: جست‌وجوی متنی در فهرست همه جلسات
            recs = await fetch_all_locations()
            nq = _squash(q)
            hits = [r for r in recs if nq in _squash(json.dumps(r, ensure_ascii=False))][:INPERSON_MAX]
            if hits:
                await send_results(message, f"🏢 جلسات حضوری «{q}»", [format_location(r) for r in hits])
            else:
                await message.answer("ℹ️ مکانی با این نام پیدا نشد. نام شهر را کامل‌تر بنویسید یا لوکیشن خود را بفرستید.")
    except Exception as e:
        log(f"In-person search error: {e!r}")
        traceback.print_exc()
        await message.answer("❌ الان نتوانستم لیست جلسات حضوری را دریافت کنم. لطفاً چند دقیقه بعد دوباره تلاش کنید.")
    finally:
        try:
            await tmp.delete()
        except Exception:
            pass

# ----- هندلرهای جلسات حضوری -----
@dp.callback_query(F.data == "menu_inperson")
async def inperson_menu_handler(callback: CallbackQuery):
    user_states[callback.from_user.id] = "waiting_for_location"
    await callback.answer()
    text = (
        "🏢 جستجوی جلسات حضوری\n\n"
        "📍 لوکیشن خود را بفرستید (از دکمه پایین، یا از منوی پیوست 📎 گزینه «موقعیت مکانی»)\n"
        "یا ✍️ نام شهر یا روستای خود را بنویسید.\n\n"
        "برای خروج، دستور /start را بزنید."
    )
    try:
        from baleio.types import ReplyKeyboardMarkup, KeyboardButton
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📍 ارسال موقعیت من", request_location=True)]],
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
    if user_states.get(user.id) != "waiting_for_location":
        await message.answer("📍 برای جستجوی جلسات حضوری، اول از منو دکمه «🔍 جستجوی جلسات حضوری» را بزنید.", reply_markup=main_markup())
        return
    loc = message.location
    tmp = await message.answer("🔎 در حال جستجوی جلسات نزدیک شما…", reply_markup=ReplyKeyboardRemove())
    try:
        await send_nearby(message, float(loc.latitude), float(loc.longitude))
    except Exception as e:
        log(f"Location search error: {e!r}")
        traceback.print_exc()
        await message.answer("❌ الان نتوانستم لیست جلسات حضوری را دریافت کنم. لطفاً چند دقیقه بعد دوباره تلاش کنید.")
    finally:
        try:
            await tmp.delete()
        except Exception:
            pass

@dp.message(Command("debuglocation"))
async def debug_location_handler(message: Message):
    """ویژه ادمین: نمایش ساختار یک رکورد جلسه حضوری (نمونه: مرکز تهران)."""
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    try:
        recs = await fetch_nearby(35.6892, 51.3890)
        near, _ = pick_nearest(recs, 35.6892, 51.3890)
        rep = [f"records={len(recs)} within_{INPERSON_RADIUS_KM:g}km={len(near)}"]
        if recs:
            rep.append("keys: " + str(list(recs[0].keys())))
            rep.append("RAW:\n" + json.dumps(recs[0], ensure_ascii=False)[:1500])
            rep.append("FORMATTED:\n" + format_location(recs[0]))
        for chunk in split_text("\n\n".join(rep), 3500):
            await message.answer(chunk)
    except Exception as e:
        await message.answer(f"❌ خطا: {type(e).__name__}: {e}"[:3500])

# =========================================================
# روزشمار پاکی (انتخاب سال/ماه/روز با دکمه‌های شیشه‌ای)
# =========================================================
from datetime import date, datetime, timedelta, timezone

JMONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
           "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
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

def clean_time(sy: int, sm: int, sd: int):
    """مدت پاکی از تاریخ شمسی شروع تا امروز: (سال، ماه، روز، مجموع روز) یا None اگر تاریخ آینده باشد."""
    (ty, tm, td), today_g = today_jalali()
    start_g = date(*jalali_to_gregorian(sy, sm, sd))
    total = (today_g - start_g).days
    if total < 0:
        return None
    y, m, d = ty - sy, tm - sm, td - sd
    if d < 0:
        pm, py = (tm - 1, ty) if tm > 1 else (12, ty - 1)
        d += jalali_month_len(py, pm)
        m -= 1
    if m < 0:
        m += 12
        y -= 1
    return y, m, d, total

def clean_result_text(sy: int, sm: int, sd: int) -> str:
    res = clean_time(sy, sm, sd)
    if res is None:
        return "⚠️ تاریخ انتخاب‌شده در آینده است. لطفاً دوباره انتخاب کنید."
    y, m, d, total = res
    (ty, tm, td), _ = today_jalali()
    parts = [f"{fa_num(v)} {u}" for v, u in ((y, "سال"), (m, "ماه"), (d, "روز")) if v]
    duration = " و ".join(parts) if parts else "امروز اولین روز شماست"
    return (
        "📊 روزشمار پاکی\n\n"
        f"📅 تاریخ شروع پاکی: {fa_num(sd)} {JMONTHS[sm - 1]} {fa_num(sy)}\n"
        f"🗓 امروز: {fa_num(td)} {JMONTHS[tm - 1]} {fa_num(ty)}\n\n"
        f"🌿 مدت پاکی شما:\n{duration}\n"
        f"🔢 مجموع: {fa_num(total)} روز\n\n"
        "هر روز پاکی یک پیروزی است. 🌱🙏"
    )

def _clean_years_markup(page: int):
    (ty, _, _), _ = today_jalali()
    min_year = ty - CLEAN_MAX_YEARS_BACK
    years = [ty - page * 12 - i for i in range(12) if ty - page * 12 - i >= min_year]
    kb = InlineKeyboardBuilder()
    for y in years:
        kb.button(text=fa_num(y), callback_data=f"cc_y_{y}")
    sizes = [4] * (len(years) // 4) + ([len(years) % 4] if len(years) % 4 else [])
    nav = 0
    if page > 0:
        kb.button(text="جدیدتر ➡️", callback_data=f"cc_yp_{page - 1}")
        nav += 1
    if ty - (page + 1) * 12 >= min_year:
        kb.button(text="⬅️ قدیمی‌تر", callback_data=f"cc_yp_{page + 1}")
        nav += 1
    if nav:
        sizes.append(nav)
    kb.button(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()

def _clean_months_markup(year: int):
    (ty, tm, _), _ = today_jalali()
    last = tm if year == ty else 12
    kb = InlineKeyboardBuilder()
    for m in range(1, last + 1):
        kb.button(text=JMONTHS[m - 1], callback_data=f"cc_m_{year}_{m}")
    sizes = [3] * (last // 3) + ([last % 3] if last % 3 else [])
    kb.button(text="🔙 انتخاب سال", callback_data="cc_yp_0")
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()

def _clean_days_markup(year: int, month: int):
    (ty, tm, td), _ = today_jalali()
    last = jalali_month_len(year, month)
    if (year, month) == (ty, tm):
        last = min(last, td)
    kb = InlineKeyboardBuilder()
    for d in range(1, last + 1):
        kb.button(text=fa_num(d), callback_data=f"cc_d_{year}_{month}_{d}")
    sizes = [7] * (last // 7) + ([last % 7] if last % 7 else [])
    kb.button(text="🔙 انتخاب ماه", callback_data=f"cc_y_{year}")
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
    await callback.answer()
    await _clean_show(callback, "📊 روزشمار پاکی\n\nسال شروع پاکی خود را انتخاب کنید:", _clean_years_markup(0))

@dp.callback_query(F.data.startswith("cc_"))
async def clean_callback_handler(callback: CallbackQuery):
    await callback.answer()
    try:
        p = callback.data.split("_")
        kind = p[1]
        if kind == "yp":
            await _clean_show(callback, "📊 روزشمار پاکی\n\nسال شروع پاکی خود را انتخاب کنید:", _clean_years_markup(int(p[2])))
        elif kind == "y":
            y = int(p[2])
            await _clean_show(callback, f"📅 سال {fa_num(y)}\n\nماه شروع پاکی را انتخاب کنید:", _clean_months_markup(y))
        elif kind == "m":
            y, m = int(p[2]), int(p[3])
            await _clean_show(callback, f"📅 {JMONTHS[m - 1]} {fa_num(y)}\n\nروز شروع پاکی را انتخاب کنید:", _clean_days_markup(y, m))
        elif kind == "d":
            y, m, d = int(p[2]), int(p[3]), int(p[4])
            kb = InlineKeyboardBuilder()
            kb.button(text="🔄 محاسبه مجدد", callback_data="cc_yp_0")
            kb.button(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
            kb.adjust(1)
            await _clean_show(callback, clean_result_text(y, m, d), kb.as_markup())
    except Exception:
        traceback.print_exc()
        await callback.message.answer("❌ خطایی رخ داد. لطفاً دوباره از منو «📊 روزشمار پاکی» را بزنید.", reply_markup=main_markup())

@dp.message(Command("testai"))
async def test_ai_handler(message: Message):
    """ویژه ادمین: آزمایش گفتگو، تبدیل متن به ویس و ویس به متن."""
    if not message.from_user or str(message.from_user.id) != str(ADMIN_ID):
        return
    if ai_client is None:
        await message.answer("❌ کلاینت هوش مصنوعی ساخته نشده (AI_API_KEY یا پکیج openai را بررسی کنید).")
        return
    rep = [f"base_url={AI_BASE_URL}\nchat={AI_CHAT_MODEL} stt={AI_STT_MODEL} tts={AI_TTS_MODEL} voice={AI_TTS_VOICE}"]
    try:
        r = await ai_client.chat.completions.create(
            model=AI_CHAT_MODEL, messages=[{"role": "user", "content": "سلام"}], max_tokens=20)
        rep.append("✅ chat: " + (r.choices[0].message.content or "")[:60])
    except Exception as e:
        rep.append(f"❌ chat: {type(e).__name__}: {e}")
    audio = None
    try:
        audio = await text_to_voice("سلام، حال شما چطور است؟")
        rep.append(f"✅ tts: {len(audio)} bytes")
    except Exception as e:
        rep.append(f"❌ tts: {type(e).__name__}: {e}")
    if audio:
        try:
            txt = await voice_to_text(audio)
            rep.append(f"✅ stt: {txt[:80]}")
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
