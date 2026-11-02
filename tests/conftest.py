"""Keep disposable test files in the workspace, independent of Windows temp ACLs."""

from pathlib import Path
from uuid import uuid4


def pytest_configure(config):
    if config.option.basetemp is None:
        root = Path(__file__).resolve().parents[1] / "runtime" / "test-runs"
        root.mkdir(parents=True, exist_ok=True)
        # Fresh path: pytest may clear its own basetemp, never a user-selected directory.
        target = root / uuid4().hex
        assert not target.exists()
        config.option.basetemp = str(target)
