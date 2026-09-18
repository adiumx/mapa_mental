"""Convierte texto plano o Markdown en un esquema jerárquico (OutlineNode).

Reglas:
- Encabezados Markdown (#, ##, ###...) definen niveles de jerarquía.
- Viñetas (-, *, +) o listas numeradas (1., 2)) se anidan según su indentación.
- Si el texto no tiene encabezados ni viñetas y es un párrafo corrido, se separa
  en oraciones y cada una se convierte en un nodo hijo del nodo raíz.
- Si el texto son varias líneas sueltas sin marcas, cada línea se convierte en
  un nodo hijo del nodo raíz.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_BULLET_RE = re.compile(r"^[-*+]\s+(.*)")
_NUMBERED_RE = re.compile(r"^\d+[.)]\s+(.*)")
_EMPHASIS_RE = re.compile(r"[*_`]{1,3}")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class OutlineNode:
    text: str
    children: List["OutlineNode"] = field(default_factory=list)


def _clean(text: str) -> str:
    return _EMPHASIS_RE.sub("", text).strip()


def parse_outline(raw_text: str) -> Optional[OutlineNode]:
    raw_text = raw_text.strip()
    if not raw_text:
        return None

    structured_lines = []  # lista de (nivel, texto)
    current_heading_level = 0
    has_structure_markers = False

    for line in raw_text.splitlines():
        if not line.strip():
            continue
        expanded = line.replace("\t", "  ")
        stripped = expanded.strip()

        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            has_structure_markers = True
            level = len(heading_match.group(1))
            text = _clean(heading_match.group(2))
            current_heading_level = level
            if text:
                structured_lines.append((level, text))
            continue

        indent = len(expanded) - len(expanded.lstrip(" "))
        indent_level = indent // 2

        bullet_match = _BULLET_RE.match(stripped) or _NUMBERED_RE.match(stripped)
        if bullet_match:
            has_structure_markers = True
            text = _clean(bullet_match.group(1))
        else:
            text = _clean(stripped)

        if not text:
            continue
        structured_lines.append((current_heading_level + 1 + indent_level, text))

    if not structured_lines:
        return None

    if not has_structure_markers and len(structured_lines) == 1:
        paragraph = structured_lines[0][1]
        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
        if len(sentences) > 1:
            root = OutlineNode(text=_shorten(sentences[0]))
            for sentence in sentences[1:]:
                root.children.append(OutlineNode(text=sentence))
            return root
        return OutlineNode(text=_shorten(paragraph))

    start_index = 0
    if structured_lines[0][0] == 1:
        root = OutlineNode(text=structured_lines[0][1])
        start_index = 1
    else:
        root = OutlineNode(text="Mapa mental")

    stack = [(0, root)]
    for level, text in structured_lines[start_index:]:
        while len(stack) > 1 and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        node = OutlineNode(text=text)
        parent.children.append(node)
        stack.append((level, node))

    return root


def _shorten(text: str, max_len: int = 60) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text or "Mapa mental"
    return text[: max_len - 1].rstrip() + "…"
