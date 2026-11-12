"""Transfert de la base avec les guides d'un poste à l'autre (clé USB), sans passer par GitHub.

Les guides de l'enseignant sont des ressources achetées : leur base ne se publie pas. On l'exporte
en un seul fichier compact et autonome (sans journal WAL à côté), puis on l'installe sur l'autre
poste après avoir vérifié que c'est bien une base edu-kb qui contient des guides.
"""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .download import DownloadError, _built_at, _drop_journal


class TransferError(ValueError):
    """Fichier absent, déjà présent, ou qui n'est pas une base edu-kb avec des guides."""


def guides_in(path: Path) -> list[str]:
    """Titres des guides d'une base edu-kb (lève TransferError si ce n'en est pas une)."""
    try:
        _built_at(path)
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)) as con:
            return [r[0] for r in con.execute("SELECT title FROM nodes WHERE kind = 'guide' ORDER BY position")]
    except (DownloadError, sqlite3.DatabaseError) as exc:
        raise TransferError(f"{path} n'est pas une base edu-kb ({exc})") from exc


def export_base(source: Path, target: Path, overwrite: bool = False) -> list[str]:
    """Copie compacte et autonome de la base `source` en `target`. Renvoie les guides qu'elle contient."""
    if not source.exists():
        raise TransferError(f"aucune base à exporter : {source} (lance `edu-kb build --guides`)")
    guides = guides_in(source)
    if not guides:
        raise TransferError(f"{source} ne contient aucun guide : rien à transférer")
    if target.is_dir():
        target = target / source.name
    if target.exists() and not overwrite:
        raise TransferError(f"{target} existe déjà (--force pour le remplacer)")
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(source)) as con:
        con.execute("VACUUM INTO ?", (str(tmp),))
    with closing(sqlite3.connect(tmp)) as con:
        con.execute("PRAGMA journal_mode = DELETE")
    tmp.replace(target)
    return guides


def import_base(source: Path, target: Path, published: Path) -> tuple[str, list[str]]:
    """Installe en `target` la base `source` (une base edu-kb avec des guides), jamais à la place de
    la base publiée. Renvoie (date de construction, guides)."""
    if not source.exists():
        raise TransferError(f"fichier introuvable : {source}")
    if target.resolve() == published.resolve():
        raise TransferError(f"la base avec les guides ne remplace pas la base publiée ({published}) : "
                            "choisis une autre base (EDU_KB_DB=~/.edu-kb/kb-guides.sqlite)")
    guides = guides_in(source)
    if not guides:
        raise TransferError(f"{source} ne contient aucun guide")
    built_at = _built_at(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".import")
    shutil.copyfile(source, tmp)
    _drop_journal(target)  # SQLite rejouerait le journal de l'ancienne base sur la nouvelle
    tmp.replace(target)
    return built_at, guides
