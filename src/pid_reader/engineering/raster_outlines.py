"""Conservative scan-only outline glyph proposals (no engineering identity claim).

An outlined bow-tie has two *separate, full end bases* plus four diagonals
meeting at a central point. An X crossing alone does not qualify. A rectangle
with an X is explicitly excluded by its continuous top/bottom outline.

The algorithm is deliberately restricted to near-axis-aligned outlines. The
absence of a candidate does NOT mean that no valve exists on a page.
"""
from __future__ import annotations

from math import hypot

MAX_BASES_PER_ORIENTATION = 260
MAX_OUTLINED_GLYPHS = 750


def _line_fraction(ink, dilated, cv2, np, a, b) -> float:
    """Fraction of a sampled expected segment supported within 1-2 pixels."""
    count = max(12, int(hypot(b[0]-a[0], b[1]-a[1]) * 1.5))
    xs = np.rint(np.linspace(a[0], b[0], count)).astype(np.intp)
    ys = np.rint(np.linspace(a[1], b[1], count)).astype(np.intp)
    xs = np.clip(xs, 0, ink.shape[1]-1)
    ys = np.clip(ys, 0, ink.shape[0]-1)
    return float(np.count_nonzero(dilated[ys, xs])) / count


def _find_bases(ink, cv2, np):
    # Isolate vertical strokes; pixels with thin CAD font stems shorter than
    # 17 px generally vanish. Oversized bases are not treated as glyphs.
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, 17)))
    lines = cv2.HoughLinesP(vertical, 1, np.pi/180, threshold=17,
                            minLineLength=17, maxLineGap=3)
    if lines is None:
        return []
    raw = []
    for x0, y0, x1, y1 in np.asarray(lines).reshape(-1, 4).tolist():  # OpenCV 4 (N,1,4) and 5 (N,4)
        if abs(x0-x1) > 3:
            continue
        upper, lower = min(y0,y1), max(y0,y1)
        if not 17 <= lower-upper <= 130:
            continue
        raw.append((int(round((x0+x1)/2)), upper, lower))
    # Keep the longest observation of each physical base. Clipped Hough
    # fragments within the same stroke should not multiply glyph proposals.
    kept = []
    for item in sorted(raw, key=lambda t: (-(t[2]-t[1]), t)):
        x,a,b = item
        if any(abs(x-u) <= 3 and max(0,min(b,d)-max(a,c)) >= .65 * min(b-a,d-c)
               for u,c,d in kept):
            continue
        kept.append(item)
        if len(kept) > MAX_BASES_PER_ORIENTATION:
            return None  # skipped, not a complete negative result
    return sorted(kept)


def _has_central_ring(ink, dilated, np, centre, span):
    """Look for a small, outlined circle; it never establishes a valve type."""
    cx,cy=(int(round(centre[0])),int(round(centre[1])))
    max_r=min(18, int(span * .25))
    for radius in range(5,max_r+1):
        angles=np.arange(0,2*np.pi,2*np.pi/36)
        xs=np.rint(cx+radius*np.cos(angles)).astype(np.intp)
        ys=np.rint(cy+radius*np.sin(angles)).astype(np.intp)
        if np.min(xs)<0 or np.max(xs)>=ink.shape[1] or np.min(ys)<0 or np.max(ys)>=ink.shape[0]:
            continue
        coverage=float(np.count_nonzero(dilated[ys,xs]))/len(xs)
        if coverage < .82:
            continue
        # An actual ring must surround predominantly light interior, not a
        # solid centre, and there must be visible ink around > 80% of circle.
        ix=np.rint(cx+(radius-3)*np.cos(angles)).astype(np.intp)
        iy=np.rint(cy+(radius-3)*np.sin(angles)).astype(np.intp)
        interior=float(np.count_nonzero(ink[iy,ix]))/len(xs)
        if interior < .40:
            return True
    return False


