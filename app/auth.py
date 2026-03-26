import os
from flask import Blueprint, redirect, url_for, session
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import json
from firebase_config import db

USERS_FILE = "users.json"

def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

load_dotenv()

auth_bp = Blueprint('auth', __name__)
oauth = OAuth()

def init_oauth(app):
    oauth.init_app(app)

    oauth.register(
        name='google',
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),

        # ✅ IMPORTANT FIX
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',

        client_kwargs={
            'scope': 'openid email profile'
        }
    )

@auth_bp.route('/login')
def login():
    redirect_uri = url_for('auth.callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri, prompt='select_account consent')

@auth_bp.route('/callback')
def callback():
    token = oauth.google.authorize_access_token()
    user = token.get('userinfo')

    # 🔥 Firestore me save
    user_ref = db.collection('users').document(user['email'])

    user_ref.set({
        "name": user.get("name"),
        "email": user.get("email"),
        "picture": user.get("picture")
    }, merge=True)

    # session
    session['user'] = {
        "name": user.get("name"),
        "email": user.get("email"),
        "picture": user.get("picture")
    }

    return redirect('/studio')
