#!/usr/bin/env python3
import json
import os
import tempfile

CONF = "/etc/docker/daemon.json"
REGISTRY = "YOUR_REGISTRY_IP:PORT"

def main():
    os.makedirs(os.path.dirname(CONF), exist_ok=True)

    data = {}
    if os.path.exists(CONF):
        try:
            with open(CONF) as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {}

    regs = data.setdefault("insecure-registries", [])
    if REGISTRY in regs:
        return False  # nothing to do

    regs.append(REGISTRY)

    # atomic write
    dir_ = os.path.dirname(CONF)
    fd, tmp_path = tempfile.mkstemp(dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, CONF)
    except Exception:
        os.unlink(tmp_path)
        raise

    return True

if __name__ == "__main__":
    changed = main()
    if changed:
        os.system("systemctl restart docker")
