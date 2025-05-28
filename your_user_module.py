# your_user_module.py
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
from google.cloud import firestore

# Firestore client instance (reuse your existing import/setup if preferred)
_db = firestore.Client()

class User(UserMixin):
    def __init__(self, id: str, username: str, password_hash: str):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    @staticmethod
    def get(user_id: str):
        """
        Load a user by Firestore document ID.
        Returns a User instance or None.
        """
        doc = _db.collection('users').document(user_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return User(id=doc.id,
                    username=data.get('username'),
                    password_hash=data.get('password_hash'))

    @staticmethod
    def authenticate(username: str, password: str):
        """
        Verify username/password. Returns a User if valid, else None.
        """
        # Query Firestore for a matching username
        users = (_db.collection('users')
                  .where('username', '==', username)
                  .limit(1)
                  .stream())
        for doc in users:
            data = doc.to_dict()
            if check_password_hash(data.get('password_hash', ''), password):
                return User(id=doc.id,
                            username=username,
                            password_hash=data['password_hash'])
        return None

    @staticmethod
    def create(username: str, password: str):
        """
        Utility to create a new user in Firestore.
        Returns the new User.
        """
        pwd_hash = generate_password_hash(password)
        doc_ref = _db.collection('users').document()
        doc_ref.set({'username': username, 'password_hash': pwd_hash})
        return User(id=doc_ref.id, username=username, password_hash=pwd_hash)