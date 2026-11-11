"""Configuration : variables d'environnement et description des sources (sources.toml)."""

from __future__ import annotations

import fnmatch
import os
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .outline import DocSpec, HeadingRule

PROJECT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    programmes_dir: Path
    sources_file: Path
    calendar_file: Path
    cache_dir: Path
    ollama_url: str
    embed_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path(os.environ.get("EDU_KB_HOME", str(Path.home() / ".edu-kb"))).expanduser()
        return cls(
            db_path=Path(os.environ.get("EDU_KB_DB", str(home / "kb.sqlite"))).expanduser(),
            programmes_dir=Path(os.environ.get("EDU_KB_PROGRAMMES", str(PROJECT_DIR / "Programmes"))).expanduser(),
            sources_file=Path(os.environ.get("EDU_KB_SOURCES", str(PROJECT_DIR / "sources.toml"))).expanduser(),
            calendar_file=Path(os.environ.get("EDU_KB_CALENDRIER", str(PROJECT_DIR / "calendrier.toml"))).expanduser(),
            cache_dir=home / "cache",
            ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
            embed_model=os.environ.get("EDU_KB_EMBED_MODEL", "bge-m3"),
        )


def parse_years(spec: str) -> tuple[int, int | None]:
    """« 2026- » → (2026, None) ; « 2016-2027 » → (2016, 2027) ; « -2027 » → (0, 2027)."""
    start, _, end = spec.partition("-")
    return int(start or 0), int(end) if end else None


def find_file(root: Path, pattern: str) -> Path | None:
    # macOS stocke les noms de fichiers décomposés (NFD) : on compare en NFC.
    wanted = unicodedata.normalize("NFC", pattern).lower()
    matches = sorted(
        p for p in root.rglob("*")
        if p.is_file() and fnmatch.fnmatch(unicodedata.normalize("NFC", p.name).lower(), wanted)
    )
    return matches[0] if matches else None


def load_sources(sources_file: Path, programmes_dir: Path) -> tuple[list[DocSpec], list[str]]:
    """Charge sources.toml. Renvoie les sources trouvées et les avertissements (fichiers absents)."""
    with sources_file.open("rb") as f:
        data = tomllib.load(f)
    defaults = data.get("defaults", {})
    specs: list[DocSpec] = []
    warnings: list[str] = []
    for raw in data.get("source", []):
        path = find_file(programmes_dir, raw["file"])
        if path is None:
            warnings.append(f"{raw['id']} : aucun fichier « {raw['file']} » dans {programmes_dir}")
            continue
        applies = {level: parse_years(years) for level, years in raw.get("applies", {}).items()}
        specs.append(
            DocSpec(
                id=raw["id"],
                path=path,
                title=raw["title"],
                discipline=raw["discipline"],
                cycle=int(raw.get("cycle", 0)),
                levels=list(applies),
                pages=tuple(raw["pages"]) if "pages" in raw else None,
                headings=[HeadingRule(**rule) for rule in raw.get("headings", [])],
                domaines=raw.get("domaines", []),
                theme_under=raw.get("theme_under", []),
                rubrique_kind=raw.get("rubrique_kind", ""),
                skip=defaults.get("skip", []) + raw.get("skip", []),
                skip_top=raw.get("skip_top", defaults.get("skip_top", 0)),
                skip_bottom=raw.get("skip_bottom", defaults.get("skip_bottom", 10_000)),
                sommaire_until=raw.get("sommaire_until", 0),
                ocr=bool(raw.get("ocr", False)),
                bo=raw.get("bo", ""),
                applies=applies,
            )
        )
    return specs, warnings
