"""Точка входа для запуска пакета: python -m keenetic."""

import sys

from keenetic.cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Отменено пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Ошибка: {e}")
        sys.exit(1)
