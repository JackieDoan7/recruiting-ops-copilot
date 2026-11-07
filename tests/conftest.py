import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
FIXTURES = Path(__file__).parent / "fixtures"

# Each skill's scripts are standalone; put them all on the path for tests.
for scripts in sorted(SKILLS.glob("*/scripts")):
    sys.path.insert(0, str(scripts))


@pytest.fixture
def fake_http():
    """An http_get double that serves saved responses by URL substring."""

    def make(routes: dict[str, str]):
        calls = []

        def get(url, headers=None):
            calls.append(url)
            for needle, filename in routes.items():
                if needle in url:
                    return (FIXTURES / filename).read_bytes()
            raise AssertionError(f"Unexpected request: {url}")

        get.calls = calls
        return get

    return make
