import os

from brewctl.core.log import logger
mode = os.getenv("BREWCTL_MODE", "api")

if mode == "hardware":
    logger.info("starting hardware mode")
    from brewctl.hardware.server import app
elif mode == "api":
    logger.info("starting api mode")
    from brewctl.api.server import app
else:
    raise ValueError(f"Unknown BREWCTL_MODE: {mode}")
