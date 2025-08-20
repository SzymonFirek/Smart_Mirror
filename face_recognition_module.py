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

def load_known_encodings(base_dir="known_faces"):
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
    def __init__(self, known_users, base_dir="known_faces"):
        """
        known_users: lista MirrorUser (z user_id i name)
        Ładuje encodings z dysku i tworzy listę do rozpoznawania.
        """
        self.base_dir = base_dir
        self.known_users = known_users
        self.known_encodings = []
        self.known_ids = []

        self.RECOGNITION_TIMEOUT = 5  # sekundy
        self.TOLERANCE = 0.6

        self.recognition_thread = None
        self.running = False

        for user in known_users:
            user_dir = os.path.join(base_dir, user.name)
            encoding_path = os.path.join(user_dir, "encoding.npy")
            if os.path.isfile(encoding_path):
                encoding = np.load(encoding_path)
                self.known_encodings.append(encoding)
                self.known_ids.append(user.user_id)
            else:
                print(f"Brak encodingu dla użytkownika {user.name} w {encoding_path}")

        self.camera = cv2.VideoCapture(0, cv2.CAP_V4L2)
        if not self.camera.isOpened():
            raise RuntimeError("Nie udało się otworzyć kamery")

    def _recognition_loop(self, callback):
        self.running = True
        print("🔍 Rozpoczynam rozpoznawanie twarzy...")

        start_time = time.time()
        while self.running and time.time() - start_time < self.RECOGNITION_TIMEOUT:
            ret, frame = self.camera.read()
            if not ret:
                print("[!] Nie udało się odczytać klatki z kamery.")
                continue

            # Zmniejsz obraz (opcjonalnie), by zwiększyć wydajność
            small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

            face_locations = face_recognition.face_locations(rgb_small_frame)

            if not face_locations:
                print(" - Brak twarzy na obrazie.")
                continue

            print(f"🧠 Wykryto {len(face_locations)} twarzy.")

            try:
                face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)
            except Exception as e:
                print(f"[!] Błąd podczas wyciągania encodingów: {e}")
                continue

            for face_encoding in face_encodings:
                matches = face_recognition.compare_faces(self.known_encodings, face_encoding, self.TOLERANCE)
                face_distances = face_recognition.face_distance(self.known_encodings, face_encoding)

                if len(face_distances) == 0:
                    continue

                best_index = np.argmin(face_distances)
                if matches[best_index]:
                    recognized_user = self.known_ids[best_index]
                    print(f"✅ Rozpoznano użytkownika: {recognized_user}")
                    callback(recognized_user)
                    self.running = False
                    self.release()
                    return

        print("⏱️ Timeout – nie rozpoznano użytkownika.")
        self.release()

    def start_recognition_thread(self, callback):
        if self.recognition_thread and self.recognition_thread.is_alive():
            print("[!] Wątek już działa")
            return

        self.recognition_thread = threading.Thread(target=self._recognition_loop, args=(callback,))
        self.recognition_thread.start()

    def stop_recognition(self):
        self.running = False
        if self.recognition_thread:
            self.recognition_thread.join()
        self.release()

    def release(self):
        """
        Zwolnij zasoby kamery.
        """
        if self.camera:
            self.camera.release()
