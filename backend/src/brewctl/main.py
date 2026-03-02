import os

mode = os.getenv("BREWCTL_MODE", "api")

if mode == "hardware":
    #from .src.brewctl.main import app
    print("starting hardware mode")
elif mode == "api":
    print("starting api mode")
    #from backend.src.brewctl.server import app
else:
    raise ValueError(f"Unknown BREWCTL_MODE: {mode}")