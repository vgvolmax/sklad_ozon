"""Small strict parsers for Ozon JSON wire values."""


def sku(value) -> str:
    if isinstance(value, bool):
        raise ValueError("invalid SKU evidence")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError("invalid SKU evidence")
        return str(value)
    if isinstance(value, str):
        value = value.strip()
        if value:
            return value
    raise ValueError("invalid SKU evidence")


def positive_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"invalid {label}")
    return value


def nonnegative_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid {label}")
    return value


def optional_text(value, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"invalid {label}")
    return value.strip() or None
