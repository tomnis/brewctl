import os

mode = os.getenv("BREWCTL_MODE", "api")

if mode == "hardware":
    print("starting hardware mode")
    from brewctl.hardware.server import app
elif mode == "api":
    print("starting api mode")
    from brewctl.api.server import app
else:
    raise ValueError(f"Unknown BREWCTL_MODE: {mode}")
