import asyncio
import logging
from logging.handlers import RotatingFileHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, BaseFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from cachetools import TTLCache

import config
import utils
from price_scraper import PriceScraperService

# НАЛАШТУВАННЯ ЛОГУВАННЯ З РОТАЦІЄЮ (10 MB)
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
rotating_handler = RotatingFileHandler("bot.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
rotating_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logging.basicConfig(level=logging.DEBUG, handlers=[rotating_handler, console_handler])
logger = logging.getLogger(__name__)

ANALOGS_CACHE = TTLCache(maxsize=1000, ttl=3600)

class IsAllowedUser(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        return message.from_user.id in config.ALLOWED_USERS

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
dp.message.filter(IsAllowedUser())

scraper_service = None
active_requests = 0

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    logger.info(f"Користувач {message.from_user.id} натиснув /start")
    await message.answer("✅ Привіт! Бот для пошуку цін готовий.\nПросто відправ мені артикул (або кілька через кому/пробіл).")

@dp.message(F.text)
async def handle_article_search(message: types.Message):
    global active_requests 
    
    if message.text.startswith('/'): return
    
    logger.info(f"📥 Нове повідомлення від {message.from_user.id}: {message.text}")
    articles = utils.clean_articles(message.text)
    
    if not articles:
        logger.warning("Артикули не знайдено після очищення тексту.")
        return await message.answer("❌ Я не знайшов дійсних артикулів у вашому повідомленні.")
    if len(articles) > 10:
        logger.warning(f"Користувач відправив забагато артикулів: {len(articles)}")
        return await message.answer("⚠️ Будь ласка, надсилайте не більше 10 артикулів за один раз.")
    if len(articles) > 1:
        await message.answer(f"📥 Отримано {len(articles)} артикулів. Починаю обробку по черзі...")

    for article in articles:
        logger.info(f"▶️ Початок обробки артикулу: {article}")
        queue_position = active_requests + 1
        wait_time = active_requests * 5
        queue_msg = f"\n\n🚦 **Ви {queue_position}-й у черзі.**\nОрієнтовний час очікування: ~{wait_time} сек." if active_requests > 0 else ""
            
        msg = await message.answer(f"💰 Шукаю ціни для `{article}`...\n⏳ Зачекайте кілька секунд.{queue_msg}", parse_mode="Markdown")
        active_requests += 1
        
        try:
            logger.debug(f"Запуск паралельних API-запитів для {article}")
            tasks = [
                scraper_service.search_autonova(article),
                scraper_service.search_fps(article),
                scraper_service.search_fourcars(article),
                scraper_service.search_inside(article)
            ]
            results = await asyncio.gather(*tasks)
            logger.debug(f"Всі API-відповіді для {article} отримано успішно.")
            
            stores = [
                ("AUTONOVAD\u200B.\u200BUA", results[0]),
                ("B2B\u200B.\u200BFORMA-PARTS\u200B.\u200BUA", results[1]),
                ("4CARS\u200B.\u200BCOM\u200B.\u200BUA", results[2]),
                ("INSIDE-AUTO\u200B.\u200BCOM", results[3])
            ]
            
            reply = f"🔎 **Запит:** `{article}`\n\n➖➖➖➖➖➖➖➖➖➖\n\n"
            analogs_parts = []
            
            for store_name, res in stores:
                logger.debug(f"Формування тексту для {store_name}")
                reply += utils.build_store_reply(store_name, res) + "\n\n➖➖➖➖➖➖➖➖➖➖\n\n"
                if res["analogs"]:
                    analogs_parts.append(f"🛒 {store_name}\n\n" + utils.format_dict_results(res["analogs"]))
                
            markup = None
            if analogs_parts:
                logger.debug(f"Збереження аналогів у кеш для {article}")
                ANALOGS_CACHE[article] = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(analogs_parts)
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Показати аналоги ♻️", callback_data=f"analogs:{article}")]
                ])
                
            await msg.edit_text(reply, reply_markup=markup, parse_mode="Markdown")
            logger.info(f"✅ Успішно відправлено результати користувачу для {article}")
            
        except Exception as e:
            logger.error(f"❌ Помилка обробки {article}: {e}", exc_info=True)
            await msg.edit_text(f"❌ Помилка при зборі цін для `{article}`. Спробуйте ще раз.", parse_mode="Markdown")
        finally:
            active_requests -= 1
            logger.debug(f"Запит для {article} завершено. Активних запитів: {active_requests}")
            
        if len(articles) > 1:
            await asyncio.sleep(1.0)

@dp.callback_query(F.data.startswith("analogs:"))
async def show_analogs(callback: CallbackQuery):
    article = callback.data.split(":")[1]
    logger.info(f"Клік по кнопці 'Показати аналоги' для {article}")
    await callback.answer() 
    
    analogs_text = ANALOGS_CACHE.get(article)
    
    if analogs_text:
        logger.debug("Аналоги знайдено в кеші. Відправка повідомлення.")
        full_reply = f"➖➖➖➖➖➖➖➖➖➖\n♻️ *АНАЛОГИ ДЛЯ {article}*\n➖➖➖➖➖➖➖➖➖➖\n\n" + analogs_text
        await callback.message.answer(full_reply, parse_mode="Markdown")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e:
            logger.debug(f"Не вдалося видалити кнопку: {e}")
    else:
        logger.warning(f"Аналоги для {article} відсутні в кеші.")
        await callback.answer("⏳ Дані аналогів видалені з пам'яті (пройшла 1 година). Зробіть пошук заново.", show_alert=True)

@dp.shutdown()
async def on_shutdown_handler():
    logger.critical("🛑 Отримано сигнал зупинки бота. Закриваю API сесії...")
    if scraper_service:
        await scraper_service.close()

async def main():
    global scraper_service
    logger.info("⚡ Бот запускається... Ініціалізую API сервіси")
    scraper_service = PriceScraperService()
    
    for user_id in config.ALLOWED_USERS:
        try:
            await bot.send_message(user_id, "✅ Бот оновлений, структурований та готовий до роботи!")
        except Exception as e:
            logger.warning(f"Не вдалося відправити повідомлення про старт користувачу {user_id}: {e}")

    logger.info("🎧 Бот слухає повідомлення.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())