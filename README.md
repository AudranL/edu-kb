# edu-kb

> **🚧 Projet en cours de développement (WIP).** Les outils, les formats de sortie et les données
> extraites peuvent encore changer. Certaines règles (par exemple le classement « en continu » du
> français) n'ont pas été validées par un enseignant, et les années d'application des programmes
> restent à vérifier sur eduscol avant tout usage officiel.

Graphe de connaissance des programmes officiels de l'école élémentaire (CP → CM2, plus la 6e pour
le cycle 3), construit à partir des PDF du ministère et mis à disposition de Claude par un serveur
MCP local. Il sert à :

- préparer une **séquence et ses séances à partir d'une notion** (objectifs, compétences, critères
  de réussite, thèmes, prérequis, prolongements, liens entre disciplines, sources) ;
- donner, pour **chaque item du programme, ses compétences** et, quand ils existent, ses **thèmes** ;
- produire pour **Skola** une **programmation annuelle** (par période) et une **progression
  hebdomadaire**.

👉 Mode d'emploi par usage, avec des exemples : [docs/guide.md](docs/guide.md).

```
Programmes/*.pdf ──build──▶ SQLite : nœuds, arêtes, index FTS5, vecteurs ◀──MCP stdio── Claude
  sources.toml (structure de chaque PDF)          ▲
  calendrier.toml (périodes, semaines)       Ollama (bge-m3)
```

## Installation (macOS)

```bash
git clone https://github.com/AudranL/edu-kb.git && cd edu-kb
./scripts/setup.sh
```

Rien à reconstruire : le script **télécharge la base publiée** (dernière release GitHub) dans
`~/.edu-kb/kb.sqlite`. Il installe aussi `uv` et `ollama` s'ils manquent et télécharge `bge-m3`,
qui sert à la recherche sémantique (sans Ollama, le serveur répond quand même, en plein texte
seulement), déclare le serveur MCP dans Claude Code et Claude Desktop (la config existante est
sauvegardée en `.bak`) et affiche les textes en vigueur par niveau.

Pour mettre la base à jour : `git pull && ./scripts/setup.sh`, puis redémarre Claude.

### Reconstruire et publier la base

Les PDF des programmes sont dans `Programmes/` (un sous-dossier par niveau, les doublons sont
ignorés) : ce sont les textes officiels du ministère, reproduits sans modification, avec leur BO
dans `sources.toml`. Après avoir ajouté ou corrigé un programme :

```bash
./scripts/setup.sh --build     # analyse les PDF et reconstruit ~/.edu-kb/kb.sqlite
./scripts/publier-base.sh      # la publie en release GitHub (depuis main à jour sur GitHub, gh connecté)
```

`--build` installe en plus `ocrmypdf` et `tesseract-lang` : les programmes de sciences de 2026 sont
publiés **scannés** et passent par l'OCR (mis en cache).

## Le graphe

