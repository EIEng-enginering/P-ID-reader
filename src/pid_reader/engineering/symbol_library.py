"""Original-geometry symbol library (Rev X, WPU-05). Shapes are composed here from primitives; nothing is copied from a standard,
a vendor catalogue or a client drawing. Raster templates are rendered on demand, at any size, stroke width and quarter turn.

Hierarchy per template: ``graphical_family`` > ``shape_variant`` > ``engineering_class`` > ``actuation`` > ``function``.
A drawn bow-tie is a *shape*; what valve it is (and whether it is closed, filled or hollow by convention) is project/legend
knowledge, so the same geometry can carry several candidate classes and some styles deliberately map to an *unspecified* class.
Valve class and actuation are separate templates so each has its own evidence.

Ports are typed (``PROCESS_UNKNOWN`` -- direction is never assumed -- ``ACTUATOR_SIGNAL``, ``SIGNAL_IN``, ``NOZZLE`` ...) and given in the
template's local frame (x right, y down, 0..1 across the symbol's box), then rotated with the symbol.
"""
from __future__ import annotations

from math import cos, pi, sin

VERSION = "symbol-library-v1"

FILL_NONE, FILL_SOLID = "hollow", "filled"


def _canvas(w: int, h: int, pad: int):
    import numpy as np
    return np.zeros((h + 2 * pad, w + 2 * pad), dtype=np.uint8)


def _pt(x: float, y: float, w: int, h: int, pad: int) -> tuple[int, int]:
    return int(round(pad + x * (w - 1))), int(round(pad + y * (h - 1)))


# ---- primitive drawers (ink = 255 on black); every drawer takes (img, w, h, pad, t)
def _poly(img, pts, w, h, pad, t, fill=False):
    import cv2
    import numpy as np
    arr = np.array([_pt(x, y, w, h, pad) for x, y in pts], dtype=np.int32)
    if fill:
        cv2.fillPoly(img, [arr], 255)
    else:
        cv2.polylines(img, [arr], True, 255, t, cv2.LINE_8)


def _line(img, a, b, w, h, pad, t):
    import cv2
    cv2.line(img, _pt(*a, w, h, pad), _pt(*b, w, h, pad), 255, t, cv2.LINE_8)


def _circle(img, c, r, w, h, pad, t, fill=False):
    import cv2
    cv2.circle(img, _pt(*c, w, h, pad), int(round(r * (w - 1))), 255, -1 if fill else t, cv2.LINE_8)


def _bowtie(img, w, h, pad, t, fill=False):
    _poly(img, [(0, 0), (0, 1), (0.5, 0.5)], w, h, pad, t, fill)
    _poly(img, [(1, 0), (1, 1), (0.5, 0.5)], w, h, pad, t, fill)


def _d_gate(img, w, h, pad, t):
    _bowtie(img, w, h, pad, t)


def _d_bowtie_filled(img, w, h, pad, t):
    _bowtie(img, w, h, pad, t, fill=True)


def _d_globe(img, w, h, pad, t):
    _bowtie(img, w, h, pad, t)
    _circle(img, (0.5, 0.5), 0.12, w, h, pad, t, fill=True)


def _d_ball(img, w, h, pad, t):
    _bowtie(img, w, h, pad, t)
    _circle(img, (0.5, 0.5), 0.17, w, h, pad, t)


def _d_butterfly(img, w, h, pad, t):
    _bowtie(img, w, h, pad, t)
    _line(img, (0.5, 0.0), (0.5, 1.0), w, h, pad, t)


def _d_check(img, w, h, pad, t):
    _poly(img, [(0.05, 0.05), (0.05, 0.95), (0.85, 0.5)], w, h, pad, t)
    _line(img, (0.95, 0.0), (0.95, 1.0), w, h, pad, t)


def _d_act_manual(img, w, h, pad, t):
    _line(img, (0.5, 1.0), (0.5, 0.15), w, h, pad, t)
    _line(img, (0.1, 0.15), (0.9, 0.15), w, h, pad, t)


def _d_act_diaphragm(img, w, h, pad, t):
    import cv2
    _line(img, (0.5, 1.0), (0.5, 0.55), w, h, pad, t)
    cv2.ellipse(img, _pt(0.5, 0.55, w, h, pad), (int(0.42 * (w - 1)), int(0.5 * (h - 1))), 0, 180, 360, 255, t)
    _line(img, (0.08, 0.55), (0.92, 0.55), w, h, pad, t)