def _one_orientation(ink, cv2, np, *, cancel=None):
    bases=_find_bases(ink,cv2,np)
    if bases is None:
        return [], True
    if len(bases)<2:
        return [], False
    height,width=ink.shape
    dilated=cv2.dilate(ink,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)))
    proposals=[]
    for i, left in enumerate(bases):
        if cancel and i%20==0:
            cancel.check()
        xl,yt, yb=left
        for right in bases[i+1:]:
            xr,rt, rb=right
            if xr<=xl+12:
                continue
            span=(yb-yt + rb-rt)/2
            gap=xr-xl
            if gap<.70*span or gap>3.25*span:
                continue
            if abs(yt-rt)>max(4,.12*span) or abs(yb-rb)>max(4,.12*span):
                continue
            if xl<8 or xr>width-8 or min(yt,rt)<8 or max(yb,rb)>height-8:
                continue
            top=(yt+rt)/2; bottom=(yb+rb)/2
            cx=(xl+xr)/2; cy=(top+bottom)/2
            # A crossed rectangle is not a valve. It has a continuous roof
            # or floor between its bases, unlike opposing triangles.
            if (_line_fraction(ink,dilated,cv2,np,(xl+5,top),(xr-5,top))>.65
                or _line_fraction(ink,dilated,cv2,np,(xl+5,bottom),(xr-5,bottom))>.65):
                continue
            # Reject filled triangles. Open and filled glyphs are different
            # kinds of evidence and must not count twice.
            roi=ink[max(0,int(top+4)):min(height,int(bottom-3)),int(xl+5):int(xr-4)]
            if roi.size==0 or cv2.countNonZero(roi)/roi.size>.32:
                continue
            p1=(xl,yt);p2=(xl,yb);p3=(xr,rt);p4=(xr,rb);tip=(cx,cy)
            coverage=[_line_fraction(ink,dilated,cv2,np,a,tip) for a in (p1,p2,p3,p4)]
            if min(coverage)<.84:
                continue
            # Four diagonal strokes plus both end bases, not just an X.
            style='CENTRAL_RING_OBSERVED' if _has_central_ring(ink,dilated,np,tip,span) else 'PLAIN_OUTLINE'
            proposals.append({'bbox_px':(xl,min(yt,rt),xr,max(yb,rb)),
                              'centre_px':(int(round(cx)),int(round(cy))),
                              'style':style,'support':round(min(coverage),4),
                              'evidence':'FOUR_DIAGONALS_TWO_END_BASES_NO_TOP_BOTTOM_EDGE'})
    # Merge duplicate Hough base observations for the same glyph. Retain
    # strongest support and then a deterministic canonical bounding box.
    proposals.sort(key=lambda p:(-p['support'], p['bbox_px']))
    unique=[]
    for cand in proposals:
        cx,cy=cand['centre_px']
        if any(abs(cx-u['centre_px'][0])<=6 and abs(cy-u['centre_px'][1])<=6 for u in unique):
            continue
        unique.append(cand)
    return sorted(unique,key=lambda p:p['bbox_px']),False


def find_outline_valves(ink, cv2, np, *, cancel=None):
    """Return (glyph candidates, warning codes) in page pixel coordinates.

    This intentionally excludes rotated diagonal-axis bowties and nonstandard
    outlines. These remain unresolved, not negative findings.
    """
    found=[]; warnings=[]
    for orientation, img in [('HORIZONTAL_AXIS',ink),('VERTICAL_AXIS',np.ascontiguousarray(ink.T))]:
        items,skipped=_one_orientation(img,cv2,np,cancel=cancel)
        if skipped:
            warnings.append(f'OUTLINE_DETECTION_SKIPPED_BASE_BUDGET_{orientation}')
        for item in items:
            if orientation=='VERTICAL_AXIS':
                x0,y0,x1,y1=item['bbox_px']
                item['bbox_px']=(y0,x0,y1,x1)
                cx,cy=item['centre_px']
                item['centre_px']=(cy,cx)
            item['orientation']=orientation
            found.append(item)
    if len(found)>MAX_OUTLINED_GLYPHS:
        warnings.append('OUTLINE_DETECTION_SKIPPED_OUTPUT_BUDGET')
        return [],warnings  # explicit skipped stage, never silent partial selection
    return sorted(found,key=lambda p:(p['bbox_px'],p['orientation'])),warnings
