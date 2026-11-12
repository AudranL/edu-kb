"""Serveur MCP (stdio) exposant le graphe des programmes de l'école élémentaire."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from . import guide_queries as gq
from . import referentiel as ref_mod
from . import sequence as seq_mod
from .config import Settings
from .embed import OllamaEmbedder
from .kb import KnowledgeBase, SearchResult, school_year
from .planning import build_plan
from .skola import export as skola_export
from .skola import to_markdown as skola_markdown

INSTRUCTIONS = """\
Graphe de connaissance des programmes officiels de l'école élémentaire (CP → CM2, et 6e pour le
cycle 3) : français, mathématiques, langues vivantes, EPS, EMC, EVAR, histoire-géographie,
sciences et technologie, arts plastiques, éducation musicale, histoire des arts (Questionner le monde,
remplacé à la rentrée 2026 par l'histoire-géographie et les sciences, n'est gardé que pour mémoire).
Chaque item du programme est relié à son niveau, sa discipline, son thème, ses compétences, au
même item du niveau précédent et suivant, et au texte officiel (BO, page) qui s'applique pour une
année scolaire donnée (certains programmes changent à la rentrée 2026 ou 2027 selon le niveau).

Pour préparer une séquence : `preparer_sequence` (ou `chercher` puis `fiche`). Pour connaître les
thèmes d'un niveau : `themes`. Pour la liste des compétences d'un niveau : `referentiel`. Pour une programmation : `programmation`. Cite toujours la source
(programme, BO, page) et distingue ce qui vient du programme de tes propres propositions."""


PROGRESSION_MARGIN = 0.1


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def format_search(query: str, result: SearchResult) -> str:
    lines = [f"Recherche « {query} » — mode {result.mode}, {len(result.hits)} résultat(s)."]
    if result.warning:
        lines.append(f"⚠ {result.warning}")
    if not result.hits:
        lines.append("Aucun résultat. Essaie un synonyme, un autre niveau, ou sans filtre de discipline.")
    for i, h in enumerate(result.hits, 1):
        where = f" · {h.source_id} p. {h.page}" if h.page else f" · {h.source_id}"
        lines.append(f"\n[{i}] {h.kind} · {h.discipline} · {', '.join(h.levels)}{where}\nid={h.id}\n{h.context}\n→ {h.title}")
    return "\n".join(lines)


GUIDES_INSTRUCTIONS = """

