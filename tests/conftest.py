import os
from pathlib import Path

import pytest


def _env_file(var: str) -> Path | None:
    value = os.environ.get(var)
    return Path(value) if value and Path(value).is_file() else None


@pytest.fixture(scope="session")
def fixture_pdf() -> Path:
    path = _env_file("DONGDONGS_FIXTURE_PDF")
    if path is None:
        pytest.skip("DONGDONGS_FIXTURE_PDF is not set to a test report PDF")
    return path


@pytest.fixture(scope="session")
def fixture_hwp() -> Path:
    path = _env_file("DONGDONGS_FIXTURE_HWP")
    if path is None:
        pytest.skip("DONGDONGS_FIXTURE_HWP is not set to the matching HWP report")
    return path


@pytest.fixture(scope="session")
def keri() -> dict:
    from dongdongs.config import institution, load_config

    return institution(load_config(), "KERI")


@pytest.fixture(scope="session")
def cleaned(fixture_pdf, keri, tmp_path_factory):
    from dongdongs.pdf.watermark import clean_pdf

    folder = tmp_path_factory.mktemp("clean")
    out = folder / "cleaned.pdf"
    report = clean_pdf(fixture_pdf, out, keri, folder / "candidates")
    return out, report


@pytest.fixture(scope="session")
def expected() -> dict:
    """Values the real-file tests expect. Kept outside the repository with the report itself."""
    import json

    path = _env_file("DONGDONGS_FIXTURE_EXPECT") or (Path(__file__).parent / "local" / "expected.json")
    if not path.is_file():
        pytest.skip("no expected-values file (set DONGDONGS_FIXTURE_EXPECT or create tests/local/expected.json)")
    return json.loads(path.read_text(encoding="utf-8"))
