"""Automatic cross-group mining team battles."""
import random
import math
from datetime import datetime, timezone
from app.db import get_pool
from app.mining_rewards import award_mining_group_win
from aiogram import F, Bot, Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

def _box_kb(war_id, matchup):
    styles = ("primary", "success", "danger")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 BOX {n}", callback_data=f"mtpick_{war_id}_{matchup}_{n}", style=styles[row_index])
         for n in range(start, start + 3)]
        for row_index, start in enumerate((1, 4, 7))
    ])


def _as_utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _edit_war_screen(bot, chat_id, message_id, text, markup=None):
    if not message_id:
        return
    try:
        await bot.edit_message_text(chat_id=int(chat_id), message_id=int(message_id), text=text, reply_markup=markup)
    except Exception:
        import logging
        logging.getLogger(__name__).debug("Could not edit mining screen %s in %s", message_id, chat_id, exc_info=True)


async def _refresh_war_screens(bot: Bot, force=False):
    """Keep both groups on the same server deadline and edit countdown checkpoints."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("""SELECT o.*,w.current_matchup,main.chat_id AS main_chat,
            opp.chat_id AS opponent_chat,main.team_size
            FROM mining_team_war_opponents o
            JOIN mining_team_wars w ON w.id=o.war_id
            JOIN mining_teams main ON main.id=w.main_team_id
            JOIN mining_teams opp ON opp.id=o.opponent_team_id
            WHERE w.status='active' AND o.status='active' AND o.deadline_at IS NOT NULL""")
    now = datetime.now(timezone.utc)
    for row in rows:
        deadline = _as_utc(row["deadline_at"])
        remaining = max(0, (deadline - now).total_seconds())
        if remaining > 15:
            checkpoint = 100 + min(3, max(1, math.ceil(remaining - 15)))
            label = f"⏳ MATCHUP STARTS IN {checkpoint - 100}..."
            markup = None
        else:
            checkpoint = math.ceil(remaining)
            label = f"⏱️ {checkpoint} SECONDS LEFT"
            markup = _box_kb(int(row["war_id"]), int(row["matchup_number"]))
        if not force and checkpoint not in {101, 102, 103, 15, 10, 7, 5, 3, 1}:
            continue
        if not force and int(row["countdown_mark"] or -1) == checkpoint:
            continue
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE mining_team_war_opponents SET countdown_mark=$1 WHERE war_id=$2 AND matchup_number=$3 AND countdown_mark<>$1",
                checkpoint, row["war_id"], row["matchup_number"]
            )
            recent = await conn.fetch(
                """SELECT p.display_name,pick.box_number,pick.box_kind
                   FROM mining_team_picks pick JOIN players p ON p.telegram_id=pick.player_id
                   WHERE pick.war_id=$1 AND pick.matchup_number=$2
                   ORDER BY pick.created_at DESC LIMIT 5""",
                row["war_id"], row["matchup_number"]
            )
        labels = {"money": "💰 MONEY", "normal": "⚪ NORMAL", "empty": "🕳 EMPTY"}
        reveal = "\\n".join(
            f"🔓 {item['display_name']}: Box {item['box_number']} → {labels[item['box_kind']]}"
            for item in reversed(recent)
        )
        text = (
            f"⚔️ <b>MINING WAR #{row['war_id']} · MATCHUP {row['matchup_number']}/4</b>\\n"
            f"👥 Team size: {row['team_size']} vs {row['team_size']}\\n"
            f"{label}\\n{reveal}\\n"
            "Each qualified teammate opens one box before the shared timer ends."
        )
        await _edit_war_screen(bot, row["main_chat"], row["main_message_id"], text, markup)
        await _edit_war_screen(bot, row["opponent_chat"], row["opponent_message_id"], text, markup)

async def finalize_mining_event(bot: Bot, event_id: int, chat_id: int):
    """Freeze applicants and qualify top three/five by net worth."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            event = await conn.fetchrow("SELECT * FROM timed_mining_events WHERE id=$1 AND status='joining' AND closes_at<=NOW()", event_id)
            if not event:
                return
            players = await conn.fetch("""SELECT p.telegram_id,p.display_name,
                p.cash+p.stocks+CAST(p.gold_grams*10 AS BIGINT)+COALESCE(v.asset_value,0) AS worth,p.reputation
                FROM timed_mining_players t JOIN players p ON p.telegram_id=t.player_id
                LEFT JOIN player_asset_valuation v ON v.player_id=p.telegram_id
                WHERE t.event_id=$1
                AND NOT EXISTS (
                    SELECT 1 FROM mining_team_players mtp
                    JOIN mining_teams mt ON mt.id=mtp.team_id
                    WHERE mtp.player_id=p.telegram_id AND mt.status IN ('waiting','assigned')
                )
                ORDER BY worth DESC,p.reputation DESC,p.telegram_id ASC""", event_id)
            if len(players) < 3:
                await conn.execute("UPDATE timed_mining_events SET status='skipped',finished_at=NOW() WHERE id=$1", event_id)
                msg = "⛏ <b>MINING SKIPPED</b> — fewer than 3 players joined. Try the next scheduled event."
                team_id = None
            else:
                size = 5 if len(players) >= 5 else 3
                selected = players[:size]
                team_id = await conn.fetchval("INSERT INTO mining_teams(event_id,chat_id,team_size,status) VALUES($1,$2,$3,'waiting') RETURNING id",event_id,chat_id,size)
                for i,p in enumerate(selected,1):
                    await conn.execute("INSERT INTO mining_team_players(team_id,player_id,roster_position,base_worth) VALUES($1,$2,$3,$4)",team_id,p["telegram_id"],i,int(p["worth"] or 0))
                await conn.execute("UPDATE timed_mining_events SET status='finished',finished_at=NOW() WHERE id=$1",event_id)
                msg = (f"⛏ <b>TEAM QUALIFIED — {size} PLAYERS</b>\nSelected the strongest {size} of {len(players)} applicants by net worth.\n"
                       + "\n".join(f"{i}. {p['display_name']} — 💎 {int(p['worth']):,} NW" for i,p in enumerate(selected,1))
                       + "\n\nWaiting for four real teams of the same size from other groups.")
    await bot.send_message(chat_id,msg)
    if team_id:
        await matchmake_waiting_teams(bot)

