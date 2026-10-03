"""Add a numeric column after the vote."""

import pandas as pd


def add_number(cells: pd.DataFrame, pdf: object) -> pd.DataFrame:
    """Add numeric values without changing their printed forms."""
    text = cells["value"].astype(str).str.strip("()")
    return cells.assign(number=pd.to_numeric(text, errors="coerce"))
