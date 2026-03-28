import os
from firebase_config import db
from dotenv import load_dotenv
from auth import auth_bp, init_oauth
from flask import Flask, session, redirect, render_template, request
from werkzeug.security import generate_password_hash, check_password_hash
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

load_dotenv()

app = Flask(__name__, static_folder="../static", static_url_path="", template_folder="../static")
app.secret_key = os.environ.get("SECRET_KEY")

# OAuth init
init_oauth(app)
app.register_blueprint(auth_bp)




# ================= GOOGLE SHEETS SETUP ================= #

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

creds_path = os.environ.get("GOOGLE_CREDS")

creds = Credentials.from_service_account_file(
    os.path.join(BASE_DIR, creds_path),
    scopes=scope
)

gs_client = gspread.authorize(creds)

spreadsheet = gs_client.open("Forms-data")

users_data = spreadsheet.worksheet("users")
inquiry_sheet = spreadsheet.worksheet("inquiry")

def save_signup_to_sheet(name, email, mobile, country, hashed_password):
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    users_data.append_row([
        name,
        email,
        mobile,
        country,
        "PROTECTED",
        date
    ])

def save_inquiry_to_sheet(name, email, message):
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    inquiry_sheet.append_row([
        name,
        email,
        message,
        date
    ])


# ================= API For Inquiry ================= #

@app.route('/submit-inquiry', methods=['POST'])
def submit_inquiry():
    name = request.form.get('name')
    email = request.form.get('email')
    message = request.form.get('message')

    db.collection('inquiries').add({
        "name": name,
        "email": email,
        "message": message
    })
    try:
        save_inquiry_to_sheet(name, email, message)
    except Exception as e:
        print("Inquiry Sheet error:", e)

    return redirect('/inquiry-success')


# ================= API For sign up ================= #

@app.route('/submit-sign-up', methods=['POST'])
def submit_sign_up():
    name = request.form.get('name')
    email = request.form.get('email')
    mobile = request.form.get('mobile')
    country = request.form.get('country')
    password = request.form.get('create_pass')
    confirm_password = request.form.get('password')
    DEFAULT_AVATAR = f"https://ui-avatars.com/api/?name={name}"

    # 🔥 password match check
    if password != confirm_password:
        return "Passwords do not match"

    # 🔐 password hash
    hashed_password = generate_password_hash(password)

    user_ref = db.collection('users').document(email)
    user_doc = user_ref.get()

    if user_doc.exists:
        return redirect('/sign-in')

    else:
        user_ref.set({
            "name": name,
            "email": email,
            "mobile": mobile,
            "country": country,
            "password": hashed_password,
            "picture": DEFAULT_AVATAR
        })

        # ✅ NEW: Google Sheet me save
        try:
            save_signup_to_sheet(name, email, mobile, country, hashed_password)
        except Exception as e:
            print("Sheet error:", e)

    return redirect('/sign-in')


# ================= API For sign in ================= #

@app.route('/submit-sign-in', methods=['POST'])
def submit_sign_in():
    email = request.form.get('email')
    password = request.form.get('password')

    # 🔍 Firestore se user fetch
    user_ref = db.collection('users').document(email)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return "User not found"

    user_data = user_doc.to_dict()

    # 🔐 password check
    if not check_password_hash(user_data.get("password"), password):
        return "Invalid password"

    # ✅ session set
    session['user'] = {
        "name": user_data.get("name"),
        "email": user_data.get("email"),
        "picture": user_data.get("picture")  # optional (Google user)
    }

    return redirect('/studio')



# ================= ROUTES ================= #

@app.route('/')
def home():
    return render_template('index.html', user=session.get('user'), page="home")

@app.route('/sign-in')
def signin():
    return render_template('sign_in.html', user=session.get('user'), page="sign-in")

@app.route('/sign-up')
def signup():
    return render_template('sign_up.html', user=session.get('user'), page="sign-up")

@app.route('/studio')
def studio():
    if 'user' not in session:
        return redirect('/sign-in')
    return render_template('studio.html', user=session.get('user'), page="studio")

@app.route('/feedback')
def feedback():
    return render_template('feedback.html', user=session.get('user'), page="feedback")

@app.route('/feedback-success')
def feedback_success():
    return render_template('feedback_succses.html', user=session.get('user'), page="feedback-success")

@app.route('/inquiry')
def inquiry():
    return render_template('inquiry.html', user=session.get('user'), page="inquiry")

@app.route('/inquiry-success')
def inquiry_success():
    return render_template('inquiry_success.html', user=session.get('user'), page="inquiry-success")

@app.route('/privacy-policy')
def privacypolicy():
    return render_template('privacy_policy.html', user=session.get('user'), page="privacy-policy")

@app.route('/who-developed')
def whodeveloped():
    return render_template('who_developed.html', user=session.get('user'), page="who-developed")

@app.route('/terms-of-service')
def termsofservices():
    return render_template('terms_of_service.html', user=session.get('user'), page="terms_of_service")

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ================= RUN ================= #

if __name__ == "__main__":
    app.run(debug=True)