# your_user_module.py
import logging
from google.cloud import firestore
from werkzeug.security import check_password_hash, generate_password_hash #
from flask_login import UserMixin #

logger = logging.getLogger(__name__)

# Firestore client instance (reuse your existing import/setup if preferred)
# It's better practice for the app to initialize and pass the db client,
# or use Flask's application context (current_app.extensions['firestore'] or similar).
# For this standalone example, initializing it here if not already done.
_DB_CLIENT_INSTANCE = None

def _get_db_client_user_module():
    global _DB_CLIENT_INSTANCE
    if _DB_CLIENT_INSTANCE is None:
        try:
            _DB_CLIENT_INSTANCE = firestore.Client()
            logger.info("Initialized FirestoreClient in your_user_module.py")
        except Exception as e:
            logger.critical(f"your_user_module.py: Failed to initialize FirestoreClient: {e}", exc_info=True)
            # Depending on usage, might want to raise here or let functions fail if _db is None
            raise # Fail hard if DB cannot be initialized
    return _DB_CLIENT_INSTANCE


class User(UserMixin): #
    def __init__(self, id: str, username: str, password_hash: str, is_admin: bool = False): # Added is_admin
        self.id = id #
        self.username = username #
        self.password_hash = password_hash #
        self.is_admin = is_admin # For admin role
        logger.debug(f"User object initialized for ID: {id}, Username: {username}, IsAdmin: {is_admin}")

    @staticmethod
    def get(user_id: str): #
        logger.debug(f"User.get called for user_id: {user_id}")
        try:
            db = _get_db_client_user_module()
            doc = db.collection('users').document(user_id).get() #
            if doc.exists:
                data = doc.to_dict() #
                username = data.get("username", "N/A")
                is_admin_flag = data.get("is_admin", False) # Load admin status
                logger.info(f"User '{username}' (ID: {user_id}, Admin: {is_admin_flag}) found by User.get.")
                return User(id=doc.id, username=username, password_hash=data.get("password_hash"), is_admin=is_admin_flag)
            else:
                logger.warning(f"User.get: No user found with ID: {user_id}")
                return None
        except Exception as e:
            logger.error(f"User.get: Error fetching user {user_id} from Firestore: {e}", exc_info=True)
            return None

    @staticmethod
    def authenticate(username: str, password: str): #
        logger.info(f"User.authenticate attempt for username: '{username}'")
        try:
            db = _get_db_client_user_module()
            # Query Firestore for a matching username
            users_query = db.collection('users').where("username", "==", username).limit(1).stream()
            user_snapshot = next(users_query, None) # Get the first result or None

            if user_snapshot:
                user_data = user_snapshot.to_dict()
                user_id = user_snapshot.id
                stored_password_hash = user_data.get("password_hash")

                if stored_password_hash and check_password_hash(stored_password_hash, password):
                    is_admin_flag = user_data.get("is_admin", False)
                    logger.info(f"User '{username}' (ID: {user_id}, Admin: {is_admin_flag}) authenticated successfully.")
                    return User(id=user_id, username=user_data.get("username"), password_hash=stored_password_hash, is_admin=is_admin_flag)
                else:
                    logger.warning(f"User.authenticate: Password mismatch for username '{username}'.")
                    return None
            else:
                logger.warning(f"User.authenticate: No user found with username '{username}'.")
                return None
        except Exception as e:
            logger.error(f"User.authenticate: Error during authentication for '{username}': {e}", exc_info=True)
            return None

    @staticmethod
    def create(username: str, password: str, is_admin: bool = False): # / Added is_admin param
        logger.info(f"User.create attempt for username: '{username}', IsAdmin: {is_admin}")
        try:
            db = _get_db_client_user_module()
            # Check if username already exists
            existing_users_query = db.collection('users').where("username", "==", username).limit(1).stream()
            if next(existing_users_query, None):
                logger.warning(f"User.create: Username '{username}' already exists. Creation aborted.")
                return None # Or raise an error indicating username taken

            pwd_hash = generate_password_hash(password) #
            doc_ref = db.collection('users').document() #
            user_data_to_set = {
                "username": username,
                "password_hash": pwd_hash,
                "is_admin": is_admin, # Store admin status
                "created_at": firestore.SERVER_TIMESTAMP # Add a creation timestamp
            }
            doc_ref.set(user_data_to_set)
            new_user_id = doc_ref.id
            logger.info(f"User '{username}' (ID: {new_user_id}, Admin: {is_admin}) created successfully.")
            return User(id=new_user_id, username=username, password_hash=pwd_hash, is_admin=is_admin)
        except Exception as e:
            logger.error(f"User.create: Error creating user '{username}': {e}", exc_info=True)
            return None

    # UserMixin provides is_active, is_authenticated, is_anonymous, get_id
    # No specific logging needed for those unless overriding.