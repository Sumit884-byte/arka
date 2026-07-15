from arka.core.notifications import notify


def test_notifications_can_be_disabled(monkeypatch, capsys):
    monkeypatch.setenv("ARKA_NOTIFICATIONS", "0")
    notify("Test", "message")
    assert capsys.readouterr().out == ""