Cette base contient aussi les guides pédagogiques des méthodes suivies en classe (`guides`) : en
français, chaque jour de classe détaillé en plusieurs séances ; en maths, une séquence par semaine
et une séance par jour. Pour « que faire tel jour » : `seances_du_jour` ; pour une période semaine par
semaine : `progression_guides` ; pour trouver une séance : `chercher_guide` ; le déroulé complet et les
objectifs du programme travaillés : `fiche` avec l'id d'une séance. La fiche d'un item du programme
liste les séances des guides qui le travaillent (« dans_les_guides »). Distingue ce que dit le guide,
ce que dit le programme et tes propres propositions."""


def create_server(kb: KnowledgeBase, calendar_file: Path) -> MCPServer:
    with_guides = gq.has_guides(kb)
    server = MCPServer(name="edu-kb", instructions=INSTRUCTIONS + (GUIDES_INSTRUCTIONS if with_guides else ""))

    @server.tool(description="Recherche hybride (plein texte + sémantique) d'une notion dans les programmes : items, objectifs, thèmes.")
    def chercher(
        notion: Annotated[str, Field(description="Notion, compétence ou mots-clés (ex. « fractions », « le Moyen Âge »)")],
        niveau: Annotated[str | None, Field(description="CP, CE1, CE2, CM1, CM2 ou 6e")] = None,
        discipline: Annotated[str | None, Field(description="Ex. Français, maths, HG, sciences, EMC, EPS, arts…")] = None,
        annee: Annotated[str | None, Field(description="Année scolaire (2026-2027) : ne garde que les programmes en vigueur")] = None,
        limite: Annotated[int, Field(ge=1, le=30)] = 10,
    ) -> str:
        year = school_year(annee) if annee or niveau else None
        return format_search(notion, kb.search(notion, level=niveau, discipline=discipline, year=year, limit=limite))

    @server.tool(description=(
        "Fiche complète d'un item (ou objectif, thème) : objectifs avec leur moment dans l'année, compétences "
        "(attendus, exemples de réussite, compétences du cycle, socle commun), thèmes, progression d'un niveau "
        "à l'autre, liens avec les autres disciplines, source officielle."))
    def fiche(
        id: Annotated[str, Field(description="id renvoyé par chercher, themes ou programme")],
        annee: Annotated[str | None, Field(description="Année scolaire, pour les liens entre disciplines")] = None,
    ) -> str:
        year = school_year(annee)
        card = gq.card(kb, id, year) if with_guides else kb.item_card(id, year)
        return _json(card) if card else f"Aucun nœud avec id={id}."

    @server.tool(description=(
        "Thèmes d'un niveau quand le programme en définit : histoire-géographie (avec les périodes conseillées), "
        "sciences et technologie, EMC (thème de l'année et axes), arts plastiques (questionnements), "
        "culture littéraire en français au cycle 3. Les mathématiques n'ont pas de thèmes."))
    def themes(
        niveau: Annotated[str, Field(description="CP, CE1, CE2, CM1, CM2 ou 6e")],
        discipline: Annotated[str | None, Field(description="Filtre facultatif")] = None,
        annee: Annotated[str | None, Field(description="Année scolaire (par défaut l'année en cours)")] = None,
    ) -> str:
        return _json(kb.themes(niveau, discipline, school_year(annee)))

    @server.tool(description="Le programme d'une discipline pour un niveau : liste ordonnée des items (contexte, id, périodes).")
    def programme(
        niveau: Annotated[str, Field(description="CP, CE1, CE2, CM1, CM2 ou 6e")],
        discipline: Annotated[str, Field(description="Ex. Français, Mathématiques, EMC…")],
        annee: Annotated[str | None, Field(description="Année scolaire (par défaut l'année en cours)")] = None,
    ) -> str:
        return _json(kb.outline(niveau, discipline, school_year(annee)))

    @server.tool(description="Comment une notion progresse du CP à la 6e : résultats de recherche regroupés par niveau.")
    def progression_notion(
        notion: Annotated[str, Field(description="Notion à suivre d'un niveau à l'autre")],
        discipline: Annotated[str | None, Field(description="Filtre facultatif")] = None,
    ) -> str:
        # marge plus large : sans filtre de niveau, on veut voir la notion à chaque niveau, pas seulement le meilleur
        res = kb.search(notion, discipline=discipline, kinds=("item", "theme"), limit=40, margin=PROGRESSION_MARGIN)
        by_level: dict[str, list] = {}
        for h in res.hits:
            for lv in h.levels:
                by_level.setdefault(lv, []).append({"id": h.id, "discipline": h.discipline, "source": h.source_id,
                                                    "contexte": h.context, "titre": h.title})
        order = ["CP", "CE1", "CE2", "CM1", "CM2", "6e"]
        return _json({lv: by_level[lv] for lv in order if lv in by_level})

    @server.tool(description=(
        "Prépare une séquence à partir d'une notion pour un niveau : objectifs du programme, compétences, "
        "critères de réussite, thèmes, pistes d'activités, prérequis et prolongements, liens interdisciplinaires, "
        "et un squelette de séances. format=skola renvoie la séquence et les fiches au format des tables Skola."))
    def preparer_sequence(
        notion: Annotated[str, Field(description="Notion à enseigner")],
        niveau: Annotated[str, Field(description="CP, CE1, CE2, CM1, CM2 ou 6e")],
        discipline: Annotated[str | None, Field(description="Discipline (sinon celle du meilleur résultat)")] = None,
        nb_seances: Annotated[int | None, Field(ge=1, le=20, description="Nombre de séances souhaité (hors évaluation)")] = None,
        annee: Annotated[str | None, Field(description="Année scolaire (par défaut l'année en cours)")] = None,
        format: Annotated[str, Field(description="markdown, json ou skola")] = "markdown",
    ) -> str:
        data = seq_mod.prepare(kb, notion, niveau, school_year(annee), discipline, nb_seances)
        if format == "json":
            return _json(data)
        if format == "skola":
            return _json(seq_mod.to_skola(data))
        return seq_mod.to_markdown(data)

    @server.tool(description=(
        "Programmation annuelle et progression hebdomadaire d'un niveau (calendrier de la zone). Renvoie la "
        "version lisible ; l'export JSON pour Skola se fait avec `edu-kb skola`."))
    def programmation(
        niveau: Annotated[str, Field(description="CP, CE1, CE2, CM1, CM2")],
        zone: Annotated[str, Field(description="Zone de vacances : A, B ou C")] = "B",
        annee: Annotated[str | None, Field(description="Année scolaire (par défaut l'année en cours)")] = None,
        disciplines: Annotated[list[str] | None, Field(description="Disciplines à inclure (toutes par défaut)")] = None,
    ) -> str:
        plan = build_plan(kb, calendar_file, niveau, school_year(annee), zone, disciplines)
        return skola_markdown(skola_export(kb, plan))

    @server.tool(description="Programmes officiels pris en compte et leur application par niveau et par année scolaire.")
    def sources(
        niveau: Annotated[str | None, Field(description="Filtre : seulement les textes en vigueur pour ce niveau")] = None,
        annee: Annotated[str | None, Field(description="Année scolaire (par défaut l'année en cours)")] = None,
    ) -> str:
        year = school_year(annee)
        rows = kb.applicable_sources(niveau, year) if niveau else kb.sources()
        return _json([{"id": s["source_id"], "titre": s["title"], "discipline": s["discipline"], "bo": s["data"].get("bo"),
                       "application": s["data"].get("application")} for s in rows])

    @server.tool(description=(
        "Référentiel de compétences d'un niveau : toutes les compétences des programmes en vigueur, par discipline "
        "puis par domaine, avec échéance, critères de réussite, socle commun, page et BO. Sert de grille d'évaluation "
        "ou de suivi des acquis. format=md (liste à cocher), json ou csv."))
    def referentiel(
        niveau: Annotated[str, Field(description="CP, CE1, CE2, CM1, CM2 ou 6e")],
        discipline: Annotated[str | None, Field(description="Une discipline (ex. Français, maths) ; toutes par défaut")] = None,
        annee: Annotated[str | None, Field(description="Année scolaire (par défaut l'année en cours)")] = None,
        format: Annotated[str, Field(description="md, json ou csv")] = "md",
    ) -> str:
        data = ref_mod.build(kb, niveau, school_year(annee), [discipline] if discipline else None)
        if format == "json":
            return _json(data)
        return ref_mod.to_csv(data) if format == "csv" else ref_mod.to_markdown(data)

    if with_guides:
        _guide_tools(server, kb, calendar_file)

    @server.prompt(name="sequence", title="Préparer une séquence",
                   description="Séquence complète et ses séances à partir d'une notion, fidèle au programme.")
    def sequence_prompt(notion: str, niveau: str, discipline: str = "", nb_seances: str = "") -> str:
        extra = f", discipline « {discipline} »" if discipline else ""
        count = f" en {nb_seances} séances" if nb_seances else ""
        return f"""Prépare une séquence sur **{notion}** pour une classe de **{niveau}**{extra}{count}.

