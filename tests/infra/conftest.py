"""Test fixtures for infra synth tests.

The OpenNext bundles under `frontend/.open-next/` are build artifacts (not
committed). CDK synth reads them via `Code.from_asset`, so without a prior
`open-next build` ComputeStack would error before assertions ran. The
autouse fixture redirects the module-level bundle paths to per-test
temp dirs containing stub `index.mjs` files — keeping the working tree
untouched so a missing real build still fails loudly during `cdk deploy`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_BUNDLE_PATH_VARS = (
    "stacks.compute_stack._OPEN_NEXT_SERVER",
    "stacks.compute_stack._OPEN_NEXT_REVALIDATION",
)


@pytest.fixture(autouse=True)
def _stub_opennext_bundles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point bundle paths at per-test temp dirs with a stub entrypoint."""
    for i, dotted in enumerate(_BUNDLE_PATH_VARS):
        bundle = tmp_path / f"opennext-bundle-{i}"
        bundle.mkdir()
        (bundle / "index.mjs").write_text(
            "export const handler = async () => ({ statusCode: 200 });\n"
        )
        monkeypatch.setattr(dotted, str(bundle))
