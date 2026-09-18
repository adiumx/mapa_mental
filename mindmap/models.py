"""Modelos de datos para nodos y conexiones del mapa mental."""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Node:
    id: int
    x: float
    y: float
    text: str = "Nueva idea"
    color: str = "#4a90d9"
    text_color: str = "#ffffff"
    width: float = 140
    height: float = 56

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "text": self.text,
            "color": self.color,
            "text_color": self.text_color,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Node":
        return cls(
            id=data["id"],
            x=data["x"],
            y=data["y"],
            text=data.get("text", "Nueva idea"),
            color=data.get("color", "#4a90d9"),
            text_color=data.get("text_color", "#ffffff"),
            width=data.get("width", 140),
            height=data.get("height", 56),
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
