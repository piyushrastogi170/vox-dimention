import os
from firebase_config import db
from dotenv import load_dotenv
from auth import auth_bp, init_oauth
from flask import Flask, session, redirect, render_template, request, send_file, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import asyncio
import io
import edge_tts
import uuid
from flask_cors import CORS

load_dotenv()

app = Flask(__name__, static_folder="../static", static_url_path="", template_folder="../static")
app.secret_key = os.environ.get("SECRET_KEY")
CORS(app)

# Resolve base dir for credentials; audio is streamed from memory (no disk writes)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# OAuth init
init_oauth(app)
app.register_blueprint(auth_bp)


# ================= GOOGLE SHEETS SETUP ================= #

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

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
    users_data.append_row([name, email, mobile, country, "PROTECTED", date])


def save_inquiry_to_sheet(name, email, message):
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inquiry_sheet.append_row([name, email, message, date])


# ================= COUNTRY → LOCALE MAP ================= #

COUNTRY_LOCALE_MAP = {
    "india":          "en-IN",
    "united states":  "en-US",
    "united kingdom": "en-GB",
    "australia":      "en-AU",
    "canada":         "en-CA",
    "ireland":        "en-IE",
    "new zealand":    "en-NZ",
    "singapore":      "en-SG",
    "south africa":   "en-ZA",
    "nigeria":        "en-NG",
    "kenya":          "en-KE",
    "philippines":    "en-PH",
    "hong kong":      "en-HK",
    "tanzania":       "en-TZ",
    "ghana":          "en-GH",
    "all":            None,   # no locale filter
}


# ================= API: Inquiry ================= #

@app.route('/submit-inquiry', methods=['POST'])
def submit_inquiry():
    name    = request.form.get('name')
    email   = request.form.get('email')
    message = request.form.get('message')

    db.collection('inquiries').add({"name": name, "email": email, "message": message})
    try:
        save_inquiry_to_sheet(name, email, message)
    except Exception as e:
        print("Inquiry Sheet error:", e)

    return redirect('/inquiry-success')


# ================= API: Sign Up ================= #

@app.route('/submit-sign-up', methods=['POST'])
def submit_sign_up():
    name             = request.form.get('name')
    email            = request.form.get('email')
    mobile           = request.form.get('mobile')
    country          = request.form.get('country')
    password         = request.form.get('create_pass')
    confirm_password = request.form.get('password')
    DEFAULT_AVATAR   = f"https://ui-avatars.com/api/?name={name}"

    if password != confirm_password:
        return "Passwords do not match"

    hashed_password = generate_password_hash(password)

    user_ref = db.collection('users').document(email)
    if user_ref.get().exists:
        return redirect('/sign-in')

    user_ref.set({
        "name":     name,
        "email":    email,
        "mobile":   mobile,
        "country":  country,
        "password": hashed_password,
        "picture":  DEFAULT_AVATAR
    })

    try:
        save_signup_to_sheet(name, email, mobile, country, hashed_password)
    except Exception as e:
        print("Sheet error:", e)

    return redirect('/sign-in')


# ================= API: Sign In ================= #

@app.route('/submit-sign-in', methods=['POST'])
def submit_sign_in():
    email    = request.form.get('email')
    password = request.form.get('password')

    user_ref = db.collection('users').document(email)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return "User not found"

    user_data = user_doc.to_dict()

    if not check_password_hash(user_data.get("password"), password):
        return "Invalid password"

    session['user'] = {
        "name":    user_data.get("name"),
        "email":   user_data.get("email"),
        "picture": user_data.get("picture")
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

@app.route('/pricing')
def pricing():
    return render_template('pricing.html', user=session.get('user'), page="pricing")

@app.route('/history')
def history():
    return render_template('users/history.html', user=session.get('user'), page="history")

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# ================= SHARED: TTS → BytesIO (zero disk writes) ================= #

def _run_tts_to_bytes(text, voice, rate="+0%", pitch="+0Hz", volume="+0%"):
    """Generate TTS audio and return raw MP3 bytes via in-memory buffer."""
    buf = io.BytesIO()

    async def _stream():
        communicate = edge_tts.Communicate(
            text=text, voice=voice, rate=rate, pitch=pitch, volume=volume
        )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_stream())
    finally:
        loop.close()

    buf.seek(0)
    return buf


# ================= API: Generate Audio ================= #

@app.route("/generate", methods=["POST"])
def generate_audio():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    text   = data.get("text", "").strip()
    voice  = data.get("voice", "en-IN-PrabhatNeural")
    rate   = data.get("rate", "+0%")
    pitch  = data.get("pitch", "+0Hz")
    volume = data.get("volume", "+0%")

    if not text:
        return jsonify({"error": "Text is required"}), 400

    try:
        audio_buf = _run_tts_to_bytes(text, voice, rate, pitch, volume)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Log to Firestore (non-blocking best-effort)
    if 'user' in session:
        try:
            db.collection("voices").add({
                "user":       session['user']['email'],
                "text":       text,
                "voice":      voice,
                "created_at": datetime.now()
            })
        except Exception as e:
            print("Firestore voice log error:", e)

    return send_file(
        audio_buf,
        mimetype="audio/mpeg",
        as_attachment=False,
        download_name="voice.mp3"
    )


# ================= API: Preview Voice ================= #

# Short demo sentence used for all previews — keeps latency low
_PREVIEW_TEXT = "Hello! This is how I sound. I hope you enjoy this voice."

@app.route("/preview", methods=["GET"])
def preview_voice():
    voice = request.args.get("voice", "").strip()
    if not voice:
        return jsonify({"error": "voice parameter required"}), 400

    try:
        audio_buf = _run_tts_to_bytes(_PREVIEW_TEXT, voice)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        audio_buf,
        mimetype="audio/mpeg",
        as_attachment=False,
        download_name="preview.mp3"
    )


# ================= API: List Voices (gender + country filter) ================= #

@app.route("/voices", methods=["GET"])
def get_voices():
    gender  = request.args.get("gender", "male").lower()
    country = request.args.get("country", "all").lower()

    # Resolve locale prefix from country name
    locale_prefix = COUNTRY_LOCALE_MAP.get(country)  # None means "all countries"

    async def fetch():
        return await edge_tts.list_voices()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        all_voices = loop.run_until_complete(fetch())
    finally:
        loop.close()

    filtered = []
    for v in all_voices:
        # Gender filter
        if gender not in v["Gender"].lower():
            continue
        # Country / locale filter (skip if "all")
        if locale_prefix and not v["Locale"].startswith(locale_prefix):
            continue
        filtered.append({
            "name":   v["ShortName"],
            "label":  f"{v['FriendlyName']} ({v['Locale']})",
            "locale": v["Locale"]
        })

    return jsonify(filtered)


# ================= RUN ================= #

if __name__ == "__main__":
    app.run(debug=True)