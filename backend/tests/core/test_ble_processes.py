"""Tests for orphaned bluepy-helper selection and signaling.

The scope rules are the whole safety story: exact comm match AND service-cgroup
membership. Anything looser risks killing unrelated processes -- tonight's
debugging session proved `pkill -f bluepy-helper` matches its own invoking
shell's command line and kills it, which is why this module matches comm
exactly instead of using command-line globs.
"""

import signal
from pathlib import Path

from brewctl.core.ble_processes import kill_orphaned_helpers, select_orphan_helpers

MARKER = "brewctl-hardware.service"


def _rows():
    return {
        1: ("systemd", "0::/init.scope"),
        100: ("bluepy-helper", f"0::/system.slice/{MARKER}"),
        101: ("bluepy-helper", "0::/system.slice/other.service"),
        102: ("python3", f"0::/system.slice/{MARKER}"),
        # comm with a space must not match: selection compares /proc/<pid>/comm
        # exactly, so command-line substring tricks cannot leak in.
        103: ("bluepy helper", f"0::/system.slice/{MARKER}"),
    }


def test_selects_only_helpers_inside_the_service_cgroup():
    assert select_orphan_helpers(_rows(), "bluepy-helper", MARKER) == [100]


def test_selects_multiple_matching_helpers_in_pid_order():
    rows = _rows()
    rows[50] = ("bluepy-helper", f"0::/system.slice/{MARKER}")
    assert select_orphan_helpers(rows, "bluepy-helper", MARKER) == [50, 100]


def test_empty_when_nothing_matches():
    assert select_orphan_helpers({}, "bluepy-helper", MARKER) == []
    assert select_orphan_helpers(_rows(), "never-matches", MARKER) == []


def _fake_proc(root: Path, rows: dict) -> Path:
    for pid, (comm, cgroup) in rows.items():
        d = root / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "comm").write_text(comm + "\n")
        (d / "cgroup").write_text(cgroup + "\n")
    return root


def test_kill_signals_only_the_selected_pids(tmp_path, monkeypatch):
    """Integration through kill_orphaned_helpers against a fake /proc tree."""
    signaled = []

    def fake_kill(pid, sig):
        signaled.append(pid)

    monkeypatch.setattr("brewctl.core.ble_processes.os.kill", fake_kill)

    victims = kill_orphaned_helpers(
        cgroup_marker=MARKER,
        proc=_fake_proc(tmp_path, _rows()),
        sig=signal.SIGTERM,
    )

    assert victims == [100]
    assert signaled == [100]


def test_kill_tolerates_dead_processes(tmp_path):
    """A pid listed but gone before signaling must not raise."""
    rows = {404: ("bluepy-helper", f"0::/system.slice/{MARKER}")}
    # Default signaling against a nonexistent pid raises ProcessLookupError,
    # which the killer swallows; the selection result is still reported.
    victims = kill_orphaned_helpers(
        cgroup_marker=MARKER, proc=_fake_proc(tmp_path, rows)
    )
    assert victims == [404]
