"""Ingestion : sources.toml → PDF analysés → graphe → base SQLite."""

from __future__ import annotations

from collections.abc import Callable

from .config import Settings, load_sources
from .extract import file_hash, ocr_pdf, read_lines
from .graph import GraphBuilder
from .kb import KnowledgeBase
from .outline import parse_document


def build(settings: Settings, kb: KnowledgeBase, log: Callable[[str], None] = print) -> dict:
    specs, warnings = load_sources(settings.sources_file, settings.programmes_dir)
    for w in warnings:
        log(f"⚠ {w}")
    builder = GraphBuilder()
    for spec in specs:
        source = ocr_pdf(spec.path, settings.cache_dir / "ocr") if spec.ocr else spec.path
        root = parse_document(spec, read_lines(source, spec.pages), source)
        builder.add_source(spec, root, file_hash(spec.path))
        items = sum(len(h[-1].items) for h in root.walk())
        log(f"  {spec.id:<30} {items:4} items  ({spec.path.parent.name}/{spec.path.name[:60]})")
    graph = builder.finish()
    kb.replace_graph(graph)
    return {"sources": len(specs), "noeuds": len(graph.nodes), "aretes": len(graph.edges), "avertissements": warnings}