1. Appelle `preparer_sequence` (format json) ; si le résultat est pauvre, complète avec `chercher` puis `fiche`.
2. Rédige la séquence : titre, place dans l'année (périodes indiquées par le programme), objectifs
   (repris du programme, mot pour mot), compétences et domaines du socle, prérequis, évaluation.
3. Pour chaque séance : objectif, durée, matériel, déroulé en phases (durée, modalité, rôle de l'enseignant,
   rôle des élèves), trace écrite, différenciation, critères de réussite issus des exemples de réussite ou
   des attendus du programme.
4. Propose un ou deux liens avec d'autres disciplines quand le graphe en signale.
5. Termine par les sources (programme, BO, page).

Sépare clairement ce qui est cité du programme de tes propositions pédagogiques. Si l'utilisateur veut
l'importer dans Skola, fournis aussi le JSON (`preparer_sequence` format skola, complété de tes déroulés)."""

    @server.prompt(name="programmation_annuelle", title="Programmation annuelle",
                   description="Programmation par période et progression par semaine pour un niveau.")
    def programmation_prompt(niveau: str, zone: str = "B") -> str:
        return f"""Construis la programmation annuelle et la progression hebdomadaire d'une classe de **{niveau}** (zone {zone}).

1. Appelle `sources` pour savoir quels programmes s'appliquent cette année à ce niveau, puis `programmation`.
2. Vérifie les périodes imposées par le programme (thèmes d'histoire-géographie, échéances en français)
   et signale les répartitions qui ne sont qu'une proposition.
3. Présente un tableau disciplines × périodes, puis la progression semaine par semaine.
4. Rappelle que l'export pour Skola se fait avec `edu-kb skola {niveau} --zone {zone} -o programmation.json`."""

    return server


