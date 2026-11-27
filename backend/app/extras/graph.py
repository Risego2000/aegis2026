"""Grafo de vínculos sobre los datos que AEGIS ya tiene.

No es Maltego: es el grafo que se puede construir sin inventar nada —
suceso↔fuente↔país, más coocurrencia país↔fuente— y su exportación a
**GraphML** para abrirlo en i2, Maltego, Gephi o yEd. Con eso el analista pasa
de «veo puntos» a «veo estructura».
"""
from __future__ import annotations

from typing import Any, Iterable
from xml.sax.saxutils import escape, quoteattr

NODE_KINDS = ("event", "source", "country", "category")


def build_graph(events: Iterable[Any], limit: int = 400) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(node_id: str, kind: str, label: str, **attrs: Any) -> None:
        if node_id in nodes:
            nodes[node_id]["weight"] = nodes[node_id].get("weight", 1) + 1
            return
        nodes[node_id] = {"id": node_id, "kind": kind, "label": label, "weight": 1, **attrs}

    def add_edge(src: str, dst: str, kind: str, weight: float = 1.0) -> None:
        key = (src, dst, kind)
        if key in edges:
            edges[key]["weight"] += weight
        else:
            edges[key] = {"src": src, "dst": dst, "kind": kind, "weight": weight}

    for ev in list(events)[:limit]:
        event_id = f"event:{getattr(ev, 'id', '')}"
        add_node(
            event_id,
            "event",
            (getattr(ev, "title", "") or "")[:90],
            category=getattr(ev, "category", ""),
            severity=getattr(ev, "severity", None),
            event_time=getattr(ev, "event_time", ""),
        )
        source = getattr(ev, "source", "") or "?"
        add_node(f"source:{source}", "source", source)
        add_edge(event_id, f"source:{source}", "reported_by")
        iso3 = getattr(ev, "iso3", "") or ""
        if iso3:
            add_node(f"country:{iso3}", "country", iso3)
            add_edge(event_id, f"country:{iso3}", "located_in")
            # coocurrencia: qué fuente cubre qué país (estructura de cobertura)
            add_edge(f"source:{source}", f"country:{iso3}", "covers", 0.5)
        category = getattr(ev, "category", "") or ""
        if category:
            add_node(f"category:{category}", "category", category)
            add_edge(event_id, f"category:{category}", "classified_as")

    return {
        "nodes": sorted(nodes.values(), key=lambda n: (-n.get("weight", 0), n["id"])),
        "edges": sorted(edges.values(), key=lambda e: (-e["weight"], e["src"])),
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }


def to_graphml(graph: dict[str, Any], title: str = "AEGIS") -> str:
    """GraphML 1.0 (yEd/Gephi/i2 lo abren sin conversión)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns '
        'http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">',
        '<key id="label" for="node" attr.name="label" attr.type="string"/>',
        '<key id="kind" for="node" attr.name="kind" attr.type="string"/>',
        '<key id="weight" for="node" attr.name="weight" attr.type="double"/>',
        '<key id="rel" for="edge" attr.name="rel" attr.type="string"/>',
        '<key id="eweight" for="edge" attr.name="weight" attr.type="double"/>',
        f'<graph id="{escape(title)}" edgedefault="undirected">',
    ]
    for node in graph["nodes"]:
        lines.append(
            f'  <node id={quoteattr(node["id"])}>'
            f'<data key="label">{escape(str(node.get("label", "")))}</data>'
            f'<data key="kind">{escape(str(node.get("kind", "")))}</data>'
            f'<data key="weight">{float(node.get("weight", 1))}</data>'
            "</node>"
        )
    for i, edge in enumerate(graph["edges"]):
        lines.append(
            f'  <edge id="e{i}" source={quoteattr(edge["src"])} target={quoteattr(edge["dst"])}>'
            f'<data key="rel">{escape(str(edge.get("kind", "")))}</data>'
            f'<data key="eweight">{float(edge.get("weight", 1))}</data>'
            "</edge>"
        )
    lines += ["</graph>", "</graphml>"]
    return "\n".join(lines)
