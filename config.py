import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    UPLOAD_FOLDER = "static/uploads/"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or "sqlite:///db/app.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 megabytes
    CAMPAIN_YEAR = os.getenv("CAMPAIN_YEAR")
    MAPBOX_KEY = os.getenv("MAPBOX_KEY")
    START_LNG = os.getenv("START_LNG")
    START_LAT = os.getenv("START_LAT")
    OAUTHLIB_INSECURE_TRANSPORT = "1"