def _d_act_solenoid(img, w, h, pad, t):
    _line(img, (0.5, 1.0), (0.5, 0.55), w, h, pad, t)
    _poly(img, [(0.2, 0.0), (0.8, 0.0), (0.8, 0.55), (0.2, 0.55)], w, h, pad, t)


def _d_act_motor(img, w, h, pad, t):
    _line(img, (0.5, 1.0), (0.5, 0.62), w, h, pad, t)
    _circle(img, (0.5, 0.32), 0.3, w, h, pad, t)


def _d_inst_field(img, w, h, pad, t):
    _circle(img, (0.5, 0.5), 0.49, w, h, pad, t)


def _d_inst_panel(img, w, h, pad, t):
    _circle(img, (0.5, 0.5), 0.49, w, h, pad, t)
    _line(img, (0.01, 0.5), (0.99, 0.5), w, h, pad, t)


def _d_inst_shared(img, w, h, pad, t):
    _poly(img, [(0, 0), (1, 0), (1, 1), (0, 1)], w, h, pad, t)
    _circle(img, (0.5, 0.5), 0.49, w, h, pad, t)


def _d_vessel_v(img, w, h, pad, t):
    import cv2
    r = 0.5
    _line(img, (0.0, 0.18), (0.0, 0.82), w, h, pad, t)
    _line(img, (1.0, 0.18), (1.0, 0.82), w, h, pad, t)
    cv2.ellipse(img, _pt(0.5, 0.18, w, h, pad), (int(r * (w - 1)), int(0.18 * (h - 1))), 0, 180, 360, 255, t)
    cv2.ellipse(img, _pt(0.5, 0.82, w, h, pad), (int(r * (w - 1)), int(0.18 * (h - 1))), 0, 0, 180, 255, t)


def _d_vessel_h(img, w, h, pad, t):
    import cv2
    _line(img, (0.14, 0.0), (0.86, 0.0), w, h, pad, t)
    _line(img, (0.14, 1.0), (0.86, 1.0), w, h, pad, t)
    cv2.ellipse(img, _pt(0.14, 0.5, w, h, pad), (int(0.14 * (w - 1)), int(0.5 * (h - 1))), 0, 90, 270, 255, t)
    cv2.ellipse(img, _pt(0.86, 0.5, w, h, pad), (int(0.14 * (w - 1)), int(0.5 * (h - 1))), 0, 270, 450, 255, t)


def _d_pump(img, w, h, pad, t):
    _circle(img, (0.5, 0.58), 0.4, w, h, pad, t)
    _line(img, (0.5, 0.18), (0.5, 0.0), w, h, pad, t)
    _line(img, (0.5, 0.0), (1.0, 0.0), w, h, pad, t)
    _poly(img, [(0.3, 0.38), (0.78, 0.58), (0.3, 0.78)], w, h, pad, t)


def _d_exchanger(img, w, h, pad, t):
    _circle(img, (0.5, 0.5), 0.49, w, h, pad, t)
    pts = [(0.0, 0.5), (0.2, 0.5), (0.32, 0.2), (0.5, 0.8), (0.68, 0.2), (0.8, 0.5), (1.0, 0.5)]
    for a, b in zip(pts[:-1], pts[1:]):
        _line(img, a, b, w, h, pad, t)


def _d_filter(img, w, h, pad, t):
    _poly(img, [(0, 0), (1, 0), (1, 1), (0, 1)], w, h, pad, t)
    _line(img, (0.0, 1.0), (1.0, 0.0), w, h, pad, t)


_END_PORTS = [{"kind": "PROCESS_UNKNOWN", "x": 0.0, "y": 0.5, "angle": 180}, {"kind": "PROCESS_UNKNOWN", "x": 1.0, "y": 0.5, "angle": 0}]


def _spec(sid, family, variant, eclass, actuation, function, aspect, symmetry, drawer, ports, sizes_pt, **extra):
    return {"template_id": sid, "graphical_family": family, "shape_variant": variant, "engineering_class": eclass,
            "actuation": actuation, "function": function, "aspect": aspect, "rotation_symmetry": symmetry, "draw": drawer,
            "ports": ports, "sizes_pt": sizes_pt, "size_range_pt": (round(min(sizes_pt) * 0.85, 2), round(max(sizes_pt) * 1.2, 2)), **extra}


