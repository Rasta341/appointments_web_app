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
# Конфигурация детальных услуг (можно вынести в config)
SERVICE_TYPES = json.loads(load_config("service_types"))
config_path = os.getenv("services_path", "./services.json")
with open(config_path, "r", encoding="utf-8") as f:
    SERVICE_NAMES = json.load(f)

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
    allow_headers=["*"],
)


# Обновленная модель данных
class Appointment(BaseModel):
    telegram_id: int = Field(gt=0, description="Telegram user ID")
    service_type: str = Field(description="Type of service")
    service_name: str = Field(description="Human readable service name")
    service_price: int = Field(gt=0, description="Service price")
    appointment_date: date = Field(description="Date of appointment")
    appointment_time: time = Field(description="Time of appointment")

    @field_validator('service_type')
    def validate_service_type(cls, v):
        allowed_services = list(SERVICE_TYPES.keys())
        if v not in allowed_services:
            raise ValueError(f'Service type must be one of: {allowed_services}')
        return v

    @field_validator('service_name')
    def validate_service_name(cls, v, info):
        # Проверяем соответствие service_name
        service_name = info.data.get('service_name')
        if service_name and service_name in SERVICE_NAMES:
            if v not in SERVICE_NAMES[service_name]:
                allowed_names = list(SERVICE_NAMES[service_name].keys())
                raise ValueError(f'Service detail must be one of: {allowed_names}')
        return v

    @field_validator('service_price')
    def validate_service_price(cls, v, info):
        # Проверяем соответствие цены с конфигурацией
        service_type = info.data.get('service_type')
        service_name = info.data.get('service_name')

        if (service_type and service_name and
                service_type in SERVICE_TYPES and
                service_name in SERVICE_NAMES[service_type]):

            expected_price = SERVICE_NAMES[service_type][service_name]['price']
            if v != expected_price:
                raise ValueError(f'Price mismatch. Expected {expected_price}, got {v}')
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
    service_name: str  # Теперь содержит service_detail ID
    service_price: int
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


def get_service_display_name(service_type: str, service_name: str) -> str:
    """Получение отображаемого имени услуги по service_detail ID"""
    if service_type in SERVICE_NAMES and service_name in SERVICE_NAMES[service_type]:
        return SERVICE_NAMES[service_type][service_name]['name']
    return SERVICE_TYPES.get(service_type, service_type)


def get_service_price(service_type: str, service_name: str) -> int:
    """Получение цены услуги по service_detail ID"""
    if service_type in SERVICE_NAMES and service_name in SERVICE_NAMES[service_type]:
        return SERVICE_NAMES[service_type][service_name]['price']
    return 0


# API Endpoints
@app.get("/service-config")
async def get_service_config():
    """Получение конфигурации услуг для фронтенда"""
    return {
        "service_types": SERVICE_TYPES,
        "service_names": SERVICE_NAMES
    }


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

        # Создаем запись - сохраняем service_detail в поле service_name
        appointment_id = await db.appointment_repo.create_appointment(
            telegram_id=appointment.telegram_id,
            service_type=appointment.service_type,
            service_name=appointment.service_name,  # Сохраняем service_detail в service_name
            service_price=appointment.service_price,
            appointment_date=appointment.appointment_date,
            appointment_time=appointment.appointment_time
        )

        # Получаем данные пользователя и отправляем уведомление
        try:
            client = await user_repo.get_user(appointment.telegram_id)
            username, first_name = safe_get_user_info(client)

            display_name = get_service_display_name(appointment.service_type, appointment.service_name)

            text_to_admin = (
                f"🔔 Новая запись!\n\n"
                f"Пользователь: @{username} ({first_name})\n"
                f"Услуга: {display_name}\n"
                f"Цена: {appointment.service_price} ₽\n"
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

        logger.info(
            f"Appointment created: ID={appointment_id}, "
            f"user={mask_user_id(appointment.telegram_id)}, "
            f"service={appointment.service_type}:{appointment.service_name}, "
            f"price={appointment.service_price}"
        )

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
    """Получение записей пользователя с расширенной информацией"""
    try:
        appointments = await db.appointment_repo.get_user_appointments(telegram_id)

        # Обогащаем данные информацией об услугах
        enriched_appointments = []
        for appointment in appointments:
            service_name = appointment.get('service_name', '')  # service_name хранится в service_name
            service_type = appointment.get('service_type', '')

            enriched_appointment = {
                **appointment,
                'display_name': get_service_display_name(service_type, service_name),
                'price': get_service_price(service_type, service_name)
            }
            enriched_appointments.append(enriched_appointment)

        return enriched_appointments
    except Exception as e:
        logger.error(f"Error getting appointments for user {mask_user_id(telegram_id)}: {e}")
        raise HTTPException(status_code=500, detail="Не удалось загрузить записи")


@app.delete("/appointments/{appointment_id}")
async def cancel_appointment(appointment_id: int, telegram_id: int):
    """Отмена записи"""
    try:
        appointment = await db.appointment_repo.get_appointment_by_id(appointment_id)
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")

        if appointment['telegram_id'] != telegram_id:
            raise HTTPException(status_code=403, detail="Access denied")

        client = await user_repo.get_user(appointment['telegram_id'])

        # service_name хранится в поле service_name
        service_name = appointment.get('service_name', '')
        service_type = appointment.get('service_type', '')
        display_name = get_service_display_name(service_type, service_name)
        service_price = get_service_price(service_type, service_name)

        text_to_admin = (
            f"🚫 Запись отменена!\n\n"
            f"Пользователь: @{client.get('username', '') or ''}:{client.get('first_name', '') or ''}\n"
            f"Услуга: {display_name}\n"
            f"Цена: {service_price} ₽\n"
            f"Дата: {appointment['appointment_date']}\n"
            f"Время: {appointment['appointment_time']}"
        )

        success = await db.appointment_repo.cancel_appointment(appointment_id, telegram_id)
        await reminder_repo.cancel_reminders_for_appointment(appointment['telegram_id'],
                                                             appointment['appointment_date'])
        await send_message_to_admin(text_to_admin)

        if not success:
            raise HTTPException(status_code=404, detail="Appointment not found")

        return {"success": True, "message": "Appointment cancelled successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling appointment {appointment_id} for user {telegram_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


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

    host = load_config('api_host') or "0.0.0.0"
    port = load_config('api_port') or 8088

    uvicorn.run(app, host=host, port=port)