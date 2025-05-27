# app.py

# BUILT-INS
import os
from datetime import datetime
import json
import uuid
from functools import wraps
from io import BytesIO
import secrets

# THIRD-PARTY LIBRARIES
from dotenv import load_dotenv
from PIL import Image

# FLASK
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    abort,
)

# FLASK EXTENSIONS
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import boto3
import botocore
from flask_dance.contrib.google import google
from authlib.integrations.flask_client import OAuth
from sqlalchemy.sql.expression import func

# from flask_dance.consumer import keycloak # If you define a LocalProxy for Keycloak

# INTERNAL IMPORTS (YOUR APP MODULES)
from models import db, Like, Campaign, User, Image as DBImage, Entry
from forms import (
    EntryForm,
    UpdateDatasheetForm,
    CampaignForm,
    UpdateEntryForm,
    UploadImageForm,
)
from login_blueprints import google_bp, facebook_bp
from utils import allowed_file, gen_rosane_id, resize_image
import logging

# --- Configuration Loading ---
load_dotenv()

# Import the configuration classes
from config import DevelopmentConfig, ProductionConfig, TestingConfig

# --- Flask App Initialization ---
app = Flask(__name__)

# Determine config based on ENV
ENV = os.getenv("ENV", "development")  # Default to development
if ENV == "prod":
    app.config.from_object(ProductionConfig)
    logging.basicConfig(level=logging.INFO)
elif ENV == "test":
    app.config.from_object(TestingConfig)
    logging.basicConfig(level=logging.DEBUG)
else:  # Default to development
    app.config.from_object(DevelopmentConfig)
    logging.basicConfig(level=logging.INFO)

# Apply ProxyFix for deployment behind a proxy (e.g., Nginx, AWS ELB)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# --- Initialize Extensions ---
db.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)

# Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Tessék csak tessék!"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- Register Blueprints ---
app.register_blueprint(google_bp, url_prefix="/login")
app.register_blueprint(facebook_bp, url_prefix="/login")

oauth = OAuth(app)

# Keycloak OAuth
oauth.register(
    name="keycloak",
    client_id=os.getenv("KEYCLOAK_CLIENT_ID"),
    client_secret=os.getenv("KEYCLOAK_CLIENT_SECRET"),
    server_metadata_url=os.getenv("KEYCLOAK_SERVER_METADATA_URL"),
    client_kwargs={"scope": "openid profile email"},
)


# --- S3 Client Initialization ---
s3_client = boto3.client(
    "s3",
    region_name=app.config["S3_REGION"],
    aws_access_key_id=app.config["S3_ACCESS_KEY_ID"],
    aws_secret_access_key=app.config["S3_SECRET_ACCESS_KEY"],
)


