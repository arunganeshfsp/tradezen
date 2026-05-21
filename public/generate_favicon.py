from PIL import Image, ImageDraw, ImageFont
import os

# Create a new image with vibrant gradient background
size = 256
img = Image.new('RGB', (size, size), color='white')
draw = ImageDraw.Draw(img)

# Draw bright gradient background (purple to blue)
for y in range(size):
    r = int(124 + (91 - 124) * (y / size))  # 124 to 91
    g = int(106 + (138 - 106) * (y / size))  # 106 to 138
    b = int(247 + (245 - 247) * (y / size))  # 247 to 245
    draw.rectangle([(0, y), (size, y+1)], fill=(r, g, b))

# Draw cyan-green accent stripe at top
stripe_height = 20
for y in range(stripe_height):
    r = int(0 + (46 - 0) * (y / stripe_height))
    g = int(212 + (204 - 212) * (y / stripe_height))
    b = int(255 + (113 - 255) * (y / stripe_height))
    draw.rectangle([(0, y), (size, y+1)], fill=(r, g, b))

# Draw white rounded rectangle for text area
box_margin = 40
box_left = box_margin
box_top = box_margin
box_right = size - box_margin
box_bottom = size - box_margin
radius = 20

# Draw rounded rectangle
draw.rectangle([box_left + radius, box_top, box_right - radius, box_bottom], fill='white')
draw.rectangle([box_left, box_top + radius, box_right, box_bottom - radius], fill='white')
draw.pieslice([box_left, box_top, box_left + 2*radius, box_top + 2*radius], 180, 270, fill='white')
draw.pieslice([box_right - 2*radius, box_top, box_right, box_top + 2*radius], 270, 360, fill='white')
draw.pieslice([box_left, box_bottom - 2*radius, box_left + 2*radius, box_bottom], 90, 180, fill='white')
draw.pieslice([box_right - 2*radius, box_bottom - 2*radius, box_right, box_bottom], 0, 90, fill='white')

# Draw TZ text in bright purple
text = "TZ"
try:
    font = ImageFont.truetype("C:\\Windows\\Fonts\\arialbd.ttf", 90)
except:
    try:
        font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 90)
    except:
        font = ImageFont.load_default()

# Get text bounding box
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]

x = (size - text_width) // 2
y = (size - text_height) // 2

# Draw text with bright purple
draw.text((x, y), text, fill=(124, 106, 247), font=font)

# Save main favicon
img.save('favicon.png')
print("Created: favicon.png (256x256)")

# Create smaller versions
for px_size in [64, 32, 16]:
    small_img = img.resize((px_size, px_size), Image.Resampling.LANCZOS)
    small_img.save(f'favicon-{px_size}.png')
    print(f"Created: favicon-{px_size}.png")

print("All favicon sizes generated!")
