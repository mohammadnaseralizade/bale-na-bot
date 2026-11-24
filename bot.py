import os
import sys
import traceback
import asyncio
import sqlite3
import random

from baleio import Bot, Dispatcher, F
from baleio.filters import CommandStart, Command
from baleio.types import Message, ReplyKeyboardRemove, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
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

if not TOKEN:
    log("❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    sys.exit(1)

dp = Dispatcher()
bot = Bot(token=TOKEN)

# =========================================================
# راه‌اندازی کلاینت هوش مصنوعی (ایمن)
# اگر پکیج openai نصب نباشد یا کلید تنظیم نشده باشد، ربات بدون AI بالا می‌آید
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
# کیبوردها
# =========================================================
def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="اطلاع از جلسات آنلاین")],
            [KeyboardButton(text="🔍 جستجوی جلسات حضوری")],
            [KeyboardButton(text="📊 روزشمار پاکی")],
            [KeyboardButton(text="🌿 پیام امید امروز")],
            [KeyboardButton(text="✉️ ارتباط با کنفرانس خدمات جهانی NA")],
            [KeyboardButton(text="🤫 ارسال پیام به سازنده")],
            [KeyboardButton(text="🤖 گفتگوی هوشمند")],
        ],
        resize_keyboard=True,
    )

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
        await message.answer("در حال بارگذاری منو...", reply_markup=ReplyKeyboardRemove())
        await message.answer(WELCOME_TEXT, reply_markup=main_reply_keyboard())
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

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: CallbackQuery):
    user_states.pop(callback.from_user.id, None)
    await callback.message.edit_text("منوی ایمیل‌ها بسته شد.")
    await callback.message.answer(WELCOME_TEXT, reply_markup=main_reply_keyboard())
    await callback.answer()

# ----- هندلرهای دکمه‌های کیبورد پایین -----
@dp.message(F.text == "اطلاع از جلسات آنلاین")
async def online_meetings(message: Message):
    await message.answer("لینک جلسات آنلاین:\nhttps://nairan1.org/onlinemeeting/")

@dp.message(F.text == "🔍 جستجوی جلسات حضوری")
async def inperson_meetings(message: Message):
    await message.answer("لینک جستجوی جلسات حضوری:\nhttps://nairan.org/fa/meetings")

@dp.message(F.text == "📊 روزشمار پاکی")
async def clean_calendar(message: Message):
    await message.answer("لینک روزشمار پاکی:\nhttps://nairan.org/fa/cleanlinesscalendar")

@dp.message(F.text == "🌿 پیام امید امروز")
async def daily_quote_msg(message: Message):
    text = (
        "🌿 **پیام امید امروز (فقط برای امروز)**\n\n"
        "برای مطالعه متن امروز و مشاهده تقویم، روی لینک زیر کلیک کنید:\n"
        "👉 https://jft.nairan1.org/"
    )
    await message.answer(text)

@dp.message(F.text == "✉️ ارتباط با کنفرانس خدمات جهانی NA")
async def global_services_msg(message: Message):
    await message.answer(EMAIL_TEXT, reply_markup=email_inline_keyboard().as_markup())

@dp.message(F.text == "🤫 ارسال پیام به سازنده")
async def anon_msg_msg(message: Message):
    if not message.from_user:
        return
    user_states[message.from_user.id] = "waiting_for_admin_msg"
    await message.answer("📝 لطفاً متن پیام خود را برای سازنده بنویسید.")

@dp.message(F.text == "🤖 گفتگوی هوشمند")
async def activate_ai(message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    user_states[user_id] = "waiting_for_ai"
    ai_chat_history[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await message.answer(
        "🤖 **دستیار هوشمند NA در خدمت شماست.**\n\n"
        "می‌توانید سوالات خود را درباره انجمن، مسیر بهبودی یا جلسات بپرسید. من اینجا هستم تا با هم صحبت کنیم.\n\n"
        "⚠️ **توجه:** برای حفظ حریم خصوصی، لطفاً نام، شماره تماس یا آدرس خود را برای من نفرستید.\n"
        "برای خروج از این بخش، دکمه «/start» را بزنید."
    )

# ----- هندلر اصلی برای دریافت متن‌ها (باید آخرین هندلر پیام باشد) -----
@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text_inputs(message: Message):
    user = message.from_user
    if not user:
        return

    user_id = user.id
    state = user_states.get(user_id)

    # 1. اگر در حالت ارسال پیام به ادمین است
    if state == "waiting_for_admin_msg":
        user_states.pop(user_id, None)
        try:
            save_message(user.id, user.first_name, user.username, message.text)
        except Exception as e:
            log(f"Error saving message: {e}")
        if not ADMIN_ID:
            await message.answer("⚠️ متاسفانه ارسال پیام به سازنده در حال حاضر غیرفعال است.", reply_markup=main_reply_keyboard())
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
            await message.answer("✅ پیام شما با موفقیت برای سازنده ارسال شد.", reply_markup=main_reply_keyboard())
        except Exception as e:
            log(f"Error sending msg to admin: {e}")
            await message.answer("❌ خطا در ارسال پیام. لطفاً بعداً تلاش کنید.", reply_markup=main_reply_keyboard())
        return

    # 2. اگر در حالت گفتگو با هوش مصنوعی است
    if state == "waiting_for_ai":
        if ai_client is None:
            await message.answer("⚠️ سرویس هوش مصنوعی در حال حاضر غیرفعال است.")
            return
        try:
            history = ai_chat_history.setdefault(user_id, [{"role": "system", "content": SYSTEM_PROMPT}])
            history.append({"role": "user", "content": message.text})
            if len(history) > 11:
                history[:] = [history[0]] + history[-10:]

            response = await ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=history,
                max_tokens=500,
                temperature=0.7
            )
            ai_reply = response.choices[0].message.content
            history.append({"role": "assistant", "content": ai_reply})

            await message.answer(ai_reply)
        except Exception as e:
            log(f"AI Error: {e}")
            await message.answer("❌ متاسفانه در حال حاضر نمی‌توانم پاسخ دهم. لطفاً بعداً تلاش کنید یا از منو استفاده کنید.")
        return

    # 3. پیام‌های متفرقه
    await message.answer("لطفاً از دکمه‌های منو استفاده کنید یا برای گفتگو با هوش مصنوعی دکمه «🤖 گفتگوی هوشمند» را بزنید.", reply_markup=main_reply_keyboard())

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
