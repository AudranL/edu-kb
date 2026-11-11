"""Lecture des PDF : lignes de texte avec leur style et leur position, bandes de lignes de tableau.

Les programmes sont justifiés serré : certains PDF n'encodent pas les espaces entre les mots.
On les réinsère d'après l'écart entre deux caractères consécutifs. Les PDF scannés passent
d'abord par ocrmypdf, qui ajoute une couche texte positionnée (mise en cache).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pymupdf

# Écart (en fraction de la taille de police) au-delà duquel deux caractères sont deux mots,
# et au-delà duquel ils appartiennent à deux colonnes différentes.
WORD_GAP = 0.12
COLUMN_GAP = 2.5

BULLET_CHARS = "-−—–_•▪◦➜"
_PRIVATE_USE = re.compile(r"[-]")


@dataclass
class Line:
    page: int  # 1-indexé
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool
    color: int
    font: str
    text: str

    @property
    def style(self) -> str:
        """Signature de style, comparée aux règles de titres de sources.toml."""
        return f"{self.size:.1f}/{'B' if self.bold else 'R'}/{self.color:06x}"

    @property
    def is_bullet(self) -> bool:
        return bool(self.text) and (self.text[0] in BULLET_CHARS or self.font.startswith(("Symbol", "Wingdings", "ZapfDingbats")))


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ocr_pdf(path: Path, cache_dir: Path) -> Path:
    """Renvoie une copie du PDF avec une couche texte OCR (tesseract, français), mise en cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{file_hash(path)[:16]}.pdf"
    if out.exists():
        return out
    if not shutil.which("ocrmypdf"):
        raise RuntimeError(f"{path.name} est un PDF scanné : installe ocrmypdf et tesseract-lang (brew install ocrmypdf tesseract-lang)")
    tmp = out.with_suffix(".tmp.pdf")
    subprocess.run(["ocrmypdf", "-q", "-l", "fra", "--force-ocr", str(path), str(tmp)], check=True)
    tmp.rename(out)
    return out


def _clean_text(text: str) -> str:
    text = _PRIVATE_USE.sub("-", text)  # puces des polices Symbol / Wingdings
    return re.sub(r"\s+", " ", text).strip()


def _segments(spans: list[dict]) -> list[tuple[list[dict], str, float, float]]:
    """Découpe une ligne PDF en segments séparés par un grand blanc (deux colonnes voisines).

    Renvoie (spans du segment, texte, x0, x1) ; les espaces manquants entre mots sont réinsérés.
    """
    segments: list[tuple[list[dict], list[str], float, float]] = []
    prev = None
    last_ink = None  # dernier caractère non blanc
    for span in spans:
        for c in span["chars"]:
            ch = c["c"]
            gap = c["bbox"][0] - prev["bbox"][2] if prev is not None else 0
            ink_gap = c["bbox"][0] - last_ink["bbox"][2] if last_ink is not None else 0
            if prev is None or (ch.strip() and ink_gap > span["size"] * COLUMN_GAP):
                segments.append(([span], [], c["bbox"][0], c["bbox"][2]))
            else:
                if span is not segments[-1][0][-1]:
                    segments[-1][0].append(span)
                if ch != " " and prev["c"] != " " and gap > span["size"] * WORD_GAP:
                    segments[-1][1].append(" ")
            segments[-1][1].append(ch)
            if ch.strip():
                spans_, chars, x0, _ = segments[-1]
                segments[-1] = (spans_, chars, x0, c["bbox"][2])
                last_ink = c
            prev = c
    return [(s, _clean_text("".join(chars)), x0, x1) for s, chars, x0, x1 in segments]


def _span_text(span: dict) -> str:
    return "".join(c["c"] for c in span["chars"])


def _stack_fractions(raws: list[tuple[tuple, list[dict]]]) -> list[tuple[tuple, list[dict]]]:
    """Fractions composées en hauteur (numérateur au-dessus du dénominateur, en petit corps) :
    le numérateur, isolé sur sa propre ligne, est réinjecté devant le dénominateur → « 1/2 »."""
    def small_digits(span: dict) -> str | None:
        t = _span_text(span).strip()
        return t if t.isdigit() and span["size"] <= 7 else None

    numerators = [i for i, (_, spans) in enumerate(raws) if len(spans) == 1 and small_digits(spans[0])]
    used: set[int] = set()
    out = list(raws)
    for i, (bbox, spans) in enumerate(raws):
        if i in numerators or not small_digits(spans[0]):
            continue
        for n in numerators:
            nb, nspans = raws[n]
            if n not in used and abs(nb[0] - bbox[0]) < 4 and 0 <= bbox[1] - nb[1] <= 6:
                den = dict(spans[0])
                first_char = den["chars"][0]
                den["chars"] = [{**first_char, "c": ch} for ch in _span_text(nspans[0]).strip() + "/"] + den["chars"]
                out[i] = (bbox, [den] + spans[1:])
                used.add(n)
                break
    return [r for k, r in enumerate(out) if k not in used]


def read_lines(path: Path, pages: tuple[int, int] | None = None) -> list[Line]:
    """Toutes les lignes non vides, dans l'ordre de lecture du PDF (page, puis bloc)."""
    doc = pymupdf.open(path)
    first, last = pages or (1, doc.page_count)
    lines: list[Line] = []
    for pno in range(first - 1, min(last, doc.page_count)):
        page = doc[pno]
        raws = []
        for block in page.get_text("rawdict")["blocks"]:
            for raw in block.get("lines", []):
                spans = [s for s in raw["spans"] if "".join(c["c"] for c in s["chars"]).strip()]
                if spans:
                    raws.append((raw["bbox"], spans))
        for (_, y0, _, y1), spans in _stack_fractions(raws):
            for seg_spans, text, x0, x1 in _segments(spans):
                if not text:
                    continue
                main = max(seg_spans, key=lambda s: len(s["chars"]))
                lines.append(
                    Line(
                        page=pno + 1,
                        x0=x0, y0=y0, x1=x1, y1=y1,
                        size=round(main["size"], 1),
                        bold=bool(main["flags"] & 16) or "Bold" in main["font"],
                        color=main["color"],
                        font=seg_spans[0]["font"],
                        text=text,
                    )
                )
    return lines
