"""Local high-CPU process skill — never a web search."""

from __future__ import annotations

from arka.core.processes import format_process_table, route_command, wants_cpu_processes


def test_wants_show_high_cpu_processes() -> None:
    assert wants_cpu_processes("show high CPU processes")
    assert wants_cpu_processes("show cpu stats")
    assert wants_cpu_processes("what is using my cpu")
    assert wants_cpu_processes("list top processes")
    assert not wants_cpu_processes("what happened in usa today")
    assert not wants_cpu_processes("Caterpillar CES keynote")


def test_route_is_local_skill() -> None:
    assert route_command("show high CPU processes") == "processes cpu"
    assert route_command("show cpu stats") == "processes stats"
    assert route_command("highest ram processes") == "processes mem"
    assert route_command("who is the president") == ""


def test_cpu_stats_is_local_not_lscpu() -> None:
    from arka.core.processes import cpu_stats

    text = cpu_stats(limit=3)
    assert "not web search" in text
    assert "lscpu" in text  # appears as "not lscpu/htop advice"
    assert "htop advice" in text
    assert "Cores:" in text


def test_table_mentions_live_ps() -> None:
    text = format_process_table(
        [{"pid": 412, "cpu": 38.2, "mem": 2.1, "user": "me", "command": "WindowServer"}],
        sort="cpu",
    )
    assert "38.2" in text
    assert "WindowServer" in text
    assert "not web search" in text
