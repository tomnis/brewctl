import time

from adafruit_motorkit import MotorKit
from adafruit_motor import stepper
from valve import AbstractValve, STEPS_PER_REVOLUTION


def flip_direction(direction):
    if direction is stepper.FORWARD:
        return stepper.BACKWARD
    elif direction is stepper.BACKWARD:
        return stepper.FORWARD
    else:
        raise RuntimeError(f"invalid direction {direction}")


class MotorKitValve(AbstractValve):
    """
    A thin wrapper around the Adafruit MotorKit stepper motor controller to implement a valve.
    Uses breadcrumbs to keep track of how far we've moved in each direction, so we can return
    to the starting position.
    """
    def __init__(self, motor_number: int=1):
        # keep track of which direction we've moved in and how many steps
        self.breadcrumbs = dict()

        self.kit = MotorKit()
        if motor_number == 1:
            self.motor = self.kit.stepper1
        elif motor_number == 2:
            self.motor = self.kit.stepper2
        else:
            raise ValueError("motor_number must be 1 or 2")

    def directions_to_return_to_start(self):
        # find which of the counts is larger, then return the reverse
        if len(self.breadcrumbs) == 0:
            return None, 0
        max_direction = max(self.breadcrumbs, key=self.breadcrumbs.get)
        opp = flip_direction(max_direction)
        count = self.breadcrumbs[max_direction]
        return opp, count

    def step_forward(self):
        """Step the valve one step forward."""
        direction = stepper.FORWARD
        self.step(direction)

    def step_backward(self):
        """Step the valve one step backward."""
        direction = stepper.BACKWARD
        self.step(direction)

    # TODO "should be private"
    def step(self, direction):
        # update breadcrumbs so we can get back to starting position
        if direction not in self.breadcrumbs:
            self.breadcrumbs[direction] = 0
        self.breadcrumbs[direction] += 1

        self.motor.onestep(direction=direction, style=stepper.INTERLEAVE)


    def return_to_start(self):
        (opp, count) = self.directions_to_return_to_start()

        # rotate motor certain number of times
        for i in range(count):
            #self.motor.onestep(direction=opp)
            self.step(opp)

        # TODO have an opportunity here to reset breadcrumbs or do any sanity checks
        print(self.breadcrumbs)
        print("returned to start")
        self.breadcrumbs = dict()
        time.sleep(1.0)
        self.release()


    def release(self):
        self.motor.release()

    def get_position(self) -> int:
        """Get current absolute position (0-199 for one full rotation).
        
        Calculates net position from breadcrumbs: forward steps minus backward steps,
        then takes modulo 200 for absolute position within one revolution.
        """
        forward_count = self.breadcrumbs.get(stepper.FORWARD, 0)
        backward_count = self.breadcrumbs.get(stepper.BACKWARD, 0)
        net_position = forward_count - backward_count
        return abs(net_position) % STEPS_PER_REVOLUTION
