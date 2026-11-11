"""Export du graphe au format GraphML (Gephi, yEd, Cytoscape)."""

from __future__ import annotations

from xml.sax.saxutils import escape

from .kb import KnowledgeBase

ATTRS = [("kind", "string"), ("title", "string"), ("discipline", "string"), ("levels", "string"), ("source", "string")]


def graphml(kb: KnowledgeBase) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    ]
    out += [f'  <key id="{name}" for="node" attr.name="{name}" attr.type="{typ}"/>' for name, typ in ATTRS]
    out.append('  <key id="rel" for="edge" attr.name="rel" attr.type="string"/>')
    out.append('  <graph id="programmes" edgedefault="directed">')
    with kb._conn() as con:
        for r in con.execute("SELECT id, kind, title, discipline, levels, source_id FROM nodes WHERE kind != 'objectif'"):
            values = [r["kind"], r["title"], r["discipline"], r["levels"].strip(","), r["source_id"]]
            data = "".join(f'<data key="{k}">{escape(str(v))}</data>' for (k, _), v in zip(ATTRS, values))
            out.append(f'    <node id="{escape(r["id"], {chr(34): "&quot;"})}">{data}</node>')
        for i, r in enumerate(con.execute(
            "SELECT e.src, e.rel, e.dst FROM edges e JOIN nodes a ON a.id = e.src JOIN nodes b ON b.id = e.dst "
            "WHERE a.kind != 'objectif' AND b.kind != 'objectif'"
        )):
            out.append(f'    <edge id="e{i}" source="{escape(r["src"], {chr(34): "&quot;"})}" '
                       f'target="{escape(r["dst"], {chr(34): "&quot;"})}"><data key="rel">{r["rel"]}</data></edge>')
    out += ["  </graph>", "</graphml>"]
    return "\n".join(out) + "\n"
