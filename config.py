# config.py

import os
import secrets

class Config:
    """Base configuration."""
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(16))
    SQLALCHEMY_DATABASE_URI = os.getenv("NEON_CONNECT_STRING")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 3600,
    }
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB
    S3_BUCKET = os.getenv("S3_BUCKET")
    S3_REGION = os.getenv("S3_REGION")
    S3_PREFIX = os.getenv("S3_PREFIX")
    S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
    MAX_SIZE_MB = int(os.getenv("MAX_SIZE_MB", 20))
    RESIZE_MAX_DIM = int(os.getenv("RESIZE_MAX_DIM", 1200)) # Default to 1200px

    # Mapbox configuration
    MAPBOX_KEY = os.getenv("MAPBOX_KEY")
    START_LNG = os.getenv("START_LNG")
    START_LAT = os.getenv("START_LAT")

class DevelopmentConfig(Config):
    DEBUG = True
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

class ProductionConfig(Config):
    DEBUG = False
    SERVER_NAME = "rosane.life"
    PREFERRED_URL_SCHEME = "https"

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URI", "sqlite:///:memory:")
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    SECRET_KEY = "x4y6v5yxv"
