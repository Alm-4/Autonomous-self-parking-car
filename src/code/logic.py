"""MicroPython car controller: drives forward and reverse-parks on UDP commands."""

import network
import socket
import time
from machine import Pin, PWM, time_pulse_us

# WiFi
SSID = "ENGMT280"
PASSWORD = "engmt280"
UDP_PORT = 4210
# Pins
P_SERVO = 32
P_MOTOR_DIR = 26
P_MOTOR_PWM = 25
P_MOTOR_MODE = 27
P_SENSOR_BACK = 16
P_SENSOR_RIGHT_FRONT = 4
# Motor and servo settings
SERVO_FREQ = 50
MOTOR_FREQ = 1000
FORWARD_SPEED = 65535
# Servo duty values (~50 = left, ~60 = straight, ~70 = right)
R_MAX = 75
L_MAX = 45
STRAIGHT = 59
# Distances in mm
BACK_P = 37
BACK_MIN = 350
# Back sensor distance ranges, and the matching distance needed in front of each spot
BACK_DIST = [330, 540, 750, 960, 1170, 1380, 1590, 1800, 2010, 2220, 2430]
PARK_D = [610, 770, 980, 1090, 1250, 1410, 1570, 1730]
# Park commands (one per spot) and whether each spot has been used
PARK_COMMANDS = ("park 1", "park 2")
parked = [False, False]
# States
PARK = "park"
FORWARD = "forward"
STOP = "stop"
state = FORWARD
# Hardware
motor_mode = Pin(P_MOTOR_MODE, Pin.OUT, value=1)
motor_dir = Pin(P_MOTOR_DIR, Pin.OUT)
motor_pwm = PWM(Pin(P_MOTOR_PWM, Pin.OUT), freq=MOTOR_FREQ, duty_u16=0)
servo_pwm = PWM(Pin(P_SERVO, Pin.OUT), freq=SERVO_FREQ, duty=60)
sens_b = Pin(P_SENSOR_BACK, Pin.IN)
sens_r_f = Pin(P_SENSOR_RIGHT_FRONT, Pin.IN)
server = None


def sensor_val(pin, timeout_us=1000000):
    """Read a range sensor in mm; return None if there is no valid reading."""
    try:
        t = time_pulse_us(pin, 1, timeout_us)
        if t <= 1000:
            return None
        return 4 * (t - 1000)
    except OSError:
        return None
 
 
def read_valid(pin):
    """Read a range sensor repeatedly until a valid reading is returned."""
    value = None
    while value is None:
        value = sensor_val(pin)
    return value
 
 
def turn(duty):
    """Set the steering servo duty."""
    servo_pwm.duty(duty)
 
 
def motor(speed, direction="forward"):
    """Drive the motor; any direction other than "forward" is reverse."""
    motor_dir.value(0 if direction == "forward" else 1)
    motor_pwm.duty_u16(speed)
 
 
def stop():
    """Stop the drive motor."""
    motor_pwm.duty_u16(0)
 
 
def connect_wifi():
    """Connect to WiFi (up to ~20 tries) and print the car's IP."""
    tries = 0
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    while not wlan.isconnected() and tries <= 20:
        print("waiting")
        time.sleep_ms(200)
        tries += 1
    print("Car IP:", wlan.ifconfig()[0])
 
 
def start_server():
    """Open a non-blocking UDP socket on UDP_PORT."""
    global server
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("0.0.0.0", UDP_PORT))
    server.settimeout(0.01)
 
 
def get_req(sock):
    """Return the received UDP message, or None if nothing arrived."""
    try:
        data, _ = sock.recvfrom(1024)
    except OSError:  # timeout / no data
        return None
    return data.decode()
 
 
def start_move(steering, direction):
    """Stop, set the steering, then drive at full speed in the given direction."""
    stop()
    time.sleep_ms(SETTLE_MS)
    turn(steering)
    time.sleep_ms(SETTLE_MS)
    motor(FORWARD_SPEED, direction)
 
 
def park():
    """Drive ahead of the chosen spot, then reverse-park into it."""
    motor(FORWARD_SPEED)
 
    # Read the current distance on the back sensor
    d_back = None
    while d_back is None:
        time.sleep_ms(50)
        d_back = sensor_val(sens_b)
 
    # Find the distance in front of the spot that is needed
    d_needed = -1
    for i, d in enumerate(BACK_DIST):
        if d_back <= d + BACK_TOLERANCE:
            d_needed = PARK_D[i]
            break
    print("d_needed", d_needed)
 
    # Get far enough ahead of the spot (two readings past the target)
    num = 0
    while num < 2:
        temp = sensor_val(sens_b)
        if temp is not None:
            print(temp, num)
            if temp >= d_needed - AHEAD_TOLERANCE:
                num += 1
    print("back1", temp)
 
    # Reverse (turning left) until near the wall
    start_move(L_MAX, "reverse")
    right = read_valid(sens_r_f)
    while right < WALL_FAR:
        right = read_valid(sens_r_f)
    print("right final", right)
 
    # Forward (turning right) until close to the wall
    start_move(R_MAX, "forward")
    right = read_valid(sens_r_f)
    while right > WALL_NEAR:
        right = read_valid(sens_r_f)
    print("final right1", right)
 
    # Reverse (turning left) into the spot
    start_move(L_MAX, "reverse")
    back = read_valid(sens_b)
    while back > BACK_P:
        back = read_valid(sens_b)
    print("back final", back)
 
    stop()
    turn(STRAIGHT)
 
 
def drive():
    """Main loop: drive forward and park when a matching UDP command arrives."""
    global state
    motor(FORWARD_SPEED)
    try:
        while True:
            req = get_req(server)
            if req is None:
                continue
 
            back = sensor_val(sens_b) or 0
            for spot, command in enumerate(PARK_COMMANDS):
                if command in req and not parked[spot] and back > BACK_MIN:
                    state = PARK
                    parked[spot] = True
                    break
 
            if state == FORWARD:
                motor(FORWARD_SPEED)
            elif state == PARK:
                park()
                state = STOP
            elif state == STOP:
                stop()
    except KeyboardInterrupt:
        pass
 
 
def init():
    """Connect to WiFi and start the UDP server."""
    connect_wifi()
    start_server()