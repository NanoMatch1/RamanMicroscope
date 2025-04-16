class DummyStage:

    def __init__(self):
        self.stage_positions = {'X': 3, 'Y': 3, 'Z': 3}

    def calculate_relative_motion(self, target_positions):

        # relative_motion = []
        current_positions = [self.stage_positions['X'], self.stage_positions['Y'], self.stage_positions['Z']]

        relative_motion = [target_positions[0] - current_positions[0], target_positions[1] - current_positions[1], target_positions[2] - current_positions[2]]

        return relative_motion
    

test = DummyStage()
print(test.calculate_relative_motion([1, 2, 3]))
print(test.calculate_relative_motion([4, 5, 6]))

