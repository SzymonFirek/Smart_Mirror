# mirror_user.py
class MirrorUser:
    def __init__(self, user_id, name, calendar_type, email=None, face_encoding=None, calendar_data=None):
        self.user_id = user_id
        self.name = name
        self.calendar_type = calendar_type
        self.email = email
        self.face_encoding = face_encoding
        self.calendar_data = calendar_data

    def __repr__(self):
        return f"<MirrorUser {self.name} ({self.calendar_type})>"