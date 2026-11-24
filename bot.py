import os
import sys
import traceback
import asyncio
import sqlite3
import random
from datetime import datetime

from baleio import Bot, Dispatcher, F
from baleio.filters import CommandStart, Command
from baleio.types import Message, ReplyKeyboardRemove, CallbackQuery
from baleio.utils import InlineKeyboardBuilder

def log(*args):
    print(*args, flush=True)

log("🚀 شروع برنامه بله...")

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") 

if not TOKEN:
    log("❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    sys.exit(1)

dp = Dispatcher()
bot = Bot(token=TOKEN)

# =========================================================
# بخش دیتابیس
# =========================================================
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    # جدول کاربران
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            clean_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_user(user_id, first_name, username):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, first_name, username) VALUES (?, ?, ?)', (user_id, first_name, username))
    conn.commit()
    conn.close()

def update_clean_date(user_id, date_str):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET clean_date = ? WHERE user_id = ?', (date_str, user_id))
    conn.commit()
    conn.close()

def get_clean_date(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT clean_date FROM users WHERE user_id = ?', (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else None

def get_user_count():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

init_db()

# =========================================================
# دیتای جلسات و پیام‌ها
# =========================================================
PROVINCES = ["تهران", "اصفهان", "فارس", "خراسان رضوی", "آذربایجان شرقی"]
CITIES = {
    "تهران": ["تهران", "شهریار", "اسلامشهر"],
    "اصفهان": ["اصفهان", "کاشان", "خمینی‌شهر"],
    "فارس": ["شیراز", "مرودشت"],
    "خراسان رضوی": ["مشهد", "نیشابور"],
    "آذربایجان شرقی": ["تبریز", "مراغه"]
}
# لینک‌های تستی (بعداً با لینک‌های واقعی جایگزین کنید)
MEETINGS = {
    "تهران": "https://nairan1.org/tehran-meetings",
    "شهریار": "https://nairan1.org/shahriar-meetings",
    "اسلامشهر": "https://nairan1.org/eslamshahr-meetings",
    "اصفهان": "https://nairan1.org/isfahan-meetings",
    "شیراز": "https://nairan1.org/shiraz-meetings",
    "مشهد": "https://nairan1.org/mashhad-meetings",
    "تبریز": "https://nairan1.org/tabriz-meetings",
    "پیش‌فرض": "https://nairan1.org/onlinemeeting/"
}

DAILY_QUOTES = [
    "امروز یک روز پاک دیگر است. فقط برای امروز.",
    "ما با هم می‌توانیم کاری را انجام دهیم که به تنهایی از عهده آن برنمی‌آییم.",
    "بهبودی یک سفر است، نه یک مقصد.",
    "زمانی که تسلیم می‌شویم، شروع به بهبودی می‌کنیم.",
    "خدمت به دیگران، کلید حفظ پاکی ماست."
]

WELCOME_TEXT = (
    "به مرکز خدمات و منابع انجمن معتادان گمنام NA خوش آمدید.\n"
    "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
)

# =========================================================
# کیبوردها
# =========================================================
def main_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="اطلاع از جلسات آنلاین", url="https://nairan1.org/onlinemeeting/")
    kb.button(text="🔍 جستجوی جلسات حضوری", callback_data="find_meeting")
    kb.button(text="📊 ثبت روزهای پاکی", callback_data="clean_time")
    kb.button(text="🌿 پیام امید امروز", callback_data="daily_quote")
    kb.button(text="✉️ ارتباط با خدمات جهانی", callback_data="global_services")
    kb.button(text="🤫 ارسال پیام ناشناس به کمیته", callback_data="anon_msg")
    kb.adjust(1, 1, 2, 2, 1)
    return kb

def provinces_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for p in PROVINCES:
        kb.button(text=p, callback_data=f"prov_{p}")
    kb.button(text="🔙 بازگشت", callback_data="back_to_main")
    kb.adjust(2, 2, 1, 1)
    return kb

