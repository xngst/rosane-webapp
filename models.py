# models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy.sql.expression import func

db = SQLAlchemy()


class Campaign(db.Model):
    __tablename__ = "campaigns"

    id = db.Column(db.Integer, primary_key=True)
    from_date = db.Column(
        db.DateTime, nullable=False
    )
    to_date = db.Column(
        db.DateTime, nullable=False
    ) 
    status = db.Column(
        db.String(256), default="active", nullable=False
    )
    name = db.Column(
        db.String(256), unique=True, nullable=False
    )
    description = db.Column(db.Text)
    updated_at = db.Column(
        db.DateTime, onupdate=datetime.utcnow, default=datetime.utcnow
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    users = db.relationship("User", back_populates="campaign", lazy=True)
    entries = db.relationship(
        "Entry", back_populates="campaign", cascade="all, delete-orphan"
    ) 
    likes = db.relationship(
        "Like", back_populates="campaign", cascade="all, delete-orphan"
    )
    
    def is_currently_active(self):
        """
        Checks if this campaign is currently active based on its 'status'
        field being 'active' AND the current date being within its from_date and to_date.
        """
        now = datetime.utcnow() 

        return (
            self.status == "aktív" and
            self.from_date <= now and
            self.to_date >= now
        )
    
    def __repr__(self):
        return f"<Campaign id={self.id}, name='{self.name}', status='{self.status}'>"


class Like(db.Model):
    __tablename__ = "likes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    entry_id = db.Column(db.Integer, db.ForeignKey("entries.id"), nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "entry_id", "campaign_id", name="_user_entry_campaign_uc"
        ),
    )

    # Relationships
    user = db.relationship("User", back_populates="likes")
    entry = db.relationship("Entry", back_populates="likes")
    campaign = db.relationship("Campaign", back_populates="likes")

    def __repr__(self):
        return f"<Like id={self.id}, user_id={self.user_id}, entry_id={self.entry_id}>"


class Entry(db.Model):
    __tablename__ = "entries"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    applicant_name = db.Column(db.String(255))
    full_address = db.Column(db.String(255))
    facebook_url = db.Column(db.String(255))
    category = db.Column(db.String(255))
    city = db.Column(db.String(255))
    county = db.Column(db.String(255))
    zipcode = db.Column(
        db.String(10)
    )
    like_count = db.Column(
        db.Integer, default=0, nullable=False
    ) 
    vote_count = db.Column(
        db.Integer, default=0, nullable=False
    )
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    created_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    rosan_id = db.Column(db.String(255))
    status = db.Column(
        db.String(50), default="pending", nullable=False
    )
    huf_awarded = db.Column(db.Integer)

    campaign_id = db.Column(
        db.Integer, db.ForeignKey("campaigns.id"), nullable=False
    ) 
    submitted_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False
    )

    # Relationships
    campaign = db.relationship("Campaign", back_populates="entries")
    user = db.relationship(
        "User", back_populates="entries"
    )
    likes = db.relationship(
        "Like", back_populates="entry", cascade="all, delete-orphan"
    )
    images = db.relationship(
        "Image", back_populates="entry", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Entry id={self.id}, title='{self.title}', status='{self.status}'>"


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(256), unique=True, nullable=False)
    google_id = db.Column(
        db.String(256), unique=True, nullable=True
    ) 
    facebook_id = db.Column(
        db.String(256), unique=True, nullable=True
    )
    user_family_name = db.Column(db.String(256))
    user_given_name = db.Column(db.String(256))
    created_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    role = db.Column(
        db.String(50), default="regular", nullable=False
    ) 
    last_like_date = db.Column(db.DateTime)
    last_login = db.Column(db.DateTime)
    campaign_id = db.Column(
        db.Integer, db.ForeignKey("campaigns.id"), nullable=True
    )

    # Relationships
    campaign = db.relationship(
        "Campaign", back_populates="users"
    )
    entries = db.relationship(
        "Entry", back_populates="user", cascade="all, delete-orphan"
    )
    likes = db.relationship("Like", back_populates="user", cascade="all, delete-orphan")

    def is_assigned_to_active_campaign(self):
        """
        Checks if the user is assigned to a campaign that is currently active.
        Relies on the Campaign.is_currently_active() method.
        """
        if self.campaign:
            return self.campaign.is_currently_active()
        return False

    def __repr__(self):
        return f"<User id={self.id}, email='{self.email}'>"


class Image(db.Model):
    __tablename__ = "images"

    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(256), nullable=False)
    url = db.Column(
        db.String(2048), nullable=False
    )
    entry_id = db.Column(db.Integer, db.ForeignKey("entries.id"), nullable=False)

    # Relationships
    entry = db.relationship("Entry", back_populates="images")

    def __repr__(self):
        return f"<Image id={self.id}, file_name='{self.file_name}'>"


class RepresentativeDistrict(db.Model):
    __tablename__ = "districts"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), unique=True, nullable=False)
    zipcode = db.Column(
        db.String(10), unique=True, nullable=False
    )

    def __repr__(self):
        return f"<District id={self.id}, name='{self.name}'>"


class Representative(db.Model):
    __tablename__ = "representatives"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=False)
    zipcode = db.Column(
        db.String(10), unique=True
    ) 
    email = db.Column(db.String(256), unique=True)
    phone = db.Column(db.String(20))

    district_id = db.Column(db.Integer, db.ForeignKey("districts.id"), nullable=False)
    district = db.relationship(
        "RepresentativeDistrict", backref="representatives"
    )

    def __repr__(self):
        return f"<Representative id={self.id}, name='{self.name}'>"
