import json
import asyncio

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

from bot_logger import logger
from config import load_config
from database.db import book_appointment, create_db_connection

DB_CONFIG = {
    "user": load_config("db_user"),
    "password": load_config("db_password"),
    "database": load_config("db_name"),
    "host": load_config("db_host"),
    "port": load_config("db_port")
}
TOKEN = load_config("token")

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()



@dp.message(CommandStart())
async def start_handler(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Записаться", web_app=WebAppInfo(url="https://s975786.ha003.t.mydomain.zone"))]
            # [KeyboardButton(text="Записаться", web_app=WebAppInfo(url="https://tg-form.webnode.page/"))]
        ],
        resize_keyboard=True
    )

    await message.answer(
        f"записаться: ", reply_markup=keyboard
    )

@dp.message(F.web_app_data)
async def handle_any_message(message: types.Message):
    pool = dp["db_pool"]
    if message.web_app_data is None:
        await message.answer("web_app_data is empty")
        return
    if message.web_app_data:
        print(message.web_app_data.data)
        try:
            data = json.loads(message.web_app_data.data)

            service = data["service"]
            date = data["date"]
            time = data["time"]
            user_name = message.from_user.first_name
            user_id = message.from_user.id
            print(f"user_data: {service}, {date},{time},{user_name},{user_id}")

            if service and date and time:
                try:
                    booked = await book_appointment(pool,service,date,time,user_name,user_id)
                    if booked:
                        await message.answer(f"✅ Вы успешно записались!\nУслуга: {service}\nДата: {date}\nВремя: {time}")
                    else:
                        await message.answer(f"Произошла ошибка")
                except asyncpg.DataError as e:
                    logger.error(f"Ошибка в данных: {e}" )

        except Exception as e:
            await message.answer(f"❌ Ошибка при обработке данных: {e}")
        return
    # если это не WebApp сообщение
    await message.answer("👋 Нажмите на кнопку ниже, для записи.")


async def main():
    pool = await create_db_connection()
    dp["db_pool"] = pool
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())