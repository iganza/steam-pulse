"""Test fixtures for infra synth tests.

The OpenNext bundles under `frontend/.open-next/` are build artifacts (not
committed). CDK synth requires those directories to exist; in CI without a
prior `open-next build`, ComputeStack would error before assertions ran.
The autouse fixture stubs whichever bundle directories are missing so synth
can proceed.
"""

from __future__ import annotations

import pathlib

import pytest

_BUNDLES = (
    "frontend/.open-next/server-functions/default",
    "frontend/.open-next/revalidation-function",
)


@pytest.fixture(autouse=True)
def _stub_opennext_bundles() -> None:
    """Create stub OpenNext bundle dirs when missing (CI without frontend build)."""
    for rel in _BUNDLES:
        path = pathlib.Path(rel)
        if path.exists():
            continue
        path.mkdir(parents=True, exist_ok=True)
        (path / "index.mjs").write_text(
            "export const handler = async () => ({ statusCode: 200 });\n"
        )