# RBAC
def role_required(*required_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user or not current_user.is_authenticated:
                flash("Előbb be kell jelentkezned.", "danger")
                return redirect(url_for("login", next=request.url))

            if current_user.role not in required_roles:
                flash("Ehhez nem vagy elég nagy kutya.", "danger")
                abort(403)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


# LOGIN PROCESSOR
def process_oauth_login(user_email, given_name, family_name):
    user = User.query.filter_by(email=user_email).first()

    if not user:
        user = User(
            email=user_email,
            user_given_name=given_name,
            user_family_name=family_name,
            role="regular",
            last_login=datetime.now(),
        )
        db.session.add(user)
        db.session.commit()
        flash("Új felhasználó sikeresen regisztrálva!", "success")
    else:
        user.last_login = datetime.now()
        db.session.commit()

    login_user(user)
    flash(f"Sikeres bejelentkezés, {user.user_given_name}!", "success")
    return redirect(url_for("index"))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    try:
        session.pop("keycloak_logged_in", None)  # Clear Keycloak session flag if set
        # If the user logged in via Keycloak, redirect to Keycloak's logout URL
        if session.get("logged_in_via_keycloak"):
            session.pop("logged_in_via_keycloak", None)  # Clear the flag
            redirect_uri = url_for("index", _external=True)
            keycloak_logout_url = os.getenv("KEYCLOAK_LOGOUT_URL")
            if keycloak_logout_url:
                return redirect(keycloak_logout_url)
            else:
                flash("Keycloak logout URL is not configured.", "warning")
    except NameError as ne:
        print(ne)
        pass
    logout_user()
    flash("Sikeresen kijelentkezve", "info")

    return redirect(url_for("index"))


# Keycloak Login Initiator
@app.route("/login/keycloak", methods=["GET"])  # Changed to GET as it's an initiation
def login_keycloak():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    nonce = secrets.token_urlsafe(16)
    session["nonce"] = nonce
    redirect_uri = url_for("auth_keycloak", _external=True)
    return oauth.keycloak.authorize_redirect(redirect_uri, nonce=nonce)


# Keycloak Auth Callback
@app.route("/auth/keycloak")
def auth_keycloak():
    try:
        token = oauth.keycloak.authorize_access_token()
        nonce_from_session = session.pop("nonce", None)
        user_info = oauth.keycloak.parse_id_token(token, nonce=nonce_from_session)

        user_email = user_info.get("email")
        given_name = user_info.get("given_name")
        family_name = user_info.get("family_name")

        if not user_email:
            flash("Nem sikerült lekérni az e-mail címet a Keycloak-tól.", "warning")
            return redirect(url_for("index"))

        session["logged_in_via_keycloak"] = True  # Set a flag for Keycloak logout
        return process_oauth_login(user_email, given_name, family_name)

    except MismatchingStateError:
        flash("Érvénytelen Keycloak OAuth state.", "danger")
        return redirect(url_for("index"))
    except MissingTokenError:
        flash("Hiányzó Keycloak OAuth token.", "danger")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Hiba történt a Keycloak bejelentkezés során: {e}", "danger")
        return redirect(url_for("index"))


# OATUH
@app.route("/oauth_callback")
def oauth_callback():
    try:
        user_info = {}
        user_email = None
        given_name = None
        family_name = None

        if google.authorized:
            resp = google.get("/oauth2/v2/userinfo")
            if not resp.ok:
                flash("Sikertelen adatlekérés a Google-től!", "danger")
                return redirect(url_for("index"))
            user_info = resp.json()
            user_email = user_info.get("email")
            family_name = user_info.get("family_name")
            given_name = user_info.get("given_name")

        elif facebook.authorized:
            resp = facebook.get("me?fields=id,name,email,first_name,last_name")
            if not resp.ok:
                flash("Sikertelen adatlekérés a Facebook-tól!", "danger")
                return redirect(url_for("index"))
            profile = resp.json()
            user_email = profile.get("email")
            given_name = profile.get("first_name")
            family_name = profile.get("last_name")

        else:
            flash("Érvénytelen bejelentkezés.", "danger")
            return redirect(url_for("index"))

        if not user_email:
            flash("Nem sikerült lekérni az e-mail címet a szolgáltatótól.", "warning")
            return redirect(url_for("index"))

        return process_oauth_login(user_email, given_name, family_name)

    except MismatchingStateError:
        flash("Érvénytelen OAuth state.", "danger")
        return redirect(url_for("index"))
    except MissingTokenError:
        flash("Hiányzó OAuth token.", "danger")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Hiba történt a bejelentkezés során: {e}", "danger")
        return redirect(url_for("index"))


# LIKE
@app.route("/like/<int:entry_id>", methods=["POST"])
@login_required
def like(entry_id):
    entry = Entry.query.get_or_404(entry_id)

    active_campaign = Campaign.query.filter_by(status="aktív").first()

    if not active_campaign:
        flash("Jelenleg nincs aktív kampány.", "warning")
        return redirect(url_for("applications"))

    current_datetime = datetime.now()

    if active_campaign.to_date and current_datetime > active_campaign.to_date:
        flash("A szavazási időszak már lejárt ehhez a kampányhoz.", "warning")
        return redirect(url_for("applications"))

    user_has_liked_entry = Like.query.filter(
        Like.user_id == current_user.id,
        Like.entry_id == entry.id,
        Like.campaign_id == active_campaign.id,
    ).first()

    if not user_has_liked_entry:
        try:
            entry.like_count += 1

            new_like = Like(
                user_id=current_user.id, entry_id=entry.id, campaign_id=active_campaign.id
            )
            db.session.add(new_like)
            db.session.commit()

            flash(
                f"Sikeres szavazat! Köszönjük, hogy szavaztál erre pályázatra!", "success"
            )
            return redirect(url_for("applications"))
        except Exception as e:
            db.session.rollback() # Rollback if database commit fails
            flash(f"Hiba történt a szavazat rögzítése során: {e}", "danger")
            app.logger.error(f"Error recording like for entry {entry_id} by user {current_user.id}: {e}")
            return redirect(url_for("applications"))
    else:
        flash(f"Egy pályázatra csak egy szavazat adható le!", "danger")
        return redirect(url_for("applications"))

# MAP
@app.route("/terkep", methods=["GET", "POST"])
def map():
    entries = Entry.query.all()
    geojson = {"type": "FeatureCollection", "features": []}
    for entry in entries:
        images = DBImage.query.filter_by(entry_id=entry.id).all()
        img_paths = [image.url for image in images]

        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [entry.lng, entry.lat]},
            "properties": {
                "id": entry.id,
                "title": entry.title,
                "category": entry.category,
                "description": entry.description,
                "address": entry.full_address,
                "rosan_id": entry.rosan_id,
                "like_count": entry.like_count,
                "status": entry.status,
                "facebook_url": entry.facebook_url,
                "img_paths": json.dumps(img_paths),
                "icon": "custom-marker.png",
            },
        }
        geojson["features"].append(feature)

    return render_template(
        "map.html",
        MAPBOX_KEY=app.config["MAPBOX_KEY"],
        START_LNG=app.config["START_LNG"],
        START_LAT=app.config["START_LAT"],
        geojson_data=geojson,
    )


