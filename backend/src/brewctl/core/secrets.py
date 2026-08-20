"""
Reading secrets from files rather than the environment.

Docker secrets (and TrueNAS app secrets, and plain bind-mounts) surface as
*files*, not environment variables, so config that only reads `os.environ` cannot
see them. This adds the conventional `<VAR>_FILE` indirection: point
`BREWCTL_INFLUXDB_TOKEN_FILE` at `/run/secrets/influxdb_token` and the value is
read from there.

The payoff is that the secret never appears in `docker inspect`, in the compose
file, or in the TrueNAS app config -- which is what makes the deployment manifest
safe to commit to git.
"""

import os

from .log import logger


class SecretConfigError(RuntimeError):
    """A `<VAR>_FILE` was configured but the file could not be read."""


def read_secret(name: str, default: str = "") -> str:
    """
    Resolve `name`, preferring `<name>_FILE` if it is set.

    Raises rather than falling back when `<name>_FILE` is set but unreadable. A
    silent fallback would hand InfluxDB an empty token and surface as an opaque
    401 on the first write -- i.e. potentially hours into a brew -- instead of a
    startup failure naming the actual problem.
    """
    path = os.environ.get(f"{name}_FILE")
    if path:
        try:
            with open(path) as f:
                value = f.read().strip()
        except OSError as e:
            raise SecretConfigError(
                f"{name}_FILE is set to {path!r} but it could not be read: {e}"
            ) from e
        if not value:
            raise SecretConfigError(f"{name}_FILE is set to {path!r} but the file is empty")
        logger.info(f"{name} loaded from {path}")
        return value

    return os.environ.get(name, default)
