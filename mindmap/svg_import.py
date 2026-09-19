"""Importación de formas SVG simples para usar como silueta de un nodo.

Sólo usa la biblioteca estándar (xml.etree.ElementTree): admite el primer
elemento de forma que encuentre en el archivo (<path>, <polygon>,
<polyline>, <rect>, <circle> o <ellipse>), y lo convierte en una lista de
puntos (x, y) normalizados, centrados en (0, 0) y con la mayor dimensión
igual a 1.0, listos para escalarse al tamaño de un nodo.
"""

import re
import xml.etree.ElementTree as ET
from typing import List, Tuple

_SVG_NS = "{http://www.w3.org/2000/svg}"
_SHAPE_TAGS = ("path", "polygon", "polyline", "rect", "circle", "ellipse")

_TOKEN_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _find_shape_element(root: ET.Element):
    for el in root.iter():
        if _local_tag(el.tag) in _SHAPE_TAGS:
            return el
    return None


def _sample_quadratic(p0, p1, p2, samples=12):
    pts = []
    for i in range(1, samples + 1):
        t = i / samples
        mt = 1 - t
        x = mt ** 2 * p0[0] + 2 * mt * t * p1[0] + t ** 2 * p2[0]
        y = mt ** 2 * p0[1] + 2 * mt * t * p1[1] + t ** 2 * p2[1]
        pts.append((x, y))
    return pts


def _sample_cubic(p0, p1, p2, p3, samples=16):
    pts = []
    for i in range(1, samples + 1):
        t = i / samples
        mt = 1 - t
        x = mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0] + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1] + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1]
        pts.append((x, y))
    return pts


def _parse_path_d(d: str) -> List[Tuple[float, float]]:
    """Convierte el atributo `d` de un <path> en una lista de puntos, muestreando
    curvas cúbicas/cuadráticas. Soporta M/L/H/V/C/S/Q/T/Z (may/minúsculas).
    Los arcos (A/a) se aproximan con una línea recta a su punto final."""
    tokens = _TOKEN_RE.findall(d)
    pts: List[Tuple[float, float]] = []
    i = 0
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    prev_ctrl = None  # último punto de control (para S/T), en coords absolutas
    cmd = None

    def nxt() -> float:
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
        relative = cmd.islower()
        c = cmd.upper()

        if c == "M":
            x, y = nxt(), nxt()
            if relative:
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y)
            start = cur
            pts.append(cur)
            cmd = "l" if relative else "L"
            prev_ctrl = None
        elif c == "L":
            x, y = nxt(), nxt()
            if relative:
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y)
            pts.append(cur)
            prev_ctrl = None
        elif c == "H":
            x = nxt()
            x = cur[0] + x if relative else x
            cur = (x, cur[1])
            pts.append(cur)
            prev_ctrl = None
        elif c == "V":
            y = nxt()
            y = cur[1] + y if relative else y
            cur = (cur[0], y)
            pts.append(cur)
            prev_ctrl = None
        elif c == "C":
            x1, y1, x2, y2, x, y = nxt(), nxt(), nxt(), nxt(), nxt(), nxt()
            if relative:
                x1, y1 = cur[0] + x1, cur[1] + y1
                x2, y2 = cur[0] + x2, cur[1] + y2
                x, y = cur[0] + x, cur[1] + y
            pts.extend(_sample_cubic(cur, (x1, y1), (x2, y2), (x, y)))
            prev_ctrl = (x2, y2)
            cur = (x, y)
        elif c == "S":
            x2, y2, x, y = nxt(), nxt(), nxt(), nxt()
            if relative:
                x2, y2 = cur[0] + x2, cur[1] + y2
                x, y = cur[0] + x, cur[1] + y
            if prev_ctrl is not None:
                x1, y1 = 2 * cur[0] - prev_ctrl[0], 2 * cur[1] - prev_ctrl[1]
            else:
                x1, y1 = cur
            pts.extend(_sample_cubic(cur, (x1, y1), (x2, y2), (x, y)))
            prev_ctrl = (x2, y2)
            cur = (x, y)
        elif c == "Q":
            x1, y1, x, y = nxt(), nxt(), nxt(), nxt()
            if relative:
                x1, y1 = cur[0] + x1, cur[1] + y1
                x, y = cur[0] + x, cur[1] + y
            pts.extend(_sample_quadratic(cur, (x1, y1), (x, y)))
            prev_ctrl = (x1, y1)
            cur = (x, y)
        elif c == "T":
            x, y = nxt(), nxt()
            if relative:
                x, y = cur[0] + x, cur[1] + y
            if prev_ctrl is not None:
                x1, y1 = 2 * cur[0] - prev_ctrl[0], 2 * cur[1] - prev_ctrl[1]
            else:
                x1, y1 = cur
            pts.extend(_sample_quadratic(cur, (x1, y1), (x, y)))
            prev_ctrl = (x1, y1)
            cur = (x, y)
        elif c == "A":
            for _ in range(5):
                nxt()
            x, y = nxt(), nxt()
            if relative:
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y)
            pts.append(cur)
            prev_ctrl = None
        elif c == "Z":
            cur = start
            pts.append(cur)
            prev_ctrl = None
        else:
            raise ValueError(f"Comando SVG no soportado: {cmd}")
    return pts