async def matchmake_waiting_teams(bot: Bot):
    """Reserve five teams from five distinct groups for a four-matchup war."""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            main = None
            opponents = []
            for size in (3,5):
                candidates = await conn.fetch("SELECT * FROM mining_teams WHERE status='waiting' AND team_size=$1 ORDER BY created_at,id",size)
                for candidate in candidates:
                    used = {int(candidate["chat_id"])}
                    found = []
                    for team in candidates:
                        if int(team["id"]) == int(candidate["id"]) or int(team["chat_id"]) in used:
                            continue
                        found.append(team); used.add(int(team["chat_id"]))
                        if len(found) == 4:
                            break
                    if len(found) == 4:
                        main, opponents = candidate, found
                        break
                if main:
                    break
            if not main:
                return
            await conn.execute("UPDATE mining_teams SET status='assigned' WHERE id=$1",main["id"])
            for team in opponents:
                await conn.execute("UPDATE mining_teams SET status='assigned' WHERE id=$1",team["id"])
            war_id = await conn.fetchval("INSERT INTO mining_team_wars(main_team_id,status,current_matchup) VALUES($1,'active',1) RETURNING id",main["id"])
            for i,team in enumerate(opponents,1):
                await conn.execute("INSERT INTO mining_team_war_opponents(war_id,matchup_number,opponent_team_id,status) VALUES($1,$2,$3,$4)",war_id,i,team["id"],"active" if i==1 else "pending")
            await _start_matchup(conn,int(war_id),1)
            teams = [main] + opponents
    intro = (f"⚔️ <b>CROSS-GROUP MINING WAR #{war_id}</b>\n"
             f"Your {main['team_size']}-player team faces four real teams from other groups. Win all four matchups. "
             "Each matchup has a simultaneous 15-second box-pick window.")
    sent_messages = []
    for index, team in enumerate(teams):
        try:
            suffix = "\\n⏳ Matchup 1 starts in 3..." if index <= 1 else "\\n⌛ Your matchup will start after the previous team finishes."
            sent_messages.append(await bot.send_message(team["chat_id"], intro + suffix))
        except Exception:
            sent_messages.append(None)
    main_message_id = sent_messages[0].message_id if sent_messages[0] else None
    async with get_pool().acquire() as conn:
        for matchup_no in range(1, 5):
            opponent_message_id = sent_messages[matchup_no].message_id if sent_messages[matchup_no] else None
            await conn.execute(
                """UPDATE mining_team_war_opponents SET main_message_id=$1,opponent_message_id=$2
                   WHERE war_id=$3 AND matchup_number=$4""",
                main_message_id, opponent_message_id, war_id, matchup_no
            )

