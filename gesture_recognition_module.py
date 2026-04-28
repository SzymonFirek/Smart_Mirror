import cv2
import mediapipe as mp
import time
import threading
import queue


class GestureRecognizer(threading.Thread):
    def __init__(
        self,
        gesture_queue=None,
        camera_index=0,
        camera_backend=cv2.CAP_V4L2,
        swipe_hand_mode="open",  # zostawione dla kompatybilności, nieużywane
        debug=False,
        show_preview=False,      # podgląd kamery do testów
    ):
        super().__init__()
        self.daemon = True

        self.gesture_queue = gesture_queue or queue.Queue()
        self.camera_index = camera_index
        self.camera_backend = camera_backend
        self.swipe_hand_mode = swipe_hand_mode
        self.debug = debug
        self.show_preview = show_preview

        # Kierunki: statyczne pozy dłoni
        # one  -> swipe_left
        # two  -> swipe_right
        self.POSE_HOLD_FRAMES = 5
        self.POSE_COOLDOWN = 0.2
        self.POSE_RELEASE_FRAMES = 3

        # OK params
        self.OK_COOLDOWN = 1.0
        self.OK_HOLD_FRAMES = 4
        self.OK_RELEASE_FRAMES = 3

        # State
        self.last_pose_emit_time = 0.0
        self.last_ok_end_time = 0.0

        self.current_pose = None
        self.pose_streak = 0

        # aktywny gest kierunkowy - żeby nie zapętlało przy trzymaniu pozy
        self.pose_active = None
        self.pose_release_streak = 0

        self.ok_active = False
        self.ok_streak = 0
        self.ok_release_streak = 0

        self.prev_hand_state = None
        self.prev_pose_debug = None

        self._stop_event = threading.Event()

        # MediaPipe
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6,
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

                # lustrzane odbicie jest wygodniejsze do testów gestów
                frame = cv2.flip(frame, 1)

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self.hands.process(rgb)

                now = time.time()
                emitted_label = None

                if results.multi_hand_landmarks:
                    hand = results.multi_hand_landmarks[0]

                    if self.show_preview:
                        self.mp_drawing.draw_landmarks(
                            frame,
                            hand,
                            self.mp_hands.HAND_CONNECTIONS
                        )

                    hand_state = self.get_hand_state(hand)

                    if self.debug and hand_state != self.prev_hand_state:
                        print("DEBUG hand_state:", hand_state)
                        self.prev_hand_state = hand_state

                    # 1) OK ma priorytet i zostaje statyczny
                    is_ok = self.is_ok_gesture(hand)

                    if is_ok:
                        self.ok_streak += 1
                        self.ok_release_streak = 0
                    else:
                        self.ok_streak = 0
                        if self.ok_active:
                            self.ok_release_streak += 1
                            if self.ok_release_streak >= self.OK_RELEASE_FRAMES:
                                self.ok_active = False
                                self.last_ok_end_time = now
                                self.ok_release_streak = 0
                        else:
                            self.ok_release_streak = 0

                    if (
                        is_ok
                        and not self.ok_active
                        and self.ok_streak >= self.OK_HOLD_FRAMES
                        and (now - self.last_ok_end_time > self.OK_COOLDOWN)
                    ):
                        if self.debug:
                            print("GEST: OK")

                        self.gesture_queue.put("ok")
                        self.ok_active = True
                        self.ok_release_streak = 0
                        emitted_label = "ok"

                        # reset pozy kierunkowych po OK
                        self.current_pose = None
                        self.pose_streak = 0
                        self.pose_active = None
                        self.pose_release_streak = 0

                    # 2) Kierunki jako statyczne pozy
                    if not is_ok:
                        pose = self.classify_direction_pose(hand)

                        # obsługa "puszczenia" wcześniej wyemitowanego gestu
                        if self.pose_active is not None:
                            if pose != self.pose_active:
                                self.pose_release_streak += 1
                                if self.pose_release_streak >= self.POSE_RELEASE_FRAMES:
                                    self.pose_active = None
                                    self.pose_release_streak = 0
                            else:
                                self.pose_release_streak = 0

                        # zwykłe zliczanie stabilnej pozy
                        if pose == self.current_pose and pose is not None:
                            self.pose_streak += 1
                        elif pose is not None:
                            self.current_pose = pose
                            self.pose_streak = 1
                        else:
                            self.current_pose = None
                            self.pose_streak = 0

                        if self.debug and pose != self.prev_pose_debug:
                            print("DEBUG pose:", pose)
                            self.prev_pose_debug = pose

                        # emituj tylko jeśli poza jest stabilna
                        # i nie jest aktualnie aktywna
                        if (
                            pose is not None
                            and pose == self.current_pose
                            and self.pose_streak >= self.POSE_HOLD_FRAMES
                            and self.pose_active is None
                            and (now - self.last_pose_emit_time > self.POSE_COOLDOWN)
                        ):
                            if pose == "one":
                                gesture = "swipe_left"
                            elif pose == "two":
                                gesture = "swipe_right"
                            else:
                                gesture = None

                            if gesture:
                                if self.debug:
                                    print("GEST:", gesture)

                                self.gesture_queue.put(gesture)
                                self.last_pose_emit_time = now
                                emitted_label = gesture

                                # zapamiętaj, że ten gest jest już "wciśnięty"
                                self.pose_active = pose
                                self.pose_release_streak = 0

                    if self.show_preview:
                        self.draw_debug_overlay(
                            frame=frame,
                            hand_state=hand_state,
                            pose=self.current_pose,
                            pose_streak=self.pose_streak,
                            ok_streak=self.ok_streak,
                            emitted=emitted_label,
                        )

                else:
                    self.current_pose = None
                    self.pose_streak = 0
                    self.ok_streak = 0

                    # zwalnianie aktywnego gestu kierunkowego
                    if self.pose_active is not None:
                        self.pose_release_streak += 1
                        if self.pose_release_streak >= self.POSE_RELEASE_FRAMES:
                            self.pose_active = None
                            self.pose_release_streak = 0
                    else:
                        self.pose_release_streak = 0

                    # zwalnianie aktywnego OK
                    if self.ok_active:
                        self.ok_release_streak += 1
                        if self.ok_release_streak >= self.OK_RELEASE_FRAMES:
                            self.ok_active = False
                            self.last_ok_end_time = now
                            self.ok_release_streak = 0
                    else:
                        self.ok_release_streak = 0

                    if self.show_preview:
                        self.draw_debug_overlay(
                            frame=frame,
                            hand_state="no_hand",
                            pose=None,
                            pose_streak=0,
                            ok_streak=0,
                            emitted=None,
                        )

                if self.show_preview:
                    cv2.imshow("GestureRecognizer demo", frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27 or key == ord("q"):
                        self.stop()
                        break

        finally:
            if self.cap is not None:
                self.cap.release()
            self.hands.close()
            if self.show_preview:
                cv2.destroyAllWindows()

    def draw_debug_overlay(self, frame, hand_state, pose, pose_streak, ok_streak, emitted):
        lines = [
            f"hand_state: {hand_state}",
            f"pose: {pose}",
            f"pose_streak: {pose_streak}",
            f"pose_active: {self.pose_active}",
            f"pose_release: {self.pose_release_streak}",
            f"ok_streak: {ok_streak}",
            f"ok_active: {self.ok_active}",
            f"ok_release: {self.ok_release_streak}",
            f"emit: {emitted or '-'}",
            "one=index only -> LEFT",
            "two=index+middle -> RIGHT",
            "q / ESC -> quit",
        ]

        y = 30
        for line in lines:
            cv2.putText(
                frame,
                line,
                (10, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            y += 28

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
    def get_finger_states(hand_landmarks):
        """
        Zwraca dict:
        {
            "thumb": bool,
            "index": bool,
            "middle": bool,
            "ring": bool,
            "pinky": bool
        }
        Na start kciuk liczymy pomocniczo, ale logika one/two
        opiera się głównie o index/middle/ring/pinky.
        """
        lm = hand_landmarks.landmark

        def is_finger_extended(tip_id, pip_id):
            return lm[tip_id].y < lm[pip_id].y

        # bardzo uproszczone dla kciuka — tylko pomocniczo
        thumb_extended = abs(lm[4].x - lm[3].x) > 0.03

        return {
            "thumb": thumb_extended,
            "index": is_finger_extended(8, 6),
            "middle": is_finger_extended(12, 10),
            "ring": is_finger_extended(16, 14),
            "pinky": is_finger_extended(20, 18),
        }

    @classmethod
    def classify_direction_pose(cls, hand_landmarks):
        """
        Statyczne pozy kierunkowe:
        - one: wyprostowany tylko wskazujący -> LEFT
        - two: wyprostowany wskazujący i środkowy -> RIGHT

        Kciuk ignorujemy, żeby nie psuł stabilności.
        """
        fs = cls.get_finger_states(hand_landmarks)

        index_ = fs["index"]
        middle_ = fs["middle"]
        ring_ = fs["ring"]
        pinky_ = fs["pinky"]

        # only index
        if index_ and not middle_ and not ring_ and not pinky_:
            return "one"

        # index + middle
        if index_ and middle_ and not ring_ and not pinky_:
            return "two"

        return None

    @classmethod
    def get_hand_state(cls, hand_landmarks):
        """
        Zachowane dla debugowania / kompatybilności.
        """
        fs = cls.get_finger_states(hand_landmarks)
        extended = sum([
            fs["index"],
            fs["middle"],
            fs["ring"],
            fs["pinky"],
        ])

        if extended == 4:
            return "open"
        elif extended <= 1:
            return "fist"
        else:
            return "other"


def _demo():
    """
    Demo do uruchamiania bezpośrednio na RPi:
    python gesture_recognition_module.py

    Pokazuje podgląd z kamery i wypisuje rozpoznane gesty.
    """
    gq = queue.Queue()
    recognizer = GestureRecognizer(
        gesture_queue=gq,
        swipe_hand_mode="open",
        debug=True,
        show_preview=True,
    )
    recognizer.start()

    print("GestureRecognizer demo running.")
    print("Gest ONE (sam wskazujący) -> swipe_left")
    print("Gest TWO (wskazujący + środkowy) -> swipe_right")
    print("Gest OK -> ok")
    print("Press q in preview window or Ctrl+C in terminal to stop.\n")

    try:
        while recognizer.is_alive():
            try:
                gesture = gq.get(timeout=0.2)
                print("DEMO got gesture:", gesture)
            except queue.Empty:
                pass
    except KeyboardInterrupt:
        print("\nStopping demo...")
    finally:
        recognizer.stop()
        recognizer.join()
        print("Demo stopped.")


if __name__ == "__main__":
    _demo()