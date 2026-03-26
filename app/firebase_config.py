import firebase_admin
from firebase_admin import credentials, firestore
import os

# path fix (important)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(BASE_DIR, "vox-dimention-firebase-adminsdk-fbsvc-5d0c64146b.json")

cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)

db = firestore.client()