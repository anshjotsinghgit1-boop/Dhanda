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


def _wrap_name(draw, name, font, max_width):
    words = str(name or "Player").split()
    lines, current = [], ""
    for word in words:
        candidate = word if not current else current + " " + word
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        # Preserve long unbroken usernames instead of silently truncating them.
        chunk = ""
        for char in word:
            if draw.textbbox((0, 0), chunk + char, font=font)[2] > max_width and chunk:
                lines.append(chunk)
                chunk = char
            else:
                chunk += char
        current = chunk
    if current:
        lines.append(current)
    return lines or ["Player"]


async def render_roster(bot, level, participants):
    """High-resolution roster with wrapped, fully visible player names."""
    columns = 2
    width, margin, gap = 1800, 42, 28
    card_w = (width - 2 * margin - gap) // columns
    avatar_size = 112
    name_font, meta_font = _font(30), _font(19)
    image = Image.new("RGB", (width, 600), (12, 18, 32))
    draw = ImageDraw.Draw(image)
    prepared = []
    for player in participants:
        name = str(player["display_name"] or "Player").replace("🤖 NPC · ", "")
        lines = _wrap_name(draw, name, name_font, card_w - avatar_size - 54)
        prepared.append((player, lines))
    row_heights = []
    for row in range((len(prepared) + 1) // 2):
        members = prepared[row * 2:row * 2 + 2]
        max_lines = max((len(item[1]) for item in members), default=1)
        row_heights.append(max(154, 42 + max_lines * 38 + 30))
    header_h = 248
    height = header_h + sum(row_heights) + 54
    image = Image.new("RGB", (width, height), (12, 18, 32))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / max(1, height)
        color = (int(14 + 10 * mix), int(23 + 13 * mix), int(42 + 20 * mix))
        draw.line((0, y, width, y), fill=color)
    draw.rounded_rectangle((margin, 28, width - margin, 214), radius=32,
                           fill=(24, 38, 63), outline=(75, 115, 160), width=3)
    draw.text((82, 58), "EMPIRE CENTURY  /  CLUB DIVISION",
              font=_font(27), fill=(137, 190, 255))
    draw.text((82, 105), f"LEVEL {level} COMPETITION",
              font=_font(52), fill=(248, 250, 255))
    draw.text((84, 174), f"ROSTER  •  {len(prepared)} PARTICIPANTS",
              font=_font(27), fill=(111, 224, 190))
    y = header_h
    for row, row_h in enumerate(row_heights):
        for col in range(columns):
            index = row * columns + col
            if index >= len(prepared):
                continue
            player, lines = prepared[index]
            x = margin + col * (card_w + gap)
            draw.rounded_rectangle((x, y, x + card_w, y + row_h - 12),
                                   radius=22, fill=(29, 43, 67),
                                   outline=(65, 91, 128), width=2)
            avatar = await _avatar(bot, player)
            avatar = ImageOps.fit(avatar, (avatar_size, avatar_size))
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
            image.paste(avatar, (x + 18, y + 15), mask)
            text_x, text_y = x + avatar_size + 42, y + 15
            for line in lines:
                draw.text((text_x, text_y), line, font=name_font, fill=(248, 250, 255))
                text_y += 38
            tag = "NPC CHARACTER" if player["is_npc"] else "PLAYER"
            draw.text((text_x, max(y + 15 + len(lines) * 38, y + 91)),
                      f"{tag}  •  BUSINESS LEVEL {level}",
                      font=meta_font, fill=(143, 174, 207))
        y += row_h
    draw.text((margin + 4, height - 38),
              "TWO DIFFERENT OPPONENTS  •  TWO MATCH WINS REQUIRED",
              font=_font(19), fill=(145, 165, 193))
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
async def render_forbes_leaderboard(bot, rows, total_players, title='FORBES LIST', subtitle='RANKED BY NET WORTH'):
    width, height = 1100, 1120
    image = Image.new("RGB", (width, height), (12, 18, 32))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / height
        draw.line((0, y, width, y), fill=(int(14+10*mix), int(23+13*mix), int(42+20*mix)))
    draw.rounded_rectangle((34, 28, width-34, 180), radius=28, fill=(24, 38, 63), outline=(75, 115, 160), width=2)
    draw.text((70, 55), "EMPIRE CENTURY  /  GLOBAL RANKINGS", font=_font(23), fill=(137, 190, 255))
    draw.text((70, 95), title, font=_font(42), fill=(248, 250, 255))
    draw.text((72, 150), f"{subtitle}  •  {total_players} PLAYERS", font=_font(17), fill=(111, 224, 190))
    podium = rows[:3]
    positions = [(397, 205, 305, 465), (65, 235, 305, 435), (729, 235, 305, 435)]
    medals = [("1ST", (255, 211, 105)), ("2ND", (207, 220, 235)), ("3RD", (202, 145, 108))]
    for idx, (player, (x, y, w, h)) in enumerate(zip(podium, positions)):
        draw.rounded_rectangle((x, y, x+w, y+h), radius=24, fill=(29, 43, 67), outline=(83, 112, 151), width=2)
        avatar = await _avatar(bot, player)
        mask = Image.new("L", (94, 94), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 93, 93), fill=255)
        image.paste(avatar.resize((94,94)), (x+(w-94)//2, y+24), mask)
        draw.text((x+w//2, y+133), medals[idx][0], anchor="mm", font=_font(25), fill=medals[idx][1])
        name = str(player["display_name"] or "Player").replace("🤖 NPC · ", "")
        draw.text((x+w//2, y+177), name[:20], anchor="mm", font=_font(20), fill=(245,248,255))
        if player["is_npc"]:
            draw.text((x+w//2, y+205), "NPC", anchor="mm", font=_font(15), fill=(137,190,255))
        draw.text((x+w//2, y+h-35), f"{int(player['worth']):,} NW", anchor="mm", font=_font(20), fill=(111,224,190))
    draw.rounded_rectangle((38, 730, width-38, 1080), radius=24, fill=(24, 38, 60), outline=(55,76,108), width=1)
    draw.text((72, 755), "TOP 10  /  NET WORTH", font=_font(22), fill=(137,190,255))
    for idx, player in enumerate(rows[3:10], start=4):
        y = 800 + (idx-4)*39
        avatar = await _avatar(bot, player)
        mask = Image.new("L", (30, 30), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 29, 29), fill=255)
        image.paste(avatar.resize((30,30)), (72, y-5), mask)
        label = f"{idx:02d}  {str(player['display_name'] or 'Player')[:23]}"
        if player["is_npc"]:
            label = f"{idx:02d}  NPC · {str(player['display_name'] or 'NPC')[:19]}"
        draw.text((116, y), label, font=_font(17), fill=(239,244,252))
        draw.text((width-75, y), f"{int(player['worth']):,}", anchor="ra", font=_font(17), fill=(111,224,190))
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
