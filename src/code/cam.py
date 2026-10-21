"""Detect coloured tiles from an ESP32-CAM stream and send state messages over UDP."""

import socket
import time
import cv2
import numpy as np
import requests

# Network
ESP_IP = "192.168.2.35"
UDP_PORT = 4210
SERVER_ADDRESS = (ESP_IP, UDP_PORT)
CAMERA_URL = "http://192.168.2.88"
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Detection parameters 
MIN_AREA_TILE = 4800    
MIN_AREA_PARKING = 1500 
MAX_COUNT = 50           
# (name, HSV lower bound, HSV upper bound)
COLOURS = [
    ("BLUE", (100, 100, 70), (120, 255, 255)),
    ("RED", (165, 90, 65), (180, 255, 255)),
    ("GREEN", (60, 40, 70), (85, 255, 255)),
    ("YELLOW", (20, 50, 70), (63, 110, 255)),
]
# Messages
SEARCHING = "searching"
PARK = "park"
# Camera/display settings
TARGET_FPS = 12
FRAME_INTERVAL = 1.0 / TARGET_FPS
FRAMESIZE_QVGA = 6
CROP_ROWS = slice(0, 120)
CROP_COLS = slice(0, 300)
# Tracking state (indices into COLOURS)
first_idx = None
second_idx = None
search_count = 0


def set_camera_setting(variable, value):
    """Set a camera parameter over HTTP; return True on success."""
    try:
        response = requests.get(
            f"{CAMERA_URL}/control",
            params={"var": variable, "val": value},
            timeout=2,
        )
        response.raise_for_status()
        print(f"Set {variable} = {value}")
        return True
    except requests.RequestException as e:
        print(f"Error setting {variable}: {e}")
        return False


def configure_camera():
    """Apply the camera settings used by this script."""
    print("\nConfiguring ESP32-CAM...")
    set_camera_setting("framesize", FRAMESIZE_QVGA)


def capture_frame():
    """Grab one frame from the camera; return None on failure."""
    try:
        response = requests.get(f"{CAMERA_URL}/capture", timeout=2)
        response.raise_for_status()
        image_array = np.frombuffer(response.content, dtype=np.uint8)
        return cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    except requests.RequestException as e:
        print(f"Capture error: {e}")
        return None


def send_state(msg, repeats=1):
    """Send a UDP message to the ESP32, optionally repeated."""
    encoded = msg.encode()
    for _ in range(repeats):
        sock.sendto(encoded, SERVER_ADDRESS)


def find_colour(low, high, min_area, hsv_img, bgr_img):
    """Return True if a contour above min_area is found; draw its bounding box."""
    found = False
    mask = cv2.inRange(hsv_img, low, high)
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        if cv2.contourArea(cnt) > min_area:
            x, y, w, h = cv2.boundingRect(cnt)
            cv2.rectangle(bgr_img, (x, y), (x + w, y + h), (255, 0, 0), 2)
            found = True
    return found


def reset_tracking():
    """Clear detected colours so the search starts again."""
    global first_idx, second_idx, search_count
    first_idx = None
    second_idx = None
    search_count = 0


def track(frame):
    """Detect tile colours in a frame and send the matching state message."""
    global first_idx, second_idx, search_count
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    if first_idx is None:
        # Stage 1: look for the first reference colour
        for i, (name, low, high) in enumerate(COLOURS):
            if find_colour(low, high, MIN_AREA_TILE, hsv, frame):
                first_idx = i
                print("First colour:", name)
                send_state(f"{SEARCHING} 1", 5)

    elif search_count < MAX_COUNT:
        # Stage 2: look for a different, second colour for MAX_COUNT frames
        for i, (name, low, high) in enumerate(COLOURS):
            if i != first_idx and find_colour(low, high, MIN_AREA_TILE, hsv, frame):
                second_idx = i
                print("Second colour:", name)
                send_state(f"{SEARCHING} 2", 5)
        search_count += 1

    else:
        # Stage 3: look for a parking bay tile in the reference colour(s)
        selected = [first_idx]
        if second_idx is not None:
            selected.append(second_idx)
        for i in selected:
            _, low, high = COLOURS[i]
            if find_colour(low, high, MIN_AREA_PARKING, hsv, frame):
                send_state(f"{PARK} {1 if i == first_idx else 2}")


def main():
    """Run the capture loop until 'q' is pressed ('r' resets tracking)."""
    configure_camera()
    time.sleep(0.5)

    frame_count = 0
    actual_fps = 0.0
    fps_start = time.perf_counter()
    next_capture = time.perf_counter()

    while True:
        # Hold the target frame rate
        now = time.perf_counter()
        if now < next_capture:
            time.sleep(next_capture - now)

        capture_start = time.perf_counter()
        frame = capture_frame()
        capture_end = time.perf_counter()

        if frame is None:
            print("Failed to capture frame")
            next_capture = time.perf_counter() + FRAME_INTERVAL
            continue

        # Update the measured FPS once per second
        frame_count += 1
        elapsed = capture_end - fps_start
        if elapsed >= 1.0:
            actual_fps = frame_count / elapsed
            frame_count = 0
            fps_start = capture_end
        capture_ms = (capture_end - capture_start) * 1000.0

        frame = frame[CROP_ROWS, CROP_COLS]
        cv2.putText(frame, f"FPS: {actual_fps:.1f}", (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.putText(frame, f"Capture: {capture_ms:.1f} ms", (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        track(frame)
        cv2.imshow("ESP32-CAM", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            print("Reset")
            reset_tracking()

        next_capture += FRAME_INTERVAL
        if next_capture < time.perf_counter():
            next_capture = time.perf_counter()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()