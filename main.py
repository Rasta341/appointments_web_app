import asyncio
from logger import bot_logger
import os
import sys
from pathlib import Path

# Добавляем пути к модулям
sys.path.append(str(Path(__file__).parent / "api"))
sys.path.append(str(Path(__file__).parent))

# Настройка логирования

logger = bot_logger.get_logger(__name__)


async def run_bot():
    """Запуск Telegram бота"""
    try:
        logger.info("Запуск Telegram бота...")

        # Импортируем и запускаем бот
        from bot import main as bot_main
        await bot_main()

    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        raise


async def run_api():
    """Запуск FastAPI сервера"""
    try:
        import uvicorn
        from api.api import app

        logger.info("Запуск API сервера...")
        config = uvicorn.Config(
            app=app,
            host=os.getenv("API_HOST", "0.0.0.0"),
            port=int(os.getenv("API_PORT", 8088)),
            log_level="info",
            access_log=True
        )
        server = uvicorn.Server(config)
        await server.serve()

    except Exception as e:
        logger.error(f"Ошибка запуска API: {e}")
        raise


async def main():
    """Основная функция - запуск бота и API одновременно"""
    logger.info("Запуск приложения Nail Salon...")

    # Небольшая задержка для инициализации
    await asyncio.sleep(2)

    # Создаем задачи для параллельного выполнения
    tasks = [
        asyncio.create_task(run_bot(), name="telegram_bot"),
        asyncio.create_task(run_api(), name="api_server")
    ]

    try:
        # Запускаем все задачи одновременно
        await asyncio.gather(*tasks, return_exceptions=True)
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        logger.info("Приложение остановлено")


if __name__ == "__main__":
    asyncio.run(main())