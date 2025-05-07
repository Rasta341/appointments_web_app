from datetime import datetime
from config import load_config
from bot_logger import logger
import asyncpg


DB_CONFIG = {
    "user": load_config("db_user"),
    "password": load_config("db_password"),
    "database": load_config("db_name"),
    "host": load_config("db_host"),
    "port": load_config("db_port")
}

async def create_db_connection():
    try:
        pool = await asyncpg.create_pool(**DB_CONFIG)
        logger.info("Подключение к базе данных установлено.")
        return pool
    except Exception as e:
        logger.error(f"Ошибка подключения к базе данных: {e}")
        return None


async def get_booked_dates(db_pool):
    async with db_pool.acquire() as conn:
        # Запрос на проверку занятых дат
        check_query = """
            SELECT date FROM appointments 
            GROUP BY date
            HAVING COUNT(time) >= 2
        """
        # Выполняем запрос и получаем занятые даты
        records = await conn.fetch(check_query)
        return {record["date"] for record in records}

async def get_free_times_from_db(db_pool, date, working_hours):
    async with db_pool.acquire() as conn:
        query = "SELECT time FROM appointments WHERE date = $1"
        date = datetime.strptime(date, "%Y-%m-%d").date()
        booked_times = await conn.fetch(query, date)
        booked_times = {record['time'].strftime("%H:%M") for record in booked_times}  # Преобразуем в строки
        # Оставляем только свободное время
        free_times = [time for time in working_hours if time not in booked_times]
        return free_times

async def book_appointment(db_pool, procedure, date, time: str, user_name, user_id) -> bool:
    date = datetime.strptime(date, "%Y-%m-%d").date()
    time = datetime.strptime(time,"%H:%M").time()
    if not user_name:
        logger.error("Ошибка: user_name = None")
        return False
    async with db_pool.acquire() as conn:
        try:
            insert_query = """
                    INSERT INTO appointments (procedure, date, time, username, user_id) 
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id;
                    """
            await conn.execute(insert_query, procedure, date, time, str(user_name), int(user_id))
            logger.info(f"Создана новая запись: {procedure}, {date}, {time}, {user_id}")
        except asyncpg.DataError as e:
            logger.error(f"Некорректные данные: {e}")
        except asyncpg.UniqueViolationError:
            logger.error(f"Запись уже существует: {procedure}, {date}, {time}, {user_id}")
            raise
        return True

async def get_user_appointments(db_pool, user_id):
    async with db_pool.acquire() as conn:
        query = "SELECT id, procedure, date, time FROM appointments WHERE user_id = $1"
        records = await conn.fetch(query, user_id)
        return records
async def delete_user_appointment(db_pool, record_id):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM appointments WHERE id = $1", record_id)

async def check_appointment_exists(db_pool, user_id, appointment_date):
    # Проверяем, существует ли запись
    async with db_pool.acquire() as conn:
        query = "SELECT user_id FROM appointments WHERE user_id = $1 AND date = $2"
        record = await conn.fetchrow(query, user_id, appointment_date)
        return record

# Функция получения пользователей для напоминания
async def get_users_for_reminder(date,db_pool):
    """Функция получения пользователей, которым нужно отправить напоминание"""
    async with db_pool.acquire() as conn:
        query = f"""
        SELECT username, date, time, user_id FROM appointments
        WHERE date = $1
        """
        records = await conn.fetch(query, date)
    return records