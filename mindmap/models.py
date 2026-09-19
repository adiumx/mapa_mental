"""Modelos de datos para nodos y conexiones del mapa mental."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Node:
    id: int
    x: float
    y: float
    text: str = "Nueva idea"
    color: str = "#4a90d9"
    shape: str = "leaf"  # "root" (nodo central, más grande) o "leaf" (nodo de rama)
    width: float = 140
    height: float = 56
    # Contorno personalizado importado de un SVG: lista de puntos (x, y)
    # normalizados (centrados en 0, mayor dimensión = 1.0). None = forma
    # normal del tema (caja/punto/nube).
    custom_shape: Optional[List[List[float]]] = None
    collapsed: bool = False
    # Nota larga adjunta al nodo: no se dibuja dentro del nodo (eso desordenaría
    # el layout), sino que se indica con un ícono y se lee al pasar el mouse.
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "text": self.text,
            "color": self.color,
            "shape": self.shape,
            "width": self.width,
            "height": self.height,
            "custom_shape": self.custom_shape,
            "collapsed": self.collapsed,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Node":
        return cls(
            id=data["id"],
            x=data["x"],
            y=data["y"],
            text=data.get("text", "Nueva idea"),
            color=data.get("color", "#4a90d9"),
            shape=data.get("shape", "leaf"),
            width=data.get("width", 140),
            height=data.get("height", 56),
            custom_shape=data.get("custom_shape"),
            collapsed=data.get("collapsed", False),
            note=data.get("note", ""),
        )


@dataclass
class Connection:
    id: int
    source_id: int
    target_id: int
    color: str = "#8a8a8a"
    line_width: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "color": self.color,
            "line_width": self.line_width,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Connection":
        return cls(
            id=data["id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            color=data.get("color", "#8a8a8a"),
            line_width=data.get("line_width", 3),
        )