| Nœud | Contenu |
|---|---|
| `source` | un programme (ou une partie d'un programme de cycle), son BO, ses années d'application par niveau |
| `discipline`, `niveau`, `cycle` | Français, Mathématiques, EMC… ; CP → 6e |
| `domaine`, `rubrique`, `sous_rubrique` | la structure du texte (Lecture › Identifier les mots…) |
| `theme` | thèmes d'histoire-géographie, de sciences, axes d'EMC, questionnements d'arts plastiques, culture littéraire au cycle 3 |
| `item` | une ligne de tableau du programme, avec tous ses champs : objectifs (et leur moment : « en fin de période 1 »…), exemples de réussite, attendus, repères, démarches proposées… |
| `objectif` | chaque objectif d'apprentissage |
| `competence` | compétences travaillées du cycle (anciens programmes encore en vigueur) |
| `socle` | domaines du socle commun D1.1 → D5 |
| `notion` | mots-clés des thèmes d'histoire-géographie |

Arêtes : `contient` (hiérarchie), `niveau`, `discipline`, `theme`, `suite` (même rubrique au
niveau suivant : progression), `competence`, `socle`, `mot_cle`, `mentionne` (une notion d'histoire-
géographie citée dans une autre discipline), `s_applique` (programme → niveau, avec les années).

**Quel texte pour quelle année ?** Les programmes changent par niveau et par rentrée. Chaque source
déclare dans `sources.toml` les niveaux et les années où elle s'applique ; toutes les requêtes
prennent une année scolaire (par défaut l'année en cours). En 2026-2027 :

| | Français, maths | EMC | Sciences, HG, EPS, langues vivantes | Arts plastiques, musique |
|---|---|---|---|---|
| CP | 2024 | 2024 | **2026** | 2020 |
| CE1, CE2 | 2024 | 2024 | HG et sciences **2026** (*Questionner le monde* n'existe plus) ; EPS et langues vivantes 2020 jusqu'à la rentrée 2027 | 2020 |
| CM1 | 2025 | 2024 | **2026** | 2020 |
| CM2 | 2025 | 2024 | 2020 / sciences 2023 — nouveaux textes à la rentrée 2027 | 2020 |

Ces dates viennent d'une synthèse des arrêtés (direkol.fr, 29 août 2026) : vérifie-les sur
eduscol (« Enseigner au cycle 2 / 3 ») et corrige `applies` dans `sources.toml` au besoin.

## Ce que Claude obtient (MCP)

| Outil | Rôle |
|---|---|
| `chercher(notion, niveau, discipline, annee)` | recherche hybride (FTS5 + bge-m3, fusion RRF) dans les items, objectifs, thèmes |
| `fiche(id, annee)` | un item complet : objectifs et moments, **compétences** (attendus de l'item, compétences du cycle, socle), **thèmes**, progression d'un niveau à l'autre, liens entre disciplines, source (BO, page) |
| `themes(niveau, discipline, annee)` | les thèmes d'un niveau, avec les périodes conseillées par le programme |
| `programme(niveau, discipline, annee)` | le programme d'une discipline pour un niveau |
| `progression_notion(notion)` | une notion du CP à la 6e |
| `preparer_sequence(notion, niveau, …, format)` | séquence et squelette de séances, en Markdown, JSON ou **format Skola** |
| `programmation(niveau, zone, annee)` | programmation annuelle et progression hebdomadaire |
| `referentiel(niveau, discipline, annee, format)` | **référentiel de compétences** d'un niveau : toutes les compétences des programmes en vigueur par discipline et domaine, avec échéances, critères de réussite, socle, page (Markdown à cocher, JSON ou CSV) |
| `sources(niveau, annee)` | textes en vigueur |
| Prompts `sequence`, `programmation_annuelle` | rédaction complète par Claude, fidèle au programme |

## Commandes

| Commande | Rôle |
|---|---|
| `edu-kb download` | télécharge la base publiée (dernière release GitHub) au lieu de la reconstruire |
| `edu-kb build [--no-embed]` | analyse les PDF de `sources.toml` et reconstruit le graphe |
| `edu-kb embed` | calcule les embeddings manquants |
| `edu-kb status` | état de la base, textes en vigueur par niveau |
| `edu-kb search "fractions" -n CE2` | tester une recherche |
| `edu-kb fiche <id>` | fiche JSON d'un item |
| `edu-kb themes CM1 [-d hg]` | thèmes d'un niveau |
| `edu-kb programme CE1 maths` | programme d'une discipline |
| `edu-kb sequence "le Moyen Âge" -n CM1 [-s 6] [-f md\|json\|skola] [-o fichier]` | préparer une séquence |
| `edu-kb referentiel CP [-d maths] [-f md\|json\|csv] [-o fichier]` | référentiel de compétences d'un niveau |
| `edu-kb skola CE1 -z B [-f json\|md\|csv] [-o fichier]` | programmation + progression pour Skola |
| `edu-kb graphe -o programmes.graphml` | exporter le graphe (Gephi, yEd) |
| `edu-kb serve` | serveur MCP (stdio), lancé par Claude |

Variables : `EDU_KB_HOME` (défaut `~/.edu-kb`), `EDU_KB_DB`, `EDU_KB_PROGRAMMES`, `EDU_KB_SOURCES`,
`EDU_KB_CALENDRIER`, `OLLAMA_URL`, `EDU_KB_EMBED_MODEL` (défaut `bge-m3`), `EDU_KB_BASE_URL` (défaut :
la base de la dernière release GitHub).

## Export Skola

`edu-kb skola CE1 -z B -o programmation-ce1.json` produit un JSON dont les clés reprennent les
tables de Skola : `subjects` (nom, couleur), `sequences` (une par unité : objectifs, compétences,
description, évaluation) et `programmation_items` (matière, période, titre, domaine, statut,
`sequence_ref`). Les matières sont désignées par leur nom et les séquences par une référence, car
les identifiants n'existent qu'une fois les lignes créées. Il ajoute ce que Skola ne stocke pas :
`calendrier` (périodes et semaines de la zone), `semaines` de chaque item et `progression`
(semaine par semaine : unités et objectifs). `-f md` et `-f csv` en donnent une version lisible.

**Limites de Skola aujourd'hui** : il n'a pas de fonction d'import (seulement la restauration d'une
sauvegarde complète), et `programmation_items` n'a pas de colonne pour la semaine. Pour exploiter
ce fichier dans l'application, il faut y ajouter un import (cf. `BKL-02` de son backlog) et, pour la
progression hebdomadaire, une colonne `week` ou une table dédiée.

**Comment la programmation est construite.** Les périodes imposées par le programme sont respectées
(thèmes d'histoire-géographie « deuxième et troisième périodes », « 1 ou 2 périodes au choix » ;
objectifs de français « en fin de période 1 », « en milieu d'année » convertis en périodes de
travail). Le reste est réparti dans l'ordre du programme, au prorata des semaines. Le français, les
langues vivantes et l'éducation musicale sont travaillés en continu (toutes les rubriques chaque
période) ; les autres disciplines enchaînent leurs unités. Le champ `origine` dit d'où vient chaque
placement : c'est une proposition à ajuster.

**Travaillé en continu.** Les objectifs que le programme dit travaillés toute l'année (« tout au long
de l'année », « au cours des périodes 1 à 5 »), ou qui n'ont aucune échéance dans le français, les
langues vivantes et l'éducation musicale, sont listés une fois dans une section « Travaillé en
continu » (clé `en_continu` du JSON). Ils ne sont pas répétés dans le tableau annuel ni dans la
progression hebdomadaire.

## Ajouter ou corriger un programme

Chaque PDF (ou partie de PDF) est décrit dans `sources.toml` : fichier, discipline, niveaux et années
d'application, pages, et **règles de titres** (signature de style « taille/gras/couleur » et rang).
Pour les écrire, regarde les styles du PDF :

```bash
uv run python -c "from edu_kb.extract import read_lines; from pathlib import Path; import sys; \
[print(l.page, l.style, round(l.x0), l.text[:80]) for l in read_lines(Path(sys.argv[1]))]" fichier.pdf | sort -k2 | uniq -c -f1
```

Le reste est générique : tableaux reconnus à leur ligne d'en-tête (« Objectifs d'apprentissage »,
« Exemples de réussite », « Attendus », « Repères »…), grilles reconstituées à partir des traits du
PDF, puces, marqueurs temporels, fractions composées en hauteur, numéros de page.

## Limites connues

- La recherche (`chercher`) filtre par niveau avant de classer et ne renvoie rien quand la notion n'est
  pas dans le programme. Elle n'interroge pas les mots-clés des thèmes (« caravelle »).
- Voir l'[évaluation des outils](docs/evaluation-outils.md) pour le détail.
- Les **mathématiques n'ont pas de thèmes** (domaines et rubriques seulement) ; le français n'en a
  qu'au cycle 3 (culture littéraire et artistique) ; l'EPS a des champs d'apprentissage.
- Les programmes 2024-2026 n'ont plus de tableau « compétences travaillées » par discipline : les
  compétences d'un item sont ses **exemples de réussite / attendus**, complétés des domaines du
  socle (correspondance indicative, d'après le volet 2 des programmes 2020). Les maths du cycle 3
  renvoient leurs exemples de réussite à Eduscol : ils ne sont pas dans le texte.
- Le cycle 1 (maternelle) n'est pas inclus : aucun PDF fourni.
- Le calendrier 2026-2027 vient de sources publiques (Onisep, franceinfo) : vérifie-le sur
  education.gouv.fr. Ajoute une année dans `calendrier.toml` pour la rentrée suivante.

## Développement

```bash
uv run pytest
```

Les tests génèrent un mini-programme PDF (titres stylés, tableau tracé, moments, thème avec ses
périodes) et vérifient toute la chaîne : extraction, arbre, graphe, recherche, planification, export.
