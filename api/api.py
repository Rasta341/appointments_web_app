from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from datetime import date, time, datetime
from typing import List
import sys
import os

from bot.bot import send_message_to_admin
from database.db import reminder_repo, user_repo

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger.bot_logger import get_logger
from database import db

logger = get_logger("api")

# Контекстный менеджер для жизненного цикла приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_database()
    yield
    # Shutdown
    await db.close_database()


app = FastAPI(title="Nail Salon API", lifespan=lifespan)

# CORS для взаимодействия с WebApp
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
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


# Модели данных
class Appointment(BaseModel):
    telegram_id: int
    service_type: str  # 'manicure', 'pedicure', 'both'
    appointment_date: date
    appointment_time: time

    @field_validator('appointment_date')
    def validate_appointment_date(cls, v):
        if v < date.today():
            raise ValueError('appointment_date cannot be in the past')
        return v

    @field_validator('appointment_time')
    def validate_appointment_time(cls, v):
        allowed_times = [time(10, 0), time(12, 0), time(14, 0), time(16, 0), time(18, 0)]
        if v not in allowed_times:
            raise ValueError(f'appointment_time must be one of: {[t.strftime("%H:%M") for t in allowed_times]}')
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

service_names = {
                'manicure': '💅 Маникюр',
                'pedicure': '🦶 Педикюр',
                'both': '✨ Маникюр + Педикюр'
            }
# API Endpoints
@app.get("/booked-slots")
async def get_booked_slots():
    """Получение занятых слотов для календаря"""
    try:
        booked_slots = await db.appointment_repo.get_booked_slots()
        return booked_slots
    except Exception as e:
        logger.error(f"Error getting booked slots: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/available-slots/{raw_date}")
async def get_available_slots(raw_date: str):
    """Получение доступных слотов для конкретной даты"""
    try:
        # Валидация формата даты
        target_date = datetime.strptime(raw_date, "%Y-%m-%d").date()

        # Проверка, что дата не в прошлом
        if target_date < date.today():
            raise HTTPException(status_code=400, detail="Date cannot be in the past")

        result = await db.appointment_repo.get_available_slots(target_date)
        return result
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Error getting available slots for date {raw_date}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


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
            raise HTTPException(status_code=400, detail="Time slot is already booked")

        # Создаем запись
        appointment_id = await db.appointment_repo.create_appointment(
            appointment.telegram_id,
            appointment.service_type,
            appointment.appointment_date,
            appointment.appointment_time
        )
        client = await user_repo.get_user(appointment.telegram_id)
        text_to_admin = (f"🔔 Новая запись!\n\nПользователь: @{client['username'] or ''}:{client['first_name'] or ''}"
                         f"\nУслуга: {service_names.get(appointment.service_type, appointment.service_type)}\nДата: {appointment.appointment_date}"
                         f"\nВремя: {appointment.appointment_time}")
        await send_message_to_admin(text_to_admin)
        await reminder_repo.create_reminder(appointment.telegram_id, appointment.appointment_date, appointment.appointment_time)
        logger.info(f"sended notify to admin: {appointment}")

        return {
            "success": True,
            "appointment_id": appointment_id,
            "message": "Appointment created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating appointment for user {appointment.telegram_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create appointment")


@app.get("/appointments/{telegram_id}")
async def get_user_appointments(telegram_id: int):
    """Получение записей пользователя"""
    try:
        appointments = await db.appointment_repo.get_user_appointments(telegram_id)
        return appointments
    except Exception as e:
        logger.error(f"Error getting appointments for user {telegram_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/appointments/{appointment_id}")
async def cancel_appointment(appointment_id: int, telegram_id: int):
    """Отмена записи"""
    try:
        # Дополнительная проверка принадлежности записи пользователю
        appointment = await db.appointment_repo.get_appointment_by_id(appointment_id)
        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")

        if appointment['telegram_id'] != telegram_id:
            raise HTTPException(status_code=403, detail="Access denied")

        success = await db.appointment_repo.cancel_appointment(appointment_id, telegram_id)
        client = await user_repo.get_user(appointment['telegram_id'])
        text_to_admin = (f"🚫 Запись отменена!\n\nПользователь: @{client['username'] or ''}:{client['first_name'] or ''}"
                         f"\nУслуга: {service_names.get(appointment['service_type'], appointment['service_type'])}\nДата: {appointment['appointment_date']}"
                         f"\nВремя: {appointment['appointment_time']}")
        await send_message_to_admin(text_to_admin)
        await reminder_repo.cancel_reminders_for_appointment(telegram_id, appointment['appointment_date'])
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
        # TODO: Добавить валидацию WebApp данных
        # TODO: Добавить проверку подписи от Telegram
        return {
            "success": True,
            "message": "Data received successfully",
            "data": data
        }
    except Exception as e:
        logger.error(f"Error processing webapp data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8088)
