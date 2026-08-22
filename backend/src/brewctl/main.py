import os

from brewctl.core.log import logger


def _apply_networking_from_env() -> None:
    """Values come from the control host's env file via compose env_file (see
    deploy/control/app.yaml). Unset everywhere else -- dev and the bare-metal
    Pi. Wrapped in a function so the entrypoint stays tidy and tests can stub."""
    from brewctl.core.container_net import apply_container_networking, parse_extra_hosts

    raw_extra = os.getenv("BREWCTL_EXTRA_HOSTS")
    if raw_extra:
        apply_container_networking(extra_hosts=parse_extra_hosts(raw_extra))
    raw_dns = os.getenv("BREWCTL_DNS_SERVER")
    if raw_dns:
        apply_container_networking(dns=raw_dns)


_apply_networking_from_env()

mode = os.getenv("BREWCTL_MODE", "api")

if mode == "hardware":
    logger.info("starting hardware mode")
    from brewctl.hardware.server import app
elif mode == "api":
    logger.info("starting api mode")
    from brewctl.api.server import app
else:
    raise ValueError(f"Unknown BREWCTL_MODE: {mode}")
