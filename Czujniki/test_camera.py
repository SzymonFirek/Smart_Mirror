import cv2

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

if not cap.isOpened():
	print("Nie działa");
else: 
	print("kamera działa")
	ret, frame = cap.read()
	if ret:
		print("klatka odczytana")
		cv2.imwrite("test.jpg", frame)
	else:
		print("nie udało sie odczytać")
	cap.release()