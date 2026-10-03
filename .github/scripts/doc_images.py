"""Render the docs' example images."""

import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tomllib
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "assets" / "examples"
OCR = {"lake-photo", "nta-toppers"}
IMAGES = {
    "mccd-table4": ("mccd/table4.toml", None),
    "mccd-table2": ("mccd/table2.toml", None),
    "mccd-table5": ("mccd/table5.toml", None),
    "mccd-table9": ("mccd/table9.toml", None),
    "srs": ("srs_life_table/recipe.toml", None),
    "iips": ("census_iips_district/recipe.toml", None),
    "mohfw": ("census_mohfw_state/recipe.toml", None),
    "crs": ("crs_state_tables/recipe.toml", None),
    "nfhs6-state": ("nfhs6/state.toml", None),
    "nfhs6-district": ("nfhs6/district.toml", None),
    "nfhs5-state": ("nfhs5/state.toml", None),
    "nfhs5-district": ("nfhs5/district.toml", None),
    "pravah": ("pravah_dams/recipe.toml", 4),  # the Mumbai dams
    "nta-notice": ("nta_notice/recipe.toml", None),
    "nta-toppers": ("nta_toppers/recipe.toml", None),
    "cii-rows": ("settings/cii_rows.toml", None),
    "lake-photo": ("lake_photo/recipe.toml", None),
}


def render(name: str, recipe: str, page: int | None) -> Path:
    path = ROOT / "examples" / recipe
    sample = (path.parent / tomllib.loads(path.read_text())["sample"]).resolve()
    out = OUT / f"{name}.png"
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "show.png"
        cmd = [sys.executable, "-m", "pdfexorcist", "show", str(sample), "--recipe", str(path)]
        cmd += ["-o", str(png), "-q", "--force"] + (["--page", str(page)] if page else [])
        subprocess.run(cmd, check=True)
        img = Image.open(png).convert("RGB")
        img.thumbnail((2000, 4000))  # wider adds bytes, not legible detail
        img.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(out, optimize=True)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    names = sys.argv[1:] or list(IMAGES)

    def one(name: str) -> None:
        out = render(name, *IMAGES[name])
        print(f"{out.relative_to(ROOT)}  {out.stat().st_size // 1024} KB", flush=True)

    with ThreadPoolExecutor() as pool:  # text-layer recipes in parallel subprocesses
        list(pool.map(one, [n for n in names if n not in OCR]))
    for name in names:  # OCR ones in turn: they share the GPU
        if name in OCR:
            one(name)


if __name__ == "__main__":
    main()