async def _start_matchup(conn, war_id: int, matchup: int):
    await conn.execute("UPDATE mining_team_war_opponents SET status='active',deadline_at=NOW()+INTERVAL '18 seconds',countdown_mark=-1 WHERE war_id=$1 AND matchup_number=$2",war_id,matchup)
    rows = await conn.fetch("""SELECT tp.player_id FROM mining_team_war_opponents o
        JOIN mining_team_wars w ON w.id=o.war_id
        JOIN mining_team_players tp ON tp.team_id=w.main_team_id OR tp.team_id=o.opponent_team_id
        WHERE o.war_id=$1 AND o.matchup_number=$2""",war_id,matchup)
    for row in rows:
        layout = ["money"]*3+["normal"]*3+["empty"]*3
        random.SystemRandom().shuffle(layout)
        await conn.execute("INSERT INTO mining_team_layouts(war_id,matchup_number,player_id,layout) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",war_id,matchup,row["player_id"],",".join(layout))

async def mining_team_tick(bot: Bot):
    """Resolve a matchup on its shared deadline and reuse both group messages."""
    await _refresh_war_screens(bot)
    async with get_pool().acquire() as conn:
        due = await conn.fetch("""SELECT o.war_id,o.matchup_number,o.main_message_id,o.opponent_message_id,
            w.main_team_id,main.event_id AS main_event_id,main.team_size,main.chat_id AS main_chat,
            o.opponent_team_id,opp.chat_id AS opponent_chat
            FROM mining_team_war_opponents o JOIN mining_team_wars w ON w.id=o.war_id
            JOIN mining_teams main ON main.id=w.main_team_id JOIN mining_teams opp ON opp.id=o.opponent_team_id
            WHERE w.status='active' AND o.status='active' AND o.deadline_at<=NOW()""")
    for item in due:
        next_matchup = None
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT status FROM mining_team_war_opponents WHERE war_id=$1 AND matchup_number=$2 AND status='active' AND deadline_at<=NOW()",
                    item["war_id"], item["matchup_number"]
                )
                if not current:
                    continue
                a = await conn.fetch("SELECT player_id,roster_position FROM mining_team_players WHERE team_id=$1 ORDER BY roster_position",item["main_team_id"])
                b = await conn.fetch("SELECT player_id,roster_position FROM mining_team_players WHERE team_id=$1 ORDER BY roster_position",item["opponent_team_id"])
                picks = await conn.fetch("SELECT player_id,temporary_worth FROM mining_team_picks WHERE war_id=$1 AND matchup_number=$2",item["war_id"],item["matchup_number"])
                pmap = {int(p["player_id"]):int(p["temporary_worth"]) for p in picks}
                aw=bw=0
                for pa,pb in zip(a,b):
                    va=pmap.get(int(pa["player_id"])); vb=pmap.get(int(pb["player_id"]))
                    if va is not None and (vb is None or va>vb): aw+=1
                    elif vb is not None and (va is None or vb>va): bw+=1
                won = aw==3 if int(item["team_size"])==3 else aw>=3
                if won:
                    await conn.execute("UPDATE mining_team_war_opponents SET status='won' WHERE war_id=$1 AND matchup_number=$2",item["war_id"],item["matchup_number"])
                    if int(item["matchup_number"])==4:
                        await conn.execute("UPDATE mining_team_wars SET status='won',finished_at=NOW(),main_wins=4 WHERE id=$1",item["war_id"])
                        await conn.execute("UPDATE mining_teams SET status='finished' WHERE id IN (SELECT main_team_id FROM mining_team_wars WHERE id=$1 UNION SELECT opponent_team_id FROM mining_team_war_opponents WHERE war_id=$1)",item["war_id"])
                        result="🏆 <b>MINING WAR WON!</b> Your team won all four matchups.\\n💰 Your group earns +15% collection for known members; winning team members get +30% until the next mining."
                    else:
                        nxt=int(item["matchup_number"])+1
                        await conn.execute("UPDATE mining_team_wars SET current_matchup=$2,main_wins=main_wins+1 WHERE id=$1",item["war_id"],nxt)
                        await _start_matchup(conn,int(item["war_id"]),nxt)
                        await conn.execute(
                            """UPDATE mining_team_war_opponents SET main_message_id=$1
                               WHERE war_id=$2 AND matchup_number=$3""",
                            item["main_message_id"],item["war_id"],nxt
                        )
                        result=f"✅ <b>MATCHUP {item['matchup_number']} WON</b> — {aw}–{bw}.\\n⏳ MATCHUP {nxt}/4 starts in 3..."
                        next_matchup = nxt
                else:
                    await conn.execute("UPDATE mining_team_war_opponents SET status='lost' WHERE war_id=$1 AND matchup_number=$2",item["war_id"],item["matchup_number"])
                    await conn.execute("UPDATE mining_team_wars SET status='lost',finished_at=NOW() WHERE id=$1",item["war_id"])
                    await conn.execute("UPDATE mining_teams SET status='finished' WHERE id IN (SELECT main_team_id FROM mining_team_wars WHERE id=$1 UNION SELECT opponent_team_id FROM mining_team_war_opponents WHERE war_id=$1)",item["war_id"])
                    result=f"❌ <b>MINING WAR LOST</b> — matchup {item['matchup_number']} ended {aw}–{bw}. All four matchups must be won."
        if won and int(item["matchup_number"]) == 4:
            try:
                await award_mining_group_win(
                    int(item["main_chat"]), int(item["main_event_id"]), int(item["main_team_id"])
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Could not award mining group bonus for war %s", item["war_id"])
        for chat_id, message_id in (
            (int(item["main_chat"]), item["main_message_id"]),
            (int(item["opponent_chat"]), item["opponent_message_id"]),
        ):
            await _edit_war_screen(
                bot, chat_id, message_id, result,
                None
            )


def register_mining_team_handlers(bot: Bot, dp: Dispatcher):
    @dp.callback_query(F.data.startswith("mtpick_"))
    async def mining_team_pick(c: CallbackQuery):
        try:
            _,war_id,matchup,box_no=c.data.split("_")
            war_id,matchup,box_no=int(war_id),int(matchup),int(box_no)
            if not 1<=box_no<=9: raise ValueError
        except (ValueError,AttributeError):
            await c.answer("Invalid box.",show_alert=True); return
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                row=await conn.fetchrow("""SELECT w.status,w.current_matchup,o.status AS matchup_status,o.deadline_at,
                    tp.base_worth,l.layout FROM mining_team_wars w
                    JOIN mining_team_war_opponents o ON o.war_id=w.id AND o.matchup_number=$2
                    JOIN mining_team_players tp ON tp.player_id=$3 AND tp.team_id IN (w.main_team_id,o.opponent_team_id)
                    JOIN mining_team_layouts l ON l.war_id=w.id AND l.matchup_number=o.matchup_number AND l.player_id=$3
                    WHERE w.id=$1 AND o.deadline_at>NOW()""",war_id,matchup,c.from_user.id)
                if not row or row["status"]!="active" or int(row["current_matchup"])!=matchup or row["matchup_status"]!="active":
                    await c.answer("This matchup is not active for you.",show_alert=True); return
                if row["deadline_at"] is None:
                    await c.answer("This matchup is not open.",show_alert=True); return
                remaining = (_as_utc(row["deadline_at"]) - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    await c.answer("The matchup timer has ended.",show_alert=True); return
                if remaining > 15:
                    await c.answer("The matchup countdown is still running.",show_alert=True); return
                exists=await conn.fetchval("SELECT 1 FROM mining_team_picks WHERE war_id=$1 AND matchup_number=$2 AND player_id=$3",war_id,matchup,c.from_user.id)
                if exists:
                    await c.answer("You already picked a box this matchup.",show_alert=True); return
                kind=str(row["layout"]).split(",")[box_no-1]
                mult=1.2 if kind=="money" else .8 if kind=="empty" else 1.0
                worth=int(round(int(row["base_worth"] or 0)*mult))
                await conn.execute("INSERT INTO mining_team_picks(war_id,matchup_number,player_id,box_number,box_kind,temporary_worth) VALUES($1,$2,$3,$4,$5,$6)",war_id,matchup,c.from_user.id,box_no,kind,worth)
        desc={"money":"Money box: +20% temporary net worth","normal":"Normal box: net worth unchanged","empty":"Empty box: -20% temporary net worth"}[kind]
        await c.answer(desc,show_alert=True)
        await _refresh_war_screens(bot, force=True)
