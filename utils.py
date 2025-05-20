"""
ROSANE utils
"""

from PIL import Image
from sqlalchemy import func
import os
from dotenv import load_dotenv
load_dotenv()
ALLOWED_EXTENSIONS = os.getenv("ALLOWED_EXTENSIONS")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def resize_image(image_path, sizes):
    img = Image.open(image_path)
    for size in sizes:
        img.thumbnail(size)
        base, ext = os.path.splitext(image_path)
        img.save(f"{base}_{size[0]}x{size[1]}{ext}")
        
def gen_rosane_id(Entry,session,campain_year):
    max_id = session.query(func.max(Entry.id)).scalar() or 0
    next_number = str(max_id + 1).zfill(4)
    return f"RÓSÁNÉ-{campain_year}-{next_number}"
