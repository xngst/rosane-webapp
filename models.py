# models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from flask_migrate import Migrate

db = SQLAlchemy()

class Campaign(db.Model):
    __tablename__ = 'campaigns'

    id = db.Column(db.Integer, primary_key=True)
    from_date = db.Column(db.DateTime)
    to_date = db.Column(db.DateTime)
    status = db.Column(db.String(256))
    name = db.Column(db.String(256))
    description = db.Column(db.String())
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    entries = db.relationship("Entry", back_populates="campaign")
    likes = db.relationship("Like", back_populates="campaign") # Relationship to likes

    def __repr__(self):
        return f"<Campaign id={self.id}, name='{self.name}', status='{self.status}'>"

class Like(db.Model):
    __tablename__ = 'likes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    entry_id = db.Column(db.Integer, db.ForeignKey('entries.id'), nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship("User", back_populates="likes")
    entry = db.relationship("Entry", back_populates="likes")
    campaign = db.relationship("Campaign", back_populates="likes") # Corrected back_populates
    
class Entry(db.Model):
    __tablename__ = 'entries'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(), nullable=False)
    description = db.Column(db.Text, nullable=False)
    applicant_name = db.Column(db.String())
    full_address = db.Column(db.String())
    facebook_url = db.Column(db.String())
    category = db.Column(db.String())
    city = db.Column(db.String())
    county = db.Column(db.String())
    zipcode = db.Column(db.Integer)
    like_count = db.Column(db.Integer, default=0)
    vote_count = db.Column(db.Integer, default=0)
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    rosan_id = db.Column(db.String())
    status = db.Column(db.String())
    huf_awarded = db.Column(db.Integer)
    
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"))
    campaign = db.relationship("Campaign", back_populates="entries")
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    user = db.relationship("User", back_populates="entries")
    likes = db.relationship(
        "Like", back_populates="entry", cascade="all, delete-orphan"
    )
    images = db.relationship("Image", back_populates="entry", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Entry id={self.id}, title='{self.title}', status='{self.status}'>"

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(256), unique=True, nullable=True)
    facebook_id = db.Column(db.String(256), unique=True, nullable=True)
    email = db.Column(db.String(256), unique=True, nullable=False)
    user_family_name = db.Column(db.String(256))
    user_given_name = db.Column(db.String(256))
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(50), default="regular")
    last_like_date = db.Column(db.DateTime)
    last_login = db.Column(db.DateTime)

    entries = db.relationship(
        "Entry", back_populates="user", cascade="all, delete-orphan"
    )
    likes = db.relationship("Like", back_populates="user", cascade="all, delete-orphan")


class Image(db.Model):
    __tablename__ = 'images'

    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(256),nullable=False)
    url = db.Column(db.String(256),nullable=False)
    entry_id = db.Column(db.Integer, db.ForeignKey('entries.id'), nullable=False)
    entry = db.relationship("Entry", back_populates="images")

    def __repr__(self):
        return f"<Image id={self.id}, filename='{self.filename}', entry_id={self.entry_id}>"


