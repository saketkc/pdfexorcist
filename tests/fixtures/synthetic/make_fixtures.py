"""Build the synthetic fixtures."""

from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
ROWS = [
    ("Region", "A", "B", "Total"),
    ("North", "65·3", "−4·0", "61·3"),
    ("South", "12·5", "(7·0)", "19·5"),
    ("East", "500·0", "13·4*", "513·4"),
    ("All regions", "577·8", "16·4", "594·2"),
]
X = (60, 220, 300, 380)


def main() -> None:
    with pymupdf.open() as doc:
        page = doc.new_page(width=480, height=260)
        page.insert_font(fontname="arial", fontfile=FONT)
        page.insert_text((60, 50), "Table 1: Values by region", fontname="arial", fontsize=12)
        for i, row in enumerate(ROWS):
            y = 90 + 30 * i
            for x, text in zip(X, row, strict=True):
                if x > X[0]:  # numbers right-aligned on their column
                    x += 50 - pymupdf.get_text_length(text, fontname="helv", fontsize=11)
                page.insert_text((x, y), text, fontname="arial", fontsize=11)
        page.insert_text((60, 245), "* provisional", fontname="arial", fontsize=8)
        doc.subset_fonts()  # only the glyphs used, so the fixture stays small
        doc.save(HERE / "cleaning.pdf", garbage=4, deflate=True, no_new_id=True)
        page.get_pixmap(dpi=200).save(HERE / "cleaning.png")


if __name__ == "__main__":
    main()
