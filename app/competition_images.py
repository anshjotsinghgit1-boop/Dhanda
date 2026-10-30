"""Pillow-based roster cards for level competition lobby updates."""
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps


def _font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


async def _avatar(bot, player):
    if not player["is_npc"]:
        try:
            photos = await bot.get_user_profile_photos(int(player["telegram_id"]), limit=1)
            if photos.total_count:
                file = await bot.get_file(photos.photos[0][-1].file_id)
                data = BytesIO()
                await bot.download_file(file.file_path, destination=data)
                data.seek(0)
                im = Image.open(data).convert("RGB")
                return ImageOps.fit(im, (76, 76))
        except Exception:
            pass
    initials = "".join(part[0] for part in str(player["display_name"] or "P").replace("🤖", "").split()[:2]).upper() or "P"
    im = Image.new("RGB", (76, 76), (54, 68, 94))
    d = ImageDraw.Draw(im)
    d.ellipse((2, 2, 74, 74), fill=(60, 92, 132))
    d.text((38, 38), initials, anchor="mm", font=_font(25), fill=(245, 248, 255))
    return im


async def render_roster(bot, level, participants):
    columns = 2
    rows = (len(participants) + columns - 1) // columns
    width, row_h, header_h = 1100, 112, 250
    height = max(420, header_h + rows * row_h + 48)
    image = Image.new("RGB", (width, height), (12, 18, 32))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / max(1, height)
        color = (int(14 + 10 * mix), int(23 + 13 * mix), int(42 + 20 * mix))
        draw.line((0, y, width, y), fill=color)
    draw.rounded_rectangle((36, 30, width - 36, 208), radius=30, fill=(24, 38, 63), outline=(75, 115, 160), width=2)
    draw.text((70, 58), "EMPIRE CENTURY  /  CLUB DIVISION", font=_font(23), fill=(137, 190, 255))
    draw.text((70, 100), f"LEVEL {level} COMPETITION", font=_font(42), fill=(248, 250, 255))
    draw.text((72, 164), f"LIVE ROSTER  •  {len(participants)} PARTICIPANTS", font=_font(23), fill=(111, 224, 190))
    for index, player in enumerate(participants):
        col, row = index % 2, index // 2
        x, y = 36 + col * 520, header_h + row * row_h
        draw.rounded_rectangle((x, y, x + 500, y + 94), radius=20, fill=(29, 43, 67), outline=(55, 76, 108), width=1)
        avatar = await _avatar(bot, player)
        mask = Image.new("L", (76, 76), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 75, 75), fill=255)
        image.paste(avatar, (x + 12, y + 9), mask)
        name = str(player["display_name"] or "Player")
        draw.text((x + 104, y + 17), name[:28], font=_font(22), fill=(245, 248, 255))
        tag = "NPC" if player["is_npc"] else "PLAYER"
        draw.text((x + 104, y + 53), f"{tag}  •  BUSINESS LEVEL {level}", font=_font(15), fill=(143, 174, 207))
    draw.text((42, height - 32), "Two different opponents  •  Two match wins required", font=_font(16), fill=(145, 165, 193))
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
async def render_competition_result(bot, level, player, matches, passed):
    width, height = 1100, 650
    image = Image.new("RGB", (width, height), (12, 18, 32))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / height
        draw.line((0, y, width, y), fill=(int(14+10*mix), int(23+13*mix), int(42+20*mix)))
    title = "COMPETITION PASSED" if passed else "COMPETITION NOT PASSED"
    accent = (105, 224, 174) if passed else (245, 145, 135)
    draw.rounded_rectangle((34, 28, width-34, 175), radius=28, fill=(24, 38, 63), outline=accent, width=3)
    draw.text((68, 55), f"LEVEL {level}  /  FINAL RESULT", font=_font(24), fill=(137, 190, 255))
    draw.text((68, 100), title, font=_font(42), fill=accent)
    draw.text((68, 190), "Both matches count — even when the first one is lost.", font=_font(20), fill=(190, 205, 225))
    for index, match in enumerate(matches):
        y = 245 + index * 165
        draw.rounded_rectangle((38, y, width-38, y+140), radius=22, fill=(29, 43, 67), outline=(55, 76, 108), width=1)
        name = str(match["opponent_name"] or "Opponent")
        draw.text((70, y+24), f"MATCH {index+1}  •  {name[:34]}", font=_font(23), fill=(245, 248, 255))
        score = f"{match['wins_a']} – {match['wins_b']}"
        draw.text((70, y+72), score, font=_font(34), fill=accent if match["won"] else (245, 160, 150))
        draw.text((330, y+82), "WON" if match["won"] else "NOT WON", font=_font(20), fill=accent if match["won"] else (245, 160, 150))
    draw.text((42, height-34), "EMPIRE CENTURY  •  CLUB DIVISION", font=_font(17), fill=(145, 165, 193))
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
