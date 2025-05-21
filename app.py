"""
RÓSÁNÉ backend
"""
# BULT-INS
import json
import os
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
    current_user
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
from flask_wtf.csrf import CSRFProtect

# SEC
from werkzeug.utils import secure_filename

#S3
import boto3, botocore

#LOGIN BLUEPRINTS
from flask_dance.contrib.google import google
from login_blueprints import google_bp, facebook_bp

# CUSTOM UTILS
from utils import allowed_file, gen_rosane_id, resize_image

# CONFIG
load_dotenv()

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

ENV = os.getenv("ENV")
MAPBOX_KEY = os.getenv("MAPBOX_KEY")
START_LNG = os.getenv("START_LNG")
START_LAT = os.getenv("START_LAT")
MAX_SIZE_MB = int(os.getenv("MAX_SIZE_MB"))
RESIZE_MAX_DIM = os.getenv("RESIZE_MAX_DIM")
NEON_CONNECT_STRING = os.getenv("NEON_CONNECT_STRING")
S3_REGION = os.getenv("S3_REGION")
S3_PREFIX = os.getenv("S3_PREFIX")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ACCESS_PATH = f"https://{S3_BUCKET}"

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["UPLOAD_FOLDER"] = "static/uploads/"
app.config["SQLALCHEMY_DATABASE_URI"] = NEON_CONNECT_STRING
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024 
app.config['S3_BUCKET'] = S3_BUCKET
app.config['S3_REGION'] = os.getenv("S3_REGION")
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
'pool_pre_ping': True,
'pool_size': 10,
'max_overflow': 20,
'pool_recycle': 3600
}

app.register_blueprint(google_bp, url_prefix="/login")
app.register_blueprint(facebook_bp, url_prefix="/login")

if ENV == "prod":
    app.config['SERVER_NAME'] = 'rosane.life'
    app.config['PREFERRED_URL_SCHEME'] = 'https'

s3_client = boto3.client(
    's3',
    region_name=S3_REGION,
    aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY")
)
migrate = Migrate(app, db)
db.init_app(app)

login_manager = LoginManager(app)
csrf = CSRFProtect(app)

@app.route("/test", methods=["GET", "POST"])
def test():
    active_campaign = Campaign.query.filter_by(status="aktív").first()
    print(active_campaign.from_date.year)

@app.route("/", methods=["GET", "POST"])
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

@app.route("/like/<int:entry_id>", methods=["POST"])
@login_required
def like(entry_id):
    entry = Entry.query.get_or_404(entry_id)

    active_campaign = Campaign.query.filter_by(status="aktív").first()

    user_has_liked_entry = Like.query.filter(
        Like.user_id == current_user.id,
        Like.entry_id == entry.id,
        Like.campaign_id == active_campaign.id
    ).first()

    if not user_has_liked_entry:
        entry.like_count += 1

        new_like = Like(user_id=current_user.id, entry_id=entry.id, campaign_id=active_campaign.id)
        db.session.add(new_like)
        db.session.commit()

        flash(f"Sikeres szavazat! Köszönjük, hogy szavaztál erre pályázatra!", "success")
        return redirect(url_for('applications'))
    else:
        flash(f"Egy pályázatra csak egy szavazat adható le!", "danger")
        return redirect(url_for('applications'))
    
def check_role(role):
    if current_user.role != role:
        return False
    else:
        return True

