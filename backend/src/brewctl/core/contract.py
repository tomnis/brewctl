"""
The api <-> hardware wire contract.

Deliberately its own module rather than part of `core/config.py`: that module is
consumed via `import *` chains (core.config -> api.config -> model -> server), and
these names should not be star-exported into half the codebase. There is also no
env lookup here -- these are literals, so there is no import-time config hazard.

The two services deploy independently and on different schedules. The api runs in
Docker on the control host and updates automatically; the hardware service runs bare metal
on the Pi and only changes when someone pushes to it by hand. The Pi can therefore
lag the api indefinitely, and "forgot to push to the Pi" is the expected failure
rather than an edge case. This version is what lets the api notice.

Bump HARDWARE_API_VERSION whenever the hardware HTTP surface changes in a way the
api depends on, and raise MIN_HARDWARE_API_VERSION only when the api genuinely
cannot function against the older contract -- raising it blocks brewing until the
Pi is updated.

History:
  1 -- POST /api/valve/heartbeat, and a watchdog that closes the valve when
       heartbeats stop. Reported in /health and in the heartbeat response.
  2 -- Scale health. /health and the scale status payloads gain "healthy" and
       "last_weight_age_seconds", and a monitor task reconnects a scale that is
       connected but no longer streaming readings. The api's brew gate reads
       "healthy"; a v1 Pi omits it, which the api treats as "unknown, allow".
"""

HARDWARE_API_VERSION = 2

# The oldest hardware the api will start a brew against.
MIN_HARDWARE_API_VERSION = 1

# What the api assumes when the hardware service reports no version at all --
# i.e. a Pi running a build from before this contract existed.
UNKNOWN_HARDWARE_API_VERSION = 0
