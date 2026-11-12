"""Small, explicit budget for vertical text: a few regions, each read at 90 and 270 degrees, with completion and omissions reported.

Vertical text is NOT handled by rotating every page tile (that doubles the EasyOCR page cost). Regions are chosen by geometry and
length from existing boxes (never by consulting any reference), capped at MAX_VERTICAL_REGIONS, and anything left out is listed.
"""
MAX_VERTICAL_REGIONS = 6
TURNS = (90, 270)


def select(candidates, max_regions=MAX_VERTICAL_REGIONS):
    """candidates: [{id, bbox, vertical, source_text?}]. Returns (selected, omitted). Order: longer strings first, then reading position."""
    if not 1 <= max_regions <= MAX_VERTICAL_REGIONS:
        raise ValueError(f"vertical budget must be 1..{MAX_VERTICAL_REGIONS}")
    vertical = [c for c in candidates if c.get("vertical")]
    vertical.sort(key=lambda c: (-len((c.get("source_text") or "").replace(" ", "")), c["bbox"]["y0"], c["bbox"]["x0"], str(c.get("id"))))
    return vertical[:max_regions], vertical[max_regions:]


def report(selected, omitted, completed_ids):
    """Explicit coverage: requested/scheduled/completed/omitted, each region tested at both turns."""
    done = set(completed_ids)
    return dict(requested=len(selected) + len(omitted), scheduled=len(selected), completed=sum(c["id"] in done for c in selected),
                omitted_by_budget=[c["id"] for c in omitted], not_completed=[c["id"] for c in selected if c["id"] not in done],
                turns_each=list(TURNS), budget=MAX_VERTICAL_REGIONS)
