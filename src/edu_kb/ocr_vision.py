"""OCR des guides pédagogiques scannés avec le framework Vision de macOS.

Tesseract (ocrmypdf) lit bien le texte courant des guides mais écarte les encadrés de couleur qui
portent leur structure (« SÉANCE 1 » sur fond jaune, objectifs du programme en blanc sur rouge).
Vision les lit, ligne par ligne, avec leur position. Les pages sont rendues à 400 dpi (en dessous,
le « a » arrondi des guides est souvent lu « o ») et le résultat est mis en cache par fichier.

Il reste des « a » lus « o », « 1 » ou sautés (« dons les rongs », « orthogrphe ») : `correct`
les répare en ne proposant que ces corrections-là, validées par le correcteur orthographique
français de macOS. Les mots en capitales (graphèmes, pseudo-mots, mots dictés) ne sont pas touchés.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .extract import file_hash

SWIFT_SOURCE = Path(__file__).with_name("vision_ocr.swift")
DPI = 400
BATCH = 8

# Mots français valides mais presque toujours des erreurs de lecture dans un guide de l'enseignant.
FORCED = {"dons": "dans", "Dons": "Dans"}
# « il y o des », « elle o » : le verbe avoir lu « o ».
AVOIR = re.compile(r"\b(il y|il|elle|on|qui|y) o\b")
# « faire foire les exercices » : « foire » est un mot, mais pas dans une consigne.
FAIRE = re.compile(r"\b([Ff]aire|[Ff]ais|[Ff]ait) foire\b")
# « la voleur des chiffres », « les voleurs de deux ensembles » : la valeur, en numération et monnaie.
VALEUR = re.compile(r"\b(la|les|leur|leurs) vol(eurs?)\b(?= (?:de|des|du|d['’]) ?(?:deux|chiffres?|ensembles?|pièces|billets|un|une|nombres?)\b)")
WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass
class OcrLine:
    text: str
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class OcrPage:
    number: int  # 1-indexé
    width: float  # en points PDF
    height: float
    lines: list[OcrLine]


class OcrUnavailable(RuntimeError):
    """Vision ou le compilateur Swift sont absents (macOS et outils en ligne de commande Xcode requis)."""


def vision_binary(cache_dir: Path) -> Path:
    """Compile l'outil Swift une fois (une version par contenu du source)."""
    digest = hashlib.sha256(SWIFT_SOURCE.read_bytes()).hexdigest()[:12]
    binary = cache_dir / "bin" / f"vision_ocr-{digest}"
    if binary.exists():
        return binary
    if not shutil.which("swiftc"):
        raise OcrUnavailable("les guides scannés passent par l'OCR de macOS : installe les outils Xcode (xcode-select --install)")
    binary.parent.mkdir(parents=True, exist_ok=True)
    tmp = binary.with_suffix(".tmp")
    subprocess.run(["swiftc", "-O", "-o", str(tmp), str(SWIFT_SOURCE)], check=True, capture_output=True)
    tmp.rename(binary)
    return binary


def ocr_document(path: Path, cache_dir: Path, progress=None) -> list[OcrPage]:
    """Toutes les pages du PDF, lues par Vision (résultat mis en cache par contenu du fichier)."""
    cached = cache_dir / "vision" / f"{file_hash(path)[:16]}-{DPI}.json"
    if cached.exists():
        return _load(cached)
    binary = vision_binary(cache_dir)
    doc = pymupdf.open(path)
    pages: list[OcrPage] = []
    with tempfile.TemporaryDirectory() as tmp:
        for start in range(0, doc.page_count, BATCH):
            numbers = list(range(start, min(start + BATCH, doc.page_count)))
            images = []
            for n in numbers:
                image = Path(tmp) / f"p{n + 1}.png"
                doc[n].get_pixmap(dpi=DPI).save(image)
                images.append(str(image))
            out = subprocess.run([str(binary), "ocr", *images], check=True, capture_output=True, text=True).stdout
            for n, raw in zip(numbers, out.splitlines()):
                rect = doc[n].rect
                lines = [OcrLine(**{k: l[k] for k in ("text", "conf", "x0", "y0", "x1", "y1")}) for l in json.loads(raw)["lines"]]
                pages.append(OcrPage(n + 1, rect.width, rect.height, lines))
            for image in images:
                Path(image).unlink()
            if progress:
                progress(len(pages), doc.page_count)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps([{"number": p.number, "width": p.width, "height": p.height,
                                   "lines": [l.__dict__ for l in p.lines]} for p in pages], ensure_ascii=False))
    return pages


