import httpx
import pytest

from edu_kb.download import DownloadError, download_base
from edu_kb.extract import read_lines
from edu_kb.graph import GraphBuilder
from edu_kb.kb import KnowledgeBase
from edu_kb.outline import parse_document

from .conftest import programme_spec

URL = "https://github.com/AudranL/edu-kb/releases/latest/download/kb.sqlite"


@pytest.fixture
def published_base(tmp_path, programme_pdf) -> bytes:
    spec = programme_spec(programme_pdf)
    builder = GraphBuilder()
    builder.add_source(spec, parse_document(spec, read_lines(programme_pdf), programme_pdf), "hash")
    kb = KnowledgeBase(tmp_path / "publiee" / "kb.sqlite")
    kb.replace_graph(builder.finish())
    return kb.db_path.read_bytes()


def serving(status: int, content: bytes) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, content=content)))


def test_replaces_the_local_base_by_the_published_one(tmp_path, published_base):
    db_path = tmp_path / "local" / "kb.sqlite"
    db_path.parent.mkdir()
    db_path.write_bytes(b"ancienne base")

    built_at = download_base(URL, db_path, serving(200, published_base))

    assert db_path.read_bytes() == published_base
    assert built_at == KnowledgeBase(db_path).stats()["construit_le"]


def test_creates_the_folder_of_a_first_install(tmp_path, published_base):
    db_path = tmp_path / ".edu-kb" / "kb.sqlite"

    download_base(URL, db_path, serving(200, published_base))

    assert db_path.read_bytes() == published_base


def test_drops_the_journal_of_the_previous_base(tmp_path, published_base):
    db_path = tmp_path / "kb.sqlite"
    db_path.write_bytes(b"ancienne base")
    (tmp_path / "kb.sqlite-wal").write_bytes(b"journal de l'ancienne base")
    (tmp_path / "kb.sqlite-shm").write_bytes(b"index du journal")

    download_base(URL, db_path, serving(200, published_base))

    assert not (tmp_path / "kb.sqlite-wal").exists()
    assert not (tmp_path / "kb.sqlite-shm").exists()


def test_refuses_a_file_that_is_not_a_base_and_keeps_the_local_one(tmp_path):
    db_path = tmp_path / "kb.sqlite"
    db_path.write_bytes(b"ancienne base")

    with pytest.raises(DownloadError, match="n'est pas une base edu-kb"):
        download_base(URL, db_path, serving(200, b"<html>Not Found</html>"))

    assert db_path.read_bytes() == b"ancienne base"
    assert [p.name for p in tmp_path.iterdir()] == ["kb.sqlite"]


def test_reports_an_unpublished_base_and_keeps_the_local_one(tmp_path):
    db_path = tmp_path / "kb.sqlite"
    db_path.write_bytes(b"ancienne base")

    with pytest.raises(DownloadError, match="404"):
        download_base(URL, db_path, serving(404, b"Not Found"))

    assert db_path.read_bytes() == b"ancienne base"
    assert [p.name for p in tmp_path.iterdir()] == ["kb.sqlite"]
