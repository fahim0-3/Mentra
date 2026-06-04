from PyQt5.QtGui import QPixmap
from PIL import Image, ImageDraw
from io import BytesIO

def pil_to_qpixmap(pil_image):
    """Converts a PIL image to a QPixmap."""
    buf = BytesIO()
    pil_image.save(buf, format="PNG")
    px = QPixmap()
    px.loadFromData(buf.getvalue())
    return px

def make_send_icon():
    """Creates the Send icon."""
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(img).polygon(
        [(35, 25), (75, 50), (35, 75)], fill=(255, 255, 255, 255)
    )
    return pil_to_qpixmap(img)

def make_copy_icon():
    """Creates the Copy icon."""
    img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = (200, 200, 200, 255)
    d.rounded_rectangle((2, 2, 12, 14), radius=2, outline=c, width=2)
    d.rounded_rectangle((7, 7, 17, 19), radius=2, outline=c, width=2)
    return pil_to_qpixmap(img)

def make_stop_icon():
    """Creates the Stop icon."""
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((25, 25, 75, 75), radius=10, fill=(255, 255, 255, 255))
    return pil_to_qpixmap(img)

def make_edit_icon():
    """Creates the Edit icon."""
    img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = (200, 200, 200, 255)
    d.polygon([(14, 2), (18, 6), (6, 18), (2, 18), (2, 14)], outline=c, width=2)
    d.line([(11, 5), (15, 9)], fill=c, width=2)
    return pil_to_qpixmap(img)

def make_delete_icon():
    """Creates the Delete icon."""
    img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = (200, 200, 200, 255)
    # Trash can body
    d.rectangle((5, 6, 15, 18), outline=c, width=2)
    # Lid
    d.line([(3, 6), (17, 6)], fill=c, width=2)
    # Lid handle
    d.line([(8, 4), (12, 4)], fill=c, width=2)
    # Vertical lines
    d.line([(8, 9), (8, 15)], fill=c, width=1)
    d.line([(12, 9), (12, 15)], fill=c, width=1)
    return pil_to_qpixmap(img)
