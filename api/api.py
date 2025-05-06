from fastapi import FastAPI
from pydantic import BaseModel
from typing import List

import config
from database.db import create_db_connection, get_free_times_from_db

app = FastAPI()

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
