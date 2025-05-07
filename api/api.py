from pydantic import BaseModel
from typing import List
import config
from database.db import create_db_connection, get_free_times_from_db, get_booked_dates
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()
host_url = config.load_config("host_url")
# Добавляем CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[host_url],  # Разрешаем все источники, для продакшн лучше указать конкретный домен
    allow_credentials=True,
    allow_methods=["*"],  # Разрешаем все методы
    allow_headers=["*"],  # Разрешаем все заголовки
)

class FreeTimesResponse(BaseModel):
    free_times: List[str]

@app.get("/api/get_free_times")
async def get_free_times(date: str):
    db_pool = await create_db_connection()
    if not db_pool:
        return {"error": "Не удалось подключиться к базе данных."}

    # Определим рабочие часы
    working_hours = config.load_config("work_hours").split(",")

    # Получаем свободные слоты времени
    free_times = await get_free_times_from_db(db_pool, date, working_hours)

    return FreeTimesResponse(free_times=free_times)

@app.get("/api/get_booked_dates")
async def get_all_booked_dates():
    db_pool = await create_db_connection()
    if not db_pool:
        return {"error": "Не удалось подключиться к базе данных."}
    booked_dates = await get_booked_dates(db_pool)
    return booked_dates
