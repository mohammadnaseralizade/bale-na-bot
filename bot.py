import os
import sys
import traceback
import asyncio

# وارد کردن کتابخانه baleio مخصوص بله
from baleio import Bot, Dispatcher
from baleio.filters import CommandStart
from baleio.types import Message
from baleio.utils import keyboard as kb

def log(*args):
    print(*args, flush=True)

log("🚀 شروع برنامه بله...")

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    log("❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    sys.exit(1)

# تنظیمات اولیه
dp = Dispatcher()
bot = Bot(token=TOKEN)

# ---------------------------------------------------------
# متن دکمه‌ها
# ---------------------------------------------------------
B_ONLINE = "اطلاع از جلسات آنلاین NA"
B_IRAN = "سایت شورای فرامنطقه ایران"
B_APF = "شورای فرامنطقه APF"
B_EDM = "شورای فرامنطقه EDM"
B_GLOBAL = "ارتباط با کنفرانس خدمات جهانی NA"
B_BACK = "بازگشت به منوی اصلی"

SITES = {
    B_ONLINE: ("جلسات آنلاین NA", "https://nairan1.org/onlinemeeting/"),
    B_IRAN: ("سایت شورای فرامنطقه ایران", "https://nairan.org/"),
    B_APF: ("شورای فرامنطقه APF", "https://fa.apfna.org/"),
    B_EDM: ("شورای فرامنطقه EDM", "https://www.edmna.org/"),
}

EMAILS = {
    "اطلاعات عمومی و فلووشیپ": "fsmail@na.org",
    "خدمات مشتری (سفارشات)": "customer_service@na.org",
    "هیئت جهانی (World Board)": "worldboard@na.org",
    "منابع انسانی (HR)": "hrp@na.org",
    "روابط عمومی (PR)": "pr@na.org",
    "بیمارستان‌ها و موسسات (H&I)": "handi@na.org",
    "وب‌سایت (Webmaster)": "webmaster@na.org",
    "رویدادها و کنوانسیون‌ها": "events@na.org",
    "مجله The NA Way": "naway@na.org",
    "کمک‌های مالی": "contributions@na.org",
    "فرصت‌های شغلی": "jobs@na.org",
}

WELCOME_TEXT = (
    "به مرکز خدمات و منابع انجمن معتادان گمنام NA خوش آمدید.\n"
    "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
)

EMAIL_TEXT = (
    "بخش‌های ارتباطی خدمات جهانی NA\n"
    "روی هر دکمه بزنید تا آدرس ایمیل آن بخش برای شما ارسال شود."
)

# ---------------------------------------------------------
# ساخت کیبوردهای بله (Reply Keyboard)
# ---------------------------------------------------------
def main_keyboard() -> kb.ReplyKeyboardMarkup:
    # در بله دکمه‌ها معمولاً در حداکثر ۲ یا ۳ ستون چیده می‌شوند
    return kb.ReplyKeyboardMarkup(
        keyboard=[
            [kb.KeyboardButton(text=B_ONLINE)],
            [kb.KeyboardButton(text=B_IRAN), kb.KeyboardButton(text=B_APF)],
            [kb.KeyboardButton(text=B_EDM)],
            [kb.KeyboardButton(text=B_GLOBAL)],
        ],
        resize_keyboard=True
    )

def email_keyboard() -> kb.ReplyKeyboardMarkup:
    names = list(EMAILS.keys())
    rows = []
    # چیدن دکمه‌های ایمیل در دو ستون
    for i in range(0, len(names), 2):
        row = [kb.KeyboardButton(text=n) for n in names[i:i + 2]]
        rows.append(row)
    rows.append([kb.KeyboardButton(text=B_BACK)])
    return kb.ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

# ---------------------------------------------------------
# هندلرها
# ---------------------------------------------------------
@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_keyboard())

# هندلر برای دکمه‌های کیبورد (مسیریاب متن)
@dp.message()
async def router(message: Message):
    text = message.text.strip() if message.text else ""

    if not text or text.startswith("/"):
        return

    if text == B_GLOBAL:
        await message.answer(EMAIL_TEXT, reply_markup=email_keyboard())
    elif text == B_BACK:
        await message.answer(WELCOME_TEXT, reply_markup=main_keyboard())
    elif text in SITES:
        title, url = SITES[text]
        await message.answer(f"{title}\n{url}")
    elif text in EMAILS:
        email = EMAILS[text]
        await message.answer(
            f"{text}\n📧 {email}\n\n"
            f"نوشتن ایمیل (با جیمیل):\n"
            f"https://mail.google.com/mail/?view=cm&to={email}"
        )
    else:
        await message.answer(WELCOME_TEXT, reply_markup=main_keyboard())

# ---------------------------------------------------------
# اجرا
# ---------------------------------------------------------
async def main():
    log("✅ ربات بله در حال اجراست...")
    try:
        # اجرای ربات به صورت polling
        await dp.start_polling(bot)
    except Exception:
        log("❌ خطا در اجرای ربات بله:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())