# APPLICATIONS
@app.route("/applications", methods=["GET", "POST"])
def applications():
    # Order entries by a random function
    entries = Entry.query.order_by(func.random()).all()
    return render_template("applications.html", entries=entries)

# CREATE ENTRY
@app.route("/formanyomtatvany", methods=["GET", "POST"])
@login_required
@role_required("dementor", "admin")
def entry_form():
    form = EntryForm()

    campaigns = Campaign.query.all()
    form.campaign_selection.choices = [(str(c.id), c.name) for c in campaigns]

    if form.validate_on_submit():
        entry_data = form.data
        selected_campaign_id = int(entry_data["campaign_selection"])
        selected_campaign = Campaign.query.get(selected_campaign_id)

        if not selected_campaign:
            flash("Érvénytelen kampány választás!", "danger")
            return redirect(url_for("entry_form"))

        new_entry = Entry(
            campaign_id=selected_campaign.id,
            submitted_by_id=current_user.id,
            title=entry_data["title"],
            description=entry_data["description"],
            full_address=entry_data["full_address"],
            category=entry_data["category"],
            city=entry_data["city"],
            county=entry_data["county"],
            zipcode=entry_data["zipcode"],
            lat=entry_data["lat"],
            lng=entry_data["lng"],
            status=entry_data["status"],
            applicant_name=entry_data["applicant_name"],
            facebook_url=entry_data["facebook_url"],
            rosan_id=gen_rosane_id(
                campain_year=selected_campaign.from_date.year,
                Entry=Entry,
                session=db.session,
            ),
        )

        db.session.add(new_entry)

        try:
            db.session.commit()
            entry_id = new_entry.id
            images = form.images.data

            if images:
                success = handle_image_upload(images, entry_id)
                if not success:
                    flash("Hiba történt a képek feltöltése közben!", "danger")
                    pass

            flash("Sikeres hozzáadás!", "success")
            return redirect(url_for("entry_form"))

        except Exception as e:
            db.session.rollback()
            flash(f"Hiba történt a mentés során: {e}", "danger")
            return render_template(
                "form.html",
                form=form,
                MAPBOX_KEY=app.config["MAPBOX_KEY"],
                START_LNG=START_LNG,
                START_LAT=START_LAT,
                campaigns=campaigns,
            )
        finally:
            db.session.close()

    return render_template(
        "form.html",
        form=form,
        MAPBOX_KEY=app.config["MAPBOX_KEY"],
        START_LNG=app.config["START_LNG"],
        START_LAT=app.config["START_LAT"],
        campaigns=campaigns,
    )


