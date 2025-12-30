from adafruit_motorkit import MotorKit
from adafruit_motor import stepper
from valve import Valve


class MotorKitValve(Valve):
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

    def flip_direction(self, direction):
        if direction is stepper.FORWARD:
            return stepper.BACKWARD
        elif direction is stepper.BACKWARD:
            return stepper.FORWARD
        else:
            raise RuntimeError(f"invalid direction {direction}")

    def directions_to_start(self, breadcrumbs):
        # find which of the counts is larger, then return the reverse
        max_direction = max(breadcrumbs, key=breadcrumbs.get)
        opp = self.flip_direction(max_direction)
        count = breadcrumbs[max_direction]
        return (opp, count)

    def step_forward(self):
        direction = stepper.FORWARD
        self.step(direction)

    def step_backward(self):
        direction = stepper.BACKWARD
        self.step(direction)

    # TODO "should be private"
    def step(self, direction):
        # update breadcrumbs so we can get back to starting position
        if direction not in self.breadcrumbs:
            self.breadcrumbs[direction] = 0
        self.breadcrumbs[direction] += 1

        self.motor.onestep(direction=direction)


    def return_to_start(self):
        (opp, count) = self.directions_to_start(self.breadcrumbs)

        # rotate motor certain number of times
        for i in range(count):
            #self.motor.onestep(direction=opp)
            self.step(opp)

        # TODO have an opportunity here to reset breadcrumbs or do any sanity checks
        print("returned to start")
        print(self.breadcrumbs)
        self.reset_breadcrumbs()
        self.release()


    def release(self):
        self.motor.release()