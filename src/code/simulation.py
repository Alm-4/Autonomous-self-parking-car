"""Simulate the car finding a matching parking spot, reverse-parking, then exiting.

Coordinates: x-y system with the origin at the top left of the image.
theta = 0 rad points right and increases clockwise. Scale is 1 px : 1 mm.
"""

import cv2 as cv
import numpy as np
import random as rand

# Parking space and tile dimensions
SPACE_WIDTH = 65
TILE_WIDTH = SPACE_WIDTH
TILE_HEIGHT = 10
# Car dimensions and steering
CAR_LENGTH = 179
CAR_WIDTH = 79
WHEELBASE = 120
TURN_ANGLE = 27  # degrees
TURN_RADIUS = WHEELBASE / np.tan(np.deg2rad(TURN_ANGLE))
# Car starting position
START_X = 30 + CAR_LENGTH / 2
START_Y = 165
# Parking lot layout 
TRACK_IMAGE_PATH = r".files/ColouredInTrack.png" # change if needed
TRACK_END_X = 1489 + CAR_LENGTH / 2
SPOT_X = [398, 518, 638, 758, 877, 997, 1117, 1237]
NUM_SPOTS = len(SPOT_X)
TILE_Y = 554                # y position of the coloured tile gaps
OCCUPIED_CAR_Y = 356        # y position inside the marked parking rectangles
PARKED_CAR_X_OFFSET = -7    # centres a car on its coloured tile gap
# Reversing parameter
PARKING_FRONT_TARGET_Y = 170
# Camera and sensor parameters 
CAR_FRONT_CENTER_LOCAL = (CAR_LENGTH, 0)
CAR_REAR_CENTER_LOCAL = (0, 0)
CAR_BOTTOM_CENTER_LOCAL = (CAR_LENGTH / 2, CAR_WIDTH)
START_AREA_THRESHOLD = 50  # px
# Colours (BGR)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
COLOURS_BGR = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255)]
COLOUR_NAMES = ["Blue", "Green", "Red", "Yellow"]
# Speeds (px per frame)
SPEED = 1
REVERSE_SPEED = 0.5
# States 
SEARCHING = "SEARCHING"
ALIGNING = "ALIGNING"
TURNING = "TURNING"
REVERSING = "REVERSING"
PARKED = "PARKED"
EXITING = "EXITING"
EXITING_TURN = "EXITING_TURN"
# Simulation state
spots = list(range(NUM_SPOTS)) # spots not yet given a coloured tile
x_car, y_car = START_X, START_Y
theta_car = 0 # rad - pointing right
initial_colour = None
second_colour = None
state = SEARCHING
turn_y = None           # px
target_x_range = None   # px


def cast_ray(img, x, y, theta, stop_fn, max_dist):
    """Step along a ray; return (distance, colour) at the first pixel where stop_fn is true."""
    h, w = img.shape[:2]
    for d in range(max_dist):
        px = int(round(x + d * np.cos(theta)))
        py = int(round(y + d * np.sin(theta)))
        if px < 0 or px >= w or py < 0 or py >= h:
            return d, None
        colour = tuple(int(c) for c in img[py, px])
        if stop_fn(colour):
            return d, colour
    return max_dist, None


def camera_sensor(img, x, y, theta, max_dist=500):
    """Return the first coloured (not white or black) pixel along a ray, or None."""
    _, colour = cast_ray(img, x, y, theta, lambda c: c != WHITE and c != BLACK, max_dist)
    return colour


def range_sensor(img, x, y, theta, max_dist=2000):
    """Return the distance along a ray to the first black pixel."""
    distance, _ = cast_ray(img, x, y, theta, lambda c: c == BLACK, max_dist)
    return distance


def colour_name(colour):
    """Return the name of a BGR colour from COLOURS_BGR."""
    return COLOUR_NAMES[COLOURS_BGR.index(colour)]


def setup(img):
    """Draw the random coloured tiles, parked cars and bicoloured start tile."""
    # Coloured empty parking spaces
    num_spaces = rand.randrange(1, NUM_SPOTS + 1)
    for _ in range(num_spaces):
        col = rand.choice(COLOURS_BGR)
        n = rand.choice(spots)
        spots.remove(n)

        x = SPOT_X[n]
        y = TILE_Y

        cv.rectangle(img, (x, y), (x + TILE_WIDTH - 1, y + TILE_HEIGHT - 1), col, cv.FILLED)

    # Non-empty spaces
    for spot in spots:
        x = SPOT_X[spot] + PARKED_CAR_X_OFFSET
        y = OCCUPIED_CAR_Y
        cv.rectangle(img, (x, y), (x + CAR_WIDTH - 1, y + CAR_LENGTH - 1), BLACK, cv.FILLED)

    # Bicoloured start tile
    start_colour = rand.choice(COLOURS_BGR)
    second_colour = rand.choice(COLOURS_BGR)
    marker_x, marker_y = 230, 326
    mid_x = marker_x + TILE_WIDTH // 2
    end_x = marker_x + TILE_WIDTH - 1
    end_y = marker_y + TILE_HEIGHT - 1

    cv.rectangle(img, (marker_x, marker_y), (mid_x - 1, end_y), start_colour, cv.FILLED)
    cv.rectangle(img, (mid_x, marker_y), (end_x, end_y), second_colour, cv.FILLED)


def local_to_global_coords(local_pt, x, y, theta):
    """Convert a point relative to the car into global image coordinates."""
    lx, ly = local_pt
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    gx = x + lx * cos_t - ly * sin_t
    gy = y + lx * sin_t + ly * cos_t
    return gx, gy


