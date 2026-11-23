import os
import sys
import traceback
import asyncio

from baleio import Bot, Dispatcher, F
from baleio.filters import CommandStart
from baleio.types import Message
from baleio.utils import InlineKeyboardBuilder, ReplyKeyboardRemove

def log(*args):
    print(*args, flush=True)

log("🚀 شروع برنامه بله...")

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    log("❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    sys.exit(1)

dp = Dispatcher()
bot = Bot(token=TOKEN)

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
    
    # ردیف اول
    kb.button(text="اطلاع از جلسات آنلاین NA", url="https://nairan1.org/onlinemeeting/")
    
    # ردیف دوم
    kb.button(text="سایت شورای فرامنطقه ایران", url="https://nairan.org/")
    kb.button(text="شورای فرامنطقه APF", url="https://fa.apfna.org/")
    
    # ردیف سوم
    kb.button(text="شورای فرامنطقه EDM", url="https://www.edmna.org/")
    
    # ردیف چهارم (دکمه باز کردن منوی ایمیل‌ها)
    kb.button(text="ارتباط با کنفرانس خدمات جهانی NA", callback_data="global_services")
    
    # چیدمان دکمه‌ها (۱، ۲، ۱، ۱)
    kb.adjust(1, 2, 1, 1)
    return kb

def email_inline_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    
    # دکمه‌های ایمیل
    kb.button(text="اطلاعات عمومی و فلووشیپ", url="mailto:fsmail@na.org")
    kb.button(text="خدمات مشتری (سفارشات)", url="mailto:customer_service@na.org")
    kb.button(text="فروشگاه آنلاین (پرداخت)", url="https://asan.shaparak.ir/")
    kb.button(text="هیئت جهانی (World Board)", url="mailto:worldboard@na.org")
    kb.button(text="منابع انسانی (HR)", url="mailto:hrp@na.org")
    kb.button(text="روابط عمومی (PR)", url="mailto:pr@na.org")
    kb.button(text="بیمارستان‌ها و موسسات (H&I)", url="mailto:handi@na.org")
    kb.button(text="وب‌سایت (Webmaster)", url="mailto:webmaster@na.org")
    kb.button(text="رویدادها و کنوانسیون‌ها", url="mailto:events@na.org")
    kb.button(text="مجله The NA Way", url="mailto:naway@na.org")
    kb.button(text="کمک‌های مالی", url="mailto:contributions@na.org")
    kb.button(text="فرصت‌های شغلی", url="mailto:jobs@na.org")
    
    # دکمه بازگشت
    kb.button(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
    
    # چیدمان (دو ستونه، و دکمه بازگشت تک در پایین)
    kb.adjust(2, 2, 2, 2, 2, 2, 1)
    return kb

# ---------------------------------------------------------
# هندلرها
# ---------------------------------------------------------
@dp.message(CommandStart())
async def start_handler(message: Message):
    # ۱. اول کیبورد پایین صفحه (اگر هست) را پاک می‌کنیم
    await message.answer("در حال بارگذاری منو...", reply_markup=ReplyKeyboardRemove())
    
    # ۲. سپس پیام اصلی با دکمه‌های شیشه‌ای را می‌فرستیم
    await message.answer(WELCOME_TEXT, reply_markup=main_inline_keyboard().as_markup())

# هندلر برای کلیک روی دکمه "ارتباط با کنفرانس جهانی"
@dp.callback_query(F.data == "global_services")
async def global_services_handler(callback):
    await callback.message.edit_text(EMAIL_TEXT, reply_markup=email_inline_keyboard().as_markup())
    await callback.answer()

# هندلر برای کلیک روی دکمه "بازگشت"
@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_inline_keyboard().as_markup())
    await callback.answer()

# ---------------------------------------------------------
# اجرا
# ---------------------------------------------------------
async def main():
    log("✅ ربات بله با دکمه‌های شیشه‌ای در حال اجراست...")
    try:
        await dp.start_polling(bot)
    except Exception:
        log("❌ خطا در اجرای ربات بله:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())