# Exemples : un appel par outil MCP

Un exemple par outil du serveur `edu-kb`, avec l'appel exact (les arguments passés) et la réponse
exacte de l'outil, enregistrés le 29 octobre 2026 sur la base 2026-2027 (les exemples 1, 5, 6, 7 et 9 ont été régénérés le 4 novembre
après les corrections décrites dans [l'évaluation des outils](../evaluation-outils.md) ; `uv run python scripts/exemples.py` les régénère). Chaque fichier `NN-outil.md`
contient la réponse complète. Ci-dessous : ce qu'on demande, l'équivalent en ligne de commande, ce
que l'outil répond et ce qu'il faut en retenir.

| # | Outil | Demande | Fichier |
|---|---|---|---|
| 1 | `chercher` | « fractions » en CM1 | [01-chercher.md](01-chercher.md) |
| 2 | `fiche` | l'item « Observer son environnement proche » (CP, sciences) | [02-fiche.md](02-fiche.md) |
| 3 | `themes` | les thèmes d'histoire-géographie en CM1 | [03-themes.md](03-themes.md) |
| 4 | `programme` | le programme d'EMC en CE2 | [04-programme.md](04-programme.md) |
| 5 | `progression_notion` | la numération du CP à la 6e | [05-progression_notion.md](05-progression_notion.md) |
| 6 | `preparer_sequence` | le Moyen Âge en CM1, 4 séances | [06-preparer_sequence.md](06-preparer_sequence.md) |
| 7 | `programmation` | les sciences en CP, zone B | [07-programmation.md](07-programmation.md) |
| 8 | `sources` | les textes en vigueur en CP | [08-sources.md](08-sources.md) |
| 9 | `referentiel` | le référentiel de compétences de mathématiques en CP | [09-referentiel.md](09-referentiel.md) |

---

## 1. `chercher` : trouver une notion

```json
{"notion": "fractions", "niveau": "CM1", "limite": 5}
```

En ligne de commande : `uv run edu-kb search "fractions" -n CM1 -k 5`

```text
[1] item · Mathématiques · CM1 · maths-c3-2025 p. 6
id=maths-c3-2025/nombres-calcul-et-resolution-de-probleme/cours-moyen-premiere-annee/les-fractions#i1
Nombres, calcul et résolution de problèmes › Cours moyen première année › Les fractions
→ Savoir interpréter, représenter, écrire et lire des fractions
```

Deux résultats, tous deux sur les fractions : l'item « Les fractions » du CM1, puis les fractions
décimales. Le niveau est appliqué avant le classement et un résultat trop éloigné du meilleur est
écarté : avant la correction, la même recherche renvoyait 5 résultats dont 2 hors sujet. L'`id` de
chaque résultat se passe à `fiche`.

## 2. `fiche` : tout savoir d'un item

```json
{"id": "sciences-c2-2026/les-etres-vivants-dans-leur-environnemen/cours-preparatoire/observer-et-decrire-son-environnement-pr#i1", "annee": "2026-2027"}
```

En ligne de commande : `uv run edu-kb fiche "<id>" -a 2026-2027`

La fiche donne, en JSON :

- **objectifs** : « Observer son environnement proche : décrire les êtres vivants qui y vivent et les
  caractéristiques du milieu de vie. » et « Se repérer dans son environnement proche. » (p. 5) ;
- **démarches proposées** : nommer des animaux, végétaux et champignons de la cour ou du parc,
  dessins d'observation, positionner les éléments sur un plan ou une maquette ;
- **socle** : D1.3, D2, D4, D5 (correspondance indicative) ;
- **progression** : CE1 « Observer le changement de peuplement […] au cours des saisons », CE2
  « Observer des environnements variés » ;
- **liens avec d'autres disciplines** (par la notion « plan ») : repérage dans l'espace en maths,
  orientation en EPS, « Thème 1 : Autour de l'école » en géographie ;
- **source** : programme de sciences et technologie du cycle 2, arrêté du 5 juin 2026, BO n° 24 du
  11 juin 2026, p. 5.

## 3. `themes` : les thèmes d'un niveau

```json
{"niveau": "CM1", "discipline": "Histoire-géographie"}
```

En ligne de commande : `uv run edu-kb themes CM1 -d hg`

| Thème | Périodes |
|---|---|
| Histoire 1 : La vie quotidienne au Moyen Âge (XIe - XIIIe siècles) | P1, P2 |
| Histoire 2 : La monarchie en France (XVIe – XVIIe siècles) | P2, P3 |
| Histoire 3 : Explorations et conquêtes par les Européens du XVe au XVIIe siècle | P4 |
| Histoire 4 : 1789, une année révolutionnaire en France | P5 |
| Géographie 1 : Se nourrir | 1 ou 2 périodes au choix |
| Géographie 2 : Les inégalités dans le monde | 1 ou 2 périodes au choix |
| Géographie 3 : Se déplacer | 1 période |
| Géographie 4 : Communiquer dans le monde avec Internet | 1 période |

Thème de l'année en géographie : « La diversité des modes de vie dans le monde ». Chaque thème vient
avec sa question directrice et ses mots-clés.

## 4. `programme` : le programme d'une discipline

```json
{"niveau": "CE2", "discipline": "EMC"}
```

En ligne de commande : `uv run edu-kb programme CE2 emc`

4 items, tous dans « CE2 : Apprendre ensemble et vivre ensemble » (EMC 2024, p. 10) :
*Bien commun, Responsabilité* ; *Service public* ; *Intérêt général et intérêt particulier* ;
*République*.

## 5. `progression_notion` : une notion du CP à la 6e

```json
{"notion": "numération des nombres entiers", "discipline": "Mathématiques"}
```

Pas d'équivalent en ligne de commande.

| Niveau | Exemple d'item renvoyé |
|---|---|
| CP | Connaitre la suite écrite et la suite orale des nombres jusqu'à cent. |
| CE1 | Connaitre la suite écrite et la suite orale des nombres jusqu'à mille. |
| CE2 | Connaitre la suite écrite et la suite orale des nombres jusqu'à dix-mille. |
| CM1 | Comparer et dénombrer des collections en les organisant |
| CM2 | Connaître et utiliser les relations entre les unités de numération |

La 6e n'apparaît plus et deux items de multiplication (CE2) restent : ni l'un ni l'autre ne parle
de numération. Sans filtre de niveau, la marge de similarité est plus large (0,10) pour voir la notion à
chaque niveau.

## 6. `preparer_sequence` : le squelette d'une séquence

```json
{"notion": "le Moyen Âge", "niveau": "CM1", "nb_seances": 4}
```

En ligne de commande : `uv run edu-kb sequence "le Moyen Âge" -n CM1 -s 4`

La séquence s'ancre dans le thème 1 d'histoire (P1, P2), reprend sa question et ses mots-clés, ses
attendus (« Décrire les fonctions d'un château […] », « Raconter la vie quotidienne des paysannes et
des paysans […] ») et le socle (D1.1, D2, D3, D5). Elle ne contient pas le déroulé des séances : c'est
à Claude de le rédiger.

Les 3 objectifs du thème (la seigneurie et la paroisse, les modes de vie, le rôle de l'Église) donnent
chacun une séance, puis l'évaluation : on ne crée pas de séance vide pour atteindre les 4 demandées. Les
critères de réussite, communs à toutes les séances, sont écrits une fois.

## 7. `programmation` : l'année, période par période et semaine par semaine

```json
{"niveau": "CP", "disciplines": ["Sciences et technologie"], "zone": "B"}
```

En ligne de commande : `uv run edu-kb skola CP -z B -d sciences -f md`

```markdown
| Période | Du | Au | Semaines |
|---|---|---|---|
| P1 — Rentrée → Toussaint | 2026-09-01 | 2026-10-16 | 7 |
| P2 — Toussaint → Noël | 2026-11-02 | 2026-12-18 | 7 |
| P3 — Noël → hiver | 2027-01-04 | 2027-02-19 | 7 |
| P4 — Hiver → printemps | 2027-03-08 | 2027-04-16 | 6 |
| P5 — Printemps → été | 2027-05-03 | 2027-07-02 | 9 |
```

Puis la programmation annuelle (4 domaines × 5 périodes) et la progression des 36 semaines. Le
vivant y tombe en P1 (S1 à S7), l'environnement proche en P2 et P3, la protection de
l'environnement en P4 et P5. Les fériés sont décomptés : la semaine S25 va du 30 mars au 2 avril
(lundi de Pâques), la semaine S28 du 3 au 4 mai.

## 8. `sources` : les textes en vigueur

```json
{"niveau": "CP"}
```

En ligne de commande : `uv run edu-kb status` (tous les niveaux)

10 programmes pour le CP en 2026-2027, chacun avec son BO et ses années d'application : sciences,
histoire-géographie, EPS et langues vivantes de 2026 ; français et maths de 2024 (appliqués depuis
2025) ; EVAR de 2025 ; EMC de 2024 ; arts plastiques et éducation musicale de 2020.

## 9. `referentiel` : les compétences d'un niveau

```json
{"niveau": "CP", "discipline": "Mathématiques"}
```

En ligne de commande : `uv run edu-kb referentiel CP -d maths` (`-f json` ou `-f csv`, `-o fichier`)

Une liste à cocher des 69 compétences de mathématiques du CP, rangées par domaine
(« Nombres, calcul et résolution de problèmes › Les nombres entiers »…), avec les critères de réussite du
programme sous chaque domaine, le socle commun de la discipline, la source (BO) et, pour le français,
l'échéance de chaque compétence (« ⏱ En fin de période 1 »). Sans `discipline`, toutes les disciplines du
niveau (320 compétences au CP). Le CSV est fait pour une grille d'évaluation dans un tableur.

---

## Défauts relevés sur ces exemples

| # | Outil | Défaut | Où le voir |
|---|---|---|---|
| 1 | `preparer_sequence` | ~~1 séance au lieu de 4~~ corrigé le 4 novembre : 3 séances (un objectif chacune) et l'évaluation. | [06](06-preparer_sequence.md) |
| 2 | `themes`, `preparer_sequence` | Mots-clés coupés : « …paroisse, paysanne et ». Les « ou » orphelins en fin d'attendu sont retirés de la séquence depuis le 4 novembre ; les mots-clés des thèmes restent coupés (texte du programme mal découpé). | [03](03-themes.md), [06](06-preparer_sequence.md) |
| 3 | `progression_notion` | Un résultat CE2 a pour titre « Objectifs d'apprentissage » (un en-tête de tableau pris pour un item). Des items de multiplication remontent sur une recherche de numération. | [05](05-progression_notion.md) |
| 4 | `fiche` | Puces mal converties (« + l'élève… », « * l'élève… ») et majuscule parasite (« sur Un plan »). | [02](02-fiche.md) |
| 5 | `programmation` | Filtrée sur les sciences, elle liste quand même les 10 programmes dans ses sources. | [07](07-programmation.md) |
| 6 | `chercher` | ~~2 résultats hors sujet sur 5 pour « fractions »~~ corrigé le 4 novembre. | [01](01-chercher.md) |
