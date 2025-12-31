import time

from brewclient.config import *
from brewclient.brew_client import BrewClient

def main():
    """The main function of the script."""
    interval = COLDBREW_VALVE_INTERVAL_SECONDS

    # using resource semantics to acquire and release a brew
    with BrewClient(COLDBREW_VALVE_URL) as brew_client:
        # TODO block until current flow rate decreases
        while True:
            # get the current flow rate
            print("====")
            current_flow_rate = brew_client.get_current_flow_rate()
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
                brew_client.step_forward()
            else:
                print("too fast")
                brew_client.step_backward()

            # TODO can just check the weight from the scale here
            time.sleep(interval)

        # TODO investigate this further, not enough torque?
        #valve.return_to_start()

        brew_client.release()


if __name__ == "__main__":
    main()

