import time

from brewclient.config import *
from BrewClient import BrewClient

def main():
    """The main function of the script."""
    interval = COLDBREW_VALVE_INTERVAL_SECONDS

    with BrewClient(COLDBREW_VALVE_URL) as valve:
        # TODO block until current flow rate decreases
        while True:
            # get the current flow rate
            print("====")
            current_flow_rate = valve.get_current_flow_rate()
            print(f"got result: {current_flow_rate}")
            if current_flow_rate is None:
                print("result is none")
                time.sleep(interval)
                continue

            elif abs(COLDBREW_TARGET_FLOW_RATE - current_flow_rate) <= COLDBREW_EPSILON:
                print("just right")
                time.sleep(interval * 2)
                continue
            # TODO should consider microadjustments here
            elif current_flow_rate <= COLDBREW_TARGET_FLOW_RATE:
                print("too slow")
                valve.step_forward()
            else:
                print("too fast")
                valve.step_backward()

            # TODO can just check the weight from the scale here
            time.sleep(interval)

        # TODO investigate this further, not enough torque?
        #valve.return_to_start()

        valve.release()


if __name__ == "__main__":
    main()

