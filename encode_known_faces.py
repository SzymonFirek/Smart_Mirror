import sys
import os
import shutil
from face_recognition_module import encode_face_image, save_face_data

def main():
    if len(sys.argv) != 3:
        print("Użycie: python encode_known_faces.py <user_name> <path_to_image>")
        sys.exit(1)

    user_name = sys.argv[1]
    image_path = sys.argv[2]

    if not os.path.isfile(image_path):
        print(f"Plik {image_path} nie istnieje.")
        sys.exit(1)

    encoding = encode_face_image(image_path)
    if encoding is None:
        print("Nie wykryto twarzy na zdjęciu, kodowanie przerwane.")
        sys.exit(1)

    save_face_data(user_name, image_path, encoding)
    print(f"Encoding zapisany dla użytkownika '{user_name}' w known_faces/{user_name}/encoding.npy")

if __name__ == "__main__":
    main()

# w terminalu:
# python encode_known_faces.py szymon known_faces/szymon/szymon.jpg
