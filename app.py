"""
RÓSÁNÉ backend
"""
# BULT-INS
import json
import os
import uuid
from datetime import datetime
from dotenv import load_dotenv
from functools import wraps
from PIL import Image
from io import BytesIO

# FLASK
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    abort,
)

# USER MANAGMENT
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)

# DB
from flask_migrate import Migrate
import psycopg2
from flask_sqlalchemy import SQLAlchemy
from models import db
from models import Like
from models import Campaign
from models import User
from models import Image
from models import Entry

# FORMS
from forms import EntryForm
from forms import UpdateDatasheetForm
from forms import CampaignForm
from forms import UpdateEntryForm
from forms import UploadImageForm

from flask_wtf.csrf import CSRFProtect

# SEC
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth
from oauthlib.oauth2.rfc6749.errors import MismatchingStateError, MissingTokenError

# MIDDLEWARE
from werkzeug.middleware.proxy_fix import ProxyFix

# S3
import boto3, botocore

# LOGIN BLUEPRINTS
from flask_dance.contrib.google import google
from login_blueprints import google_bp, facebook_bp

# CUSTOM UTILS
from utils import allowed_file, gen_rosane_id, resize_image

# CONFIG
load_dotenv()

MAPBOX_KEY = os.getenv("MAPBOX_KEY")
START_LNG = os.getenv("START_LNG")
START_LAT = os.getenv("START_LAT")

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("NEON_CONNECT_STRING")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
app.config["S3_BUCKET"] = os.getenv("S3_BUCKET")
app.config["S3_REGION"] = os.getenv("S3_REGION")
app.config["S3_PREFIX"] = os.getenv("S3_PREFIX")
app.config["S3_ACCESS_KEY_ID"] = os.getenv("S3_ACCESS_KEY_ID")
app.config["S3_SECRET_ACCESS_KEY"] = os.getenv("S3_SECRET_ACCESS_KEY")
app.config["MAX_SIZE_MB"] = int(os.getenv("MAX_SIZE_MB"))
app.config["RESIZE_MAX_DIM"] = os.getenv("RESIZE_MAX_DIM")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_size": 10,
    "max_overflow": 20,
    "pool_recycle": 3600,
}

db.init_app(app)
migrate = Migrate(app, db)


app.register_blueprint(google_bp, url_prefix="/login")
app.register_blueprint(facebook_bp, url_prefix="/login")

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

ENV = os.getenv("ENV")
if ENV == "prod":
    app.config["SERVER_NAME"] = "rosane.life"
    app.config["PREFERRED_URL_SCHEME"] = "https"

if ENV == "test":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

s3_client = boto3.client(
    "s3",
    region_name=app.config["S3_REGION"],
    aws_access_key_id=app.config["S3_ACCESS_KEY_ID"],
    aws_secret_access_key=app.config["S3_SECRET_ACCESS_KEY"],
)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Tessék csak tessék!"
csrf = CSRFProtect(app)
#oauth = OAuth(app)

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
    logout_user()
    flash("Sikeresen kijelentkezve", "info")
    return redirect(url_for("index"))


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

    user_has_liked_entry = Like.query.filter(
        Like.user_id == current_user.id,
        Like.entry_id == entry.id,
        Like.campaign_id == active_campaign.id,
    ).first()

    if not user_has_liked_entry:
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
    else:
        flash(f"Egy pályázatra csak egy szavazat adható le!", "danger")
        return redirect(url_for("applications"))

# MAP
@app.route("/terkep", methods=["GET", "POST"])
def map():
    entries = Entry.query.all()
    geojson = {"type": "FeatureCollection", "features": []}
    for entry in entries:
        images = Image.query.filter_by(entry_id=entry.id).all()
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
        MAPBOX_KEY=MAPBOX_KEY,
        START_LNG=START_LNG,
        START_LAT=START_LAT,
        geojson_data=geojson,
    )


# APPLICATIONS
@app.route("/applications", methods=["GET", "POST"])
def applications():
    entries = Entry.query.all()
    return render_template("applications.html", entries=entries)


# CREATE ENTRY
@app.route("/formanyomtatvany", methods=["GET", "POST"])
@login_required
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
                MAPBOX_KEY=MAPBOX_KEY,
                START_LNG=START_LNG,
                START_LAT=START_LAT,
                campaigns=campaigns,
            )
        finally:
            db.session.close()

    return render_template(
        "form.html",
        form=form,
        MAPBOX_KEY=MAPBOX_KEY,
        START_LNG=START_LNG,
        START_LAT=START_LAT,
        campaigns=campaigns,
    )


# DELETE ENTRY
@app.route("/adatlap/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete_entry(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    images = Image.query.filter_by(entry_id=entry.id).all()
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
    images = Image.query.filter_by(entry_id=entry.id).all()
    return render_template("datasheet.html", entry=entry, images=images)

# UPDATE DATASHEET
@app.route("/update_datasheet/<int:entry_id>", methods=["GET", "POST"])
@login_required
def update_datasheet(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    images = Image.query.filter_by(entry_id=entry.id).all()
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
        MAPBOX_KEY=MAPBOX_KEY,
    )

# UPDATE ADDRESS
@app.route("/entry/update_address/<int:entry_id>", methods=["GET", "POST"])
@login_required
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
        MAPBOX_KEY=MAPBOX_KEY,
        START_LNG=START_LNG,
        START_LAT=START_LAT,
    )

