import os
import shutil
import cv2
import numpy as np
import face_recognition
import time
import threading

def encode_face_image(image_path):
    """
    Załaduj obraz, wykryj twarz i zakoduj ją do wektora 128-dim.
    Zwraca encoding (np.ndarray) lub None jeśli nie wykryto twarzy.
    """
    image = face_recognition.load_image_file(image_path)
    encodings = face_recognition.face_encodings(image)
    if len(encodings) > 0:
        return encodings[0]
    else:
        print(f"Nie wykryto twarzy na obrazku {image_path}")
        return None

def save_face_data(user_name, image_path, encoding):
    """
    Zapisuje encoding i kopiuje obraz do folderu known_faces/user_name/
    """
    target_dir = os.path.join("known_faces", user_name)
    os.makedirs(target_dir, exist_ok=True)

    encoding_path = os.path.join(target_dir, "encoding.npy")
    np.save(encoding_path, encoding)

    image_dst = os.path.join(target_dir, os.path.basename(image_path))
    # kopiuj plik tylko jeśli różne ścieżki
    if os.path.abspath(image_path) != os.path.abspath(image_dst):
        shutil.copyfile(image_path, image_dst)
    else:
        print(f"Plik {image_path} już znajduje się w docelowym folderze, kopiowanie pominięte.")

def load_known_encodings(base_dir="Dane_users/known_faces"):
    """
    Wczytuje wszystkie encodings z podfolderów base_dir.
    Zwraca dict: {user_name: encoding}
    """
    known_encodings = {}
    if not os.path.exists(base_dir):
        return known_encodings

    for user_name in os.listdir(base_dir):
        user_folder = os.path.join(base_dir, user_name)
        encoding_path = os.path.join(user_folder, "encoding.npy")
        if os.path.isfile(encoding_path):
            encoding = np.load(encoding_path)
            known_encodings[user_name] = encoding
    return known_encodings