def _guide_tools(server: MCPServer, kb: KnowledgeBase, calendar_file: Path) -> None:
    """Outils des guides pédagogiques (base locale construite avec `edu-kb build --guides`)."""

    @server.tool(description="Guides pédagogiques indexés (méthodes suivies en classe) : rythme, périodes, séquences ou leçons.")
    def guides() -> str:
        return _json(gq.guides(kb))

    @server.tool(description=(
        "Recherche une notion dans les séances des guides pédagogiques (plein texte + sens). Renvoie des ids "
        "de séances ou de séquences : `fiche` donne le déroulé complet et les objectifs du programme travaillés."))
    def chercher_guide(
        notion: Annotated[str, Field(description="Notion, activité ou graphème (ex. « le son ch », « dictée de syllabes », « monnaie »)")],
        discipline: Annotated[str | None, Field(description="Français ou maths")] = None,
        periode: Annotated[int | None, Field(ge=1, le=5, description="Période 1 à 5")] = None,
        limite: Annotated[int, Field(ge=1, le=30)] = 10,
    ) -> str:
        return gq.search_markdown(notion, gq.search(kb, notion, discipline, periode, limite))

    @server.tool(description=(
        "Ce que prévoient les guides pour un jour de classe : la séquence de maths de la semaine et ses séances du "
        "jour, la leçon de français et ses séances, d'après le calendrier scolaire de la zone."))
    def seances_du_jour(
        date: Annotated[str | None, Field(description="2026-11-16 ou 16/11/2026 (par défaut aujourd'hui)")] = None,
        zone: Annotated[str, Field(description="Zone de vacances : A, B ou C")] = "B",
        format: Annotated[str, Field(description="markdown ou json")] = "markdown",
    ) -> str:
        plan = gq.day_plan(kb, calendar_file, gq.parse_date(date), zone)
        return _json(plan) if format == "json" else gq.day_markdown(plan)

    @server.tool(description=(
        "Progression des guides semaine par semaine (séquence de maths, leçon de français de chaque jour) pour une "
        "période ou toute l'année, avec les jours sans contenu prévu et ce qui reste à placer."))
    def progression_guides(
        periode: Annotated[int | None, Field(ge=1, le=5, description="Période 1 à 5 (toute l'année par défaut)")] = None,
        zone: Annotated[str, Field(description="Zone de vacances : A, B ou C")] = "B",
        annee: Annotated[str | None, Field(description="Année scolaire (par défaut l'année en cours)")] = None,
        format: Annotated[str, Field(description="markdown ou json")] = "markdown",
    ) -> str:
        plan = gq.period_plan(kb, calendar_file, school_year(annee), zone, periode)
        return _json(plan) if format == "json" else gq.period_markdown(plan)


def main() -> None:
    settings = Settings.from_env()
    kb = KnowledgeBase(settings.db_path, OllamaEmbedder(settings.ollama_url, settings.embed_model))
    create_server(kb, settings.calendar_file).run("stdio")
