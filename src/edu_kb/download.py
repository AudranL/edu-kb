"""Téléchargement de la base publiée en release GitHub : ni PDF, ni OCR, ni reconstruction."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import httpx


class DownloadError(ValueError):
    """Base publiée introuvable, ou fichier reçu qui n'est pas une base edu-kb."""


def download_base(url: str, db_path: Path, http: httpx.Client) -> str:
    """Remplace la base locale par celle publiée à `url` et renvoie sa date de construction.

    La base locale n'est remplacée que si le fichier reçu est bien une base edu-kb."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    received = db_path.with_name(db_path.name + ".download")
    built_at = _receive(url, received, http)
    # SQLite rejouerait le journal de l'ancienne base sur la nouvelle et la corromprait.
    _drop_journal(db_path)
    received.replace(db_path)
    return built_at


def _receive(url: str, received: Path, http: httpx.Client) -> str:
    try:
        _fetch(url, received, http)
        return _built_at(received)
    except DownloadError:
        received.unlink(missing_ok=True)
        _drop_journal(received)
        raise


def _fetch(url: str, target: Path, http: httpx.Client) -> None:
    try:
        with http.stream("GET", url, follow_redirects=True) as resp:
            if not resp.is_success:
                raise DownloadError(f"{url} a répondu {resp.status_code} : aucune base publiée à cette adresse")
            with target.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    except httpx.HTTPError as exc:
        raise DownloadError(f"téléchargement impossible depuis {url} : {exc}") from exc


def _built_at(path: Path) -> str:
    try:
        with closing(sqlite3.connect(path)) as con:
            row = con.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    except sqlite3.DatabaseError as exc:
        raise DownloadError(f"le fichier reçu n'est pas une base edu-kb ({exc})") from exc
    if row is None:
        raise DownloadError("le fichier reçu n'est pas une base edu-kb (aucune date de construction)")
    return row[0]


def _drop_journal(db_path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