# DELETE ENTRY
@app.route("/adatlap/delete/<int:entry_id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_entry(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    images = DBImage.query.filter_by(entry_id=entry.id).all()
    for image in images:
        db.session.delete(image)
    db.session.delete(entry)
    db.session.commit()
    flash("Adatlap sikeresen törölve!", "success")
    return redirect(url_for("applications"))


# VIEW DATASHEET
@app.route("/adatlap/<int:entry_id>")
def adatlap(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    images = DBImage.query.filter_by(entry_id=entry.id).all()
    return render_template("datasheet.html", entry=entry, images=images)


# UPDATE DATASHEET
@app.route("/update_datasheet/<int:entry_id>", methods=["GET", "POST"])
@login_required
@role_required("dementor", "admin")
def update_datasheet(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    images = DBImage.query.filter_by(entry_id=entry.id).all()
    campaigns = Campaign.query.all()
    form = UpdateDatasheetForm(obj=entry)

    current_id = str(entry.campaign.id)
    campaign_list = [(str(c.id), c.name) for c in campaigns if str(c.id) != current_id]
    campaign_list.insert(0, (current_id, entry.campaign.name))
    form.campaign_selection.choices = campaign_list

    if form.validate_on_submit():
        selected_campaign_id = int(form.campaign_selection.data)

        entry.rosan_id = form.rosan_id.data
        entry.applicant_name = form.applicant_name.data
        entry.facebook_url = form.facebook_url.data
        entry.category = form.category.data
        entry.campaign_id = selected_campaign_id
        entry.status = form.status.data
        entry.huf_awarded = form.huf_awarded.data
        entry.description = form.description.data
        entry.title = form.title.data

        db.session.commit()
        flash("Az adatlap sikeresen frissítve!", "success")
        return redirect(
            url_for("adatlap", entry_id=entry.id)
        )  # Redirect back to the view page

    return render_template(
        "datasheet_update.html",
        form=form,
        entry=entry,
        images=images,
        MAPBOX_KEY=app.config["MAPBOX_KEY"],
    )


# UPDATE ADDRESS
@app.route("/entry/update_address/<int:entry_id>", methods=["GET", "POST"])
@login_required
@role_required("dementor", "admin")
def update_address(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    form = UpdateEntryForm(obj=entry)

    if form.validate_on_submit():
        entry.full_address = form.full_address.data
        entry.city = form.city.data
        entry.county = form.county.data
        entry.zipcode = form.zipcode.data
        entry.lat = form.lat.data
        entry.lng = form.lng.data

        db.session.commit()
        flash("Az adatlap sikeresen frissítve!", "success")
        return redirect(url_for("adatlap", entry_id=entry.id))

    return render_template(
        "update_address.html",
        form=form,
        entry=entry,
        MAPBOX_KEY=app.config["MAPBOX_KEY"],
        START_LNG=app.config["START_LNG"],
        START_LAT=app.config["START_LAT"],
    )


# ADD MORE IMAGES
@app.route("/entries/<int:entry_id>/images", methods=["GET", "POST"])
@login_required
@role_required("dementor", "admin")
def upload_image_route(entry_id):
    print("upload_image_route()")
    entry = Entry.query.get_or_404(entry_id)
    form = UploadImageForm()

    if form.validate_on_submit():
        images = form.images.data

        if images:
            success = handle_image_upload(images, entry_id)
            if success:
                return redirect(url_for("adatlap", entry_id=entry_id))
            else:
                return redirect(request.url)
            return redirect(request.url)
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Hiba '{form[field].label.text}' mezőben: {error}", "danger")

    return render_template("upload_image.html", form=form, entry=entry)


# DELETE IMAGE
@app.route("/image/delete/<int:image_id>", methods=["POST"])
@login_required
@role_required("dementor", "admin")
def delete_image(image_id):
    image = DBImage.query.get_or_404(image_id)
    s3_key = f"{S3_PREFIX}/{image.entry_id}_{image.file_name}"
    s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
    try:
        response = s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        if response["ResponseMetadata"]["HTTPStatusCode"] == 204:
            db.session.delete(image)
            db.session.commit()
            flash(
                "A kép sikeresen törölve lett az S3-ról és az adatbázisból.", "success"
            )
        else:
            flash(
                f"Hiba történt a kép törlésekor az S3-ról. Válasz: {response}", "danger"
            )
            db.session.rollback()
    except Exception as e:
        flash(f"Hiba történt a kép törlésekor az S3-ról: {e}", "danger")
        db.session.rollback()

    return redirect(request.referrer or url_for("index"))


# CAMPAIGN
@app.route("/campaign/")
@login_required
@role_required("admin")
def campaign_list():
    campaigns = Campaign.query.all()
    return render_template("campaign_list.html", campaigns=campaigns)


# CREATE CAMPAIGN
@app.route("/campaigns/create/", methods=["GET", "POST"])
@login_required
@role_required("admin")
def campaign_create():
    form = CampaignForm()
    active_campaign = Campaign.query.filter_by(status="aktív").first()

    if form.validate_on_submit():
        name = form.name.data
        description = form.description.data
        from_date = form.from_date.data
        to_date = form.to_date.data
        status = form.status.data
        created_at = datetime.now()

        if active_campaign and status == "aktív":
            flash("Egyszerre nem létezhet két aktív kampány!", "danger")
            return render_template("campaign_form.html", form=form)

        new_campaign = Campaign(
            name=name,
            description=description,
            from_date=from_date,
            to_date=to_date,
            status=status,
            created_at=created_at,
            updated_at=created_at,
        )
        db.session.add(new_campaign)
        db.session.commit()
        flash("Kampány sikeresen létrehozva!", "success")
        return redirect(url_for("campaign_list"))
    return render_template("campaign_form.html", form=form)


# EDIT CAMPAIGN
@app.route("/campaigns/<int:campaign_id>/edit/", methods=["GET", "POST"])
@login_required
@role_required("admin")
def campaign_edit(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    form = CampaignForm(obj=campaign)

    active_campaign = Campaign.query.filter_by(status="aktív").first()

    if form.validate_on_submit():
        form.populate_obj(campaign)
        campaign.updated_at = datetime.now()

        if (
            form.status.data == "aktív"
            and active_campaign
            and active_campaign.id != campaign.id
        ):
            campaigns = Campaign.query.all()
            flash("Egyszerre nem létezhet két aktív kampány!", "danger")
            return render_template("campaign_list.html", campaigns=campaigns)

        db.session.commit()
        flash("Campaign updated successfully!", "success")
        return redirect(url_for("campaign_list"))

    return render_template("campaign_form.html", form=form, campaign=campaign)


# DELETE CAMPAIGN
@login_required
@role_required("admin")
@app.route("/campaigns/<int:campaign_id>/delete/", methods=["POST"])
def campaign_delete(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    db.session.delete(campaign)
    db.session.commit()
    flash("Campaign deleted successfully!", "success")
    return redirect(url_for("campaign_list"))


# USERS
@app.route("/admin_user", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_user():
    if current_user.role != "admin":
        flash("Nincs jogosultságod ehhez a művelethez!", "danger")
        return redirect(url_for("admin_user"))
    users = User.query.all()
    campaigns = Campaign.query.all()
    campaigns_data = [{"id": c.id, "name": c.name} for c in campaigns]
    return render_template("admin_user.html", users=users, campaigns=campaigns_data)


# UPDATE ROLE
@app.route("/update_role/<int:user_id>", methods=["POST"])
@login_required
@role_required("admin")
def update_role(user_id):
    if current_user.role != "admin":
        flash("Nincs jogosultságod ehhez a művelethez!", "danger")
        return redirect(url_for("admin_user"))

    new_role = request.form.get("role")
    user = User.query.get_or_404(user_id)
    if new_role in ["admin", "dementor", "regular"]:
        user.role = new_role
        db.session.commit()
        flash("Jogosultsági szint sikeresen megváltoztatva!", "success")
    else:
        flash("Érvénytelen jogosultsági szint!", "danger")
    return redirect(url_for("admin_user"))


# ASSIGN USER TO CAMPAIGN
@app.route("/update_campaign/<int:user_id>", methods=["POST"])
@login_required
@role_required("admin")
def update_campaign(user_id):
    if current_user.role != "admin":
        flash("Nincs jogosultságod ehhez a művelethez!", "danger")
        return redirect(url_for("admin_user"))

    new_campaign_id_str = request.form.get("campaign_id")
    user = User.query.get_or_404(user_id)

    if new_campaign_id_str:
        try:
            new_campaign_id = int(new_campaign_id_str)
            campaign = Campaign.query.get(new_campaign_id)
            if campaign:
                user.campaign_id = new_campaign_id
                db.session.commit()
                flash(
                    f"Felhasználó '{user.email}' kampánya sikeresen megváltoztatva!",
                    "success",
                )
            else:
                flash("A kiválasztott kampány nem létezik!", "danger")
        except ValueError:
            flash("Érvénytelen kampány azonosító!", "danger")
    else:
        user.campaign_id = None
        db.session.commit()
        flash(f"Felhasználó '{user.email}' kampánya sikeresen eltávolítva!", "success")

    return redirect(url_for("admin_user"))


# ACCOUNT
@app.route("/profil", methods=["GET"])
@login_required
def profil():
    active_campaign = Campaign.query.filter_by(status="aktív").first()

    user_likes_in_active_campaign = Like.query.filter(
        Like.user_id == current_user.id,
        Like.campaign_id == active_campaign.id if active_campaign else None,
    ).all()

    voted_entries = []

    for like_obj in user_likes_in_active_campaign:
        entry = Entry.query.get(like_obj.entry_id)
        if entry:
            voted_entries.append(entry)

    return render_template(
        "profile.html", voted_entries=voted_entries, active_campaign=active_campaign
    )


# ACCOUNT DELETION
@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    user_to_delete = current_user

    try:
        db.session.delete(user_to_delete)
        db.session.commit()
        logout_user()

        flash(
            "A fiók és minden hozzá tartozó adat sikeresen törölve lett a rendszerből.",
            "success",
        )
        return redirect(url_for("index"))

    except Exception as e:
        db.session.rollback()
        flash("Nem sikerült törölni a fiókot", "danger")
        return redirect(url_for("profil"))


@app.errorhandler(413)
def request_entity_too_large(error):
    return "A feltöltött fájl túl nagy (max 5MB)!", 413


@app.errorhandler(403)
def err403(e):
    return render_template("error/error_404.html")


@app.errorhandler(404)
def err404(e):
    return render_template("error/error_404.html")


@app.errorhandler(401)
def err401(e):
    return render_template("error/error_401.html")


def handle_image_upload(image_files, entry_id):
    successful_uploads_count = 0
    image_objects_to_add = []

    for image_file in image_files:
        if not image_file:
            continue

        original_filename = secure_filename(image_file.filename)

        if not allowed_file(original_filename):
            flash(
                f"Érvénytelen fájltípus. Csak JPG, JPEG és PNG engedélyezett.",
                "warning",
            )
            continue

        buffer_to_upload = BytesIO(image_file.read())
        image_file.seek(0)

        unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}_{original_filename}"
        s3_key = f"{app.config['S3_PREFIX']}/{entry_id}/{unique_filename}"
        img_url = f"https://{app.config['S3_BUCKET']}/{s3_key}"

        try:
            s3_client.upload_fileobj(
                Fileobj=buffer_to_upload,
                Bucket=app.config["S3_BUCKET"],
                Key=s3_key,
                ExtraArgs={"ContentType": image_file.content_type},
            )

            new_image = DBImage(
                entry_id=entry_id, file_name=unique_filename, url=img_url
            )
            image_objects_to_add.append(new_image)
            successful_uploads_count += 1

        except Exception as e:
            flash(f"Hiba történt a kép feltöltése során.", "warning")

    if image_objects_to_add:
        try:
            db.session.add_all(image_objects_to_add)
            db.session.commit()
            flash(f"{successful_uploads_count} kép sikeresen feltöltve!", "success")
            return True
        except Exception as e:
            db.session.rollback()
            flash(f"Hiba történt a képek adatbázisba mentése során: {e}", "danger")
            return False
    elif successful_uploads_count == 0:
        flash("Nincs kép feltöltve vagy minden kép feltöltése sikertelen volt.", "info")
        return False
    return True


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    if ENV == "development":
        app.run(debug=True)
    elif ENV == "prod":
        app.run(debug=True, host="0.0.0.0", port=5001)