def _parse_points_attr(points_attr: str) -> List[Tuple[float, float]]:
    nums = [float(n) for n in re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", points_attr)]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def _ellipse_points(cx, cy, rx, ry, samples=48) -> List[Tuple[float, float]]:
    import math
    return [
        (cx + rx * math.cos(2 * math.pi * i / samples),
         cy + ry * math.sin(2 * math.pi * i / samples))
        for i in range(samples)
    ]


def _shape_element_to_points(el: ET.Element) -> List[Tuple[float, float]]:
    tag = _local_tag(el.tag)
    if tag == "path":
        d = el.get("d", "")
        if not d.strip():
            raise ValueError("El <path> no tiene atributo 'd'.")
        return _parse_path_d(d)
    if tag in ("polygon", "polyline"):
        points_attr = el.get("points", "")
        if not points_attr.strip():
            raise ValueError(f"<{tag}> no tiene atributo 'points'.")
        return _parse_points_attr(points_attr)
    if tag == "rect":
        x, y = float(el.get("x", 0)), float(el.get("y", 0))
        w, h = float(el.get("width", 0)), float(el.get("height", 0))
        if w <= 0 or h <= 0:
            raise ValueError("El <rect> no tiene ancho/alto válidos.")
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if tag == "circle":
        cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
        r = float(el.get("r", 0))
        if r <= 0:
            raise ValueError("El <circle> no tiene radio válido.")
        return _ellipse_points(cx, cy, r, r)
    if tag == "ellipse":
        cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
        rx, ry = float(el.get("rx", 0)), float(el.get("ry", 0))
        if rx <= 0 or ry <= 0:
            raise ValueError("El <ellipse> no tiene radios válidos.")
        return _ellipse_points(cx, cy, rx, ry)
    raise ValueError(f"Elemento SVG no soportado: <{tag}>")


def _normalize(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
    w, h = max_x - min_x, max_y - min_y
    scale = 1.0 / max(w, h, 1e-6)
    return [((x - cx) * scale, (y - cy) * scale) for x, y in points]


def import_svg_shape(path: str) -> List[Tuple[float, float]]:
    """Lee un archivo .svg y devuelve los puntos de su primera forma, como una
    lista de (x, y) normalizados (centrados en el origen, mayor dimensión = 1.0).

    Lanza ValueError con un mensaje claro si el archivo no es un SVG válido,
    no contiene ninguna forma soportada, o la forma no se puede interpretar.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise ValueError(f"El archivo no es un SVG válido: {e}") from e
    except OSError as e:
        raise ValueError(f"No se pudo leer el archivo: {e}") from e

    root = tree.getroot()
    el = _find_shape_element(root)
    if el is None:
        raise ValueError(
            "No se encontró ninguna forma soportada en el SVG "
            "(se admiten <path>, <polygon>, <polyline>, <rect>, <circle>, <ellipse>)."
        )

    points = _shape_element_to_points(el)
    if len(points) < 3:
        raise ValueError("La forma tiene muy pocos puntos para formar un polígono.")
    return _normalize(points)
