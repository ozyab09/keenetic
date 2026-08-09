# AGENTS.md — инструкции для AI-ассистентов

Этот файл содержит рекомендации для AI-ассистентов (Claude, Codebuff, Copilot и др.)  
при работе с проектом **keenetic**.

---

## Общие правила

### Язык
- Код, комментарии и docstrings — **русский** (проект для русскоязычного пользователя).
- AGENTS.md — **русский**.
- Внешние интерфейсы (GitHub, CI) — можно на английском.

### Стиль кода
- Python 3.10+ с type hints (`str | None`, `list[Host]`).
- Dataclasses для моделей данных.
- Только **стандартная библиотека** — никаких внешних зависимостей (`pip install`).
- `urllib` для HTTP, `socket` для WHOIS, `hashlib` для MD5/SHA256.
- Максимальная длина строки — ~120 символов.

### Импорты
- Внутренние модули импортируем через `import keenetic.X as X` или `from keenetic.X import Y`.
- Конфигурация: `import keenetic.config as config`, обращение через `config.XXX`.
- **Никогда** не использовать `from keenetic.config import DEBUG` — это создаёт локальную копию, и флаг `--debug` не будет работать. Всегда писать `config.DEBUG`.

### Структура модулей

```
keenetic/                  ← корень репозитория
├── keenetic/              ← пакет
│   ├── __init__.py        → экспортирует main()
│   ├── __main__.py        → python -m keenetic
│   ├── cli.py             → аргументы, интерактивное меню, main()
│   ├── config.py          → константы (ROUTER_IP, LOGIN, DEBUG, COLLECT_COUNT...)
│   ├── models.py          → dataclasses + вспомогательные функции
│   ├── session.py         → KeeneticSession (HTTP-клиент)
│   ├── auth.py            → challenge-response авторизация
│   ├── hosts.py           → получение/вывод/выбор хостов
│   ├── connections.py     → получение/вывод активных соединений
│   ├── collector.py       → режим сбора (5 запросов + агрегация)
│   ├── whois.py           → WHOIS-запросы
│   ├── static_routes.py   → сравнение подсетей + выбор группы
│   └── last_choice.py     → последний выбор пользователя (~/.keenetic/)
├── tests/                 → юнит-тесты (unittest, stdlib)
├── pyproject.toml         → метаданные пакета
├── keenetic.sh            → bash-лаунчер
├── AGENTS.md              → этот файл
└── README.md              → документация
```

### Отладка
- Глобальный флаг `config.DEBUG` включает вывод сырых JSON.
- Флаг устанавливается через `--debug` в `cli.py`: `config.DEBUG = True`.

## Основные сценарии

### Добавление нового функционала
1. Определить, в какой модуль логически входит функционал
2. Создать новый модуль, если нужно (например, `dns.py` для DNS-lookup)
3. Подключить в `cli.py`
4. Проверить: `python -c "from keenetic.cli import main"`

### Изменение конфигурации
- Все настраиваемые параметры — в `keenetic/config.py`
- Если параметр изменяется во время работы (например, `DEBUG`) — **только** через `import keenetic.config as config; config.XXX = val`
- Если параметр статический — можно импортировать `from keenetic.config import XXX`

### Работа с API Keenetic
- Эндпоинты: `/rci/show/ip/hotspot` (хосты), `/rci/show/ip/connections` и альтернативы (соединения)
- Ответы могут быть в разных форматах: `{"address": "..."}` или просто строка
- Для безопасного извлечения значений используется `models.str_val()`
- NAT-записи содержат поля `x_src_ip` / `x_dst_ip` — их нужно проверять при фильтрации
- Авторизация: challenge-response (MD5 + SHA256), описана в `keenetic/auth.py`

### Тестирование
- Юнит-тесты: `python -m unittest discover -s tests -v` (из корня репозитория)
- `./keenetic.sh` или `python -m keenetic` — полный цикл запуска (из корня репозитория)
- Проверка импортов: `python -c "from keenetic.cli import main"`
- Проверка синтаксиса: `python -c "import ast; ast.parse(open('path/to/file.py').read())"`

## Типовые задачи

### Добавить новый эндпоинт соединений
Дополнить список `CONNECTION_ENDPOINTS` в `keenetic/connections.py`.

### Добавить новое поле в вывод
- Если поле из API: добавить ключ в `_pick()` в `models.parse_connection()`
- Если новое поле в моделях: дополнить соответствующий dataclass
- Обновить вывод в `print_connections()` (connections.py) или `print_collected()` (collector.py)

### Добавить новый источник данных (не WHOIS)
- Создать модуль `keenetic/new_source.py` с функцией `lookup(ip) -> SomeInfo`
- Вызвать из `print_collected()` или из нового режима в `cli.py`
- Формат: dataclass с полями + функция `lookup(ip) -> Dataclass`, ошибка в поле `error`