class FaceRecognitionModule:
    """
    Odporny moduł rozpoznawania twarzy z kamerą:
    - nie otwiera kamery w __init__, tylko dopiero w wątku rozpoznawania,
    - automatycznie ponownie otwiera kamerę, jeśli read() się nie udaje,
    - start jest idempotentny (nie uruchamia drugiego wątku),
    - ensure_running() „wskrzesza” kamerę/wątek bez ryzyka duplikacji,
    - stop_recognition() prawidłowo uwalnia zasoby.
    """

    def __init__(self, known_users, base_dir="Dane_users/known_faces", camera_index=0, backend=None):
        """
        known_users: lista MirrorUser (z user_id i name)
        Ładuje encodings z dysku i tworzy listę do rozpoznawania.
        """
        self.base_dir = base_dir
        self.known_users = known_users
        self.known_encodings = []
        self.known_ids = []

        # Parametry rozpoznawania
        self.RECOGNITION_TIMEOUT = 5.0  # sekundy maks. dla pojedynczego cyklu startu
        self.TOLERANCE = 0.6

        # Kamera / wątek
        self.camera_index = camera_index
        self.backend = cv2.CAP_V4L2 if backend is None else backend  # V4L2 jest stabilniejsze na RPi
        self.camera = None
        self.running = False
        self.recognition_thread = None
        self.lock = threading.Lock()
        self._callback = None

        # Odporność na błędy odczytu
        self._fail_reads = 0
        self._READ_SLEEP = 0.02
        self._REOPEN_AFTER_FAILS = 30  # po tylu błędnych odczytach zrobimy reopen
        self._WARMUP_FRAMES = 5

        # Załaduj encodings
        for user in known_users:
            user_dir = os.path.join(base_dir, user.name)
            encoding_path = os.path.join(user_dir, "encoding.npy")
            if os.path.isfile(encoding_path):
                encoding = np.load(encoding_path)
                self.known_encodings.append(encoding)
                self.known_ids.append(user.user_id)
            else:
                print(f"Brak encodingu dla użytkownika {user.name} w {encoding_path}")

    # ---------------- Kamera: otwieranie / zamykanie ----------------
    def _open_camera(self):
        """Otwórz kamerę bezpiecznie; zwróć True/False."""
        self._close_camera()

        cam = cv2.VideoCapture(self.camera_index, self.backend)
        # parametry minimalizujące lag
        try:
            cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        if not cam.isOpened():
            print("[CAM] Nie można otworzyć kamery.")
            return False

        # krótka rozgrzewka – odczytaj kilka klatek
        for _ in range(self._WARMUP_FRAMES):
            cam.read()
            time.sleep(0.02)

        self.camera = cam
        self._fail_reads = 0
        return True

    def _close_camera(self):
        if self.camera is not None:
            try:
                self.camera.release()
            except Exception:
                pass
        self.camera = None

    # ---------------- Sterowanie wątkiem ----------------
    def start_recognition_thread(self, callback):
        """
        Start idempotentny: jeśli już działa, tylko upewnia kamerę.
        """
        with self.lock:
            self._callback = callback
            if self.recognition_thread and self.recognition_thread.is_alive():
                # wątek żyje – upewnij się, że kamera jest otwarta
                if self.camera is None or (not self.camera.isOpened()):
                    self._open_camera()
                return

            # uruchom nowy wątek
            self.running = True
            self.recognition_thread = threading.Thread(
                target=self._recognition_loop, args=(callback,), daemon=True
            )
            self.recognition_thread.start()

    def ensure_running(self):
        """
        Idempotentne 'szturchnięcie': jeśli nie działa – uruchom; jeśli kamera padła – otwórz.
        """
        with self.lock:
            if not (self.recognition_thread and self.recognition_thread.is_alive()):
                self.running = False  # na wszelki wypadek
                self.start_recognition_thread(self._callback or (lambda _uid: None))
            else:
                if self.camera is None or (not self.camera.isOpened()):
                    self._open_camera()

    def restart_recognition(self):
        """
        Miękki restart kamery w trakcie pracy (np. po serii błędów read()).
        """
        with self.lock:
            self._close_camera()  # pętla sama spróbuje otworzyć ponownie

    def stop_recognition(self):
        with self.lock:
            self.running = False
        if self.recognition_thread:
            self.recognition_thread.join(timeout=2.0)
        self.recognition_thread = None
        self._close_camera()

    def release(self):
        """Alias dla stop_recognition (zachowanie wstecznej kompatybilności)."""
        self.stop_recognition()

    # ---------------- Pętla rozpoznawania ----------------
    def _recognition_loop(self, callback):
        """
        Główna pętla: bezpieczny read + auto-reopen kamery + rozpoznawanie twarzy.
        Kończy się, gdy:
          - wywoła callback po rozpoznaniu, albo
          - upłynie RECOGNITION_TIMEOUT (bez rozpoznania), albo
          - running zostanie ustawione na False (stop_recognition()).
        """
        t_start = time.time()
        camera_opened = False

        # Otwórz kamerę; jeśli się nie uda, próbuj aż running=False lub minie timeout
        while self.running and (time.time() - t_start) < self.RECOGNITION_TIMEOUT:
            if self._open_camera():
                camera_opened = True
                break
            time.sleep(0.2)

        if not camera_opened:
            return

        print("🔍 Rozpoczynam rozpoznawanie twarzy...")

        while self.running and (time.time() - t_start) < self.RECOGNITION_TIMEOUT:
            # Jeżeli kamera padła, spróbuj ją otworzyć ponownie
            if self.camera is None or (not self.camera.isOpened()):
                if not self._open_camera():
                    time.sleep(0.1)
                    continue

            ok, frame = self.camera.read()
            if not ok or frame is None:
                self._fail_reads += 1
                # Ogranicz spam logów – informacja co 20 błędów
                if (self._fail_reads % 20) == 0:
                    print("[CAM] read() nie zwrócił klatki, próba ponownego otwarcia…")
                if self._fail_reads >= self._REOPEN_AFTER_FAILS:
                    self.restart_recognition()
                time.sleep(self._READ_SLEEP)
                continue

            self._fail_reads = 0

            # Zmniejsz obraz (opcjonalnie), by zwiększyć wydajność
            small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

            # Wykryj twarze
            face_locations = face_recognition.face_locations(rgb_small_frame, model="hog")
            if not face_locations:
                # brak twarzy – nie spamuj logiem w każdej iteracji
                time.sleep(0.01)
                continue

            print(f"🧠 Wykryto {len(face_locations)} twarzy.")

            try:
                face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)
            except Exception as e:
                print(f"[!] Błąd podczas wyciągania encodingów: {e}")
                continue

            if len(self.known_encodings) == 0:
                # Brak znanych — nie ma z czym porównać
                time.sleep(0.05)
                continue

            # Porównaj każdą wykrytą twarz
            for face_encoding in face_encodings:
                matches = face_recognition.compare_faces(self.known_encodings, face_encoding, self.TOLERANCE)
                face_distances = face_recognition.face_distance(self.known_encodings, face_encoding)
                if len(face_distances) == 0:
                    continue

                best_index = np.argmin(face_distances)
                if matches[best_index]:
                    recognized_user = self.known_ids[best_index]
                    print(f"✅ Rozpoznano użytkownika: {recognized_user}")
                    try:
                        callback(recognized_user)
                    except Exception:
                        pass
                    # zakończ bieżący cykl
                    with self.lock:
                        self.running = False
                    break

            time.sleep(0.01)  # delikatna drzemka, żeby nie zajechać CPU

        if self.running:
            # limit czasu dobiegł końca
            print("⏱️ Timeout – nie rozpoznano użytkownika.")

        # Porządki
        self._close_camera()