def draw_car(x, y, theta, img):
    """Draw the car as a filled black rotated rectangle."""
    pt = (int(x), int(y + CAR_WIDTH / 2))
    rect = cv.boxPoints((pt, (CAR_LENGTH, CAR_WIDTH), np.rad2deg(theta)))
    box = np.int32(rect)

    cv.fillPoly(img, [box], BLACK)


def steer(speed):
    """Move the car one step along its turning arc (negative speed reverses)."""
    global x_car, y_car, theta_car

    new_theta = theta_car + (speed / TURN_RADIUS)

    x_car += TURN_RADIUS * (np.sin(new_theta) - np.sin(theta_car))
    y_car -= TURN_RADIUS * (np.cos(new_theta) - np.cos(theta_car))

    theta_car = new_theta


def start_aligning(colour, range_reading):
    """Set how far to drive past the matched tile, then switch to ALIGNING."""
    global state, target_x_range

    # Go past the tile to give the needed turning room
    target_x_range = (range_reading + TURN_RADIUS + CAR_LENGTH / 2 + SPACE_WIDTH / 2
                      + (SPACE_WIDTH - CAR_WIDTH) / 2 - PARKED_CAR_X_OFFSET)

    print(f"Match found: {colour_name(colour)} -> aligning")
    state = ALIGNING


def find_spot():
    """Drive along the lot, remember the start tile colours and detect a matching spot."""
    global x_car, y_car, initial_colour, second_colour

    # Rear range sensor reading
    range_x, range_y = local_to_global_coords(CAR_REAR_CENTER_LOCAL, x_car, y_car, theta_car)
    range_reading = range_sensor(img, range_x, range_y, theta_car + np.pi)
    in_starting_area = range_reading < START_AREA_THRESHOLD

    # Camera points downwards
    cam_x, cam_y = local_to_global_coords(CAR_BOTTOM_CENTER_LOCAL, x_car, y_car, theta_car)
    seen_colour = camera_sensor(img, cam_x, cam_y, theta_car + np.pi / 2)

    if seen_colour is not None and seen_colour in COLOURS_BGR:
        if in_starting_area:
            # Remember the starting tile colours
            if initial_colour is None:
                initial_colour = seen_colour
                print("colour found: " + colour_name(seen_colour))
            elif second_colour is None and seen_colour != initial_colour:
                second_colour = seen_colour
                print("second colour found: " + colour_name(seen_colour))

        elif initial_colour is not None and seen_colour == initial_colour:
            start_aligning(seen_colour, range_reading)
            initial_colour = None
            return

        elif second_colour is not None and seen_colour == second_colour:
            start_aligning(seen_colour, range_reading)
            second_colour = None
            return

    # Drive forward until the end is reached
    if x_car <= TRACK_END_X:
        x_car += SPEED * np.cos(theta_car)
        y_car += SPEED * np.sin(theta_car)


def align_to_spot():
    """Drive forward until past the spot, then switch to TURNING."""
    global x_car, state

    # Rear range sensor reading
    range_x, range_y = local_to_global_coords(CAR_REAR_CENTER_LOCAL, x_car, y_car, theta_car)
    range_reading = range_sensor(img, range_x, range_y, theta_car + np.pi)

    x_car += SPEED

    if range_reading >= target_x_range:
        state = TURNING


def park():
    """Run one step of the turning, reversing, exiting and exit-turn states."""
    global x_car, y_car, state, turn_y

    if state == TURNING:
        steer(-REVERSE_SPEED)

        if theta_car <= -np.pi / 2:
            state = REVERSING
            # Store the front distance for exiting
            range_x, range_y = local_to_global_coords(CAR_FRONT_CENTER_LOCAL, x_car, y_car, theta_car)
            turn_y = range_sensor(img, range_x, range_y, theta_car)

    elif state == REVERSING:
        # Front range sensor reading
        range_x, range_y = local_to_global_coords(CAR_FRONT_CENTER_LOCAL, x_car, y_car, theta_car)
        range_reading = range_sensor(img, range_x, range_y, theta_car)

        y_car += REVERSE_SPEED

        if range_reading >= PARKING_FRONT_TARGET_Y:
            state = PARKED
            print("Parked.")

    elif state == EXITING:
        # Front range sensor reading
        range_x, range_y = local_to_global_coords(CAR_FRONT_CENTER_LOCAL, x_car, y_car, theta_car)
        range_reading = range_sensor(img, range_x, range_y, theta_car)

        if range_reading >= turn_y:
            x_car += REVERSE_SPEED * np.cos(theta_car)
            y_car += REVERSE_SPEED * np.sin(theta_car)
        else:
            state = EXITING_TURN

    elif state == EXITING_TURN:
        steer(REVERSE_SPEED)

        if theta_car >= 0:
            state = SEARCHING
            print("Exited")


def main():
    """Run the simulation until 'q' is pressed."""
    global state

    print("Search started")

    while True:
        if cv.waitKey(1) == ord("q"):
            break

        if state == SEARCHING:
            find_spot()
        elif state == ALIGNING:
            align_to_spot()
        elif state in (TURNING, REVERSING, EXITING, EXITING_TURN):
            park()
        elif state == PARKED:
            state = EXITING
            park()

        img_car = img.copy()
        draw_car(x_car, y_car, theta_car, img_car)
        cv.imshow("Simulation", img_car)

    cv.destroyAllWindows()


img = cv.imread(TRACK_IMAGE_PATH)
setup(img)

if __name__ == "__main__":
    main()