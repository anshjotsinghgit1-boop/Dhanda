import json
import random
from app.db import get_pool

KINDS = ("money", "normal", "empty")

def new_layout():
    items = ["money"] * 3 + ["normal"] * 3 + ["empty"] * 3
    random.shuffle(items)
    return items

async def save_layout(player_id, slot, items):
    if slot not in range(1, 6) or len(items) != 9:
        return False
    if any(items.count(k) != 3 for k in KINDS):
        return False
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO box_layouts(player_id,layout_no,outcomes) VALUES($1,$2,$3) ON CONFLICT(player_id,layout_no) DO UPDATE SET outcomes=excluded.outcomes,updated_at=CURRENT_TIMESTAMP",
            player_id, slot, json.dumps(items))
    return True

async def random_layout(player_id):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT outcomes FROM box_layouts WHERE player_id=$1", player_id)
    return json.loads(random.choice(rows)["outcomes"]) if rows else new_layout()