VALVE_SIZES = (14, 20, 28)
LIBRARY: dict[str, dict] = {s["template_id"]: s for s in [
    _spec("VALVE_BOWTIE_HOLLOW", "VALVE", "BOWTIE_HOLLOW", "GATE_VALVE", None, "ISOLATION", 0.6, 2, _d_gate, _END_PORTS, VALVE_SIZES),
    _spec("VALVE_BOWTIE_FILLED", "VALVE", "BOWTIE_FILLED", "ISOLATION_VALVE_TYPE_UNSPECIFIED", None, "ISOLATION", 0.6, 2, _d_bowtie_filled,
          _END_PORTS, VALVE_SIZES, class_alternatives=["GATE_VALVE", "BALL_VALVE", "UNKNOWN"]),
    _spec("VALVE_GLOBE", "VALVE", "BOWTIE_CENTRE_DOT", "GLOBE_VALVE", None, "THROTTLING", 0.6, 2, _d_globe, _END_PORTS, VALVE_SIZES),
    _spec("VALVE_BALL", "VALVE", "BOWTIE_CENTRE_RING", "BALL_VALVE", None, "ISOLATION", 0.6, 2, _d_ball, _END_PORTS, VALVE_SIZES),
    _spec("VALVE_BUTTERFLY", "VALVE", "BOWTIE_CENTRE_BAR", "BUTTERFLY_VALVE", None, "ISOLATION", 0.6, 2, _d_butterfly, _END_PORTS, VALVE_SIZES),
    _spec("VALVE_CHECK", "VALVE", "TRIANGLE_BAR", "CHECK_VALVE", None, "NON_RETURN", 0.7, 4, _d_check,
          [{"kind": "PROCESS_UNKNOWN", "x": 0.0, "y": 0.5, "angle": 180}, {"kind": "PROCESS_UNKNOWN", "x": 1.0, "y": 0.5, "angle": 0}],
          VALVE_SIZES, directional=True),
    _spec("ACT_MANUAL", "ACTUATOR", "STEM_TBAR", "HAND_ACTUATOR", "MANUAL_HANDWHEEL", "ACTUATION", 0.9, 1, _d_act_manual,
          [{"kind": "ACTUATOR_SIGNAL", "x": 0.5, "y": 1.0, "angle": 90}], (8, 12, 17)),
    _spec("ACT_DIAPHRAGM", "ACTUATOR", "STEM_DOME", "PNEUMATIC_DIAPHRAGM_ACTUATOR", "PNEUMATIC_DIAPHRAGM", "ACTUATION", 0.9, 1, _d_act_diaphragm,
          [{"kind": "ACTUATOR_SIGNAL", "x": 0.5, "y": 1.0, "angle": 90}], (8, 12, 17)),
    _spec("ACT_SOLENOID", "ACTUATOR", "STEM_BOX", "SOLENOID_ACTUATOR", "SOLENOID", "ACTUATION", 0.9, 1, _d_act_solenoid,
          [{"kind": "ACTUATOR_SIGNAL", "x": 0.5, "y": 1.0, "angle": 90}], (8, 12, 17)),
    _spec("ACT_MOTOR", "ACTUATOR", "STEM_RING", "MOTOR_ACTUATOR", "MOTOR", "ACTUATION", 0.9, 1, _d_act_motor,
          [{"kind": "ACTUATOR_SIGNAL", "x": 0.5, "y": 1.0, "angle": 90}], (8, 12, 17)),
    _spec("INST_FIELD", "INSTRUMENT", "BUBBLE_PLAIN", "INSTRUMENT_FIELD_MOUNTED", None, "INDICATION", 1.0, 1, _d_inst_field,
          [{"kind": "INSTRUMENT_TAP", "x": 0.5, "y": 1.0, "angle": 90}, {"kind": "SIGNAL_OUT", "x": 0.5, "y": 0.0, "angle": 270}], (14, 20, 28)),
    _spec("INST_PANEL", "INSTRUMENT", "BUBBLE_BAR", "INSTRUMENT_PANEL_MOUNTED", None, "INDICATION", 1.0, 1, _d_inst_panel,
          [{"kind": "SIGNAL_IN", "x": 0.5, "y": 1.0, "angle": 90}, {"kind": "SIGNAL_OUT", "x": 0.5, "y": 0.0, "angle": 270}], (14, 20, 28)),
    _spec("INST_SHARED", "INSTRUMENT", "BUBBLE_IN_SQUARE", "INSTRUMENT_SHARED_DISPLAY_CONTROL", None, "CONTROL_SYSTEM_INTERFACE", 1.0, 1, _d_inst_shared,
          [{"kind": "SIGNAL_IN", "x": 0.5, "y": 1.0, "angle": 90}, {"kind": "SIGNAL_OUT", "x": 0.5, "y": 0.0, "angle": 270}], (16, 24, 32)),
    _spec("EQ_VESSEL_V", "EQUIPMENT", "CAPSULE_VERTICAL", "PRESSURE_VESSEL", None, "CONTAINMENT", 2.2, 2, _d_vessel_v,
          [{"kind": "NOZZLE", "x": 0.5, "y": 0.0, "angle": 270}, {"kind": "NOZZLE", "x": 0.5, "y": 1.0, "angle": 90}], (45, 75, 110),
          class_alternatives=["SEPARATOR", "FILTER_HOUSING", "COLUMN", "UNKNOWN"]),
    _spec("EQ_VESSEL_H", "EQUIPMENT", "CAPSULE_HORIZONTAL", "PRESSURE_VESSEL", None, "CONTAINMENT", 0.45, 2, _d_vessel_h,
          [{"kind": "NOZZLE", "x": 0.0, "y": 0.5, "angle": 180}, {"kind": "NOZZLE", "x": 1.0, "y": 0.5, "angle": 0}], (60, 100, 150),
          class_alternatives=["SEPARATOR", "DRUM", "UNKNOWN"]),
    _spec("EQ_PUMP", "EQUIPMENT", "CIRCLE_TANGENT_OUTLET", "CENTRIFUGAL_PUMP", None, "PUMPING", 1.0, 1, _d_pump,
          [{"kind": "NOZZLE", "x": 0.5, "y": 1.0, "angle": 90}, {"kind": "NOZZLE", "x": 1.0, "y": 0.0, "angle": 0}], (28, 44, 64)),
    _spec("EQ_EXCHANGER", "EQUIPMENT", "CIRCLE_ZIGZAG", "HEAT_EXCHANGER", None, "HEAT_TRANSFER", 1.0, 2, _d_exchanger,
          [{"kind": "NOZZLE", "x": 0.0, "y": 0.5, "angle": 180}, {"kind": "NOZZLE", "x": 1.0, "y": 0.5, "angle": 0}], (28, 44, 64),
          class_alternatives=["HEATER", "COOLER", "UNKNOWN"]),
    _spec("EQ_FILTER", "EQUIPMENT", "BOX_DIAGONAL", "FILTER_OR_STRAINER", None, "SEPARATION", 1.0, 2, _d_filter,
          [{"kind": "NOZZLE", "x": 0.0, "y": 0.5, "angle": 180}, {"kind": "NOZZLE", "x": 1.0, "y": 0.5, "angle": 0}], (18, 28, 40),
          class_alternatives=["STRAINER", "FILTER", "UNKNOWN"]),
]}


