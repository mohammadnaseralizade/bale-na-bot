import os
import sys
import traceback
import asyncio
import sqlite3
import random

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT
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

def get_user_count():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

init_db()

# =========================================================
# متن‌ها
# =========================================================
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

EMAIL_TEXT = (
    "بخش‌های ارتباطی خدمات جهانی NA\n"
    "روی هر دکمه بزنید تا مستقیماً برای آن بخش ایمیل بفرستید."
)

# =========================================================
# کیبوردها
# =========================================================
def main_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="اطلاع از جلسات آنلاین", url="https://nairan1.org/onlinemeeting/")
    kb.button(text="🔍 جستجوی جلسات حضوری", url="https://nairan.org/fa/meetings")
    kb.button(text="📊 روزشمار پاکی", url="https://nairan.org/fa/cleanlinesscalendar")
    kb.button(text="🌿 پیام امید امروز", callback_data="daily_quote")
    kb.button(text="✉️ ارتباط با خدمات جهانی", callback_data="global_services")
    kb.button(text="🤫 ارسال پیام ناشناس به کمیته", callback_data="anon_msg")
    
    kb.adjust(1, 1, 1, 2, 1)
    return kb

def email_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    # لیست کامل دکمه‌های ایمیل (بدون فروشگاه)
    kb.button(text="اطلاعات عمومی و فلووشیپ", url="mailto:fsmail@na.org")
    kb.button(text="خدمات مشتری (سفارشات)", url="mailto:customer_service@na.org")
    kb.button(text="هیئت جهانی (World Board)", url="mailto:worldboard@na.org")
    kb.button(text="منابع انسانی (HR)", url="mailto:hrp@na.org")
    kb.button(text="روابط عمومی (PR)", url="mailto:pr@na.org")
    kb.button(text="بیمارستان‌ها و موسسات (H&I)", url="mailto:handi@na.org")
    kb.button(text="وب‌سایت (Webmaster)", url="mailto:webmaster@na.org")
    kb.button(text="رویدادها و کنوانسیون‌ها", url="mailto:events@na.org")
    kb.button(text="مجله The NA Way", url="mailto:naway@na.org")
    kb.button(text="کمک‌های مالی", url="mailto:contributions@na.org")
    kb.button(text="فرصت‌های شغلی", url="mailto:jobs@na.org")
    
    kb.button(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
    
    # چیدمان دو ستونه برای ۱۱ دکمه بالا و دکمه بازگشت در پایین
    kb.adjust(2, 2, 2, 2, 2, 1, 1)
    return kb

# =========================================================
# وضعیت‌های موقت کاربر
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
    
    user_states.pop(user.id, None)
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

# ----- هندلر دریافت متن (برای پیام ناشناس) -----
@dp.message()
async def handle_text_inputs(message: Message):
    user = message.from_user
    if not user: return
    
    state = user_states.get(user.id)

    if state == "waiting_for_anon_msg":
        user_states.pop(user.id, None)
        
        if not ADMIN_ID:
            await message.answer("⚠️ متاسفانه ارسال پیام به کمیته در حال حاضر غیرفعال است.")
            return
            
        try:
            await bot.send_message(
                chat_id=ADMIN_ID, 
                text=f"📩 **پیام ناشناس جدید:**\n\n{message.text}\n\n(برای پاسخ به این کاربر از دستور زیر استفاده کنید: `/reply {user.id} متن پاسخ`)"
            )
            await message.answer("✅ پیام شما با موفقیت و به صورت کاملاً ناشناس برای کمیته ارسال شد.", reply_markup=main_inline_keyboard().as_markup())
        except Exception as e:
            log(f"Error sending anon msg: {e}")
            await message.answer("❌ خطا در ارسال پیام. لطفاً بعداً تلاش کنید.")
        return

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

# ----- پیام امید روزانه -----
@dp.callback_query(F.data == "daily_quote")
async def daily_quote_handler(callback: CallbackQuery):
    quote = random.choice(DAILY_QUOTES)
    await callback.message.edit_text(
        f"🌿 **پیام امید امروز:**\n\n{quote}\n\n«فقط برای امروز»",
        reply_markup=main_inline_keyboard().as_markup()
    )
    await callback.answer()

# ----- پیام ناشناس -----
@dp.callback_query(F.data == "anon_msg")
async def anon_msg_handler(callback: CallbackQuery):
    user_states[callback.from_user.id] = "waiting_for_anon_msg"
    await callback.message.edit_text(
        "🤫 لطفاً متن پیام خود را برای کمیته خدمات بنویسید.\n"
        "نام و آیدی شما برای کمیته نمایش داده نخواهد شد.\n\n"
        "برای انصراف دستور /start را بزنید."
    )
    await callback.answer()

# ----- منوی ایمیل‌ها -----
@dp.callback_query(F.data == "global_services")
async def global_services_handler(callback: CallbackQuery):
    await callback.message.edit_text(EMAIL_TEXT, reply_markup=email_inline_keyboard().as_markup())
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