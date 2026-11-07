"""Generate an original, synthetic dense-stroke regression P&ID-like PDF.

No industrial-standard graphics or client drawing data are included.
The fixture is a 5,500-stroke geometry stress drawing, NOT a representative P&ID.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from io import BytesIO
from reportlab.pdfgen import canvas


def make_fixture(cols: int = 100, rows: int = 55) -> bytes:
    output = BytesIO()
    c = canvas.Canvas(output, pagesize=(max(700, cols*6+20),max(420, rows*6+20)),pageCompression=1)
    for row in range(rows):
        for col in range(cols):
            x,y = 12+col*6,12+row*6
            c.line(x,y,x+2.1,y)
    c.save()
    return output.getvalue()


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.output.exists():parser.error('Refusing to overwrite an existing fixture')
    args.output.write_bytes(make_fixture())
    print(f'Wrote {args.output} with 5500 disjoint 2.1pt source line strokes')


if __name__=='__main__':main()
