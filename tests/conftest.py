import sys

import pytest

# Clean up namespace packages pre-loaded by global environment site-packages .pth files
# (e.g. google_cloud_aiplatform-*-nspkg.pth) to maintain domain provider-purity invariants.
for _mod in ("google", "google.cloud"):
    sys.modules.pop(_mod, None)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
