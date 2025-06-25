import logging
from logging.handlers import RotatingFileHandler


logger = logging.getLogger("__name__")
logger.setLevel(logging.INFO)  # Уровень логирования
# Создаём обработчик с ротацией по размеру
log_handler = RotatingFileHandler(
    "bot.log",        # Файл логов
    maxBytes=5*1024*1024,
    backupCount=2# Храним 5 mb логов
)
# Формат сообщений
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log_handler.setFormatter(formatter)
# Добавляем обработчик к логгеру
logger.addHandler(log_handler)