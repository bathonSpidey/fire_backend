"""Set (or change) the household PIN used to open the app from other devices.

Run on the laptop:  uv run python scripts/set_pin.py
Changing the PIN signs every phone and computer out.
"""

import getpass
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from services import auth  # noqa: E402


def main() -> int:
    pin = getpass.getpass(f"New PIN (at least {auth.MIN_PIN_LENGTH} characters, digits are fine): ")
    if pin != getpass.getpass("Type it again: "):
        print("The two entries differ. Nothing was changed.")
        return 1
    try:
        auth.set_pin(pin)
    except ValueError as exc:
        print(exc)
        return 1
    print("PIN saved. Everybody has to sign in again with the new PIN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
