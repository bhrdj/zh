#!/usr/bin/env python3
"""Generate double-sided A4 flashcard PDFs from a TSV file.

Usage: flashcards.py INPUT.tsv [OUTPUT.pdf]

The first column is displayed large on the front of each card with a
four-box grid background (田字格).  The remaining columns are printed
in 11pt font across the top of the matching back-of-card box, leaving
space below for handwritten notes.

Cards are laid out 6 per page (2 columns × 3 rows).  Back pages are
horizontally mirrored so cards align when printed double-sided.
"""

import csv
import math
import sys
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
PAGE_W, PAGE_H = A4  # 210 × 297 mm
COLS, ROWS = 2, 3
MARGIN_X = 15 * mm
MARGIN_Y = 15 * mm
CARD_W = (PAGE_W - 2 * MARGIN_X) / COLS
CARD_H = (PAGE_H - 2 * MARGIN_Y) / ROWS
GRID_COLOR = (0.82, 0.82, 0.82)
BORDER_COLOR = (0.4, 0.4, 0.4)

# ---------------------------------------------------------------------------
# Font setup – try to find a CJK font on the system
# ---------------------------------------------------------------------------
CJK_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]

LATIN_FONT_CANDIDATES = [
    "/usr/share/fonts/chromeos/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

CJK_FONT = "Helvetica"
LATIN_FONT = "Helvetica"

for p in CJK_FONT_CANDIDATES:
    if Path(p).exists():
        pdfmetrics.registerFont(TTFont("CJK", p))
        CJK_FONT = "CJK"
        break

for p in LATIN_FONT_CANDIDATES:
    if Path(p).exists():
        pdfmetrics.registerFont(TTFont("Latin", p))
        LATIN_FONT = "Latin"
        break


def load_tsv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def card_rect(col: int, row: int) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) for a card position (y from bottom)."""
    x = MARGIN_X + col * CARD_W
    y = PAGE_H - MARGIN_Y - (row + 1) * CARD_H
    return x, y, CARD_W, CARD_H


def draw_border(c: canvas.Canvas, x: float, y: float, w: float, h: float):
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.6)
    c.rect(x, y, w, h, stroke=1, fill=0)


def draw_grid(c: canvas.Canvas, x: float, y: float, w: float, h: float):
    """Draw a 田字格 (four-box grid) inside the card area."""
    # Use a square region centered in the card
    side = min(w, h) * 0.72
    cx = x + w / 2
    cy = y + h / 2
    gx = cx - side / 2
    gy = cy - side / 2

    # Outer square
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.8)
    c.rect(gx, gy, side, side, stroke=1, fill=0)

    # Dashed cross
    c.setStrokeColor(GRID_COLOR)
    c.setLineWidth(0.5)
    c.setDash(3, 3)
    # Vertical
    c.line(gx + side / 2, gy, gx + side / 2, gy + side)
    # Horizontal
    c.line(gx, gy + side / 2, gx + side, gy + side / 2)
    c.setDash()


STROKE_SVG_DIR = Path(__file__).resolve().parent / "radicals" / "stroke_svgs"


def draw_front(c: canvas.Canvas, x: float, y: float, w: float, h: float,
               character: str):
    draw_border(c, x, y, w, h)

    # Try to use a stroke-order SVG if available
    codepoint = ord(character)
    svg_path = STROKE_SVG_DIR / f"{codepoint}.svg"
    if svg_path.exists():
        drawing = svg2rlg(str(svg_path))
        # Scale SVG to fit card area with some padding
        side = min(w, h) * 0.85
        scale = side / max(drawing.width, drawing.height)
        drawing.width = drawing.width * scale
        drawing.height = drawing.height * scale
        drawing.scale(scale, scale)
        dx = x + (w - drawing.width) / 2
        dy = y + (h - drawing.height) / 2
        renderPDF.draw(drawing, c, dx, dy)
    else:
        # Fallback: draw character with font
        draw_grid(c, x, y, w, h)
        font_size = min(w, h) * 0.52
        c.setFont(CJK_FONT, font_size)
        c.setFillColorRGB(0, 0, 0)
        tw = c.stringWidth(character, CJK_FONT, font_size)
        tx = x + (w - tw) / 2
        ty = y + (h - font_size) / 2 + font_size * 0.1
        c.drawString(tx, ty, character)


def draw_back(c: canvas.Canvas, x: float, y: float, w: float, h: float,
              details: str):
    draw_border(c, x, y, w, h)

    # Details text across the top
    pad = 4 * mm
    c.setFont(LATIN_FONT, 11)
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.drawString(x + pad, y + h - pad - 11, details)


def generate_pdf(records: list[dict], output: str):
    c = canvas.Canvas(output, pagesize=A4)
    cards_per_page = COLS * ROWS
    total_pages = math.ceil(len(records) / cards_per_page)
    headers = list(records[0].keys())
    first_col = headers[0]
    detail_cols = headers[1:]

    for page_idx in range(total_pages):
        batch = records[page_idx * cards_per_page:(page_idx + 1) * cards_per_page]

        # --- Front page ---
        for i, rec in enumerate(batch):
            col = i % COLS
            row = i // COLS
            x, y, w, h = card_rect(col, row)
            draw_front(c, x, y, w, h, rec[first_col])
        c.showPage()

        # --- Back page (mirrored horizontally for double-sided printing) ---
        for i, rec in enumerate(batch):
            col = i % COLS
            row = i // COLS
            # Mirror: swap column 0 ↔ column 1
            mirrored_col = (COLS - 1) - col
            x, y, w, h = card_rect(mirrored_col, row)
            details = "  ·  ".join(rec[k] for k in detail_cols if rec.get(k))
            draw_back(c, x, y, w, h, details)
        c.showPage()

    c.save()
    print(f"Written {output}  ({len(records)} cards, {total_pages * 2} pages)")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} INPUT.tsv [OUTPUT.pdf]")
        sys.exit(1)

    tsv_path = sys.argv[1]
    if len(sys.argv) >= 3:
        pdf_path = sys.argv[2]
    else:
        pdf_path = str(Path(tsv_path).with_suffix(".pdf"))

    records = load_tsv(tsv_path)
    generate_pdf(records, pdf_path)


if __name__ == "__main__":
    main()
