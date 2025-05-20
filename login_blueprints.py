
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.contrib.facebook import make_facebook_blueprint, facebook

import os

google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    redirect_to="welcome",
    scope=[
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid",
    ],
)

facebook_bp = make_facebook_blueprint(
    client_id=os.getenv("FB_CLIENT_ID"),
    client_secret=os.getenv("FB_CLIENT_SECRET"),
    scope=["email"],
    redirect_url="/login/facebook/authorized",
)
