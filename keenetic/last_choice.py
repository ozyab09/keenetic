"""Хранение последнего выбора пользователя в файле last_choice.json.

Файл лежит в корне репозитория (рядом с README.md, на уровень выше пакета)
и содержит JSON:
    {"host": "<ip>", "mode": "collect|once", "port": <int>, "group": "<имя_группы>"}

Поле "group" — последняя выбранная группа DNS-маршрутов для автоматического
добавления подсетей. Пустая строка означает явный отказ от автоматического
добавления; при режиме "once" ключ не перезаписывается.

Используется, чтобы в интерактивных промптах предлагать по умолчанию
последний выбор пользователя. Файл добавлен в .gitignore (личные данные).
"""

import json
import os

# Ключи файла last_choice.json
KEY_HOST = "host"
KEY_MODE = "mode"
KEY_PORT = "port"
KEY_GROUP = "group"

# Режимы по умолчанию, если файла нет или он повреждён
DEFAULT_MODE = "collect"
DEFAULT_PORT = 443


def _file_path() -> str:
    """Путь к last_choice.json: корень репозитория.

    Пакет лежит в <корень>/keenetic/, поэтому поднимаемся на один уровень
    вверх от каталога этого модуля.
    """
    package_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(package_dir), "last_choice.json")


def load_last_choice(path: str | None = None) -> dict:
    """Читает последний выбор из файла. При ошибке возвращает пустой словарь."""
    file_path = path or _file_path()
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}

    if not isinstance(data, dict):
        return {}
    # Оставляем только строки и числа — валидные значения
    return {k: v for k, v in data.items() if isinstance(v, (str, int))}


def save_last_choice(host_ip: str, mode: str, port: int, group: str | None = None,
                     path: str | None = None) -> None:
    """Сохраняет последний выбор в файл (некритичные ошибки игнорируются).

    group=None в режиме "collect" запоминается как пустая строка
    (явный отказ от автодобавления). В режиме "once" ключ не трогается.
    """
    file_path = path or _file_path()
    data = {KEY_HOST: host_ip, KEY_MODE: mode, KEY_PORT: port}
    if group is not None:
        data[KEY_GROUP] = group
    elif mode == "collect":
        data[KEY_GROUP] = ""  # «не добавлять автоматически»
    else:
        # режим once — группа не выбирается, сохраняем прежнее значение
        prev = load_last_choice(path)
        if KEY_GROUP in prev:
            data[KEY_GROUP] = prev[KEY_GROUP]
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[!] Не удалось сохранить {os.path.basename(file_path)}: {e}")
