"""Ingestion : sources.toml → PDF analysés → graphe → base SQLite (et, sur demande, les guides)."""

from __future__ import annotations

from collections.abc import Callable

from .config import Settings, load_sources
from .extract import file_hash, ocr_pdf, read_lines
from .graph import GraphBuilder
from .kb import KnowledgeBase
from .outline import parse_document


def build(settings: Settings, kb: KnowledgeBase, log: Callable[[str], None] = print, guides: bool = False) -> dict:
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
    report = {"sources": len(specs), "avertissements": warnings, "guides": []}
    if guides:
        report["guides"] = add_guides(settings, graph, log)
        report["avertissements"] += [w for g in report["guides"] for w in g.get("avertissements", [])]
    kb.replace_graph(graph)
    report.update(noeuds=len(graph.nodes), aretes=len(graph.edges))
    return report


def add_guides(settings: Settings, graph, log: Callable[[str], None] = print) -> list[dict]:
    """Lit les guides du guides.toml de l'enseignant (OCR de macOS, mis en cache) et les ajoute au graphe."""
    from .guides import add_guide, load_guides, parse_daily_guide, parse_weekly_guide
    from .ocr_vision import Speller, correct_pages, ocr_document, vision_binary

    if not settings.guides_file.exists():
        raise ValueError(f"aucune description des guides de la classe : {settings.guides_file} "
                         "(modèle : guides.exemple.toml, à copier et compléter)")
    specs, warnings = load_guides(settings.guides_file, settings.programmes_dir)
    for w in warnings:
        log(f"⚠ {w}")
    speller = Speller(vision_binary(settings.cache_dir))
    position = 10_000_000
    out = []
    for spec in specs:
        files = []
        for gfile in spec.files:
            def progress(done: int, total: int, name: str = gfile.path.name) -> None:
                log(f"    OCR {name[:50]} : {done}/{total} pages")
            pages = ocr_document(gfile.path, settings.cache_dir, progress)
            correct_pages(pages, speller)
            files.append((gfile, pages))
        notes: list[str] = []
        if spec.rhythm == "jour":
            units, annexes = parse_daily_guide(files, log=notes.append)
            extra = {"annexes": annexes}
        else:  # « semaine » : les séquences de chaque fichier se suivent
            units, extra = [], {}
            for _, pages in files:
                for unit in parse_weekly_guide(pages):
                    unit.number = len(units) + 1
                    units.append(unit)
        for note in notes:
            log(note)
        position = add_guide(graph, spec, units, extra, position)
        seances = sum(len(u.all_seances) for u in units)
        days = sum(len(u.days) for u in units)
        cited = sum(1 for (src, rel, _) in graph.edges if rel == "travaille" and src.startswith(f"guide:{spec.id}/"))
        log(f"  {spec.id:<30} {len(units):4} {'séquences' if not days else 'leçons'}, "
            + (f"{days} jours, " if days else "") + f"{seances} séances"
            + (f", {cited} liens vers les objectifs du programme cités par le guide" if cited else ""))
        out.append({"id": spec.id, "unites": len(units), "jours": days, "seances": seances, "objectifs_cites": cited,
                    "avertissements": [n.strip() for n in notes]})
    return out
