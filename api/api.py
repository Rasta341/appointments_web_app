import logging

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import date, time, datetime
import asyncpg
import os
from typing import List, Optional
import json

import bot_logger
from config import load_config

app = FastAPI(title="Nail Salon API")
logging.basicConfig(level=logging.ERROR)
logger = bot_logger
# CORS для взаимодействия с WebApp
app.add_middleware(
    CORSMiddleware,
    #allow_origins=["*"],
    allow_origins=[
        "https://manicure-appointments.shop",
        "http://manicure-appointments.shop",
        "https://www.manicure-appointments.shop",
        "http://www.manicure-appointments.shop",
        "https://web.telegram.org",
        "http://web.telegram.org",
    ],                                              # В продакшене укажите конкретный домен
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Конфигурация базы данных
DATABASE_URL = f"postgresql://{load_config("db_user")}:{load_config("db_password")}@{load_config("db_host")}/postgres"


# Модели данных
class AppointmentCreate(BaseModel):
    telegram_id: int
    service_type: str  # 'manicure', 'pedicure', 'both'
    appointment_date: date
    appointment_time: time


class AppointmentResponse(BaseModel):
    id: int
    service_type: str
    appointment_date: date
    appointment_time: time
    status: str


class BookedSlotsResponse(BaseModel):
    date: str
    booked_times: List[str]


# Подключение к базе данных
async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)

# Получение занятых слотов для календаря
@app.get("/booked-slots")
async def get_booked_slots():
    conn = await get_db_connection()
    try:
        # Получаем все записи на ближайшие 2 месяца
        query = """
        SELECT appointment_date, appointment_time, COUNT(*) as count
        FROM appointments 
        WHERE appointment_date >= CURRENT_DATE 
        AND appointment_date <= CURRENT_DATE + INTERVAL '2 months'
        AND status != 'cancelled'
        GROUP BY appointment_date, appointment_time
        """

        rows = await conn.fetch(query)

        # Группируем по датам
        booked_slots = {}
        for row in rows:
            date_str = row['appointment_date'].strftime('%Y-%m-%d')
            time_str = row['appointment_time'].strftime('%H:%M')

            if date_str not in booked_slots:
                booked_slots[date_str] = []

            booked_slots[date_str].append(time_str)

        return booked_slots

    finally:
        await conn.close()


# Получение доступных слотов для конкретной даты
@app.get("/available-slots/{rawDate}")
async def get_available_slots(rawDate: str):
    conn = await get_db_connection()
    date = datetime.strptime(rawDate,"%Y-%m-%d")
    try:
        # Все возможные временные слоты
        all_slots = ["10:00", "12:00", "14:00", "16:00", "18:00"]

        # Получаем занятые слоты на эту дату
        query = """
        SELECT appointment_time, COUNT(*) as count
        FROM appointments 
        WHERE appointment_date = $1
        AND status != 'cancelled'
        GROUP BY appointment_time
        HAVING COUNT(*) >= 1
        """
        # Максимум 1 запись на слот

        rows = await conn.fetch(query, date)
        booked_times = [row['appointment_time'].strftime('%H:%M') for row in rows]

        # Возвращаем доступные слоты
        available_slots = [slot for slot in all_slots if slot not in booked_times]

        return {
            "date": date,
            "available_slots": available_slots,
            "booked_slots": booked_times
        }

    finally:
        await conn.close()


# Создание новой записи
@app.post("/appointments")
async def create_appointment(appointment: AppointmentCreate):
    conn = await get_db_connection()
    try:
        # Проверяем, что слот свободен
        check_query = """
        SELECT COUNT(*) as count
        FROM appointments 
        WHERE appointment_date = $1 
        AND appointment_time = $2
        AND status != 'cancelled'
        """

        #максимум 1 запись на слот:
        result = await conn.fetchrow(
            check_query,
            appointment.appointment_date,
            appointment.appointment_time
        )

        if result['count'] >= 1: 
            raise HTTPException(status_code=400, detail="Время уже занято")

        # Создаем пользователя если не существует
        user_query = """
        INSERT INTO users (telegram_id) 
        VALUES ($1) 
        ON CONFLICT (telegram_id) DO NOTHING
        """
        await conn.execute(user_query, appointment.telegram_id)

        # Создаем запись
        insert_query = """
        INSERT INTO appointments (telegram_id, service_type, appointment_date, appointment_time)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """

        appointment_id = await conn.fetchval(
            insert_query,
            appointment.telegram_id,
            appointment.service_type,
            appointment.appointment_date,
            appointment.appointment_time
        )

        return {
            "success": True,
            "appointment_id": appointment_id,
            "message": "Запись успешно создана"
        }

    except Exception as e:
        logger.error()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


# Получение записей пользователя
@app.get("/appointments/{telegram_id}")
async def get_user_appointments(telegram_id: int):
    conn = await get_db_connection()
    try:
        query = """
        SELECT id, service_type, appointment_date, appointment_time, status, created_at
        FROM appointments
        WHERE telegram_id = $1
        ORDER BY appointment_date DESC, appointment_time DESC
        """

        rows = await conn.fetch(query, telegram_id)

        appointments = []
        for row in rows:
            appointments.append({
                "id": row['id'],
                "service_type": row['service_type'],
                "appointment_date": row['appointment_date'].strftime('%Y-%m-%d'),
                "appointment_time": row['appointment_time'].strftime('%H:%M'),
                "status": row['status'],
                "created_at": row['created_at'].isoformat()
            })

        return appointments

    finally:
        await conn.close()


# Отмена записи
@app.delete("/appointments/{appointment_id}")
async def cancel_appointment(appointment_id: int, telegram_id: int):
    conn = await get_db_connection()
    try:
        query = """
        UPDATE appointments 
        SET status = 'cancelled'
        WHERE id = $1 AND telegram_id = $2
        RETURNING id
        """

        result = await conn.fetchval(query, appointment_id, telegram_id)

        if not result:
            raise HTTPException(status_code=404, detail="Запись не найдена")

        return {"success": True, "message": "Запись отменена"}

    finally:
        await conn.close()


# Эндпоинт для получения данных от WebApp
@app.post("/webapp-data")
async def process_webapp_data(data: dict):
    """
    Обрабатывает данные от Telegram WebApp
    """
    try:
        # Здесь можно добавить дополнительную обработку
        # например, отправку уведомлений или логирование

        return {
            "success": True,
            "message": "Данные получены",
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8088)
