import asyncio
import datetime

from config import load_config
from database.db import ReminderRecord
from logger.bot_logger import get_logger

logger = get_logger("reminder_scheduler")



class ReminderScheduler:
    """Планировщик напоминаний с периодической проверкой БД"""

    def __init__(self, bot, reminder_repo, user_repo, appointment_repo, check_interval: int = 300):
        """
        Args:
            bot: Telegram bot instance
            reminder_repo: Репозиторий напоминаний
            user_repo: Репозиторий пользователей
            appointment_repo: Репозиторий записей
            check_interval: Интервал проверки в секундах (по умолчанию 5 минут)
        """
        self.bot = bot
        self.reminder_repo = reminder_repo
        self.user_repo = user_repo
        self.appointment_repo = appointment_repo
        self.check_interval = check_interval
        self.running = False
        self._task = None
        self._last_cleanup = None

    async def start(self):
        """Запускает планировщик"""
        if self.running:
            logger.warning("Планировщик уже запущен")
            return

        self.running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"Планировщик напоминаний запущен (интервал: {self.check_interval}с)")

    async def stop(self):
        """Останавливает планировщик"""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Планировщик напоминаний остановлен")

    async def _scheduler_loop(self):
        """Основной цикл планировщика"""
        while self.running:
            try:
                await self._check_and_send_reminders()
                now = datetime.datetime.now()
                if self._last_cleanup is None or (now - self._last_cleanup).days >= 1:
                    await self._cleanup_cancelled_appointments()
                    self._last_cleanup = now
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле планировщика: {e}")
                await asyncio.sleep(60)  # Короткая пауза при ошибке

    async def _cleanup_cancelled_appointments(self):
        interval = load_config('CLEANUP_INTERVAL')
        await self.appointment_repo.remove_appointment(interval=interval)

    async def _check_and_send_reminders(self):
        """Проверяет и отправляет готовые напоминания"""
        current_time = datetime.datetime.now()
        reminders = await self.reminder_repo.get_pending_reminders(current_time)
        logger.info(f"Найдено {len(reminders)} напоминаний для отправки")

        if not reminders:
            return

        for reminder in reminders:
            await self._process_reminder(reminder)

    async def _process_reminder(self, reminder: ReminderRecord):
        """Обрабатывает одно напоминание"""
        try:
            # Проверяем, что запись все еще существует
            appointment_exists = await self.appointment_repo.check_appointment_exists(
                telegram_id=reminder.telegram_id,
                appointment_date=reminder.appointment_date
            )

            if not appointment_exists:
                logger.info(f"Запись отменена, пропускаем напоминание для {reminder.telegram_id}")
                await self.reminder_repo.mark_reminder_sent(reminder.id)  # Помечаем как обработанное
                return

            # Отправляем напоминание
            message = (
                f"🔔 Напоминание: у вас запись на {reminder.appointment_date} "
                f"в {reminder.appointment_time}."
            )

            await self.bot.send_message_to(reminder.telegram_id, message)
            await self.reminder_repo.mark_reminder_sent(reminder.id)

            logger.info(f"Напоминание отправлено пользователю {reminder.telegram_id}")

        except Exception as e:
            logger.error(f"Ошибка обработки напоминания {reminder.id}: {e}")


# Функции для интеграции с существующим кодом
async def schedule_appointment_reminder(telegram_id: int, appointment_date: datetime.date,
                                        appointment_time: datetime.time, reminder_repo):
    """Планирует напоминание при создании записи"""
    return await reminder_repo.create_reminder(telegram_id, appointment_date, appointment_time)


async def cancel_appointment_reminders(telegram_id: int, appointment_date: datetime.date,
                                       reminder_repo):
    """Отменяет напоминания при отмене записи"""
    return await reminder_repo.cancel_reminders_for_appointment(telegram_id, appointment_date)