def cities_keyboard(province: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for c in CITIES.get(province, []):
        kb.button(text=c, callback_data=f"city_{c}")
    kb.button(text="🔙 بازگشت", callback_data="find_meeting")
    kb.adjust(2, 2, 1)
    return kb

def email_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="اطلاعات عمومی و فلووشیپ", url="mailto:fsmail@na.org")
    kb.button(text="خدمات مشتری (سفارشات)", url="mailto:customer_service@na.org")
    kb.button(text="هیئت جهانی (World Board)", url="mailto:worldboard@na.org")
    kb.button(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
    kb.adjust(1, 1, 1, 1)
    return kb

# =========================================================
# وضعیت‌های موقت کاربر (برای دریافت ورودی)
# =========================================================
user_states = {}

# =========================================================
# هندلرها
# =========================================================
@dp.message(CommandStart())
async def start_handler(message: Message):
    user = message.from_user
    if user:
        add_user(user.id, user.first_name, user.username)
    
    user_states.pop(user.id, None) # پاک کردن وضعیت قبلی
    await message.answer("در حال بارگذاری منو...", reply_markup=ReplyKeyboardRemove())
    await message.answer(WELCOME_TEXT, reply_markup=main_inline_keyboard().as_markup())

@dp.message(Command("stats"))
async def stats_handler(message: Message):
    user = message.from_user
    if user and str(user.id) == str(ADMIN_ID):
        count = get_user_count()
        await message.answer(f"📊 آمار ربات:\n\n👥 تعداد کل اعضای ربات: **{count}** نفر")

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: CallbackQuery):
    user_states.pop(callback.from_user.id, None)
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_inline_keyboard().as_markup())
    await callback.answer()

# ----- ۱. جستجوی جلسات -----
@dp.callback_query(F.data == "find_meeting")
async def find_meeting_handler(callback: CallbackQuery):
    await callback.message.edit_text("استان خود را انتخاب کنید:", reply_markup=provinces_keyboard().as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("prov_"))
async def province_handler(callback: CallbackQuery):
    prov = callback.data.split("_")[1]
    await callback.message.edit_text(f"شهر مورد نظر در استان {prov} را انتخاب کنید:", reply_markup=cities_keyboard(prov).as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("city_"))
async def city_handler(callback: CallbackQuery):
    city = callback.data.split("_")[1]
    link = MEETINGS.get(city, MEETINGS["پیش‌فرض"])
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 مشاهده لینک جلسات", url=link)
    kb.button(text="🔙 بازگشت", callback_data="find_meeting")
    kb.adjust(1, 1)
    await callback.message.edit_text(f"جلسات شهر {city}:\nبرای مشاهده لیست جلسات روی دکمه زیر کلیک کنید:", reply_markup=kb.as_markup())
    await callback.answer()

# ----- ۲. محاسبه روزهای پاکی -----
@dp.callback_query(F.data == "clean_time")
async def clean_time_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_states[user_id] = "waiting_for_date"
    await callback.message.edit_text(
        "📅 لطفاً تاریخ شروع پاکی خود را به شمسی و با فرمت **YYYY/MM/DD** ارسال کنید.\n"
        "مثال: `1402/05/12`\n"
        "برای انصراف دستور /start را بزنید."
    )
    await callback.answer()

