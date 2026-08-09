"""Entry point for running the package: python -m keenetic."""

import sys

from keenetic.cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Error: {e}")
        sys.exit(1)
