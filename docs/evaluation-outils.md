# Évaluation des outils MCP

Évaluation faite le 4 novembre 2026 sur la base 2026-2027 : un appel réel par outil, un avis sur la
pertinence du résultat, puis les corrections apportées. Les sorties complètes d'un appel par outil
(enregistrées le 29 octobre, avant ces corrections) sont dans [exemples/](exemples/README.md) ;
le mode d'emploi est dans [guide.md](guide.md).

## Synthèse

| Outil | Appel testé | Avant | Après |
|---|---|---|---|
| `chercher` | « fractions », CM1 | moyenne : l'item attendu arrivait 5e, noyé dans du bruit | bonne |
| `fiche` | l'item « Les fractions » du CM1 | bonne | inchangée |
| `themes` | thèmes d'histoire-géographie, CM1 | très bonne | inchangée |
| `programme` | maths, CE1 | bonne | inchangée |
| `progression_notion` | « fractions » | moyenne : items sans rapport au CP, au CE1 et au CM1 | bonne (profite de la recherche corrigée) |
| `preparer_sequence` | « le Moyen Âge », CM1 | faible : un seul objectif retenu | correcte : un objectif par séance |
| `programmation` | CE1, zone B | bonne sur la structure, bruyante en français | bonne : section « en continu » |
| `sources` | CM2 | bonne | inchangée |
| `referentiel` (nouveau) | CP | — | 320 compétences, 10 disciplines |

## Ce qui a été constaté, outil par outil

### `chercher` : « fractions », CM1

**Avant.** Dix résultats : trois objectifs isolés (demi-droite graduée, fractions décimales, calcul
mental), puis des items qui ne parlent pas de fractions (calcul mental, nombres entiers, quatre
opérations, résolution de problèmes…). L'item « Savoir interpréter, représenter, écrire et lire des
fractions » n'apparaissait que par l'un de ses objectifs.

**Causes.**
1. Le niveau, la discipline et l'année étaient appliqués *après* le classement. Les 80 meilleurs
   candidats venaient des autres niveaux ; une fois filtrés, il ne restait que le reste du niveau,
   classé presque au hasard.
