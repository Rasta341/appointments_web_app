import asyncio
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiohttp import web
import aiohttp

from api.api import Appointment
from bot_logger import get_logger
from config import load_config

# Настройки
BOT_TOKEN = load_config("token")
WEBAPP_URL = load_config("WEBAPP_URL")  # URL вашего WebApp
API_URL = load_config("API_URL")  # URL вашего API


# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Логирование
# logging.basicConfig(level=logging.INFO)
# logger = bot_logger
logger = get_logger("bot")

# Стартовое сообщение с WebApp кнопкой
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📅 Записаться на маникюр/педикюр",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
        [InlineKeyboardButton(
            text="📋 Мои записи",
            callback_data="my_appointments"
        )]
    ])

    await message.answer(
        "🌸 Добро пожаловать в студию красоты!\n\n"
        "Здесь вы можете записаться на:\n"
        "• 💅 Маникюр\n"
        "• 🦶 Педикюр\n"
        "• ✨ Комплексный уход\n\n"
        "Нажмите кнопку ниже для записи:",
        reply_markup=keyboard
    )


# Показать записи пользователя
@dp.callback_query(lambda c: c.data == "my_appointments")
async def show_appointments(callback_query: types.CallbackQuery):
    telegram_id = callback_query.from_user.id

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/appointments/{telegram_id}") as response:
                if response.status == 200:
                    appointments = await response.json()

                    if not appointments:
                        await callback_query.message.edit_text(
                            "📅 У вас пока нет записей.\n"
                            "Нажмите /start чтобы записаться!"
                        )
                        return

                    text = "📋 Ваши записи:\n\n"
                    keyboard_buttons = []

                    for apt in appointments:
                        service_names = {
                            'manicure': '💅 Маникюр',
                            'pedicure': '🦶 Педикюр',
                            'both': '✨ Маникюр + Педикюр'
                        }

                        status_emoji = {
                            'pending': '⏳',
                            'confirmed': '✅',
                            'cancelled': '❌'
                        }

                        date = datetime.strptime(apt['appointment_date'], '%Y-%m-%d').strftime('%d.%m.%Y')

                        text += f"{apt['id']}. {status_emoji.get(apt['status'], '⏳')} {service_names.get(apt['service_type'], apt['service_type'])}\n"
                        text += f"📅 {date} в {apt['appointment_time']}\n"
                        text += f"Статус: {apt['status']}\n\n"

                        # Добавляем кнопку отмены только для активных записей
                        if apt['status'] in ['pending', 'confirmed']:
                            keyboard_buttons.append([
                                InlineKeyboardButton(
                                    text=f"❌ Отменить запись: {apt['id']}",
                                    callback_data=f"cancel_{apt['id']}"
                                )
                            ])

                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text="📅 Записаться еще",
                            web_app=WebAppInfo(url=WEBAPP_URL)
                        )
                    ])

                    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

                    await callback_query.message.edit_text(text, reply_markup=keyboard)
                else:
                    await callback_query.message.edit_text(
                        "❌ Ошибка получения записей. Попробуйте позже."
                    )

    except Exception as e:
        logger.error(f"Ошибка получения записей: {e}")
        await callback_query.message.edit_text(
            "❌ Произошла ошибка. Попробуйте позже."
        )


# Отмена записи
@dp.callback_query(lambda c: c.data.startswith("cancel_"))
async def cancel_appointment(callback_query: types.CallbackQuery):
    appointment_id = int(callback_query.data.split("_")[1])
    telegram_id = callback_query.from_user.id

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                    f"{API_URL}/appointments/{appointment_id}",
                    params={"telegram_id": telegram_id}
            ) as response:
                if response.status == 200:
                    await callback_query.answer("✅ Запись отменена")
                    # Обновляем список записей
                    await show_appointments(callback_query)
                else:
                    await callback_query.answer("❌ Ошибка отмены записи")

    except Exception as e:
        logger.error(f"Ошибка отмены записи: {e}")
        await callback_query.answer("❌ Произошла ошибка")


# Обработка данных от WebApp
@dp.message(lambda message: message.web_app_data)
async def handle_webapp_data(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)

        if data.get('action') == 'booking_confirmed':
            service_names = {
                'manicure': '💅 Маникюр',
                'pedicure': '🦶 Педикюр',
                'both': '✨ Маникюр + Педикюр'
            }

            date = datetime.strptime(data['appointment_date'], '%Y-%m-%d').strftime('%d.%m.%Y')
            service = service_names.get(data['service_type'], data['service_type'])

            confirmation_text = (
                f"✅ Запись подтверждена!\n\n"
                f"🎯 Услуга: {service}\n"
                f"📅 Дата: {date}\n"
                f"⏰ Время: {data['appointment_time']}\n"
                f"🔢 Номер записи: {data['appointment_id']}\n\n"
                f"📍 Ждем вас в нашей студии!\n"
                f"При необходимости отменить запись, используйте команду /start"
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📋 Мои записи",
                    callback_data="my_appointments"
                )],
                [InlineKeyboardButton(
                    text="📅 Записаться еще",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )]
            ])

            await message.answer(confirmation_text, reply_markup=keyboard)



    except Exception as e:
        logger.error(f"Ошибка обработки данных WebApp: {e}")
        await message.answer("❌ Произошла ошибка при обработке записи.")


# Команда для получения списка записей
@dp.message(Command("appointments"))
async def cmd_appointments(message: types.Message):
    fake_callback = types.CallbackQuery(
        id="fake",
        from_user=message.from_user,
        chat_instance="fake",
        message=message,
        data="my_appointments"
    )
    await show_appointments(fake_callback)

async def send_message_to_admin(appointment: Appointment):
    client_id = appointment.telegram_id,
    service = appointment.service_type,
    date = appointment.appointment_date,
    time = appointment.appointment_time
    # Отправляем уведомление администратору
    admin_chat_id = load_config("admin_id")  # ID чата администратора
    admin_text = f"🔔 Новая запись!\n\nПользователь: @{client_id}\nУслуга: {service}\nДата: {date}\nВремя: {time}"
    await bot.send_message(admin_chat_id, admin_text)

# Webhook handler
async def webhook_handler(request):
    try:
        bot_instance = request.app["bot"]
        update = types.Update.model_validate(await request.json(), strict=False)
        await dp.feed_update(bot_instance, update)
        return web.Response(status=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(status=500)


# Главная функция
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
