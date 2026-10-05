import os

import pytest

from gold_intelligence.credentials import credential_environment


def test_explicit_key_file_is_scoped_and_restores_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "existing")
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    path = tmp_path / "keys.env"
    path.write_text('# local credentials\nFRED_API_KEY="temporary"\nALPHAVANTAGE_API_KEY=testkey\n')
    with credential_environment(path):
        assert os.environ["FRED_API_KEY"] == "temporary"
        assert os.environ["ALPHAVANTAGE_API_KEY"] == "testkey"
    assert os.environ["FRED_API_KEY"] == "existing"
    assert "ALPHAVANTAGE_API_KEY" not in os.environ


@pytest.mark.parametrize(
    "content",
    [
        "UNKNOWN=secret",
        "FRED_API_KEY=secret\nFRED_API_KEY=again",
        "FRED_API_KEY=$(secret)",
        "FRED_API_KEY=secret with spaces",
    ],
)
def test_invalid_credentials_never_echo_values(tmp_path, content):
    path = tmp_path / "keys.env"
    path.write_text(content)
    with pytest.raises(ValueError) as error, credential_environment(path):
        pytest.fail("invalid credential file was loaded")
    assert "secret" not in str(error.value)


def test_keys_are_restored_after_failure_and_blanks_preserve_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "existing")
    path = tmp_path / "keys.env"
    path.write_text("FRED_API_KEY=\n")
    with pytest.raises(RuntimeError), credential_environment(path):
        assert os.environ["FRED_API_KEY"] == "existing"
        raise RuntimeError("test failure")
    assert os.environ["FRED_API_KEY"] == "existing"
