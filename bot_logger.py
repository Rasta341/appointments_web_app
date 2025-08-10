import logging
from logging.handlers import RotatingFileHandler
import os

# Создаем директорию для логов если не существует
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Исправлено: __name__ без кавычек, используем __name__ модуля
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Проверяем, что обработчики еще не добавлены (избегаем дублирования)
if not logger.handlers:
    # Создаём обработчик с ротацией по размеру
    log_handler = RotatingFileHandler(
        os.path.join(log_dir, "bot.log"),  # Путь к файлу логов
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=2,  # Исправлено: добавлена запятая
        encoding='utf-8'  # Добавлено: кодировка для корректного отображения
    )

    # Формат сообщений
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    log_handler.setFormatter(formatter)

    # Добавляем обработчик к логгеру
    logger.addHandler(log_handler)

    # Дополнительно: добавляем консольный вывод для разработки
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# Предотвращаем распространение логов к родительским логгерам
logger.propagate = False


def get_logger(name: str = None) -> logging.Logger:
    """
    Функция для получения настроенного логгера
    Args:
        name: Имя логгера (по умолчанию используется имя модуля)
    Returns:
        Настроенный логгер
    """
    if name:
        child_logger = logger.getChild(name)
        return child_logger
    return logger


# Добавляем функции для совместимости с bot_logger.error()
def info(message):
    logger.info(message)


def error(message):
    logger.error(message)


def warning(message):
    logger.warning(message)


def debug(message):
    logger.debug(message)


# Экспортируем настроенный логгер
__all__ = ['logger', 'get_logger', 'info', 'error', 'warning', 'debug']
