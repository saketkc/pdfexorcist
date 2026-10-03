"""Drop "na" before the vote."""


def drop_na(value: str) -> str | None:
    """Return a vote value or None to discard the reading."""
    return None if value == "na" else value
