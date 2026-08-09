"""Конфигурация и константы для работы с Keenetic API."""

import os

# IP роутера можно переопределить переменной окружения (по умолчанию —
# стандартный адрес Keenetic в локальной сети)
ROUTER_IP = os.environ.get("KEENETIC_ROUTER_IP", "192.168.1.1")
BASE_URL = f"http://{ROUTER_IP}"
LOGIN = "admin"

# Флаг отладки (устанавливается через --debug)
DEBUG = False

# Настройки сбора
COLLECT_COUNT = 5          # количество запросов
COLLECT_INTERVAL = 5       # 5 секунд между запросами


def fmt_interval(seconds: int) -> str:
    """Форматирует интервал: 5 → '5 сек', 300 → '5 мин', 3600 → '1 ч'."""
    if seconds < 60:
        return f"{seconds} сек"
    if seconds < 3600:
        return f"{seconds // 60} мин"
    return f"{seconds / 3600:.1f} ч"
