import base64
import hashlib
from html import escape
from io import BytesIO
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageDraw, ImageFont


class AssetStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, image_bytes):
        if len(image_bytes) > 20 * 1024 * 1024:
            raise ValueError('Image too large')
        with Image.open(BytesIO(image_bytes)) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError('Image dimensions too large')
            output = BytesIO()
            image.convert('RGB').save(output, format='PNG')
        data = output.getvalue()
        name = hashlib.sha256(data).hexdigest() + '.png'
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as file:
            file.write(data)
            temporary = Path(file.name)
        temporary.replace(self.root / name)
        return name

    def read(self, name):
        if not re.fullmatch(r'[a-f0-9]{64}\.png', name):
            raise ValueError('Invalid asset reference')
        return (self.root / name).read_bytes()


def font(size):
    path = next((path for path in (
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf') if Path(path).exists()), None)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


def layout(document):
    title_font = font(32)
    lines = ['']
    for character in document['title']:
        if character in '\r\n':
            character = ' '
        if title_font.getlength(lines[-1] + character) > 928:
            lines.append('')
        lines[-1] += character
    if len(lines) > 3:
        lines = lines[:3]
        while title_font.getlength(lines[-1] + '…') > 928:
            lines[-1] = lines[-1][:-1]
        lines[-1] += '…'
    price_size = 64
    while price_size > 20 and font(price_size).getlength(document['price']) > 928:
        price_size -= 2
    return lines, price_size


def render_svg(document, store):
    image = base64.b64encode(store.read(document['image_ref'])).decode()
    lines, price_size = layout(document)
    title = ''.join(f'<tspan x="48" y="{782 + index * 42}">{escape(line)}</tspan>' for index, line in enumerate(lines))
    price = escape(document['price'])
    label = 'SIMULATED DEMO' if document['simulated'] else 'AI GENERATED'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
<image width="1024" height="1024" href="data:image/png;base64,{image}"/>
<rect y="720" width="1024" height="304" fill="#111827" fill-opacity="0.92"/>
<text fill="white" font-family="Noto Sans CJK SC,sans-serif" font-size="32">{title}</text>
<text x="48" y="958" fill="#f97316" font-family="sans-serif" font-size="{price_size}">{price}</text>
<text x="48" y="1004" fill="#cbd5e1" font-family="sans-serif" font-size="18">{label}</text>
</svg>'''.encode()


def render_png(document, store):
    with Image.open(BytesIO(store.read(document['image_ref']))) as original:
        image = original.convert('RGB').resize((1024, 1024))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 720, 1024, 1024), fill='#111827')
    lines, price_size = layout(document)
    for index, line in enumerate(lines):
        draw.text((48, 742 + index * 42), line, font=font(32), fill='white')
    draw.text((48, 888), document['price'], font=font(price_size), fill='#f97316')
    draw.text((48, 980), 'SIMULATED DEMO' if document['simulated'] else 'AI GENERATED', font=font(18), fill='white')
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()
