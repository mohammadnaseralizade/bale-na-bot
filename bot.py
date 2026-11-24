import os
import sys
import traceback
import asyncio
import sqlite3

from baleio import Bot, Dispatcher, F
from baleio.filters import CommandStart, Command
from baleio.types import Message, ReplyKeyboardRemove
from baleio.utils import InlineKeyboardBuilder

def log(*args):
    print(*args, flush=True)

log("🚀 شروع برنامه بله...")

TOKEN = os.getenv("BOT_TOKEN")
# ⚠️ یک متغیر محیطی جدید برای آیدی عددی خودتان (ادمین) بسازید
ADMIN_ID = os.getenv("ADMIN_ID") 

if not TOKEN:
    log("❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    sys.exit(1)

dp = Dispatcher()
bot = Bot(token=TOKEN)

# ---------------------------------------------------------
# بخش دیتابیس (ذخیره کاربران)
# ---------------------------------------------------------
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
    # اگر کاربر جدید باشد اضافه می‌شود، اگر بود آپدیت می‌شود
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, first_name, username)
        VALUES (?, ?, ?)
    ''', (user_id, first_name, username))
    conn.commit()
    conn.close()

def get_user_count():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

# راه‌اندازی اولیه دیتابیس
init_db()

# ---------------------------------------------------------
# متن‌ها
# ---------------------------------------------------------
WELCOME_TEXT = (
    "به مرکز خدمات و منابع انجمن معتادان گمنام NA خوش آمدید.\n"
    "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
)

EMAIL_TEXT = (
    "بخش‌های ارتباطی خدمات جهانی NA\n"
    "روی هر دکمه بزنید تا مستقیماً برای آن بخش ایمیل بفرستید."
)

# ---------------------------------------------------------
# ساخت دکمه‌های شیشه‌ای (Inline)
# ---------------------------------------------------------
def main_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="اطلاع از جلسات آنلاین NA", url="https://nairan1.org/onlinemeeting/")
    kb.button(text="سایت شورای فرامنطقه ایران", url="https://nairan.org/")
    kb.button(text="شورای فرامنطقه APF", url="https://fa.apfna.org/")
    kb.button(text="شورای فرامنطقه EDM", url="https://www.edmna.org/")
    kb.button(text="ارتباط با کنفرانس خدمات جهانی NA", callback_data="global_services")
    kb.adjust(1, 2, 1, 1)
    return kb

def email_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
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
    kb.adjust(2, 2, 2, 2, 2, 1, 1)
    return kb

# ---------------------------------------------------------
# هندلرها
# ---------------------------------------------------------
@dp.message(CommandStart())
async def start_handler(message: Message):
    user = message.from_user
    if user:
        # ثبت کاربر جدید در دیتابیس
        add_user(user.id, user.first_name, user.username)
    
    await message.answer("در حال بارگذاری منو...", reply_markup=ReplyKeyboardRemove())
    await message.answer(WELCOME_TEXT, reply_markup=main_inline_keyboard().as_markup())

# هندلر اختصاصی ادمین برای دیدن آمار (دستور /stats)
@dp.message(Command("stats"))
async def stats_handler(message: Message):
    user = message.from_user
    if user and str(user.id) == str(ADMIN_ID):
        count = get_user_count()
        await message.answer(f"📊 آمار ربات:\n\n👥 تعداد کل اعضای ربات: **{count}** نفر")
    else:
        # اگر کسی غیر از ادمین این دستور را بزند، پیامی نمی‌بیند
        pass

@dp.callback_query(F.data == "global_services")
async def global_services_handler(callback):
    await callback.message.edit_text(EMAIL_TEXT, reply_markup=email_inline_keyboard().as_markup())
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_inline_keyboard().as_markup())
    await callback.answer()

# ---------------------------------------------------------
# اجرا
# ---------------------------------------------------------
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