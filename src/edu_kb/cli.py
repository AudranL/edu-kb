"""Ligne de commande : edu-kb download | build | embed | status | search | fiche | themes | programme | sequence | skola
| referentiel | graphe | serve, et pour les guides pédagogiques : guides | guide-jour | guide-progression | guide-search
| guides-export | guides-import."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from .config import Settings
from .embed import EmbeddingUnavailable, OllamaEmbedder
from .kb import KnowledgeBase, school_year


def _kb(settings: Settings, semantic: bool = True) -> KnowledgeBase:
    embedder = OllamaEmbedder(settings.ollama_url, settings.embed_model) if semantic else None
    return KnowledgeBase(settings.db_path, embedder)


def _embed(kb: KnowledgeBase) -> None:
    from .guide_queries import has_guides

    try:
        n = kb.embed_missing(lambda done, total: print(f"\r  embeddings {done}/{total}", end="", flush=True))
        print(f"\nEmbeddings calculés : {n}")
        kept, dropped = kb.prune_mentions()
        print(f"Liens entre disciplines : {kept} gardés, {dropped} écartés (homonymes, mots trop courants)")
        if has_guides(kb):
            print(f"Séances des guides reliées au programme par le sens : {kb.link_guides()} liens")
    except EmbeddingUnavailable as exc:
        print(f"⚠ {exc}\n  L'index plein texte est prêt ; relance `edu-kb embed` quand Ollama tourne.")


def _guides_kb(settings: Settings, semantic: bool = True) -> KnowledgeBase:
    """La base locale avec les guides (EDU_KB_DB, sinon ~/.edu-kb/kb-guides.sqlite)."""
    if not settings.guides_db_path.exists():
        raise ValueError(f"aucune base avec les guides dans {settings.guides_db_path} : lance `edu-kb build --guides`")
    embedder = OllamaEmbedder(settings.ollama_url, settings.embed_model) if semantic else None
    return KnowledgeBase(settings.guides_db_path, embedder)


def _write(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Écrit : {output}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="edu-kb", description="Graphe de connaissance des programmes de l'école élémentaire.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("download", help="Télécharger la base publiée sur GitHub, sans reconstruire")
    p_build = sub.add_parser("build", help="Analyser les programmes de sources.toml et reconstruire le graphe")
    p_build.add_argument("--no-embed", action="store_true", help="Plein texte uniquement, sans Ollama")
    p_build.add_argument("--guides", action="store_true",
                         help="Ajouter les guides pédagogiques de la classe (~/.edu-kb/guides.toml, ou EDU_KB_GUIDES), "
                              "dans une base locale à part (~/.edu-kb/kb-guides.sqlite, ou EDU_KB_DB) : jamais dans la base publiée")
    sub.add_parser("embed", help="Calculer les embeddings manquants (Ollama)")
    sub.add_parser("status", help="État de la base et des sources")

    def common(p: argparse.ArgumentParser, level: bool = True) -> None:
        if level:
            p.add_argument("-n", "--niveau", help="CP, CE1, CE2, CM1, CM2 ou 6e")
        p.add_argument("-d", "--discipline", help="Ex. français, maths, HG, sciences, EMC")
        p.add_argument("-a", "--annee", help="Année scolaire : 2026-2027 (défaut : année en cours)")

    p_search = sub.add_parser("search", help="Chercher une notion")
    p_search.add_argument("query")
    p_search.add_argument("-k", "--limit", type=int, default=10)
    common(p_search)

    p_card = sub.add_parser("fiche", help="Fiche complète d'un item, objectif ou thème (JSON)")
    p_card.add_argument("id")
    p_card.add_argument("-a", "--annee")

    p_themes = sub.add_parser("themes", help="Thèmes d'un niveau")
    p_themes.add_argument("niveau")
    common(p_themes, level=False)

    p_prog = sub.add_parser("programme", help="Programme d'une discipline pour un niveau")
    p_prog.add_argument("niveau")
    p_prog.add_argument("discipline")
    p_prog.add_argument("-a", "--annee")

    p_seq = sub.add_parser("sequence", help="Préparer une séquence à partir d'une notion")
    p_seq.add_argument("notion")
    p_seq.add_argument("-n", "--niveau", required=True)
    p_seq.add_argument("-d", "--discipline")
    p_seq.add_argument("-a", "--annee")
    p_seq.add_argument("-s", "--seances", type=int, help="Nombre de séances (hors évaluation)")
    p_seq.add_argument("-f", "--format", choices=["md", "json", "skola"], default="md")
    p_seq.add_argument("-o", "--output", type=Path)

    p_skola = sub.add_parser("skola", help="Programmation annuelle et progression hebdomadaire pour Skola")
    p_skola.add_argument("niveau")
    p_skola.add_argument("-z", "--zone", default="B", help="Zone de vacances (A, B, C)")
    p_skola.add_argument("-a", "--annee")
    p_skola.add_argument("-d", "--discipline", action="append", help="Discipline à inclure (répétable ; toutes par défaut)")
    p_skola.add_argument("-f", "--format", choices=["json", "md", "csv"], default="json")
    p_skola.add_argument("-o", "--output", type=Path)

    p_ref = sub.add_parser("referentiel", help="Référentiel de compétences d'un niveau")
    p_ref.add_argument("niveau")
    p_ref.add_argument("-a", "--annee")
    p_ref.add_argument("-d", "--discipline", action="append", help="Discipline à inclure (répétable ; toutes par défaut)")
    p_ref.add_argument("-f", "--format", choices=["md", "json", "csv"], default="md")
    p_ref.add_argument("-o", "--output", type=Path)

    p_graph = sub.add_parser("graphe", help="Exporter le graphe (GraphML, pour Gephi ou yEd)")
    p_graph.add_argument("-o", "--output", type=Path, default=Path("edu-kb.graphml"))

    sub.add_parser("guides", help="Guides pédagogiques de la base locale")
    p_gday = sub.add_parser("guide-jour", help="Ce que prévoient les guides pour un jour de classe")
    p_gday.add_argument("date", nargs="?", help="2026-11-16 ou 16/11/2026 (défaut : aujourd'hui)")
    p_gday.add_argument("-z", "--zone", default="B", help="Zone de vacances (A, B, C)")
    p_gday.add_argument("-f", "--format", choices=["md", "json"], default="md")
    p_gprog = sub.add_parser("guide-progression", help="Progression des guides semaine par semaine")
    p_gprog.add_argument("-p", "--periode", type=int, help="Période 1 à 5 (défaut : toute l'année)")
    p_gprog.add_argument("-z", "--zone", default="B", help="Zone de vacances (A, B, C)")
    p_gprog.add_argument("-a", "--annee")
    p_gprog.add_argument("-f", "--format", choices=["md", "json"], default="md")
    p_gprog.add_argument("-o", "--output", type=Path)
    p_gsearch = sub.add_parser("guide-search", help="Chercher une séance dans les guides")
    p_gsearch.add_argument("query")
    p_gsearch.add_argument("-d", "--discipline")
    p_gsearch.add_argument("-p", "--periode", type=int)
    p_gsearch.add_argument("-k", "--limit", type=int, default=10)

    p_gexport = sub.add_parser("guides-export", help="Copier la base avec les guides (clé USB) pour un autre poste")
    p_gexport.add_argument("destination", type=Path, help="Fichier ou dossier (ex. /Volumes/CLE)")
    p_gexport.add_argument("--force", action="store_true", help="Remplacer le fichier s'il existe")
    p_gimport = sub.add_parser("guides-import", help="Installer une base avec les guides copiée depuis un autre poste")
    p_gimport.add_argument("fichier", type=Path)

    sub.add_parser("serve", help="Lancer le serveur MCP (stdio)")

    args = parser.parse_args(argv)
    settings = Settings.from_env()

    try:
        _run(args, settings)
    except ValueError as exc:
        sys.exit(f"Erreur : {exc}")


def _run(args: argparse.Namespace, settings: Settings) -> None:
    if args.cmd == "serve":
        from .server import main as serve

        serve()
        return
    if args.cmd == "download":
        from .download import download_base

        print(f"Téléchargement de {settings.base_url} → {settings.db_path}")
        with httpx.Client(timeout=120) as http:
            built_at = download_base(settings.base_url, settings.db_path, http)
        print(f"Base construite le {built_at} installée. Redémarre Claude s'il tournait.")
    elif args.cmd == "build":
        from .ingest import build

        target = settings.db_path
        published = settings.cache_dir.parent / "kb.sqlite"
        if args.guides:
            target = settings.guides_db_path
            if target.resolve() == published.resolve():
                raise ValueError(f"les guides des éditeurs n'entrent pas dans la base publiée ({published}) : "
                                 "choisis une autre base (EDU_KB_DB=~/.edu-kb/kb-guides.sqlite)")
        embedder = OllamaEmbedder(settings.ollama_url, settings.embed_model) if not args.no_embed else None
        kb = KnowledgeBase(target, embedder)
        print(f"Analyse de {settings.sources_file.name}" + (f" et {settings.guides_file.name}" if args.guides else "")
              + f" ({settings.programmes_dir}) → {target}")
        report = build(settings, kb, guides=args.guides)
        print(f"Graphe : {report['noeuds']} nœuds, {report['aretes']} arêtes, {report['sources']} sources"
              + (f", {len(report['guides'])} guides" if args.guides else "") + ".")
        if args.guides and published.exists():
            print(f"Vecteurs repris de {published} : {kb.import_embeddings(published)}")
        if not args.no_embed:
            _embed(kb)
    elif args.cmd == "embed":
        _embed(_kb(settings))
    elif args.cmd == "status":
        kb = _kb(settings, semantic=False)
        st = kb.stats()
        print(f"Base : {settings.db_path} · construite le {st['construit_le'] or 'jamais'} · {st['vecteurs']} vecteurs ({st['modele'] or 'aucun modèle'})")
        print("Nœuds : " + ", ".join(f"{k} {v}" for k, v in st["noeuds"].items()))
        print("Arêtes : " + ", ".join(f"{k} {v}" for k, v in st["aretes"].items()))
        if st["mentions_filtrees"]:
            print(f"Liens entre disciplines filtrés par le sens (similarité ≥ {st['mentions_filtrees']})")
        else:
            print("⚠ Liens entre disciplines non filtrés (lexicaux) : lance `edu-kb embed` avec Ollama démarré")
        year = school_year()
        print(f"\nTextes en vigueur en {year}-{year + 1} :")
        for level in ("CP", "CE1", "CE2", "CM1", "CM2"):
            print(f"  {level:4} " + ", ".join(s["source_id"] for s in kb.applicable_sources(level, year)))
    elif args.cmd == "search":
        from .server import format_search

        kb = _kb(settings)
        year = school_year(args.annee) if args.annee or args.niveau else None
        print(format_search(args.query, kb.search(args.query, args.niveau, args.discipline, year, limit=args.limit)))
    elif args.cmd == "fiche":
        from .guide_queries import card as guide_card
        from .guide_queries import has_guides

        kb = _kb(settings, semantic=False)
        year = school_year(args.annee)
        card = guide_card(kb, args.id, year) if has_guides(kb) else kb.item_card(args.id, year)
        print(json.dumps(card, ensure_ascii=False, indent=1) if card else f"Aucun nœud avec id={args.id}.")
    elif args.cmd == "themes":
        kb = _kb(settings, semantic=False)
        for t in kb.themes(args.niveau, args.discipline, school_year(args.annee)):
            periods = t.get("periodes_programme", {}).get("texte", "")
            print(f"- [{t['discipline']}] {t['domaine'] + ' › ' if t['domaine'] else ''}{t['theme']}" + (f" ({periods})" if periods else "") + f"\n  id={t['id']}")
    elif args.cmd == "programme":
        kb = _kb(settings, semantic=False)
        for row in kb.outline(args.niveau, args.discipline, school_year(args.annee)):
            print(f"- {row['contexte']}\n    {row['titre']}\n    id={row['id']}")
    elif args.cmd == "sequence":
        from . import sequence as seq_mod

        data = seq_mod.prepare(_kb(settings), args.notion, args.niveau, school_year(args.annee), args.discipline, args.seances)
        if args.format == "md":
            _write(seq_mod.to_markdown(data), args.output)
        else:
            payload = data if args.format == "json" else seq_mod.to_skola(data)
            _write(json.dumps(payload, ensure_ascii=False, indent=2), args.output)
    elif args.cmd == "skola":
        from . import skola
        from .planning import build_plan

        kb = _kb(settings, semantic=False)
        plan = build_plan(kb, settings.calendar_file, args.niveau, school_year(args.annee), args.zone, args.discipline)
        data = skola.export(kb, plan)
        render = {"json": skola.to_json, "md": skola.to_markdown, "csv": skola.to_csv}[args.format]
        _write(render(data), args.output)
    elif args.cmd == "referentiel":
        from . import referentiel

        data = referentiel.build(_kb(settings, semantic=False), args.niveau, school_year(args.annee), args.discipline)
        render = {"md": referentiel.to_markdown, "csv": referentiel.to_csv,
                  "json": lambda d: json.dumps(d, ensure_ascii=False, indent=2)}[args.format]
        _write(render(data), args.output)
    elif args.cmd in ("guides", "guide-jour", "guide-progression", "guide-search"):
        from . import guide_queries as gq

        kb = _guides_kb(settings, semantic=args.cmd == "guide-search")
        if args.cmd == "guides":
            print(json.dumps(gq.guides(kb), ensure_ascii=False, indent=1))
        elif args.cmd == "guide-jour":
            plan = gq.day_plan(kb, settings.calendar_file, gq.parse_date(args.date), args.zone)
            print(gq.day_markdown(plan) if args.format == "md" else json.dumps(plan, ensure_ascii=False, indent=1))
        elif args.cmd == "guide-progression":
            plan = gq.period_plan(kb, settings.calendar_file, school_year(args.annee), args.zone, args.periode)
            _write(gq.period_markdown(plan) if args.format == "md" else json.dumps(plan, ensure_ascii=False, indent=1), args.output)
        else:
            print(gq.search_markdown(args.query, gq.search(kb, args.query, args.discipline, args.periode, args.limit)))
    elif args.cmd in ("guides-export", "guides-import"):
        from .transfer import TransferError, export_base, import_base

        published = settings.cache_dir.parent / "kb.sqlite"
        try:
            if args.cmd == "guides-export":
                guides = export_base(settings.guides_db_path, args.destination, args.force)
                print(f"Base exportée vers {args.destination} ({', '.join(guides)}).\n"
                      "Sur l'autre poste : uv run edu-kb guides-import <fichier>")
            else:
                built_at, guides = import_base(args.fichier, settings.guides_db_path, published)
                print(f"Base construite le {built_at} installée en {settings.guides_db_path} ({', '.join(guides)}).\n"
                      "Pour Claude (outils des guides, à côté du serveur edu-kb des programmes) : "
                      f"claude mcp add --scope user edu-kb-guides -e EDU_KB_DB={settings.guides_db_path} "
                      "-- uv --directory <dépôt edu-kb> run edu-kb serve")
        except TransferError as exc:
            raise ValueError(str(exc)) from exc
    elif args.cmd == "graphe":
        from .export import graphml

        _write(graphml(_kb(settings, semantic=False)), args.output)


if __name__ == "__main__":
    main()
