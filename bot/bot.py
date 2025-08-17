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
ADMIN_CHAT_ID = load_config("admin_id")
SERVICE_NAMES = json.loads(load_config("service_names"))
STATUS = json.loads(load_config("status_emoji"))

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Логирование
logger = get_logger("bot")

user_repo = user_repo
appointment_repo = appointment_repo


async def check_is_admin(telegram_id) -> bool:
    return int(telegram_id) == int(ADMIN_CHAT_ID)


# Стартовое сообщение с WebApp кнопкой
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user

    if await check_is_admin(user.id):
        admin_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Заявки на запись", callback_data="admin_appointents")]
            ])
        await message.answer(text="""
        Для просмотра заявок на запись - нажмите соответствующую кнопку
        """, reply_markup=admin_keyboard)
        return

    try:
        user_created = await user_repo.create_user(telegram_id=user.id, username=user.username,
                                                   first_name=user.first_name, last_name=user.last_name)
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
                "📅 У вас пока нет записей. Отдыхаем!\n"
            )
            return

        text = ("📋 Записи в ожидании\n"
                "✅ - для подтверждения записи,\n"
                "❌ - для отмены:\n\n")
        keyboard_buttons = []

        for apt in appointments:
            user = await user_repo.get_user(apt['telegram_id'])

            date = datetime.strptime(apt['appointment_date'], '%Y-%m-%d').strftime('%d.%m.%Y')

            text += f"{apt['id']}.@{user['username']}, {SERVICE_NAMES.get(apt['service_type'], apt['service_type'])}\n"
            text += f"📅 {date} в {apt['appointment_time']}\n"
            text += f"Статус: {STATUS.get(apt['status'])}\n\n"

            match apt['status']:
                case 'pending':
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text=f"❌: {apt['id']}",
                            callback_data=f"list_cancel_{apt['id']}"  # Изменили префикс для списка
                        ),
                        InlineKeyboardButton(
                            text=f"✅: {apt['id']}",
                            callback_data=f"list_approve_{apt['id']}"  # Изменили префикс для списка
                        )
                    ])
                case 'confirmed':
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text=f"❌: {apt['id']}",
                            callback_data=f"list_cancel_{apt['id']}"  # Изменили префикс для списка
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

                        date = datetime.strptime(apt['appointment_date'], '%Y-%m-%d').strftime('%d.%m.%Y')

                        text += f"{apt['id']}. {STATUS.get(apt['status'])} {SERVICE_NAMES.get(apt['service_type'], apt['service_type'])}\n"
                        text += f"📅 {date} в {apt['appointment_time']}\n"
                        text += f"Статус: {apt['status']}\n\n"

                        # Добавляем кнопку отмены только для активных записей
                        if apt['status'] in ['pending', 'confirmed']:
                            keyboard_buttons.append([
                                InlineKeyboardButton(
                                    text=f"❌ Отменить запись: {apt['id']}",
                                    callback_data=f"user_cancel_{apt['id']}"  # Префикс для пользователя
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


# === HANDLERS ДЛЯ УВЕДОМЛЕНИЙ АДМИНУ (с редактированием сообщения) ===

@dp.callback_query(lambda c: c.data.startswith("admin_cancel_"))
async def admin_cancel_from_notification(callback_query: types.CallbackQuery):
    """Отмена записи из уведомления админу - редактирует сообщение"""
    appointment_id = int(callback_query.data.split("_")[2])

    appointment = await appointment_repo.get_appointment_by_id(appointment_id=appointment_id)
    telegram_id = appointment['telegram_id']
    result = await appointment_repo.cancel_appointment(appointment_id=appointment_id, telegram_id=telegram_id)

    if result:
        # Редактируем сообщение - добавляем статус и убираем кнопки
        new_text = callback_query.message.text + "\n\n❌ ЗАПИСЬ ОТКЛОНЕНА"
        await callback_query.message.edit_text(text=new_text)

        await send_message_to(user_id=telegram_id, text="Администратор отменил вашу запись")
        await callback_query.answer("✅ Запись отменена")
    else:
        await callback_query.answer("❌ Ошибка отмены записи")


@dp.callback_query(lambda c: c.data.startswith("admin_approve_"))
async def admin_approve_from_notification(callback_query: types.CallbackQuery):
    """Подтверждение записи из уведомления админу - редактирует сообщение"""
    appointment_id = int(callback_query.data.split("_")[2])

    user_id = await appointment_repo.admin_confirm_appointment(appointment_id)
    if user_id:
        # Редактируем сообщение - добавляем статус и убираем кнопки
        new_text = callback_query.message.text + "\n\n✅ ЗАПИСЬ ПОДТВЕРЖДЕНА"
        await callback_query.message.edit_text(text=new_text)

        await send_message_to(user_id=user_id, text="Ваша запись подтверждена")
        await callback_query.answer("✅ Запись подтверждена")
    else:
        await callback_query.answer("❌ Ошибка подтверждения записи")


# === HANDLERS ДЛЯ СПИСКА ЗАПИСЕЙ АДМИНА (обновляют список) ===

@dp.callback_query(lambda c: c.data.startswith("list_cancel_"))
async def admin_cancel_from_list(callback_query: types.CallbackQuery):
    """Отмена записи из списка админа - обновляет список"""
    appointment_id = int(callback_query.data.split("_")[2])

    appointment = await appointment_repo.get_appointment_by_id(appointment_id=appointment_id)
    telegram_id = appointment['telegram_id']
    result = await appointment_repo.cancel_appointment(appointment_id=appointment_id, telegram_id=telegram_id)

    if result:
        await send_message_to(user_id=telegram_id, text="Администратор отменил вашу запись")
        await callback_query.answer("✅ Запись отменена")
        # Обновляем список
        await admin_appointments_handler(callback_query)
    else:
        await callback_query.answer("❌ Ошибка отмены записи")


@dp.callback_query(lambda c: c.data.startswith("list_approve_"))
async def admin_approve_from_list(callback_query: types.CallbackQuery):
    """Подтверждение записи из списка админа - обновляет список"""
    appointment_id = int(callback_query.data.split("_")[2])

    user_id = await appointment_repo.admin_confirm_appointment(appointment_id)
    if user_id:
        await send_message_to(user_id=user_id, text="Ваша запись подтверждена")
        await callback_query.answer("✅ Запись подтверждена")
        # Обновляем список
        await admin_appointments_handler(callback_query)
    else:
        await callback_query.answer("❌ Ошибка подтверждения записи")


# === HANDLER ДЛЯ ОТМЕНЫ ПОЛЬЗОВАТЕЛЕМ ===

@dp.callback_query(lambda c: c.data.startswith("user_cancel_"))
async def user_cancel_appointment(callback_query: types.CallbackQuery):
    """Отмена записи пользователем"""
    appointment_id = int(callback_query.data.split("_")[2])
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


# === ФУНКЦИИ ОТПРАВКИ СООБЩЕНИЙ ===

async def send_pending_message_to_admin(admin_text, appointment_id):
    """Отправка уведомления админу с кнопками (для редактирования)"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"❌ Отклонить",
                callback_data=f"admin_cancel_{appointment_id}"  # Префикс для уведомлений
            ),
            InlineKeyboardButton(
                text=f"✅ Подтвердить",
                callback_data=f"admin_approve_{appointment_id}"  # Префикс для уведомлений
            )
        ]
    ])

    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_text,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения админу: {e}")


async def send_message_to_admin(admin_text):
    try:
        await bot.send_message(ADMIN_CHAT_ID, admin_text)
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