@app.route("/welcome")
def welcome():
    if not google.authorized:
        return redirect(url_for("google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Sikertelen adatlekérés!", "danger")
        return redirect(url_for("index"))

    user_info = resp.json()
    user_email = user_info.get("email")
    family_name = user_info.get("family_name")
    given_name = user_info.get("given_name")
    last_login = datetime.now()

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

    login_user(user)
    return render_template("index.html")


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


@app.route("/applications", methods=["GET", "POST"])
def applications():
    entries = Entry.query.all()
    return render_template("applications.html", entries=entries)


@app.route("/profil", methods=["GET", "POST"])
@login_required
def profil():

    active_campaign = Campaign.query.filter_by(status="aktív").first()

    user_likes_in_active_campaign = Like.query.filter(
        Like.user_id == current_user.id,
        Like.campaign_id == active_campaign.id if active_campaign else None
    ).all()

    voted_entries = []

    for like_obj in user_likes_in_active_campaign:
        entry = Entry.query.get(like_obj.entry_id)
        if entry:
            voted_entries.append(entry)

    return render_template(
        "profile.html",
        voted_entries=voted_entries,
        active_campaign=active_campaign
    )


@app.route("/admin_user", methods=["GET", "POST"])
@login_required
def admin_user():
    users = User.query.all()
    return render_template("admin_user.html", users=users)


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


@app.route("/adatlap/<int:entry_id>")
def adatlap(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    images = Image.query.filter_by(entry_id=entry.id).all()
    return render_template("datasheet.html", entry=entry, images=images)
    
    
@app.route("/adatlap/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete_entry(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    images = Image.query.filter_by(entry_id=entry.id).all()
    for image in images:
        db.session.delete(image)
    db.session.delete(entry)
    db.session.commit()
    flash('Adatlap sikeresen törölve!', 'success')
    return redirect(url_for('applications'))

@app.route("/update_datasheet/<int:entry_id>", methods=["GET", "POST"])
@login_required
def update_datasheet(entry_id):
    entry = Entry.query.get_or_404(entry_id)

    images = Image.query.filter_by(entry_id=entry.id).all()
  
    form = UpdateDatasheetForm(obj=entry) 
    
    if form.validate_on_submit():

        #entry.full_address = form.full_address.data
        entry.rosan_id = form.rosan_id.data
        entry.applicant_name = form.applicant_name.data
        entry.facebook_url = form.facebook_url.data
        entry.category = form.category.data
        entry.status = form.status.data
        entry.huf_awarded = form.huf_awarded.data
        entry.description = form.description.data
        entry.title = form.title.data

        db.session.commit()
        flash("Az adatlap sikeresen frissítve!", "success")
        return redirect(
            url_for("adatlap", entry_id=entry.id)
        )  # Redirect back to the view page

    return render_template("datasheet_update.html", 
    form=form, 
    entry=entry, 
    images=images, 
    MAPBOX_KEY=MAPBOX_KEY
    )

@app.route("/entry/update_address/<int:entry_id>", methods=["GET", "POST"])
@login_required
def update_address(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    form = UpdateEntryForm(obj=entry)
    
    if form.validate_on_submit():
        entry.full_address = form.full_address.data
        entry.city=form.city.data
        #entry.campaign=form.campaign.data
        entry.county=form.county.data
        entry.zipcode=form.zipcode.data
        entry.lat=form.lat.data
        entry.lng=form.lng.data  	
    	
        db.session.commit()
        flash("Az adatlap sikeresen frissítve!", "success")
        return redirect(
            url_for("adatlap", entry_id=entry.id)
        )
    
    """
    if entry.lat:
        START_LAT = entry.lat
    if entry.lng:
        START_LNG = entry.lng
    """
    
    return render_template("update_address.html", 
    form=form, 
    entry=entry,
    MAPBOX_KEY=MAPBOX_KEY,
    START_LNG=START_LNG,
    START_LAT=START_LAT
    )    

@app.route('/image/delete/<int:image_id>', methods=['POST'])
@login_required
def delete_image(image_id):
    image = Image.query.get_or_404(image_id)
    s3_key = f"{S3_PREFIX}/{image.entry_id}_{image.file_name}"
    s3_client.delete_object(
            Bucket=S3_BUCKET,
            Key=s3_key
        )
    try:
        response = s3_client.delete_object(
            Bucket=S3_BUCKET,
            Key=s3_key
        )
        if response['ResponseMetadata']['HTTPStatusCode'] == 204:
            db.session.delete(image)
            db.session.commit()
            flash('A kép sikeresen törölve lett az S3-ról és az adatbázisból.', 'success')
        else:
            flash(f'Hiba történt a kép törlésekor az S3-ról. Válasz: {response}', 'danger')
            db.session.rollback()
    except Exception as e:
        flash(f'Hiba történt a kép törlésekor az S3-ról: {e}', 'danger')
        db.session.rollback()

    return redirect(request.referrer or url_for('index'))


@app.route("/formanyomtatvany", methods=["GET", "POST"])
@login_required
def entry_form():
    form = EntryForm()

    active_campaign = Campaign.query.filter_by(status="aktív").first()
    if not active_campaign:
        flash("Minimum egy aktív kampánynak léteznie kell!", "danger")
        return redirect(url_for("index"))

    if form.validate_on_submit():
        entry_data = form.data

        new_entry = Entry(
            campaign_id=active_campaign.id,
            title=entry_data['title'],
            description=entry_data['description'],
            full_address=entry_data['full_address'],
            category=entry_data['category'],
            city=entry_data['city'],
            county=entry_data['county'],
            zipcode=entry_data['zipcode'],
            lat=entry_data['lat'],
            lng=entry_data['lng'],
            status=entry_data['status'],
            applicant_name=entry_data['applicant_name'],
            facebook_url=entry_data['facebook_url'],
            rosan_id=gen_rosane_id(
                campain_year=active_campaign.from_date.year,
                Entry=Entry,
                session=db.session
            ),
        )

        db.session.add(new_entry)

        try:
            db.session.commit()
            entry_id = new_entry.id
            entry_folder = os.path.join(app.config["UPLOAD_FOLDER"], str(entry_id))
            os.makedirs(entry_folder, exist_ok=True)
            images = form.images.data

            image_objects = []

            for image_file in images:
                filename = secure_filename(image_file.filename)

                if not allowed_file(filename):
                    flash("Csak JPG and PNG kiterjesztéseket lehet feltölteni.")
                    return redirect(request.url)

                file_size_mb = image_file.content_length / (1024 * 1024) if image_file.content_length else 0
                buffer_to_upload = image_file  # Default to the original file

                if file_size_mb >= MAX_SIZE_MB:
                    try:
                        img = Image.open(image_file)  # Open the FileStorage object
                        img_format = img.format
                        img.thumbnail((RESIZE_MAX_DIM, RESIZE_MAX_DIM))
                        buffer = BytesIO()
                        img.save(buffer, format=img_format, optimize=True)
                        buffer.seek(0)
                        buffer_to_upload = buffer  # Use the resized buffer for upload
                    except Exception as e:
                        flash(f"Hiba történt a képfeldolgozás során: {e}", "warning")
                        pass

                s3_key = f"{S3_PREFIX}/{entry_id}_{filename}"
                img_url = f"https://{S3_BUCKET}/{s3_key}"
                
                s3_client.upload_fileobj(
                    Fileobj=buffer_to_upload,
                    Bucket=S3_BUCKET,
                    Key=s3_key,
                )

                new_image = Image(entry_id=new_entry.id, file_name=filename, url=img_url)
                image_objects.append(new_image)

            db.session.add_all(image_objects)
            db.session.commit()
            flash("Sikeres hozzáadás!", "success")
            return redirect(url_for("entry_form"))

        except Exception as e:
            db.session.rollback()
            flash(f"Hiba történt a mentés során: {e}", "danger")
        finally:
            db.session.close()
            return redirect(request.url)

    return render_template(
        "form.html",
        form=form,
        MAPBOX_KEY=MAPBOX_KEY,
        START_LNG=START_LNG,
        START_LAT=START_LAT,
    )

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

        if form.status.data == "aktív" and active_campaign and active_campaign.id != campaign.id:
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


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.errorhandler(413)
def request_entity_too_large(error):
    return "A feltöltött fájl túl nagy (max 5MB)!", 413

def datestamp():
    return datetime.now().strftime("%Y-%m-%d")

@app.errorhandler(404)
def not_found(e):
  return render_template("error_404.html")


if __name__ == "__main__":
    if not os.path.exists(app.config["UPLOAD_FOLDER"]):
        os.makedirs(app.config["UPLOAD_FOLDER"])
    with app.app_context():
        db.create_all()
    if ENV == "test":
        app.run(debug=True)
    elif ENV == "prod":
        app.run(debug=True,host="0.0.0.0", port=5001)
