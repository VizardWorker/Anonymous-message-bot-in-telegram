import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logger():
    # Создаём директорию logs, если её нет
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Путь к файлу логов
    log_file_path = os.path.join('logs', 'log.txt')

    # Настраиваем обработчик логов с ротацией
    rotating_handler = RotatingFileHandler(
        log_file_path, 
        maxBytes=2 * 1024 * 1024,  # 2 MB
        backupCount=5,  # Максимум 5 файлов с логами
        encoding='utf-8'
    )

    # Формат для логов
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    rotating_handler.setFormatter(formatter)

    # Обработчик для вывода логов в консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Очищаем существующие обработчики
    root_logger.handlers.clear()
    
    # Добавляем новые обработчики
    root_logger.addHandler(rotating_handler)
    root_logger.addHandler(console_handler)

    # Отключаем логгирование aiogram.event на уровне INFO
    logging.getLogger('aiogram.event').setLevel(logging.WARNING)

    return root_logger