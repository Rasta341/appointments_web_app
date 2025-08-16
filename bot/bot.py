import asyncio
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiohttp import web
import aiohttp

from database.db import user_repo, appointment_repo
from logger.bot_logger import get_logger
from config import load_config

# Настройки
BOT_TOKEN = load_config("token")
WEBAPP_URL = load_config("WEBAPP_URL")  # URL вашего WebApp
API_URL = load_config("API_URL")  # URL вашего API


# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Логирование
logger = get_logger("bot")

user_repo = user_repo
appointment_repo = appointment_repo
admin_chat_id = load_config("admin_id")
async def check_is_admin(telegram_id) -> bool:
    return int(telegram_id) == int(admin_chat_id)

# Стартовое сообщение с WebApp кнопкой
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user

    if await check_is_admin(user.id):
        admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Заявки на запись", callback_data="admin_appointents")]])
        await message.answer(text="""
        Для просмотра заявок на запись - нажмите соответствующую кнопку
        """,reply_markup=admin_keyboard)
        return

    try:
        user_created = await user_repo.create_user(telegram_id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name)
        logger.info(user_created)
    except Exception as e:
        logger.error(e)

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

@dp.callback_query(lambda c: c.data == "admin_appointents")
async def admin_appointments_handler(callback_query: types.CallbackQuery):
    try:
        appointments = await appointment_repo.admin_get_pending_and_confirmed_appointments_list()
        if not appointments:
            await callback_query.message.edit_text(
                "📅 У вас пока нет записей.\n"
                "Нажмите /start чтобы записаться!"
            )
            return

        text = ("📋 Записи в ожидании\n"
                "✅ - для подтверждения записи,\n"
                "❌ - для отмены:\n\n")
        keyboard_buttons = []

        for apt in appointments:
            service_names = {
                'manicure': '💅 Маникюр',
                'pedicure': '🦶 Педикюр',
                'both': '✨ Маникюр + Педикюр'
            }
            user = await user_repo.get_user(apt['telegram_id'])

            status_emoji = {
                'pending': '⏳ В обработке',
                'confirmed': '✅ Подтверждена',
                'cancelled': '❌ Отменена'
            }
            date = datetime.strptime(apt['appointment_date'], '%Y-%m-%d').strftime('%d.%m.%Y')

            text += f"{apt['id']}.@{user['username']}, {service_names.get(apt['service_type'], apt['service_type'])}\n"
            text += f"📅 {date} в {apt['appointment_time']}\n"
            text += f"Статус: {status_emoji.get(apt['status'], '⏳')}\n\n"

            match apt['status']:
                case 'pending':
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text=f"❌: {apt['id']}",
                            callback_data=f"cancel_admin_{apt['id']}"
                        ),
                        InlineKeyboardButton(
                            text=f"✅: {apt['id']}",
                            callback_data=f"approve_{apt['id']}"
                        )
                    ])
                case 'confirmed':
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text=f"❌: {apt['id']}",
                            callback_data=f"cancel_admin_{apt['id']}"
                        )
                    ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        await callback_query.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        await callback_query.message.edit_text(
            "❌ Ошибка получения записей. Попробуйте позже."
        )
        logger.error(e)


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
    data_parts = callback_query.data.split("_")

    if "admin" in data_parts:
        appointment_id = int(data_parts[2])
        appointment = await appointment_repo.get_appointment_by_id(appointment_id=appointment_id)
        telegram_id = appointment['telegram_id']
        logger.info(f"app_id: {appointment_id}\n appid_type: {type(appointment_id)}")
        result = await appointment_repo.cancel_appointment(appointment_id=appointment_id, telegram_id=telegram_id)

        await send_message_to(user_id=telegram_id, text="Администратор отменил вашу запись")
        await callback_query.answer("✅ Запись отменена")

        if not result:
            await callback_query.answer("❌ Ошибка отмены записи")

    else:
        appointment_id = int(data_parts[1])
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

@dp.callback_query(lambda c: c.data.startswith("approve_"))
async def admin_approve_appointment(callback_query: types.CallbackQuery):
    appointment_id = int(callback_query.data.split("_")[1])

    user_id = await appointment_repo.admin_confirm_appointment(appointment_id)
    if user_id:
        await send_message_to(user_id=user_id,text="Ваша запись подтверждена Администратором, ждем Вас в назначенное время :)" )
        await callback_query.answer("✅ Запись подтверждена")
        await admin_appointments_handler(callback_query)
    else:
        logger.error("Ошибка в подтверждении записи")
        await send_message_to(user_id=user_id, text="❌ Не удалось подтвердить вашу запись, свяжитесь с Администратором для записи вручную!!!")
        await callback_query.answer("❌ Ошибка отмены записи")

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


async def send_pending_message_to_admin(admin_text, appointment_id):
    # Создаем кнопки
    keyboard_buttons = [
        [
            InlineKeyboardButton(
                text=f"❌ Отклонить",
                callback_data=f"cancel_admin_{appointment_id}"
            ),
            InlineKeyboardButton(
                text=f"✅ Подтвердить",
                callback_data=f"approve_{appointment_id}"
            )
        ]
    ]

    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=admin_text,
            reply_markup=keyboard  # Добавляем клавиатуру
        )
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения админу: {e}")


async def send_message_to_admin(admin_text):  # ID чата администратора
    try:
        await bot.send_message(admin_chat_id, admin_text)
    except Exception as e:
        logger.error(e)

async def send_message_to(user_id, text):
    try:
        await bot.send_message(user_id, text)
    except Exception as e:
        logger.error(e)

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
    logger.info("Бот запущен")


if __name__ == "__main__":
    asyncio.run(main())
