from arka.agent.ui_copy_audit import audit
from arka.routing.symbolic import route_ui_copy


def test_duplicate_button_and_chip_labels(tmp_path):
    (tmp_path / "App.tsx").write_text("<button>Save</button>\n<Chip> save </Chip>\n")
    findings = audit(str(tmp_path))
    assert findings[0]["phrase"] == "save"
    assert len(findings[0]["occurrences"]) == 2


def test_route_ui_copy():
    assert route_ui_copy("find duplicate button phrases in src") == "ui_copy src"
