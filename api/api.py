from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator, Field
from datetime import date, time, datetime
from typing import List
import sys
import os
import json

from config import load_config
from bot.bot import send_message_to_admin, send_pending_message_to_admin
from bot import bot
from database import db
from database.db import reminder_repo, user_repo, appointment_repo
from notifier.reminder import ReminderScheduler
from logger.bot_logger import get_logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = get_logger("api")

# Константы
SERVICE_NAMES = json.loads(load_config("service_names"))
user_repo = user_repo
appointment_repo = appointment_repo
reminder_repo = reminder_repo

reminder = ReminderScheduler(bot, reminder_repo, user_repo, appointment_repo)


# Контекстный менеджер для жизненного цикла приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_database()
    await reminder.start()
    logger.info("API started successfully")
    yield
    # Shutdown
    await db.close_database()
    await reminder.stop()
    logger.info("API shutdown completed")


app = FastAPI(
    title="Nail Salon API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    description="Internal API for Telegram bot appointment system"
)

# CORS для Telegram WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://manicure-appointments.shop",
        "http://manicure-appointments.shop",
        "https://www.manicure-appointments.shop",
        "http://www.manicure-appointments.shop",
        "https://web.telegram.org",
        "http://web.telegram.org",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],  # Telegram WebApp может отправлять разные заголовки
)


# Модели данных
class Appointment(BaseModel):
    telegram_id: int = Field(gt=0, description="Telegram user ID")
    service_type: str = Field(description="Type of service")
    appointment_date: date = Field(description="Date of appointment")
    appointment_time: time = Field(description="Time of appointment")

    @field_validator('service_type')
    def validate_service_type(cls, v):
        allowed_services = list(SERVICE_NAMES.keys())  # Берем из конфига
        if v not in allowed_services:
            raise ValueError(f'Service type must be one of: {allowed_services}')
        return v

    @field_validator('appointment_date')
    def validate_appointment_date(cls, v):
        if v < date.today():
            raise ValueError('appointment_date cannot be in the past')
        return v

    @field_validator('appointment_time')
    def validate_appointment_time(cls, v):
        allowed_times = [time(10, 0), time(12, 0), time(14, 0), time(16, 0), time(18, 0)]
        if v not in allowed_times:
            raise ValueError(f'Appointment time must be one of: {[t.strftime("%H:%M") for t in allowed_times]}')
        return v


class AppointmentResponse(BaseModel):
    id: int
    service_type: str
    appointment_date: date
    appointment_time: time
    status: str


class BookedSlotsResponse(BaseModel):
    date: str
    booked_times: List[str]


class CancelAppointmentRequest(BaseModel):
    telegram_id: int = Field(gt=0, description="Telegram ID of the user who owns the appointment")


# Вспомогательные функции
def mask_user_id(telegram_id: int) -> str:
    """Маскируем telegram_id для безопасного логирования"""
    return f"***{str(telegram_id)[-3:]}"


def safe_get_user_info(user_data: dict) -> tuple[str, str]:
    """Безопасно извлекаем данные пользователя"""
    username = user_data.get('username', '').replace('@', '') if user_data.get('username') else 'не указан'
    first_name = user_data.get('first_name', 'не указано')
    return username, first_name


# API Endpoints
@app.get("/booked-slots")
async def get_booked_slots():
    """Получение занятых слотов для календаря"""
    try:
        booked_slots = await db.appointment_repo.get_booked_slots()
        return booked_slots
    except Exception as e:
        logger.error(f"Error getting booked slots: {e}")
        raise HTTPException(status_code=500, detail="Не удалось загрузить занятые слоты")


@app.get("/available-slots/{raw_date}")
async def get_available_slots(raw_date: str):
    """Получение доступных слотов для конкретной даты"""
    try:
        # Валидация формата даты
        target_date = datetime.strptime(raw_date, "%Y-%m-%d").date()

        if target_date < date.today():
            raise HTTPException(status_code=400, detail="Нельзя выбрать прошедшую дату")

        result = await db.appointment_repo.get_available_slots(target_date)
        return result
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Error getting available slots for date {raw_date}: {e}")
        raise HTTPException(status_code=500, detail="Не удалось загрузить доступные слоты")