def _load(path: Path) -> list[OcrPage]:
    return [OcrPage(p["number"], p["width"], p["height"], [OcrLine(**l) for l in p["lines"]])
            for p in json.loads(path.read_text())]


# --------------------------------------------------------------------------- correction
def candidates(word: str) -> list[str]:
    """Corrections possibles d'un mot mal lu, de la plus probable à la moins probable :
    « o » lus à la place de « a », « 1 » à la place de « a », un « a » sauté."""
    out: list[str] = []
    positions = [i for i, c in enumerate(word) if c == "o"][:4]
    for k in range(1, len(positions) + 1):
        for chosen in itertools.combinations(positions, k):
            out.append("".join("a" if i in chosen else c for i, c in enumerate(word)))
    if "1" in word:
        out.append(word.replace("1", "a"))
    out += [word[:i] + "a" + word[i:] for i in range(len(word) + 1)]
    return list(dict.fromkeys(c for c in out if c != word and not any(ch.isdigit() for ch in c)))


def _correctable(token: str) -> bool:
    """Mot en minuscules (ou avec une capitale initiale) : les capitales seules (A, OU, LARI) ne bougent pas."""
    if len(token) < 2 or token.isdigit() or not any(c.isalpha() for c in token):
        return False
    if len(token) == 2 and not token.islower():  # « Ol », « El » : des graphèmes OI, EI mal lus, pas des mots
        return False
    rest = token[1:]
    return rest == rest.lower() and any(c.islower() for c in rest)


class Speller:
    """Interroge le correcteur orthographique de macOS par lots (un appel pour tous les mots)."""

    def __init__(self, binary: Path):
        self.binary = binary
        self._known: dict[str, bool] = {}

    def valid(self, words: list[str]) -> dict[str, bool]:
        todo = [w for w in dict.fromkeys(words) if w not in self._known]
        if todo:
            out = subprocess.run([str(self.binary), "mots"], input="\n".join(todo) + "\n", check=True,
                                 capture_output=True, text=True).stdout.split()
            self._known.update(zip(todo, (v == "1" for v in out)))
        return {w: self._known[w] for w in words}


def correct(texts: list[str], speller: Speller) -> list[str]:
    """Corrige les « a » mal lus dans une liste de lignes (deux appels au correcteur en tout)."""
    tokens = {t for text in texts for t in WORD.findall(text) if _correctable(t)}
    lowered = {t: t[0].lower() + t[1:] for t in tokens}
    validity = speller.valid(sorted(set(lowered.values())))
    # le correcteur de macOS accepte tout mot qui contient un chiffre (« Pr1tique », « d1ns »)
    wrong = [t for t in tokens if not validity[lowered[t]] or any(c.isdigit() for c in t)]
    options = {t: candidates(lowered[t]) for t in wrong}
    ok = speller.valid(sorted({c for cs in options.values() for c in cs}))
    fixes: dict[str, str] = {}
    for t, cs in options.items():
        found = next((c for c in cs if ok[c]), None)
        if found:
            fixes[t] = found[0].upper() + found[1:] if t[0].isupper() else found
    fixes.update(FORCED)

    def fix_line(text: str) -> str:
        text = WORD.sub(lambda m: fixes.get(m.group(0), m.group(0)), text)
        text = FAIRE.sub(r"\1 faire", AVOIR.sub(r"\1 a", text))
        return VALEUR.sub(r"\1 val\2", re.sub(r"\bla voleur\b", "la valeur", text))

    return [fix_line(t) for t in texts]


def correct_pages(pages: list[OcrPage], speller: Speller) -> None:
    """Corrige sur place le texte de toutes les lignes d'un document."""
    lines = [l for p in pages for l in p.lines]
    for line, text in zip(lines, correct([l.text for l in lines], speller)):
        line.text = text