2. Un mot courant suffisait à ramener un résultat (« moyen » de « Cours moyen », « lire » de
   « lire l'heure »).
3. Un objectif classé avant son item masquait l'item.
4. Une notion absente des programmes (« photosynthèse ») renvoyait quand même dix résultats.

**Corrections** (`src/edu_kb/kb.py`).
- Niveau, discipline et année filtrent les candidats *avant* le classement.
- On coupe les résultats sémantiques à 0,06 de similarité sous le meilleur ; les résultats
  purement lexicaux ne restent que dans les 3 premiers quand la sémantique est disponible.
- Un objectif classé avant son item est remplacé par l'item.
- Sans mot de la requête dans le programme et avec une similarité maximale sous 0,5, la recherche ne
  renvoie rien plutôt que du bruit.

**Après.**

| Recherche | Résultats |
|---|---|
| « fractions », CM1 | 2 : les fractions, puis les fractions décimales |
| « Moyen Âge », CM1 | 2 : le thème 1 et l'item sur la seigneurie |
| « lire l'heure », CE1 | 1 : lire l'heure sur une horloge à aiguilles |
| « photosynthèse », CM2 | 0 : le mot n'est pas dans le programme |

**Mots-clés des thèmes.** Les mots-clés d'histoire-géographie (« caravelle », « dîme »…) sont des
nœuds `notion` que `chercher` n'interrogeait pas. Ils sont maintenant cherchés et ramenés à leur
thème : « caravelle » donne le thème 3 du CM1, « dîme » le thème 1.

**Expression entière.** Pour une requête de plusieurs mots, l'expression entière est cherchée d'abord
(« Moyen Âge » ne ramène plus tout le « Cours moyen »).

**Marge élargie pour `progression_notion`.** Sans filtre de niveau, on veut voir la notion à chaque
niveau : la marge de similarité passe de 0,06 à 0,10. Résultat : fractions du CE1 à la 6e, numération du
CP au CM2 ; la 6e n'apparaît plus pour la numération, et deux items de multiplication du CE2 restent.

### `fiche` : l'item « Les fractions », CM1

Pertinente : 9 objectifs avec leur page, progression CE1 → CE2 → CM2 → 6e, source (BO n° 16 du
17 avril 2025, p. 6). Deux vides à connaître : `attendus_de_l_item` et les compétences du cycle sont
vides (le programme 2025 n'a plus de tableau de compétences), et les domaines du socle sont une
correspondance indicative. Les items de la 6e n'ont pas de liste d'objectifs dans la progression.

### `themes` : histoire-géographie, CM1

Très pertinente : 4 thèmes d'histoire et 4 de géographie, avec question, mots-clés et période
imposée (« première et deuxième période », « 1 ou 2 périodes au choix »). Utilisable tel quel.

### `programme` : maths, CE1

Pertinente : les 40 items du CE1 avec leur page. Le champ `periodes` est vide pour tous : le
programme de maths 2024 ne donne pas d'échéances.

### `progression_notion` : « fractions »

**Avant.** Le CP contenait quatre items sans rapport (problèmes additifs, doubles et moitiés…) ;
le CE1 et le CM1 en mêlaient d'autres (calcul mental, nombres entiers).
**Après.** Même cause, même correction que `chercher` : seuls restent les items sur les fractions,
du CE1 à la 6e. Les titres tronqués par « … » viennent du texte du programme, pas de l'outil.

### `preparer_sequence` : « le Moyen Âge », CM1

**Avant.**
- Un seul objectif retenu (« Le rôle de l'Église »), alors que le thème en compte trois.
- Des critères de réussite qui parlaient de châteaux et de paysans, sans lien avec la séance.
- Des critères coupés (« …l'Église, etc.). ou »).
- Deux séances au lieu de quatre. Ce point venait de l'appel, pas de l'outil : l'argument se nomme
  `nb_seances`, et j'avais écrit `seances`.

**Corrections** (`src/edu_kb/sequence.py`).
- Le bon objectif de départ vient de la recherche corrigée : les trois objectifs du thème sont
  retenus et répartis sur les séances demandées.
- Les « ou » et « et » orphelins en fin de ligne sont retirés des critères et des attendus.
- Le titre d'une séance est la première proposition de l'objectif, pas l'objectif entier.
- Quand toutes les séances partagent les mêmes critères, ils sont écrits une fois, dans une section
  « Critères de réussite (communs à toutes les séances) ».

**Après.** `-s 4` donne trois séances (une par objectif) puis l'évaluation : on ne crée pas de
séance vide pour atteindre le nombre demandé.

**Reste faible.** Le déroulé des phases (découverte, recherche, mise en commun, entraînement) est
générique : il ne dépend pas de la notion. C'est voulu (le programme ne le fournit pas) ; la
rédaction détaillée relève du prompt `sequence`, donc de Claude.

### `programmation` : CE1, zone B

**Avant.** Le français répétait les mêmes rubriques à chaque période, puis chaque objectif revenait
en « En continu : … » dans chaque semaine de la progression : plus de 130 Ko pour une classe.

**Correction** (`src/edu_kb/planning.py`, `src/edu_kb/skola.py`). Une section
**« Travaillé en continu (toute l'année) »**, qui liste une fois chaque objectif travaillé toute
l'année. Un objectif y entre dans deux cas :
- le programme le dit (« tout au long de l'année », « au cours des périodes 1 à 5 »,
  « en cours d'année ») ;
- il n'a aucune échéance et appartient à une discipline travaillée en continu (français, langues
  vivantes, éducation musicale), hors des thèmes dont le programme fixe les périodes.

Ces objectifs ne sont plus répétés dans le tableau annuel (la case indique « ↻ en continu » quand
toute la discipline est concernée) ni dans la progression hebdomadaire. Le JSON porte une clé
`en_continu` et un drapeau `en_continu` sur chaque entrée de `programmation_items`. Les objectifs
qui ont une échéance (« en fin de période 1 ») restent placés dans leur période.

**Après.** CE1 zone B : 118 Ko au lieu de 130 Ko, sans les répétitions de français ; les
références « (suite) » ne sont plus écrites pour les disciplines en continu.

**Reste à voir.**
- L'ordre des unités de maths suit le programme, sans logique pédagogique (les solides en période 1).
- Les maths, l'EMC et les arts n'ont pas d'échéances : tout est réparti à égalité.

### `sources` : CM2

Pertinente : 11 textes avec BO et années d'application (histoire-géographie 2020 jusqu'en 2027,
français et maths 2025/2026). À vérifier sur eduscol avant usage officiel, comme le dit le README.

## Tests ajoutés

`tests/test_planning.py` (objectifs en continu, marqueurs « toute l'année »),
`tests/test_skola_and_sequence.py` (nettoyage des critères, titres de séance),
`tests/test_graph_and_kb.py` (filtre par niveau avant le classement, expression entière),
`tests/test_referentiel.py` (référentiel, année, Markdown, CSV). 30 tests passent.

## Nouvel outil : `referentiel`

`edu-kb referentiel CP` (ou l'outil MCP `referentiel`) extrait du graphe la liste des compétences d'un
niveau : par discipline puis par domaine, avec échéance, critères de réussite, socle, page et BO ;
Markdown à cocher, JSON ou CSV. Au CP en 2026-2027 : 320 compétences dans 10 disciplines (les
sciences, l'histoire-géographie, l'EPS et les langues vivantes viennent des programmes 2026).
Module `src/edu_kb/referentiel.py`, exemple dans [exemples/09-referentiel.md](exemples/09-referentiel.md).

**Limites.**
- La qualité suit celle de l'extraction : les « compétences travaillées du cycle » des arts plastiques
  contiennent des fragments (« sensible aux questions de l'art. ») ; les mots-clés de thèmes sont
  coupés (« paysanne et »).
- Les critères de réussite sont rattachés au domaine, pas à chaque compétence : le programme les
  donne par item, pas puce à puce.
- EMC et EVAR ne décrivent pas des compétences à évaluer mais des contenus et des notions : ils sont
  repris tels quels.
- Les maths du cycle 3 renvoient leurs exemples de réussite à Eduscol : ils ne sont pas dans le texte.

## Exemples régénérés

`docs/exemples/01`, `05`, `06`, `07` et le nouveau `09` ont été régénérés avec
`uv run python scripts/exemples.py`. Les autres (`02`, `03`, `04`, `08`) n'étaient pas touchés.

## À faire

1. Faire vérifier les marqueurs « toute l'année » par un enseignant sur le français et les langues
   vivantes : la règle « sans échéance = en continu » est une hypothèse raisonnable, pas une lecture
   du texte.
