GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def message(msg: str, end: str | None = "\n") -> None:
    print(f"{msg}{RESET}", end=end)


def ok(msg: str, end: str | None = "\n") -> None:
    print(f"{GREEN}{msg}{RESET}", end=end)


def fail(msg: str, end: str | None = "\n") -> None:
    print(f"{RED}{msg}{RESET}", end=end)


def info(msg: str, end: str | None = "\n") -> None:
    print(f"{CYAN}{msg}{RESET}", end=end)


def header(title: str) -> None:
    print(f"\n{BOLD}{YELLOW}{'═' * 50}")
    print(f"  {title}")
    print(f"{'═' * 50}{RESET}")


def subheader(title: str, width: int = 56) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}{RESET}")


def separator(char: str = "·", width: int = 56, end: str | None = "\n") -> None:
    print(f"  {DIM}{char * width}{RESET}", end=end)


def prompt(label: str, choices: list[str] | None = None) -> str:
    choices_str = f" [{'/'.join(choices)}]" if choices is not None else ""
    while True:
        choice = input(f"{label}{choices_str}{RESET}").strip().lower()
        if choices is None:
            return choice
        if choice in choices:
            return choice
        else:
            fail(f"Invalid input. Please enter one of: {choices_str}.")


def prompt_yes_no(label: str, default: bool = True) -> bool:
    while True:
        choices_str = "[Y/n]" if default else "[y/N]"
        choice = input(f"{label} {choices_str}: {RESET}").strip().lower()
        if not choice:
            return default
        if choice in ("y", "yes"):
            return True
        elif choice in ("n", "no"):
            return False
        else:
            fail("Invalid input. Please enter 'Y' or 'N'.")
