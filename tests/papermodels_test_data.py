"""
Locates the papermodels test drawings (tests/test_data/*.pdf in the papermodels
repository) for the integration tests. They are not in the papermodels package,
so they are taken from, in order:

1. the directory in the PAPERMODELS_TEST_DATA environment variable
2. a papermodels checkout next to this repository (../papermodels)
3. the papermodels repository on GitHub, at the version that is installed: the
   release tag (e.g. v0.22.4) of a PyPI install, or the commit of a git install.
   They are downloaded once and cached in
   LOADTRACER_CACHE_DIR (default ~/.cache/loadtracer).

Returns None when none of these is available (e.g. offline).
"""

import io
import json
import os
import pathlib
import shutil
import tarfile
import tempfile
import urllib.request
from importlib import metadata
from typing import Optional

REPOSITORY = "StructuralPython/papermodels"
TEST_DATA_DIR = "tests/test_data"
SIBLING_CHECKOUT = pathlib.Path(__file__).parents[2] / "papermodels" / TEST_DATA_DIR


def papermodels_test_data() -> Optional[pathlib.Path]:
    if os.environ.get("PAPERMODELS_TEST_DATA"):
        return pathlib.Path(os.environ["PAPERMODELS_TEST_DATA"])
    if SIBLING_CHECKOUT.exists():
        return SIBLING_CHECKOUT
    try:
        return download_test_data(installed_ref())
    except OSError:
        return None


def installed_ref() -> str:
    """The git commit or tag of the installed papermodels."""
    distribution = metadata.distribution("papermodels")
    direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
    commit = direct_url.get("vcs_info", {}).get("commit_id")
    return commit or f"v{distribution.version}"


def download_test_data(ref: str) -> pathlib.Path:
    cache_dir = pathlib.Path(
        os.environ.get("LOADTRACER_CACHE_DIR", pathlib.Path.home() / ".cache" / "loadtracer")
    )
    target = cache_dir / "papermodels-test-data" / ref
    if target.exists():
        return target
    url = f"https://codeload.github.com/{REPOSITORY}/tar.gz/{ref}"
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = io.BytesIO(response.read())
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        staging = pathlib.Path(tmp) / "test_data"
        staging.mkdir()
        with tarfile.open(fileobj=archive, mode="r:gz") as tar:
            for member in tar.getmembers():
                # Members are "<repo>-<ref>/tests/test_data/<name>"
                parts = pathlib.PurePosixPath(member.name).parts
                if member.isfile() and "/".join(parts[1:-1]) == TEST_DATA_DIR:
                    with tar.extractfile(member) as src, open(staging / parts[-1], "wb") as dst:
                        shutil.copyfileobj(src, dst)
        staging.rename(target)  # Only complete downloads are cached
    return target
