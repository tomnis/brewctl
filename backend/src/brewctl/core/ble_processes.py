"""Orphaned bluepy-helper hygiene for the Lunar BLE connection.

Each failed LunarScale connect attempt can leak its `bluepy-helper` child with
a half-established HCI link (the GATT layer times out after the controller has
already accepted the connection). The leaked link holds the scale's single
connection slot, so every later attempt refuses with "Failed to connect to
peripheral" until the orphan dies -- observed live on coldbrewer, where two
accumulated orphans kept recovery loop churning forever
(docs/plans/scale-recovery-stability-plan.md).

Scope rules, both required:
- process name (`/proc/<pid>/comm`, exact match) is `helper_name`;
- the process belongs to the service cgroup (`cgroup_marker` appears in
  `/proc/<pid>/cgroup`) -- so helpers of other units, other users, and dev
  machines are never touched.

Exact comm matching is deliberate: `pkill -f bluepy-helper` matches its own
invoking shell's command line and kills it (observed live). Killing is paired,
by callers, with an unconditional rebuild of the scale object so a false
positive on a live attempt self-heals on the next try.
"""

import os
import signal
from pathlib import Path

PROC = Path("/proc")


def select_orphan_helpers(
    rows: dict[int, tuple[str, str]], helper_name: str, cgroup_marker: str
) -> list[int]:
    """Pure selection over {pid: (comm, cgroup_text)} rows.

    Returns pids whose comm matches exactly AND whose cgroup text contains the
    marker. Everything else -- init, other units' helpers, our own shell --
    is ignored.
    """
    return sorted(
        pid
        for pid, (comm, cgroup) in rows.items()
        if comm == helper_name and cgroup_marker in cgroup
    )


def _read_proc_rows(proc: Path) -> dict[int, tuple[str, str]]:
    """Best-effort snapshot of {pid: (comm, cgroup_text)} under proc."""
    rows: dict[int, tuple[str, str]] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            cgroup = (entry / "cgroup").read_text()
        except OSError:
            # The process died mid-read, or it is not ours to inspect.
            continue
        rows[int(entry.name)] = (comm, cgroup)
    return rows


def kill_orphaned_helpers(
    cgroup_marker: str = "brewctl-hardware.service",
    helper_name: str = "bluepy-helper",
    proc: Path = PROC,
    sig: int = signal.SIGTERM,
) -> list[int]:
    """SIGTERM orphaned helpers matching the scope rules. Returns pids signaled.

    Tolerates processes dying between listing and signaling. Callers pair this
    with rebuilding their scale object: if a live attempt's helper is caught
    (it should not be -- connects are serialized), that attempt fails and
    retries cleanly.
    """
    victims = select_orphan_helpers(_read_proc_rows(proc), helper_name, cgroup_marker)
    for pid in victims:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    return victims
