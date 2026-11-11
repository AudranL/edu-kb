# Guide d'utilisation d'edu-kb

edu-kb rassemble les programmes officiels de l'école élémentaire dans un graphe que tu interroges de
deux façons : **en parlant à Claude** (Claude Code ou Claude Desktop, via le serveur MCP `edu-kb`) ou
**en ligne de commande** (`uv run edu-kb …` depuis le dossier du projet). Les deux donnent les mêmes
informations ; Claude ajoute la rédaction (déroulés de séances, reformulations), la ligne de
commande produit des fichiers (JSON pour Skola, Markdown, CSV).

Tout reste sur ta machine : la base est dans `~/.edu-kb/kb.sqlite`.

---

## 1. Ce que contient la base

- **Les programmes en vigueur, niveau par niveau et année par année.** Un même niveau peut relever de
  textes de 2020, 2024, 2025 ou 2026 selon la discipline ; edu-kb sait lequel s'applique. Pour le
  voir :

  ```bash
  uv run edu-kb status
  ```

  ```
  Textes en vigueur en 2026-2027 :
    CE1  c2-2020-arts-plastiques, c2-2020-education-musicale, c2-2020-eps, c2-2020-lv, emc-2024,
         evar-2025, francais-c2-2024, hg-c2-2026, maths-c2-2024, sciences-c2-2026
  ```

  Par défaut, tout est filtré sur l'année scolaire en cours ; l'option `-a 2027-2028` (ou « pour
  l'an prochain » dans une demande à Claude) interroge une autre année.

- **Chaque ligne des tableaux du programme** (un « item ») avec tous ses champs, cités mot pour mot :
  objectifs d'apprentissage et leur moment dans l'année (« en fin de période 1 », « en milieu
  d'année »), exemples de réussite, attendus, repères, propositions de démarches, notions, et la page
  du PDF d'où ils viennent.

- **Les thèmes, quand le programme en définit** : histoire-géographie (avec les périodes conseillées),
  sciences et technologie, EMC (thème de l'année et axes), arts plastiques (questionnements), culture
  littéraire au cycle 3. Les mathématiques n'ont pas de thèmes.

- **Les compétences de chaque item** : ses attendus ou exemples de réussite, les compétences
  travaillées du cycle quand le texte en donne, les domaines du socle commun.

- **Les liens** : même rubrique au niveau précédent et suivant (progression du CP à la 6e), notions
  partagées entre disciplines.

---

## 2. Avec Claude

Le serveur `edu-kb` est branché sur Claude Code et Claude Desktop (redémarre Desktop la première
fois). Tu parles normalement ; Claude choisit les outils. Exemples de demandes :

| Tu veux… | Demande |
|---|---|
| préparer une séquence | « Prépare une séquence de 6 séances sur la lecture de l'heure en CE1. » |
| la même, prête pour Skola | « …et donne-la au format Skola. » |
| savoir ce que dit le programme | « Que dit le programme de CM1 sur les fractions décimales ? » |
| les compétences d'une notion | « Quelles compétences et quels critères de réussite pour l'accord sujet-verbe en CE2 ? » |
| le référentiel de compétences | « Donne-moi le référentiel de compétences du CP en français et en maths. » |
| les thèmes d'un niveau | « Quels sont les thèmes d'histoire et de géographie en CE2, et sur quelles périodes ? » |
| une progression sur plusieurs niveaux | « Comment évolue l'étude des durées du CP à la 6e ? » |
| des liens entre disciplines | « Avec quoi puis-je relier le thème sur Rome en CE2 dans les autres disciplines ? » |
| une programmation | « Fais-moi la programmation annuelle de CM1, zone B. » |
| vérifier un texte | « Quel programme d'EPS s'applique en CE2 cette année ? » |

Deux prompts guidés sont aussi disponibles dans Claude Code (tape `/` puis cherche `edu-kb`) :

- `/mcp__edu-kb__sequence` — notion, niveau, discipline, nombre de séances : séquence complète, avec
  séances détaillées (durée, matériel, phases, différenciation, trace écrite).
- `/mcp__edu-kb__programmation_annuelle` — niveau et zone.

Claude doit distinguer ce qui est **cité du programme** (objectifs, attendus, exemples de réussite,
avec la source) de **ses propres propositions** (déroulés, activités). Si ce n'est pas clair dans une
réponse, demande-lui de le préciser.

Outils MCP disponibles, si tu veux les nommer : `chercher`, `fiche`, `themes`, `programme`,
`progression_notion`, `preparer_sequence`, `programmation`, `referentiel`, `sources`. Un appel exact par outil, avec
sa réponse complète, et une séquence rédigée de bout en bout : [docs/exemples](exemples/README.md).

---

## 3. En ligne de commande

Toutes les commandes se lancent depuis le dossier du projet avec `uv run edu-kb …`. Options communes :
`-n` niveau (CP, CE1, CE2, CM1, CM2, 6e), `-d` discipline (accepte `maths`, `français`, `hg`,
`sciences`, `emc`, `eps`, `lv`, `arts`, `musique`…), `-a` année scolaire, `-o` fichier de sortie.

### Trouver une notion dans le programme

```bash
uv run edu-kb search "lire l'heure" -n CE1
```

```
[1] objectif · Mathématiques · CE1 · maths-c2-2024 p. 28
id=maths-c2-2024/grandeurs-et-mesures/cours-elementaire-premiere-annee/le-reperage-dans-le-temps-et-les-durees#i1/o1
Grandeurs et mesures › Cours élémentaire première année › Le repérage dans le temps et les durées
→ Lire l'heure sur une horloge à aiguilles (lorsque l'heure est donnée en heures entières, …).
```

La recherche comprend les synonymes et les formulations proches (recherche sémantique) ; sans
niveau, elle couvre tous les niveaux.

### Lire la fiche complète d'un item

```bash
uv run edu-kb fiche "maths-c2-2024/grandeurs-et-mesures/cours-elementaire-premiere-annee/le-reperage-dans-le-temps-et-les-durees#i1"
```

Elle donne, en JSON :

- `objectifs` : les objectifs, avec leur moment dans l'année quand le programme en indique ;
- `champs` : tous les champs du tableau (exemples de réussite, attendus, repères…) ;
- `competences` : attendus de l'item, compétences travaillées du cycle, domaines du socle ;
- `themes` : le thème englobant, sa question, ses mots-clés, ses périodes ;
- `progression` : la même rubrique aux niveaux d'avant et d'après (ici CE2, CM1, CM2, 6e) ;
- `liens_autres_disciplines` : items d'autres disciplines qui partagent une notion ;
- `source` : programme, BO, fichier, page, années d'application.

### Voir les thèmes d'un niveau

```bash
uv run edu-kb themes CE2 -d hg
```

```
- [Histoire-géographie] Histoire › Thème 1 : La vie des femmes et des hommes au Paléolithique et au Néolithique (…) (première période)
- [Histoire-géographie] Histoire › Thème 2 : Vivre à Rome et en Gaule romaine (…) (deuxième et troisième périodes)
- [Histoire-géographie] Géographie › Thème 2 : Se loger en France (deux périodes)
```

Sans `-d`, toutes les disciplines qui ont des thèmes.

### Parcourir le programme d'une discipline

```bash
uv run edu-kb programme CM2 hg
```

Liste ordonnée des items du niveau, avec leur contexte et leur `id` (à passer à `fiche`).

### Préparer une séquence

```bash
uv run edu-kb sequence "le Moyen Âge" -n CM1                 # Markdown à l'écran
uv run edu-kb sequence "fractions" -n CE1 -s 4 -o fractions-ce1.md
uv run edu-kb sequence "fractions" -n CE1 -f skola -o fractions-ce1.json
```

La séquence part du thème ou de la rubrique qui correspond le mieux à la notion. Elle contient :

- l'ancrage dans le programme et les périodes que celui-ci indique ;
- les thèmes (question, mots-clés), les objectifs, les compétences et le socle ;
- les pistes d'activités proposées par le programme (sciences, HG, EMC…) ;
- les prérequis (niveau précédent), les prolongements (niveau suivant), les liens avec d'autres
  disciplines ;
- un **squelette de séances** : une par objectif (ou regroupés pour tenir dans `-s` séances), avec des
  critères de réussite et des phases types (découverte, recherche, mise en commun, entraînement),
  plus une séance d'évaluation.

Le déroulé détaillé des séances n'est pas inventé par la ligne de commande : demande-le à Claude.
Formats : `md` (défaut), `json` (tout le contenu), `skola` (une séquence et ses fiches de
préparation, avec les colonnes des tables `sequences` et `preps` de Skola).

### Référentiel de compétences d'un niveau

```bash
uv run edu-kb referentiel CP                       # toutes les disciplines, en liste à cocher
uv run edu-kb referentiel CP -d maths -d français  # certaines disciplines
uv run edu-kb referentiel CP -f csv -o cp.csv      # tableur : une ligne par compétence
uv run edu-kb referentiel CM1 -f json              # tout le contenu
```

Chaque compétence est une puce du programme en vigueur (objectif d'apprentissage, compétence
travaillée, contenu d'EMC…), rangée par discipline et par domaine. On y trouve son échéance quand le
programme en donne une (`⏱ En fin de période 1`), le repère `↻` quand elle se travaille toute l'année,
les critères de réussite du domaine, le socle commun de la discipline, la page et le BO. Rien n'est
inventé : c'est une vue du graphe. Le CP compte 320 compétences en 10 disciplines.

### Programmation annuelle et progression hebdomadaire pour Skola

```bash
uv run edu-kb skola CE2 -z B -o programmation-ce2.json         # JSON pour Skola
uv run edu-kb skola CE2 -z B -f md -o programmation-ce2.md      # lisible
uv run edu-kb skola CE2 -z B -f csv -o progression-ce2.csv      # tableur, une ligne par semaine et unité
uv run edu-kb skola CE2 -d maths -d français                    # seulement certaines disciplines
```

- **Calendrier** : périodes et semaines de classe de la zone (`-z A|B|C`, B par défaut), sans les
  vacances ni les jours fériés et ponts (36 semaines en zone B en 2026-2027).
- **Programmation annuelle** : pour chaque discipline et chaque période, les unités (thèmes ou
  rubriques).
- **Travaillé en continu** : une section à part liste, une seule fois, les objectifs que le programme
  dit travaillés toute l'année (« tout au long de l'année », « au cours des périodes 1 à 5 ») ou qui
  n'ont aucune échéance en français, langues vivantes et éducation musicale. Ils ne sont pas répétés
  dans le tableau annuel ni dans la progression.
- **Progression hebdomadaire** : pour chaque semaine, les unités et les objectifs travaillés. Un
  objectif travaillé sur plusieurs périodes est rappelé en début de période (« En continu : … »).
- **Séquences** : une par unité, avec objectifs, compétences et critères d'évaluation.

Comment les unités sont placées :

- les **périodes imposées par le programme** sont respectées — thèmes d'histoire-géographie
  (« deuxième et troisième périodes », « deux périodes »), échéances du français (« en fin de
  période 1 » → P1, « en milieu d'année » → P2-P3, « en fin d'année » → P4-P5) ;
- le **français, les langues vivantes et l'éducation musicale** sont travaillés en continu : chaque
  rubrique sur toute l'année, ses objectifs étalés sur les semaines ;
- les **autres disciplines** enchaînent leurs unités dans l'ordre du programme, au prorata des
  semaines, chaque domaine en parallèle (Nombres / Grandeurs et mesures / Espace et géométrie…).

Le champ `origine` de chaque placement indique s'il vient du programme ou d'une répartition
proposée : c'est une base de travail à ajuster.

Le JSON reprend les tables de Skola (`subjects`, `sequences`, `programmation_items`) et y ajoute
`calendrier`, `semaines` et `progression`. **Skola n'a pas encore de fonction d'import ni de colonne
« semaine »** : pour l'instant, le fichier sert de référence ou de base à un futur import.

### Visualiser le graphe

```bash
uv run edu-kb graphe -o programmes.graphml
```

S'ouvre dans [Gephi](https://gephi.org) ou yEd : disciplines, niveaux, thèmes, items et leurs liens
(les objectifs sont omis pour garder le graphe lisible).

---

## 4. Faire évoluer la base

### Un programme change d'année d'application

Chaque programme déclare les niveaux et les années où il s'applique dans `sources.toml` :

```toml
applies = { CP = "2026-", CE1 = "2026-", CE2 = "2026-" }   # depuis la rentrée 2026
applies = { CE1 = "2016-2026" }                            # jusqu'à la rentrée 2026, exclue
```

Modifie la ligne, puis reconstruis :

```bash
uv run edu-kb build
```

C'est ainsi que *Questionner le monde* a été retiré : il reste dans la base pour mémoire, mais ne
s'applique plus à partir de 2026-2027.

### Ajouter un nouveau programme

1. Dépose le PDF dans `Programmes/`.
2. Ajoute un bloc `[[source]]` dans `sources.toml` (fichier, discipline, niveaux et années, pages,
   règles de titres). Le plus simple : copier le bloc d'un programme de la même série et ajuster les
   styles de titres (le README explique comment les relever).
3. Relance `./scripts/setup.sh --build` (ou `uv run edu-kb build`).
4. Commite, fusionne dans `main` et pousse, puis `./scripts/publier-base.sh` : les autres l'installent sans reconstruire.

Les PDF scannés sont passés automatiquement par l'OCR (`ocr = true` dans le bloc).

### Préparer l'année suivante

Ajoute la rentrée suivante dans `calendrier.toml` (dates de rentrée, de vacances par zone, jours
fériés). Sans elle, `edu-kb skola -a 2027-2028` répond :

```
Erreur : Pas de calendrier pour la rentrée 2027 dans calendrier.toml (années : 2026)
```

### Changer la façon de répartir une discipline

Le mode continu ou séquentiel de chaque discipline est réglé dans `src/edu_kb/planning.py`
(`MODES`).

---

## 5. Ce qu'il faut garder en tête

- **Vérifier les dates.** Les années d'application viennent d'une synthèse des arrêtés et de ta
  correction (QLM) ; le calendrier 2026-2027 vient de sources publiques. Un doute : eduscol et
  education.gouv.fr font foi.
- **Compétences.** Les programmes de 2024 à 2026 n'ont plus de tableau « compétences travaillées » :
  les compétences d'un item sont ses exemples de réussite ou ses attendus. Les domaines du socle
  associés à une discipline sont une correspondance indicative (d'après le volet 2 des programmes
  2020). Les maths du cycle 3 publient leurs exemples de réussite sur Eduscol, pas dans le texte.
- **Liens entre disciplines.** Ils viennent des mots-clés de l'histoire-géographie retrouvés dans le
  contenu des autres programmes, puis filtrés par le sens : un lien n'est gardé que si l'item
  ressemble au thème qui porte le mot-clé (similarité ≥ 0,5). Les homonymes (« égalité » des maths,
  « carte » d'anniversaire) et les mots trop courants sont ainsi écartés ; il reste quelques faux
  positifs isolés. Sans Ollama, ce filtre n'est pas appliqué (`edu-kb status` le signale).
- **Extraction automatique.** Le texte est lu dans les PDF par des règles de mise en page : il est
  fidèle dans l'ensemble, mais un intertitre peut avoir été fusionné avec son voisin ou une puce
  coupée. En cas de doute, la fiche donne la page du PDF.
- **Pas de maternelle** pour l'instant (aucun programme de cycle 1 fourni).