# UPLOAD IMAGE
@app.route("/entries/<int:entry_id>/images", methods=["POST"])
@login_required
def upload_image(entry_id):
    form = UploadImageForm()

    if form.validate_on_submit():
        images = form.images.data

        successful_uploads_count = 0
        image_objects_to_add = []

        for image_file in images:
            if not image_file:
                continue

            original_filename = secure_filename(image_file.filename)

            if not allowed_file(original_filename):
                flash(
                    f"A(z) '{original_filename}' kép érvénytelen fájltípusú. Csak JPG, JPEG és PNG engedélyezett.",
                    "warning",
                )
                continue

            file_size_mb = (
                image_file.content_length / (1024 * 1024)
                if image_file.content_length
                else 0
            )
            buffer_to_upload = BytesIO(image_file.read())
            image_file.seek(0)

            if file_size_mb >= MAX_SIZE_MB:
                try:
                    img = Image.open(buffer_to_upload)
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGB")

                    img_format = img.format if img.format else "JPEG"
                    img.thumbnail((RESIZE_MAX_DIM, RESIZE_MAX_DIM))

                    resized_buffer = BytesIO()
                    save_format = "PNG" if img_format == "PNG" else "JPEG"
                    img.save(resized_buffer, format=save_format, optimize=True)
                    resized_buffer.seek(0)
                    buffer_to_upload = resized_buffer
                except Exception as e:
                    flash(
                        f"Hiba történt a(z) '{original_filename}' kép feldolgozása során. Kérjük, próbálja újra.",
                        "warning",
                    )
                    continue

            # Generate unique S3 key
            unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}_{original_filename}"
            s3_key = f"{S3_PREFIX}/{entry_id}/{unique_filename}"
            img_url = f"https://{S3_BUCKET}/{s3_key}"

            try:
                s3_client.upload_fileobj(
                    Fileobj=buffer_to_upload,
                    Bucket=S3_BUCKET,
                    Key=s3_key,
                    ExtraArgs={"ContentType": image_file.content_type},
                )

                new_image = ImageModel(
                    entry_id=entry_id, file_name=unique_filename, url=img_url
                )
                image_objects_to_add.append(new_image)
                successful_uploads_count += 1

            except Exception as e:
                flash(
                    f"Hiba történt '{original_filename}' kép feltöltése során. Kérjük, próbáld újra.",
                    "warning",
                )

        if image_objects_to_add:
            try:
                db.session.add_all(image_objects_to_add)
                db.session.commit()
                flash(f"{successful_uploads_count} kép sikeresen feltöltve!", "success")
            except Exception as e:
                db.session.rollback()
                flash("Hiba történt a képek adatbázisba mentése során.", "danger")
        elif successful_uploads_count == 0:
            flash(
                "Nincs kép feltöltve vagy minden kép feltöltése sikertelen volt.",
                "info",
            )

        return redirect(url_for("adatlap", entry_id=entry_id))

    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Hiba '{form[field].label.text}' mezőben: {error}", "danger")
        return redirect(request.url)

# ADD MORE IMAGES
@app.route("/entries/<int:entry_id>/images", methods=["GET", "POST"])
@login_required
def upload_image_route(entry_id):
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
def delete_image(image_id):
    image = Image.query.get_or_404(image_id)
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
def campaign_list():
    campaigns = Campaign.query.all()
    return render_template("campaign_list.html", campaigns=campaigns)


# CREATE CAMPAIGN
@app.route("/campaigns/create/", methods=["GET", "POST"])
@login_required
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
def admin_user():
    users = User.query.all()
    return render_template("admin_user.html", users=users)

# UPDATE ROLE
@app.route("/update_role/<int:user_id>", methods=["POST"])
@login_required
def update_role(user_id):
    new_role = request.form.get("role")
    user = User.query.get_or_404(user_id)
    if new_role in ["admin", "dementor", "regular"]:
        user.role = new_role
        db.session.commit()
        flash("Jogosultsági szint sikeresen megváltoztatva!", "success")
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
@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user_to_delete = current_user

    try:
        db.session.delete(user_to_delete)
        db.session.commit()
        logout_user()

        flash('A fiók és minden hozzá tartozó adat sikeresen törölve lett a rendszerből.', 'success')
        return redirect(url_for('index'))

    except Exception as e:
        db.session.rollback() 
        flash('Nem sikerült törölni a fiókot', 'danger')
        return redirect(url_for('profil'))

@app.errorhandler(413)
def request_entity_too_large(error):
    return "A feltöltött fájl túl nagy (max 5MB)!", 413


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

        file_size_mb = (
            image_file.content_length / (1024 * 1024)
            if image_file.content_length
            else 0
        )
        buffer_to_upload = BytesIO(image_file.read())
        image_file.seek(0)

        if file_size_mb >= app.config["MAX_SIZE_MB"]:
            try:
                img = Image.open(buffer_to_upload)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")

                img_format = img.format if img.format else "JPEG"
                img.thumbnail(
                    (app.config["RESIZE_MAX_DIM"], app.config["RESIZE_MAX_DIM"])
                )

                resized_buffer = BytesIO()
                save_format = "PNG" if img_format == "PNG" else "JPEG"
                img.save(resized_buffer, format=save_format, optimize=True)
                resized_buffer.seek(0)
                buffer_to_upload = resized_buffer
            except Exception as e:
                flash(
                    f"Hiba történt '{original_filename}' kép feldolgozása során. {e}",
                    "warning",
                )
                continue

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

            new_image = Image(entry_id=entry_id, file_name=unique_filename, url=img_url)
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
    if ENV == "test":
        app.run(debug=True)
    elif ENV == "prod":
        app.run(debug=True, host="0.0.0.0", port=5001)
