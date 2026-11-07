"""Standalone mapping between PDFium's rendered CropBox and pdfplumber's MediaBox.

The Worksheet R1 extractor keeps its original top-left MediaBox coordinates.
This adapter makes locally rendered OCR observations use that SAME coordinate
frame even when a source PDF has CropBox offsets and /Rotate metadata.

This is geometry conversion, not proof of reading accuracy. No raster OCR is
performed here. Source-to-render transforms must be tested per PDF renderer.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class PageFrame:
    media_width: float
    media_height: float
    crop_x0: float
    crop_top: float
    crop_width: float
    crop_height: float
    rotation: int

    def __post_init__(self) -> None:
        vals = (self.media_width, self.media_height, self.crop_x0,
                self.crop_top, self.crop_width, self.crop_height)
        if not all(isfinite(v) for v in vals):
            raise ValueError("Non-finite PDF page dimensions")
        if min(self.media_width, self.media_height, self.crop_width, self.crop_height) <= 0:
            raise ValueError("Invalid PDF page dimensions")
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError("Unsupported PDF rotation")
        if (self.crop_x0 < -.001 or self.crop_top < -.001 or
            self.crop_x0 + self.crop_width > self.media_width + .001 or
            self.crop_top + self.crop_height > self.media_height + .001):
            raise ValueError("CropBox extends outside supported MediaBox")

    def render_to_media(self, x: float, y: float) -> tuple[float, float]:
        """Map relative rendered-CropBox coordinates to MediaBox-normalised."""
        if not (isfinite(x) and isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("Invalid rendered page coordinate")
        return ((self.crop_x0 + x * self.crop_width) / self.media_width,
                (self.crop_top + y * self.crop_height) / self.media_height)

    def media_to_render(self, x: float, y: float) -> tuple[float, float]:
        if not (isfinite(x) and isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("Invalid source page coordinate")
        a = (x * self.media_width - self.crop_x0) / self.crop_width
        b = (y * self.media_height - self.crop_top) / self.crop_height
        if not (-1e-9 <= a <= 1+1e-9 and -1e-9 <= b <= 1+1e-9):
            raise ValueError("Source point is outside rendered CropBox")
        return max(0., min(1., a)), max(0., min(1., b))

    def media_bbox_to_render_clipped(self, b: dict) -> dict | None:
        """Map a MediaBox-normalized source rectangle into the visible CropBox.

        A source box entirely outside the visible CropBox has no overlay. Partial
        regions are clipped, not extended or falsely placed on the drawing.
        """
        if not isinstance(b,dict) or set(b)!={"x0","y0","x1","y1"}:
            raise ValueError("Invalid MediaBox rectangle")
        a=[b["x0"],b["y0"],b["x1"],b["y1"]]
        if not all(isfinite(x) and 0<=x<=1 for x in a) or a[0]>=a[2] or a[1]>=a[3]:
            raise ValueError("Invalid normalized MediaBox box")
        x0=(a[0]*self.media_width-self.crop_x0)/self.crop_width
        x1=(a[2]*self.media_width-self.crop_x0)/self.crop_width
        y0=(a[1]*self.media_height-self.crop_top)/self.crop_height
        y1=(a[3]*self.media_height-self.crop_top)/self.crop_height
        if x1<=0 or x0>=1 or y1<=0 or y0>=1:
            return None
        return {"x0":round(max(0,x0),7),"y0":round(max(0,y0),7),
                "x1":round(min(1,x1),7),"y1":round(min(1,y1),7)}

    def bbox_to_media(self, b: dict) -> dict:
        if not isinstance(b, dict) or set(b) != {"x0","y0","x1","y1"}:
            raise ValueError("Invalid rendered bounding box")
        x0, y0 = self.render_to_media(b["x0"], b["y0"])
        x1, y1 = self.render_to_media(b["x1"], b["y1"])
        if not (x0 < x1 and y0 < y1):
            raise ValueError("Degenerate rendered bounding box")
        return {"x0": round(x0,7), "y0": round(y0,7),
                "x1": round(x1,7), "y1": round(y1,7)}

    def as_metadata(self) -> dict:
        return {"media_size": [round(self.media_width,5),round(self.media_height,5)],
                "render_size": [round(self.crop_width,5),round(self.crop_height,5)],
                "crop_origin": [round(self.crop_x0,5),round(self.crop_top,5)],
                "rotation": self.rotation, "coordinate_frame": "PDFPLUMBER_MEDIA_NORMALIZED_V1"}


def frame_from_pdfplumber(page) -> PageFrame:
    """Interpret pdfplumber's rotation-aware top-left CropBox coordinates.

    PDFium renders the CropBox; pdfplumber exposes page lines/words in the
    larger MediaBox view. pdfplumber.cropbox is rotation-aware and records the
    visible rectangle in top-left page coordinates.
    """
    crop = getattr(page, "cropbox", None)
    if not crop:
        crop = (0., 0., page.width, page.height)
    x0, top, x1, bottom = [float(v) for v in crop]
    return PageFrame(float(page.width), float(page.height), x0, top,
                     x1-x0, bottom-top, int(getattr(page,"rotation",0) or 0) % 360)
