from pathlib import Path
from unittest.mock import patch

from arka.agent.dev_tools import security_scan


def test_security_scan_flags_secret(tmp_path: Path) -> None:
    with patch("arka.agent.dev_tools._run", return_value=(0, "config.py\0", "")):
        (tmp_path / "config.py").write_text("API_KEY = 'abcdefghijklmnop'\n", encoding="utf-8")
        findings = security_scan(tmp_path)
    assert findings[0]["kind"] == "secret"


def test_security_scan_clean_repo(tmp_path: Path) -> None:
    with patch("arka.agent.dev_tools._run", return_value=(0, "safe.py\0", "")):
        (tmp_path / "safe.py").write_text("print('ok')\n", encoding="utf-8")
        assert security_scan(tmp_path) == []