def families() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for sid, s in LIBRARY.items():
        out.setdefault(s["graphical_family"], []).append(sid)
    return out


def render(template_id: str, width_px: int, stroke_px: int = 2, rotation: int = 0):
    """Ink image (255 = ink) of one template at ``width_px`` wide (height from its aspect), rotated by ``rotation`` degrees clockwise."""
    import numpy as np
    spec = LIBRARY[template_id]
    if rotation not in (0, 90, 180, 270):
        raise ValueError("rotation must be a quarter turn")
    w = max(8, int(width_px))
    h = max(8, int(round(w * spec["aspect"])))
    pad = max(2, stroke_px)
    img = _canvas(w, h, pad)
    spec["draw"](img, w, h, pad, max(1, int(stroke_px)))
    return np.rot90(img, k=(-rotation // 90) % 4).copy()


def rotated_ports(template_id: str, rotation: int) -> list[dict]:
    """Template ports after a clockwise quarter turn, in the rotated box's 0..1 frame (y down)."""
    spec = LIBRARY[template_id]
    out = []
    for p in spec["ports"]:
        x, y = p["x"], p["y"]
        for _ in range((rotation // 90) % 4):          # 90 degrees clockwise: (x, y) -> (1 - y, x)
            x, y = 1.0 - y, x
        out.append({"kind": p["kind"], "x": round(x, 6), "y": round(y, 6), "angle": (p["angle"] + rotation) % 360})
    return out


def rotations_for(template_id: str) -> tuple[int, ...]:
    """Distinct orientations to search: symmetric symbols need fewer."""
    return (0, 90) if LIBRARY[template_id]["rotation_symmetry"] == 2 else (0, 90, 180, 270)
