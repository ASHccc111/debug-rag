"""The live verifier must not spend or report hybrid success on weak evidence."""

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from debug_rag.errors import RagError


@pytest.fixture
def verifier():
    path = Path(__file__).resolve().parents[2] / "scripts/verify_bge_remote.py"
    spec = importlib.util.spec_from_file_location("bge_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verifier_configuration_failure_does_not_print_input(verifier, monkeypatch, capsys):
    def invalid_settings():
        raise ValidationError.from_exception_data(
            "Settings",
            [
                {
                    "type": "extra_forbidden",
                    "loc": ("unknown_key",),
                    "input": "private-fixture-value",
                }
            ],
        )

    monkeypatch.setattr(verifier, "Settings", invalid_settings)
    assert verifier.main([]) == 2
    assert verifier.main(["--allow-paid"]) == 2
    output = capsys.readouterr().out
    assert "invalid_local_configuration" in output
    assert "private-fixture-value" not in output


@pytest.mark.parametrize(
    "dense,sparse,source",
    [
        ([], ["hit"], "demo-file-export"),
        (["hit"], [], "demo-file-export"),
        (["hit"], ["hit"], "other-source"),
    ],
)
def test_hybrid_verification_rejects_missing_route_or_wrong_evidence(
    verifier, dense, sparse, source
):
    with pytest.raises(RagError) as caught:
        verifier.validate_retrieval(
            {
                "trace": {"dense": dense, "sparse": sparse},
                "context": [{"source_key": source}],
            }
        )
    assert caught.value.code == "hybrid_verification_failed"
