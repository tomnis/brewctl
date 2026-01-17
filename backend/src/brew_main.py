from appserver.config import *
from appserver.brew_client import HttpBrewClient
from brewserver.brew_strategy import DefaultBrewStrategy

def main():
    """The main function of the script."""
    strategy = DefaultBrewStrategy()

    # using resource semantics to acquire and release a brew
    with HttpBrewClient(strategy, COLDBREW_VALVE_URL) as brew_client:
        # TODO block until current flow rate decreases
        brew_client.do_brew()

        # TODO investigate this further, not enough torque?
        #valve.return_to_start()

        # brew_client.release()

if __name__ == "__main__":
    main()