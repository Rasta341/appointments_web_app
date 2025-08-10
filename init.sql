-- Инициализация базы данных для Nail Salon
-- Создание таблиц по структуре из скриншотов

-- Создание таблицы appointments
CREATE TABLE IF NOT EXISTS appointments (
    id SERIAL PRIMARY KEY,
    user_id INT4,
    telegram_id INT8 NOT NULL,
    service_type VARCHAR(50),
    appointment_date DATE,
    appointment_time TIME,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'cancelled', 'completed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Создание таблицы users
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id INT8 NOT NULL UNIQUE,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Создание индексов для оптимизации
CREATE INDEX IF NOT EXISTS idx_appointments_telegram_id ON appointments(telegram_id);
CREATE INDEX IF NOT EXISTS idx_appointments_date_time ON appointments(appointment_date, appointment_time);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status);
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);

-- Создание уникального индекса для предотвращения дублирования записей на одно время
CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_slot 
ON appointments(appointment_date, appointment_time) 
WHERE status IN ('pending', 'confirmed');

-- Функция для автоматического обновления created_at (если потребуется updated_at)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.created_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Вставка тестовых данных (опционально)
-- INSERT INTO users (telegram_id, username, first_name, last_name, phone) 
-- VALUES (123456789, 'test_user', 'Test', 'User', '+1234567890');

-- INSERT INTO appointments (user_id, telegram_id, service_type, appointment_date, appointment_time, status) 
-- VALUES (1, 123456789, 'manicure', '2024-12-15', '14:00:00', 'pending');

-- Создание дополнительных ограничений
ALTER TABLE appointments 
ADD CONSTRAINT check_service_type 
CHECK (service_type IN ('manicure', 'pedicure', 'both'));

-- Комментарии к таблицам
COMMENT ON TABLE appointments IS 'Таблица записей на услуги';
COMMENT ON TABLE users IS 'Таблица пользователей Telegram бота';

COMMENT ON COLUMN appointments.id IS 'Уникальный идентификатор записи';
COMMENT ON COLUMN appointments.user_id IS 'Внешний ключ на пользователя';
COMMENT ON COLUMN appointments.telegram_id IS 'ID пользователя в Telegram';
COMMENT ON COLUMN appointments.service_type IS 'Тип услуги: manicure, pedicure, both';
COMMENT ON COLUMN appointments.appointment_date IS 'Дата записи';
COMMENT ON COLUMN appointments.appointment_time IS 'Время записи';
COMMENT ON COLUMN appointments.status IS 'Статус записи';
COMMENT ON COLUMN appointments.created_at IS 'Время создания записи';

COMMENT ON COLUMN users.id IS 'Уникальный идентификатор пользователя';
COMMENT ON COLUMN users.telegram_id IS 'ID пользователя в Telegram';
COMMENT ON COLUMN users.username IS 'Имя пользователя в Telegram';
COMMENT ON COLUMN users.first_name IS 'Имя пользователя';
COMMENT ON COLUMN users.last_name IS 'Фамилия пользователя';
COMMENT ON COLUMN users.phone IS 'Номер телефона';
COMMENT ON COLUMN users.created_at IS 'Время регистрации пользователя';
