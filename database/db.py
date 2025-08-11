import datetime
from dataclasses import dataclass
from enum import Enum

import asyncpg
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from datetime import date, time

from config import load_config
from logger.bot_logger import get_logger

logger = get_logger("database")
# Конфигурация базы данных
DATABASE_URL = f"postgresql://{load_config('DB_USER')}:{load_config('DB_PASSWORD')}@{load_config('DB_HOST')}/postgres"


class DatabaseManager:
    """Менеджер для работы с базой данных"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool = None

    async def init_pool(self, min_size: int = 1, max_size: int = 10):
        """Инициализация пула соединений"""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.database_url,
                min_size=min_size,
                max_size=max_size
            )
            logger.info("Database pool initialized")

    async def close_pool(self):
        """Закрытие пула соединений"""
        if self._pool:
            await self._pool.close()
            logger.info("Database pool closed")

    @asynccontextmanager
    async def get_connection(self):
        """Контекстный менеджер для получения соединения с БД"""
        if self._pool is None:
            await self.init_pool()

        conn = await self._pool.acquire()
        try:
            yield conn
        except Exception as e:
            logger.error(f"Database error: {e}")
            raise
        finally:
            await self._pool.release(conn)


# Глобальный экземпляр менеджера БД
db_manager = DatabaseManager(DATABASE_URL)


class AppointmentRepository:
    """Репозиторий для работы с записями"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def get_booked_slots(self) -> Dict[str, List[str]]:
        """Получение занятых слотов для календаря"""
        async with self.db_manager.get_connection() as conn:
            query = """
                    SELECT appointment_date, appointment_time, COUNT(*) as count
                    FROM appointments
                    WHERE appointment_date >= CURRENT_DATE
                      AND appointment_date <= CURRENT_DATE + INTERVAL '2 months'
                      AND status != 'cancelled'
                    GROUP BY appointment_date, appointment_time \
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

    async def get_available_slots(self, target_date: date) -> Dict[str, Any]:
        """Получение доступных слотов для конкретной даты"""
        async with self.db_manager.get_connection() as conn:
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

            rows = await conn.fetch(query, target_date)
            booked_times = [row['appointment_time'].strftime('%H:%M') for row in rows]

            # Возвращаем доступные слоты
            available_slots = [slot for slot in all_slots if slot not in booked_times]

            return {
                "date": target_date.isoformat(),
                "available_slots": available_slots,
                "booked_slots": booked_times
            }

    async def is_slot_available(self, appointment_date: date, appointment_time: time) -> bool:
        """Проверка доступности слота"""
        async with self.db_manager.get_connection() as conn:
            query = """
                    SELECT COUNT(*) as count
                    FROM appointments
                    WHERE appointment_date = $1
                      AND appointment_time = $2
                      AND status != 'cancelled' \
                    """

            result = await conn.fetchrow(query, appointment_date, appointment_time)
            return result['count'] < 1

    async def create_appointment(
            self,
            telegram_id: int,
            service_type: str,
            appointment_date: date,
            appointment_time: time
    ) -> int:
        """Создание новой записи"""
        async with self.db_manager.get_connection() as conn:
            # Используем транзакцию для атомарности операции
            async with conn.transaction():
                # Создаем пользователя если не существует
                user_query = """
                             INSERT INTO users (telegram_id)
                             VALUES ($1)
                             ON CONFLICT (telegram_id) DO NOTHING \
                             """
                await conn.execute(user_query, telegram_id)

                # Создаем запись
                insert_query = """
                               INSERT INTO appointments (telegram_id, service_type, appointment_date, appointment_time)
                               VALUES ($1, $2, $3, $4)
                               RETURNING id \
                               """

                appointment_id = await conn.fetchval(
                    insert_query,
                    telegram_id,
                    service_type,
                    appointment_date,
                    appointment_time
                )
                logger.info(f"{telegram_id}, {service_type}, {appointment_date}:{appointment_time} was created")

                return appointment_id

    async def get_user_appointments(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Получение записей пользователя"""
        async with self.db_manager.get_connection() as conn:
            query = """
                    SELECT id, service_type, appointment_date, appointment_time, status, created_at
                    FROM appointments
                    WHERE telegram_id = $1
                    ORDER BY appointment_date DESC, appointment_time DESC \
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

    async def cancel_appointment(self, appointment_id: int, telegram_id: int) -> bool:
        """Отмена записи"""
        async with self.db_manager.get_connection() as conn:
            query = """
                    UPDATE appointments
                    SET status = 'cancelled'
                    WHERE id = $1 \
                      AND telegram_id = $2
                    RETURNING id \
                    """

            result = await conn.fetchval(query, appointment_id, telegram_id)
            logger.info(f"{appointment_id}, {telegram_id} was deleted")
            return result is not None

    async def get_appointment_by_id(self, appointment_id: int) -> Optional[Dict[str, Any]]:
        """Получение записи по ID"""
        async with self.db_manager.get_connection() as conn:
            query = """
                    SELECT id, telegram_id, service_type, appointment_date, appointment_time, status, created_at
                    FROM appointments
                    WHERE id = $1 \
                    """

            row = await conn.fetchrow(query, appointment_id)
            if row:
                return {
                    "id": row['id'],
                    "telegram_id": row['telegram_id'],
                    "service_type": row['service_type'],
                    "appointment_date": row['appointment_date'],
                    "appointment_time": row['appointment_time'],
                    "status": row['status'],
                    "created_at": row['created_at']
                }
            return None

    async def check_appointment_exists(self, user_id, appointment_date):
        # Проверяем, существует ли запись
        async with self.db_manager.get_connection() as conn:
            query = "SELECT user_id FROM appointments WHERE user_id = $1 AND appointment_date = $2"
            record = await conn.fetchrow(query, user_id, appointment_date)
            return record

class UserRepository:
    """Репозиторий для работы с пользователями"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def create_user(self, telegram_id: int, username, first_name, last_name):
        """Создание пользователя"""
        async with self.db_manager.get_connection() as conn:
            query = """
                    INSERT INTO users (telegram_id, username, first_name, last_name)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (telegram_id) DO NOTHING
                    RETURNING telegram_id 
                    """
            try:
                result = await conn.fetchval(query, telegram_id, username, first_name, last_name)
            except Exception as e:
                logger.error(e)
            return result is not None

    async def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Получение пользователя по telegram_id"""
        async with self.db_manager.get_connection() as conn:
            query = """
                    SELECT telegram_id, username, first_name, last_name
                    FROM users
                    WHERE telegram_id = $1 
                    """

            row = await conn.fetchrow(query, telegram_id)

            if row:
                return {
                    "telegram_id": row['telegram_id'],
                    "username": row['username'],
                    "first_name":row['first_name'],
                    "last_name":row['last_name']
                }
            return None


class ReminderStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    CANCELLED = "cancelled"


@dataclass
class ReminderRecord:
    id: int
    telegram_id: int
    appointment_date: datetime.date
    appointment_time: datetime.time
    reminder_time: datetime.datetime
    status: ReminderStatus
    created_at: datetime.datetime

class ReminderRepository:
    """Репозиторий для работы с напоминаниями в БД"""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    async def create_reminder(self, telegram_id: int, appointment_date: datetime.date,
                              appointment_time: datetime.time) -> bool:
        """Создает напоминание в БД"""
        async with self.db_manager.get_connection() as conn:
            try:
                # Вычисляем время напоминания (день до записи в 18:00)
                reminder_time = datetime.datetime.combine(
                    appointment_date, datetime.time(18, 0)
                ) - datetime.timedelta(days=1)

                query = """
                    INSERT INTO reminders (telegram_id, appointment_date, appointment_time, 
                                         reminder_time, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """
                await conn.execute(
                    query,
                    telegram_id, appointment_date, appointment_time,
                    reminder_time, ReminderStatus.PENDING.value, datetime.datetime.now()
                )
                logger.info(f"Создано напоминание для пользователя {telegram_id} на {reminder_time}")
                return True

            except Exception as e:
                logger.error(f"Ошибка создания напоминания: {e}")
                return False

    async def get_pending_reminders(self, current_time: datetime.datetime) -> List[ReminderRecord]:
        """Получает напоминания, которые нужно отправить"""
        async with self.db_manager.get_connection() as conn:
            try:
                query = """
                    SELECT id, telegram_id, appointment_date, appointment_time, 
                           reminder_time, status, created_at
                    FROM reminders 
                    WHERE status = $1 AND reminder_time <= $2
                    ORDER BY reminder_time
                """
                rows = await conn.fetch(query, ReminderStatus.PENDING.value, current_time)

                reminders = []
                for row in rows:
                    reminders.append(ReminderRecord(
                        id=row['id'],
                        telegram_id=row['telegram_id'],
                        appointment_date=row['appointment_date'],
                        appointment_time=row['appointment_time'],
                        reminder_time=row['reminder_time'],
                        status=ReminderStatus(row['status']),
                        created_at=row['created_at']
                    ))

                return reminders

            except Exception as e:
                logger.error(f"Ошибка получения напоминаний: {e}")
                return []

    async def mark_reminder_sent(self, reminder_id: int) -> bool:
        """Помечает напоминание как отправленное"""
        async with self.db_manager.get_connection() as conn:
            try:
                query = "UPDATE reminders SET status = $1, sent_at = $2 WHERE id = $3"
                await conn.execute(query, ReminderStatus.SENT.value, datetime.datetime.now(), reminder_id)
                return True
            except Exception as e:
                logger.error(f"Ошибка обновления статуса напоминания {reminder_id}: {e}")
                return False

    async def cancel_reminders_for_appointment(self, telegram_id: int,
                                               appointment_date: datetime.date) -> bool:
        """Отменяет напоминания при отмене записи"""
        async with self.db_manager.get_connection() as conn:
            try:
                query = """
                    UPDATE reminders 
                    SET status = $1 
                    WHERE telegram_id = $2 AND appointment_date = $3 AND status = $4
                """
                await conn.execute(
                    query,
                    ReminderStatus.CANCELLED.value,
                    telegram_id,
                    appointment_date,
                    ReminderStatus.PENDING.value
                )
                logger.info(f"Отменены напоминания для пользователя {telegram_id} на {appointment_date}")
                return True
            except Exception as e:
                logger.error(f"Ошибка отмены напоминаний: {e}")
                return False


# Создаем экземпляры репозиториев
appointment_repo = AppointmentRepository(db_manager)
user_repo = UserRepository(db_manager)
reminder_repo = ReminderRepository(db_manager)


# Функции для управления жизненным циклом БД
async def init_database():
    """Инициализация подключения к БД"""
    await db_manager.init_pool()


async def close_database():
    """Закрытие подключения к БД"""
    await db_manager.close_pool()