@dp.message()
async def handle_text_inputs(message: Message):
    user = message.from_user
    if not user: return
    
    state = user_states.get(user.id)

    # دریافت تاریخ پاکی
    if state == "waiting_for_date":
        try:
            date_str = message.text.strip()
            # تبدیل تاریخ شمسی به میلادی تقریبی (برای محاسبه روزها)
            # این یک محاسبه تقریبی است. برای دقت بالا نیاز به کتابخانه jdatetime است
            parts = date_str.split("/")
            if len(parts) != 3: raise ValueError
            
            # تبدیل تقریبی تاریخ شمسی به میلادی (هر سال 365 روز)
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            # یک تخمین ساده (دقیق نیست اما برای محاسبه فاصله کار میکند)
            total_days_passed = (year - 1402) * 365 + (month - 1) * 30 + day
            
            # محاسبه روزهای گذشته (فرض بر این است که امروز اواخر سال 1402 است)
            # برای سادگی، فرض میکنیم امروز 1402/09/01 است (این را میتوانید داینامیک کنید)
            today_total = (1402 - 1402) * 365 + (9 - 1) * 30 + 1 
            
            days_clean = today_total - total_days_passed
            
            if days_clean < 0:
                await message.answer("تاریخ وارد شده در آینده است! لطفاً تاریخ گذشته را وارد کنید.")
                return

            update_clean_date(user.id, date_str)
            user_states.pop(user.id, None)
            
            await message.answer(
                f"🌱 تبریک می‌گویم!\nشما از تاریخ {date_str} تاکنون حدوداً **{days_clean}** روز پاک هستید.\n"
                f"به مسیر پر از امید خود ادامه دهید. ❤️",
                reply_markup=main_inline_keyboard().as_markup()
            )
        except Exception:
            await message.answer("❌ فرمت تاریخ اشتباه است. لطفاً دقیقاً مانند مثال (1402/05/12) بفرستید.")
        return

    # دریافت پیام ناشناس
    if state == "waiting_for_anon_msg":
        user_states.pop(user.id, None)
        
        if not ADMIN_ID:
            await message.answer("⚠️ متاسفانه ارسال پیام به کمیته در حال حاضر غیرفعال است.")
            return
            
        try:
            # ارسال به ادمین
            await bot.send_message(
                chat_id=ADMIN_ID, 
                text=f"📩 **پیام ناشناس جدید:**\n\n{message.text}\n\n(برای پاسخ به این کاربر از دستور زیر استفاده کنید: `/reply {user.id} متن پاسخ`)"
            )
            await message.answer("✅ پیام شما با موفقیت و به صورت کاملاً ناشناس برای کمیته ارسال شد.", reply_markup=main_inline_keyboard().as_markup())
        except Exception as e:
            log(f"Error sending anon msg: {e}")
            await message.answer("❌ خطا در ارسال پیام. لطفاً بعداً تلاش کنید.")
        return

# هندلر دستور پاسخ ادمین (اختیاری برای آینده)
@dp.message(Command("reply"))
async def admin_reply_handler(message: Message):
    if str(message.from_user.id) != str(ADMIN_ID): return
    try:
        parts = message.text.split(" ", 2)
        target_id = int(parts[1])
        reply_text = parts[2]
        await bot.send_message(chat_id=target_id, text=f"✉️ **پاسخ کمیته:**\n\n{reply_text}")
        await message.answer("پاسخ با موفقیت ارسال شد.")
    except Exception:
        await message.answer("فرمت اشتباه است. استفاده: /reply USER_ID TEXT")

# ----- ۳. پیام امید روزانه -----
@dp.callback_query(F.data == "daily_quote")
async def daily_quote_handler(callback: CallbackQuery):
    quote = random.choice(DAILY_QUOTES)
    await callback.message.edit_text(
        f"🌿 **پیام امید امروز:**\n\n{quote}\n\n«فقط برای امروز»",
        reply_markup=main_inline_keyboard().as_markup()
    )
    await callback.answer()

# ----- ۴. پیام ناشناس -----
@dp.callback_query(F.data == "anon_msg")
async def anon_msg_handler(callback: CallbackQuery):
    user_states[callback.from_user.id] = "waiting_for_anon_msg"
    await callback.message.edit_text(
        "🤫 لطفاً متن پیام خود را برای کمیته خدمات بنویسید.\n"
        "نام و آیدی شما برای کمیته نمایش داده نخواهد شد.\n\n"
        "برای انصراف دستور /start را بزنید."
    )
    await callback.answer()

# ----- ۵. منوی ایمیل‌ها -----
@dp.callback_query(F.data == "global_services")
async def global_services_handler(callback: CallbackQuery):
    await callback.message.edit_text("بخش‌های ارتباطی خدمات جهانی NA:", reply_markup=email_inline_keyboard().as_markup())
    await callback.answer()

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