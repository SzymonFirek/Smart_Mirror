import cv2
import mediapipe as mp
import time
from collections import deque
import threading
import queue


class GestureRecognizer(threading.Thread):
    def __init__(
        self,
        gesture_queue=None,
        camera_index=0,
        camera_backend=cv2.CAP_V4L2,
        swipe_hand_mode="open",  # "open" or "fist"
        debug=False,
    ):
        super().__init__()
        self.daemon = True

        self.gesture_queue = gesture_queue or queue.Queue()
        self.camera_index = camera_index
        self.camera_backend = camera_backend
        self.swipe_hand_mode = swipe_hand_mode
        self.debug = debug

        # Swipe params (horizontal and vertical separately)
        self.SWIPE_DIST_X_FRAC = 0.20   # 20% of width
        self.SWIPE_MIN_SPEED_X_FRAC = 0.25

        self.SWIPE_DIST_Y_FRAC = 0.15   # 15% of height (a bit easier)
        self.SWIPE_MIN_SPEED_Y_FRAC = 0.20

        self.SWIPE_COOLDOWN = 0.5

        # OK params
        self.OK_COOLDOWN = 1.0

        # State
        self.positions = deque(maxlen=4)
        self.last_swipe_time = 0.0
        self.ok_active = False
        self.last_ok_end_time = 0.0

        self.prev_ok_active = False
        self.prev_hand_state = None

        self._stop_event = threading.Event()

        # MediaPipe
        self.hands = mp.solutions.hands.Hands(
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        self.cap = None

    def stop(self):
        self._stop_event.set()

    def run(self):
        self.cap = cv2.VideoCapture(self.camera_index, self.camera_backend)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        try:
            while not self._stop_event.is_set():
                ret, frame = self.cap.read()
                if not ret:
                    continue

                h, w, _ = frame.shape

                # thresholds dependent on resolution
                horiz_dist_threshold = self.SWIPE_DIST_X_FRAC * w
                horiz_speed_threshold = self.SWIPE_MIN_SPEED_X_FRAC * w

                vert_dist_threshold = self.SWIPE_DIST_Y_FRAC * h
                vert_speed_threshold = self.SWIPE_MIN_SPEED_Y_FRAC * h

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self.hands.process(rgb)

                now = time.time()

                if results.multi_hand_landmarks:
                    hand = results.multi_hand_landmarks[0]

                    hand_state = self.get_hand_state(hand)
                    open_hand_flag = hand_state == "open"
                    fist_flag = hand_state == "fist"

                    if self.debug and hand_state != self.prev_hand_state:
                        print(
                            "DEBUG hand_state:",
                            hand_state,
                            "open_hand_flag:",
                            open_hand_flag,
                            "fist_flag:",
                            fist_flag,
                        )
                        self.prev_hand_state = hand_state

                    # center of hand (middle finger MCP, landmark 9)
                    cx = int(hand.landmark[9].x * w)
                    cy = int(hand.landmark[9].y * h)

                    self.positions.append((now, cx, cy))

                    # Swipe detection for selected hand shape
                    if hand_state == self.swipe_hand_mode and len(self.positions) >= 3:
                        t0, x0, y0 = self.positions[0]
                        t1, x1, y1 = self.positions[-1]

                        dt = t1 - t0
                        if dt > 0:
                            dx = x1 - x0
                            dy = y1 - y0

                            # separate thresholds for horizontal vs vertical
                            if abs(dx) > abs(dy):
                                # horizontal swipe
                                dist_x = abs(dx)
                                speed_x = dist_x / dt

                                if (
                                    dist_x > horiz_dist_threshold
                                    and speed_x > horiz_speed_threshold
                                    and (now - self.last_swipe_time > self.SWIPE_COOLDOWN)
                                ):
                                    # mirror: dx > 0 means visual move right, user hand moves left
                                    gesture = "swipe_left" if dx > 0 else "swipe_right"

                                    if self.debug:
                                        print("GEST:", gesture)

                                    self.gesture_queue.put(gesture)
                                    self.last_swipe_time = now
                                    self.positions.clear()
                            else:
                                # vertical swipe
                                dist_y = abs(dy)
                                speed_y = dist_y / dt

                                if (
                                    dist_y > vert_dist_threshold
                                    and speed_y > vert_speed_threshold
                                    and (now - self.last_swipe_time > self.SWIPE_COOLDOWN)
                                ):
                                    gesture = "swipe_down" if dy > 0 else "swipe_up"

                                    if self.debug:
                                        print("GEST:", gesture)

                                    self.gesture_queue.put(gesture)
                                    self.last_swipe_time = now
                                    self.positions.clear()

                    # OK gesture with edge detection and cooldown after release
                    self.prev_ok_active = self.ok_active
                    is_ok = self.is_ok_gesture(hand)

                    if is_ok:
                        if (
                            not self.ok_active
                            and (now - self.last_ok_end_time > self.OK_COOLDOWN)
                        ):
                            if self.debug:
                                print("GEST: OK")
                            self.gesture_queue.put("ok")
                            self.ok_active = True
                    else:
                        if self.ok_active:
                            self.ok_active = False
                            self.last_ok_end_time = now

                    if self.debug and self.ok_active != self.prev_ok_active:
                        print("DEBUG ok_active:", self.ok_active)

        finally:
            if self.cap is not None:
                self.cap.release()
            self.hands.close()

    @staticmethod
    def is_ok_gesture(hand_landmarks):
        lm = hand_landmarks.landmark

        thumb = lm[4]
        index = lm[8]

        wrist = lm[0]
        middle_mcp = lm[9]

        hand_size = (
            (wrist.x - middle_mcp.x) ** 2 + (wrist.y - middle_mcp.y) ** 2
        ) ** 0.5
        if hand_size < 1e-5:
            return False

        dist_ok = (
            (thumb.x - index.x) ** 2 + (thumb.y - index.y) ** 2
        ) ** 0.5 / hand_size

        if dist_ok > 0.4:
            return False

        other_tips = [lm[12], lm[16], lm[20]]
        for tip in other_tips:
            d = (
                (thumb.x - tip.x) ** 2 + (thumb.y - tip.y) ** 2
            ) ** 0.5 / hand_size
            if d < 0.7:
                return False

        return True

    @staticmethod
    def get_hand_state(hand_landmarks):
        """
        Count extended fingers (index, middle, ring, little)
        4 extended -> "open"
        1 or less extended -> "fist"
        else -> "other"
        """
        lm = hand_landmarks.landmark

        def is_finger_extended(tip_id, pip_id):
            return lm[tip_id].y < lm[pip_id].y

        extended = 0
        if is_finger_extended(8, 6):
            extended += 1
        if is_finger_extended(12, 10):
            extended += 1
        if is_finger_extended(16, 14):
            extended += 1
        if is_finger_extended(20, 18):
            extended += 1

        if extended == 4:
            return "open"
        elif extended <= 1:
            return "fist"
        else:
            return "other"


def _demo():
    """
    Simple demo when running this file directly:
    python gesture_recognition_module.py
    """
    gq = queue.Queue()
    recognizer = GestureRecognizer(
        gesture_queue=gq,
        swipe_hand_mode="open",
        debug=True,
    )
    recognizer.start()

    print("GestureRecognizer demo running.")
    print("Show gestures to the camera (OK, swipes).")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            gesture = gq.get()
            print("DEMO got gesture:", gesture)
    except KeyboardInterrupt:
        print("\nStopping demo...")
    finally:
        recognizer.stop()
        recognizer.join()
        print("Demo stopped.")


if __name__ == "__main__":
    _demo()
