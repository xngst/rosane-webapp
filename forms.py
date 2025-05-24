"""
forms.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

CATEGORIES = [cat.strip() for cat in os.getenv("CATEGORIES").split(",")]
STATES =  [state.strip() for state in os.getenv("STATES").split(",")]

from flask_wtf import FlaskForm, CSRFProtect
from wtforms import (
    StringField,
    TextAreaField,
    MultipleFileField,
    ValidationError,
    HiddenField,
    SelectField,
    SubmitField,
    IntegerField,
    DateTimeField,
)
from wtforms.validators import DataRequired, URL, NumberRange, Optional
from flask_wtf.file import FileField, FileAllowed, FileRequired

class EntryForm(FlaskForm):
    title = StringField(
        "Title",
        validators=[
            DataRequired(message="Ejnye az elnevezés mező kitöltése kötelező!")
        ],
    )
    description = TextAreaField("Description", validators=[DataRequired()])
    full_address = StringField("Location", validators=[DataRequired()])
    applicant_name = StringField("Applicant", validators=[DataRequired()])
    facebook_url = StringField("FB_URL", validators=[DataRequired()])
    images = MultipleFileField("Images", validators=[DataRequired()])
    category = SelectField("Category", choices=CATEGORIES)
    status = SelectField("Status", choices=STATES)
    campaign_selection = SelectField("Kampány", validators=[DataRequired()])
    city = HiddenField("City")
    county = HiddenField("County")
    zipcode = HiddenField("Zipcode")
    lat = HiddenField("Lat")
    lng = HiddenField("Lon")
    submit = SubmitField("Küldés")

class UpdateEntryForm(FlaskForm):
    full_address = StringField("Helyszín", validators=[DataRequired()])
    city = HiddenField("City", validators=[DataRequired()])
    campaign_selection = SelectField("Kampány", validators=[DataRequired()])
    county = HiddenField("County", validators=[DataRequired()])
    zipcode = HiddenField("Zipcode", validators=[DataRequired()])
    lat = HiddenField("Lat", validators=[DataRequired()])
    lng = HiddenField("Lon", validators=[DataRequired()])
    
class UpdateDatasheetForm(FlaskForm):
    full_address = StringField("Helyszín", validators=[Optional()])
    campaign_selection = SelectField("Kampány", validators=[DataRequired()])
    rosan_id = StringField("Azonosító", validators=[Optional()])
    title = StringField("Pályázat neve", validators=[Optional()])
    applicant_name = StringField("Pályázó neve", validators=[Optional()])
    facebook_url = StringField("Facebook esemény linkje", validators=[Optional()])
    category = SelectField("Kategória", choices=CATEGORIES)
    status = SelectField("Állapot", choices=STATES)
    huf_awarded = IntegerField("Megítélt támogatás összege", validators=[Optional()])
    description = TextAreaField("Projekt leírás", validators=[Optional()])
    img_paths = MultipleFileField("További képek feltöltése", validators=[Optional()])
    submit = SubmitField("Mentés")

class UploadImageForm(FlaskForm):
    images = MultipleFileField("Képek", validators=[DataRequired()])
    submit = SubmitField('Feltöltés')

class CampaignForm(FlaskForm):
    name = StringField("Név", validators=[DataRequired()])
    description = TextAreaField("Leírás")
    from_date = DateTimeField("Ettől", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    to_date = DateTimeField("Eddig", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    status = SelectField(
        "Státusz", choices=[("aktív", "aktív"), ("passzív", "passzív")]
    )
    submit = SubmitField("Mentés")

    def validate_from_date(form, field):
        if form.from_date.data and form.to_date.data:
            if form.from_date.data > form.to_date.data:
                raise ValidationError("Nem kezdődhet előbb mint ahog befejeződik!")