@app.post("/appointments")
async def create_appointment(appointment: Appointment):
    """Создание новой записи"""
    try:
        # Проверяем доступность слота
        is_available = await db.appointment_repo.is_slot_available(
            appointment.appointment_date,
            appointment.appointment_time
        )

        if not is_available:
            raise HTTPException(status_code=400, detail="Это время уже занято")

        # Создаем запись
        appointment_id = await db.appointment_repo.create_appointment(
            appointment.telegram_id,
            appointment.service_type,
            appointment.appointment_date,
            appointment.appointment_time
        )

        # Получаем данные пользователя и отправляем уведомление
        try:
            client = await user_repo.get_user(appointment.telegram_id)
            username, first_name = safe_get_user_info(client)

            text_to_admin = (
                f"🔔 Новая запись!\n\n"
                f"Пользователь: @{username} ({first_name})\n"
                f"Услуга: {SERVICE_NAMES.get(appointment.service_type, appointment.service_type)}\n"
                f"Дата: {appointment.appointment_date}\n"
                f"Время: {appointment.appointment_time}"
            )

            await send_pending_message_to_admin(text_to_admin, appointment_id)
            await reminder_repo.create_reminder(
                appointment.telegram_id,
                appointment.appointment_date,
                appointment.appointment_time
            )
        except Exception as e:
            logger.error(f"Error sending notification for appointment {appointment_id}: {e}")
            # Не прерываем создание записи из-за ошибки уведомления

        # Безопасное логирование
        logger.info(
            f"Appointment created: ID={appointment_id}, user={mask_user_id(appointment.telegram_id)}, service={appointment.service_type}")

        return {
            "success": True,
            "appointment_id": appointment_id,
            "message": "Запись успешно создана"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating appointment for user {mask_user_id(appointment.telegram_id)}: {e}")
        raise HTTPException(status_code=500, detail="Не удалось создать запись")


@app.get("/appointments/{telegram_id}")
async def get_user_appointments(telegram_id: int):
    """Получение записей пользователя"""
    try:
        appointments = await db.appointment_repo.get_user_appointments(telegram_id)
        return appointments
    except Exception as e:
        logger.error(f"Error getting appointments for user {mask_user_id(telegram_id)}: {e}")
        raise HTTPException(status_code=500, detail="Не удалось загрузить записи")


@app.delete("/appointments/{appointment_id}")
async def cancel_appointment(appointment_id: int, cancel_request: CancelAppointmentRequest):
    """Отмена записи"""
    try:
        # Получаем запись для проверки
        appointment = await db.appointment_repo.get_appointment_by_id(appointment_id)
        if not appointment:
            raise HTTPException(status_code=404, detail="Запись не найдена")

        # Проверяем принадлежность записи пользователю
        if appointment['telegram_id'] != cancel_request.telegram_id:
            logger.warning(
                f"Unauthorized cancellation attempt: appointment {appointment_id} by user {mask_user_id(cancel_request.telegram_id)}")
            raise HTTPException(status_code=403, detail="Нет доступа к этой записи")

        # Отменяем запись
        success = await db.appointment_repo.cancel_appointment(appointment_id, cancel_request.telegram_id)
        if not success:
            raise HTTPException(status_code=404, detail="Запись не найдена")

        # Уведомляем админа
        try:
            client = await user_repo.get_user(appointment['telegram_id'])
            username, first_name = safe_get_user_info(client)

            text_to_admin = (
                f"🚫 Запись отменена!\n\n"
                f"Пользователь: @{username} ({first_name})\n"
                f"Услуга: {SERVICE_NAMES.get(appointment['service_type'], appointment['service_type'])}\n"
                f"Дата: {appointment['appointment_date']}\n"
                f"Время: {appointment['appointment_time']}"
            )

            await reminder_repo.cancel_reminders_for_appointment(
                appointment['telegram_id'],
                appointment['appointment_date']
            )
            await send_message_to_admin(text_to_admin)
        except Exception as e:
            logger.error(f"Error sending cancellation notification for appointment {appointment_id}: {e}")

        logger.info(f"Appointment {appointment_id} cancelled by user {mask_user_id(cancel_request.telegram_id)}")
        return {"success": True, "message": "Запись успешно отменена"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling appointment {appointment_id}: {e}")
        raise HTTPException(status_code=500, detail="Не удалось отменить запись")


@app.post("/webapp-data")
async def process_webapp_data(data: dict):
    """Обрабатывает данные от Telegram WebApp"""
    try:
        logger.info(f"WebApp data received with keys: {list(data.keys()) if data else 'empty'}")
        return {
            "success": True,
            "message": "Данные получены",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error processing webapp data: {e}")
        raise HTTPException(status_code=500, detail="Ошибка обработки данных")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Простая проверка соединения с БД
        await db.appointment_repo.get_booked_slots()
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


if __name__ == "__main__":
    import uvicorn

    # Получаем настройки из конфига
    host = load_config('api_host') or "0.0.0.0"
    port = load_config('api_port') or 8088

    uvicorn.run(app, host=host, port=port)