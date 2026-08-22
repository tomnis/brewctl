"""Container-side networking config applied at process start.

The deployment manifest no longer carries `dns:` / `extra_hosts:` literals --
those values are delivered as container environment variables via compose
`env_file` (see deploy/control/app.yaml) and applied here, to the files the
libc resolver actually reads. env_file cannot parametrize compose-level keys
(it sets container env, it does not interpolate the compose file), which is why
this module exists rather than a ${VAR} in the manifest.

IPv4-only: BREWCTL_EXTRA_HOSTS pins use host:ipv4 pairs (an IPv6 address would
need bracket syntax and unambiguous separators; add deliberately if ever
needed).

Only acts on variables that are set: dev machines and the bare-metal Pi never
define them. Malformed values raise -- same policy as core.secrets: refuse to
start rather than degrade silently.
"""

import ipaddress
import re
from pathlib import Path

from brewctl.core.log import logger

_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9_.-]*[A-Za-z0-9])?$")


def parse_extra_hosts(raw: str) -> list[tuple[str, str]]:
    """Parse comma-separated `host:ip` pairs (compose extra_hosts syntax).

    Raises ValueError on malformed entries -- including hostnames containing
    anything outside [A-Za-z0-9_.-], so nothing unexpected can be written into
    /etc/hosts.
    """
    entries = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        host, sep, ip = part.rpartition(":")
        if not sep or not host or not ip:
            raise ValueError(f"BREWCTL_EXTRA_HOSTS: expected host:ip, got {part!r}")
        if not _HOSTNAME_RE.match(host):
            raise ValueError(f"BREWCTL_EXTRA_HOSTS: invalid hostname {host!r}")
        ipaddress.ip_address(ip)  # raises ValueError on garbage
        entries.append((host, ip))
    return entries


def _ensure_line(path: Path, line: str) -> bool:
    """Append `line` unless an equivalent line is already present.

    Returns True if written. Tolerates files missing their trailing newline and
    treats surrounding whitespace as insignificant when deduplicating.
    """
    existing = path.read_text() if path.exists() else ""
    if line.strip() in {l.strip() for l in existing.splitlines()}:
        return False
    with path.open("a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(line)
    return True


def apply_container_networking(
    dns: str | None = None,
    extra_hosts: list[tuple[str, str]] | None = None,
    resolv_conf: str | Path = "/etc/resolv.conf",
    hosts_file: str | Path = "/etc/hosts",
) -> None:
    if dns is not None:
        ipaddress.ip_address(dns)  # raises ValueError on garbage
        if _ensure_line(Path(resolv_conf), f"nameserver {dns}\n"):
            logger.info("container_net: nameserver %s added to %s", dns, resolv_conf)
    for host, ip in extra_hosts or []:
        if _ensure_line(Path(hosts_file), f"{ip}\t{host}\n"):
            logger.info("container_net: pinned %s -> %s in %s", host, ip, hosts_file)
