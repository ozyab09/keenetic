#!/usr/bin/env bash
#
# keenetic.sh — запуск утилиты для работы с Keenetic через REST API
#
# Использование:
#   ./keenetic.sh                # обычный запуск
#   ./keenetic.sh --debug        # режим отладки
#   KEENETIC_ROUTER_IP="10.0.0.1" KEENETIC_ROUTER_PASSWORD="пароль" ./keenetic.sh
#
# Скрипт можно запускать из любой директории.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Проверка наличия Python 3
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[!] Python 3 не найден. Установите Python 3." >&2
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/keenetic/__main__.py" ]; then
    echo "[!] Не найден пакет keenetic: $SCRIPT_DIR/keenetic" >&2
    exit 1
fi

# Добавляем корень репозитория в PYTHONPATH, чтобы пакет keenetic был виден
# (нужно для python -m keenetic / from keenetic.cli import main)
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

exec "$PYTHON" -m keenetic "$@"
