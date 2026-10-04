"""Write and summarise extract results."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from rich.table import Table

from ._ui import EXIT_FAILED, err, esc, path_text, plural
from .recipe import RecipeError

META = ["value", "status", "failed", "n_agree", "votes", "sources", "dissent"]


@dataclass
class Grid:
    """Table layout and agreed cells outside it."""

    table: pd.DataFrame | None
    unplaced: pd.Series  # bool per cell: agreed, but its row/column name is missing
    clashes: pd.Series  # bool per cell: agreed, but read differently elsewhere
    notes: list[str] = field(default_factory=list)


def cell_columns(res: pd.DataFrame, key: Sequence[str]) -> list[str]:
    keys = [k for k in key if k in res.columns]
    extra = [c for c in res.columns if c not in keys and c not in META]
    return keys + extra + [c for c in META if c in res.columns]


def to_table(
    res: pd.DataFrame,
    key: Sequence[str],
    columns: str,
    rows: Sequence[str] | None = None,
) -> Grid:
    """Grid with one row per row key and one column per column key."""
    none = pd.Series(False, index=res.index)
    if columns not in res.columns:
        return Grid(None, none, none)
    index = list(rows) if rows else [k for k in key if k != columns and k in res.columns]
    lost = [c for c in [*index] if c not in res.columns]
    if lost:
        raise RecipeError(
            f"[output] rows names {lost[0]!r}, but the cells only have: "
            f"{', '.join(map(str, res.columns))}",
            hint="Use those column names in [output] rows.",
        )
    if not index:
        return Grid(None, none, none)
    where = [*index, columns]
    verified = res.status == "verified"
    placeable = res[where].notna().all(axis=1)
    unplaced = verified & ~placeable
    ok = res[verified & placeable]
    n_values = ok.groupby(where, sort=False)["value"].nunique()
    clash_keys = list(n_values[n_values > 1].index)
    clashes = pd.Series(
        verified & placeable & pd.MultiIndex.from_frame(res[where]).isin(clash_keys),
        index=res.index,
    )
    good = ok[~clashes[ok.index]].drop_duplicates(where)
    grid = good.set_index(where)["value"].unstack(columns)
    # rows and columns with no agreed value go to the review file only
    order = ok[index].drop_duplicates()
    grid = grid.reindex(
        pd.MultiIndex.from_frame(order) if len(index) > 1 else pd.Index(order[index[0]])
    )
    seen = list(dict.fromkeys(ok[columns]))
    try:
        cols = sorted(seen, key=float)
    except (TypeError, ValueError):
        cols = seen
    grid = grid.reindex(columns=cols)
    grid.columns = [str(c) for c in grid.columns]
    extras = [c for c in res.columns if c not in key and c not in META and c not in where]
    placed = res[placeable]
    keep = [
        c for c in extras if (placed.groupby(index, sort=False)[c].nunique(dropna=True) <= 1).all()
    ]
    table = grid.reset_index()
    if keep:
        front = placed.groupby(index, sort=False)[keep].first().reset_index()
        table = table.merge(front, on=index, how="left")[index + keep + list(grid.columns)]
    if "row" in index and "label" in keep:
        table = table.drop(columns="row")
    notes = []
    if unplaced.any():
        notes.append(
            f"{plural(int(unplaced.sum()), 'agreed cell')} had no {' / '.join(where)} name, so "
            "they are not in the table; they are in the review file."
        )
    if clashes.any():
        notes.append(
            f"{plural(int(clashes.sum()), 'agreed cell')} were read with different values in "
            "different places (e.g. two pages); left blank in the table and listed for review."
        )
    return Grid(table, unplaced, clashes, notes)


def review_frame(res: pd.DataFrame, key: Sequence[str], grid: Grid | None) -> pd.DataFrame:
    """Review cells with the reason before each value."""
    failed = res.get("failed", pd.Series("", index=res.index)).fillna("")
    reason = pd.Series("", index=res.index)
    reason[res.status != "verified"] = "engines disagreed"
    reason[failed != ""] = "fails: " + failed[failed != ""]
    if grid is not None:
        reason[grid.unplaced & (reason == "")] = "not in the table: no row/column name"
        reason[grid.clashes & (reason == "")] = "read differently elsewhere"
    cells = res[cell_columns(res, key)]
    return cells[reason != ""].assign(reason=reason[reason != ""])[["reason", *cells.columns]]


def write(plan: Any, res: pd.DataFrame, key: Sequence[str]) -> dict[str, Any]:
    """Write outputs and return written paths, layout, table, and notes."""
    grid = to_table(res, key, plan.columns, plan.rows) if plan.layout == "table" else None
    if grid is not None and grid.table is None:
        grid = None
    layout = "table" if grid is not None else "cells"
    main: pd.DataFrame = (
        grid.table if grid is not None and grid.table is not None else res[cell_columns(res, key)]
    )
    review = review_frame(res, key, grid) if grid is not None else None
    plan.output.parent.mkdir(parents=True, exist_ok=True)
    written = [plan.output]
    if plan.fmt == "xlsx":
        with pd.ExcelWriter(plan.output) as xl:
            main.to_excel(xl, sheet_name=layout, index=False)
            if review is not None and len(review):
                review.to_excel(xl, sheet_name="review", index=False)
    else:
        _write_one(main, plan.output, plan.fmt)
        if plan.review is not None:
            if review is not None and len(review):
                _write_one(review, plan.review, plan.fmt)
                written.append(plan.review)
            elif plan.review.exists():
                plan.review.unlink()  # stale, from an earlier run; --force was given
    notes = list(grid.notes) if grid is not None else []
    if plan.layout == "table" and grid is None:
        notes.append(
            f"No {plan.columns!r} column to spread into a grid, so the cells layout was written."
        )
    return {
        "written": written,
        "layout": layout,
        "table": main if grid is not None else None,
        "notes": notes,
    }


def _write_one(df: pd.DataFrame, path: Path, fmt: str) -> None:
    if fmt == "csv":
        df.to_csv(path, index=False, encoding="utf-8")
    elif fmt == "json":
        path.write_text(df.to_json(orient="records", force_ascii=False, indent=1), encoding="utf-8")
    elif fmt == "parquet":
        df.astype({c: "string" for c in df.columns if df[c].dtype == object}).to_parquet(
            path, index=False
        )


def summarise(
    plan: Any, res: pd.DataFrame, prog: Any, result: dict[str, Any], notes: list[str]
) -> dict[str, Any]:
    """JSON-ready run summary."""
    is_verified = res.status == "verified"
    verified = int(is_verified.sum())
    failed_mask = res.get("failed", pd.Series("", index=res.index)).fillna("") != ""
    by_check: dict[str, int] = {}
    for f in res.loc[failed_mask, "failed"]:
        for name in str(f).split("; "):
            by_check[name] = by_check.get(name, 0) + 1
    skipped = {
        **{m: f"not installed: {fix}" for m, fix in plan.not_installed.items()},
        **prog.skipped,
    }
    table = result["table"]
    agreed = res.loc[is_verified, "n_agree"].value_counts().sort_index(ascending=False)
    return {
        "input": str(plan.src),
        "outputs": [str(p) for p in result["written"]],
        "review": str(plan.review) if plan.review in result["written"] else None,
        "format": plan.fmt,
        "layout": result["layout"],
        "pages": plan.pages,
        "engines": {"used": prog.counts, "skipped": skipped},
        "min_agree": plan.min_agree,
        "cells": {
            "total": len(res),
            "verified": verified,
            "unresolved": len(res) - verified,
            "failed_checks": int(failed_mask.sum()),
        },
        # verified cells by how many engines read their value
        "agreement": {str(n): int(c) for n, c in agreed.items()},
        "table": None if table is None else {"rows": len(table), "columns": int(table.shape[1])},
        "checks": by_check,
        "checks_run": list(res.attrs.get("checks_run", [])),
        "notes": plan.notes + result["notes"] + notes,
        "exit_code": EXIT_FAILED if verified == 0 or failed_mask.any() else 0,
    }


def render_summary(s: dict[str, Any]) -> None:
    """Render the human summary to stderr."""
    for m, why in s["engines"]["skipped"].items():
        if why.startswith("not installed"):
            err.print(f"  {m:<11} [yellow]skipped[/], {esc(why)}", soft_wrap=True)
    for m, n in s["engines"]["used"].items():
        if not n:
            err.print(f"  [yellow]{m} read no values on these pages.[/]")
    c = s["cells"]
    pct = 100 * c["verified"] / max(c["total"], 1)
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold")
    t.add_column(justify="right")
    t.add_column()
    t.add_row("Agreed", f"{c['verified']:,}", f"[green]{pct:.1f}% of cells[/]")
    t.add_row(
        "Unresolved",
        f"{c['unresolved']:,}",
        "[yellow]engines disagreed: left blank, not guessed[/]" if c["unresolved"] else "",
    )
    if s["checks_run"] and not c["failed_checks"]:
        t.add_row("Checks", plural(len(s["checks_run"]), "rule"), "[green]all passed[/]")
    if s["checks"] or c["failed_checks"]:
        t.add_row(
            "Failed checks",
            f"{c['failed_checks']:,}",
            "[red]agreed values that break a rule[/]",
        )
    err.print()
    err.print(t)
    for name, n in s["checks"].items():
        err.print(f"  [red]x[/] {esc(name)}: {plural(n, 'cell')}")
    for note in s["notes"]:
        err.print(f"[yellow]Note:[/] {esc(note)}")
    outs = [Path(p) for p in s["outputs"]]
    shape = f", {plural(s['table']['rows'], 'row')}" if s["table"] else ""
    err.print(
        f"\nWrote [bold]{esc(path_text(outs[0]))}[/] ({s['layout']} layout{shape}).",
        soft_wrap=True,
    )
    if len(outs) > 1:
        err.print(
            "Cells to review, with the reason and every engine's reading: "
            f"[bold]{esc(path_text(outs[1]))}[/]",
            soft_wrap=True,
        )
    elif (
        s["layout"] == "table" and s["format"] == "xlsx" and (c["unresolved"] or c["failed_checks"])
    ):
        err.print(
            "Cells to review, with the reason and every engine's reading: the [bold]review[/] "
            "sheet."
        )
    if c["verified"] == 0:
        err.print(
            "[red]No value was agreed on.[/] For scans add --ocr; check the pages with "
            "pdfexorcist inspect."
        )
    elif c["failed_checks"]:
        err.print(
            "[red]Some agreed values break a rule[/] (see the failed column), so the exit code is "
            "1."
        )
