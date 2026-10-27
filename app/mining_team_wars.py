"""Automatic cross-group mining team battles."""
import random
from app.db import get_pool
from aiogram import F, Bot, Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

def _box_kb(war_id, matchup):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {n}", callback_data=f"mtpick_{war_id}_{matchup}_{n}") for n in range(start,start+3)]
        for start in (1,4,7)
    ])

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
                WHERE t.event_id=$1 ORDER BY worth DESC,p.reputation DESC,p.telegram_id ASC""", event_id)
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
    for team in teams:
        try:
            await bot.send_message(team["chat_id"],intro,reply_markup=_box_kb(int(war_id),1))
        except Exception:
            pass

async def _start_matchup(conn, war_id: int, matchup: int):
    await conn.execute("UPDATE mining_team_war_opponents SET status='active',deadline_at=NOW()+INTERVAL '15 seconds' WHERE war_id=$1 AND matchup_number=$2",war_id,matchup)
    rows = await conn.fetch("""SELECT tp.player_id FROM mining_team_war_opponents o
        JOIN mining_team_wars w ON w.id=o.war_id
        JOIN mining_team_players tp ON tp.team_id=w.main_team_id OR tp.team_id=o.opponent_team_id
        WHERE o.war_id=$1 AND o.matchup_number=$2""",war_id,matchup)
    for row in rows:
        layout = ["money"]*3+["normal"]*3+["empty"]*3
        random.SystemRandom().shuffle(layout)
        await conn.execute("INSERT INTO mining_team_layouts(war_id,matchup_number,player_id,layout) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",war_id,matchup,row["player_id"],",".join(layout))

async def mining_team_tick(bot: Bot):
    """Resolve a matchup after its server-side deadline, then advance or end the war."""
    async with get_pool().acquire() as conn:
        due = await conn.fetch("""SELECT o.war_id,o.matchup_number,w.main_team_id,main.team_size,main.chat_id AS main_chat,
            o.opponent_team_id,opp.chat_id AS opponent_chat
            FROM mining_team_war_opponents o JOIN mining_team_wars w ON w.id=o.war_id
            JOIN mining_teams main ON main.id=w.main_team_id JOIN mining_teams opp ON opp.id=o.opponent_team_id
            WHERE w.status='active' AND o.status='active' AND o.deadline_at<=NOW()""")
    for item in due:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow("SELECT status FROM mining_team_war_opponents WHERE war_id=$1 AND matchup_number=$2 AND status='active' AND deadline_at<=NOW()",item["war_id"],item["matchup_number"])
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
                        result="🏆 <b>MINING WAR WON!</b> Your team won all four matchups."
                    else:
                        nxt=int(item["matchup_number"])+1
                        await conn.execute("UPDATE mining_team_wars SET current_matchup=$2,main_wins=main_wins+1 WHERE id=$1",item["war_id"],nxt)
                        await _start_matchup(conn,int(item["war_id"]),nxt)
                        result=f"✅ <b>MATCHUP {item['matchup_number']} WON</b> — {aw}–{bw}. Next matchup starts now."
                else:
                    await conn.execute("UPDATE mining_team_war_opponents SET status='lost' WHERE war_id=$1 AND matchup_number=$2",item["war_id"],item["matchup_number"])
                    await conn.execute("UPDATE mining_team_wars SET status='lost',finished_at=NOW() WHERE id=$1",item["war_id"])
                    await conn.execute("UPDATE mining_teams SET status='finished' WHERE id IN (SELECT main_team_id FROM mining_team_wars WHERE id=$1 UNION SELECT opponent_team_id FROM mining_team_war_opponents WHERE war_id=$1)",item["war_id"])
                    result=f"❌ <b>MINING WAR LOST</b> — matchup {item['matchup_number']} ended {aw}–{bw}. All four matchups must be won."
        for chat_id in {int(item["main_chat"]),int(item["opponent_chat"])}:
            try:
                await bot.send_message(chat_id,result)
                if "Next matchup" in result:
                    await bot.send_message(chat_id,f"⚔️ <b>MATCHUP {int(item['matchup_number'])+1}</b> — choose one box within 15 seconds.",reply_markup=_box_kb(int(item["war_id"]),int(item["matchup_number"])+1))
            except Exception:
                pass

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
                exists=await conn.fetchval("SELECT 1 FROM mining_team_picks WHERE war_id=$1 AND matchup_number=$2 AND player_id=$3",war_id,matchup,c.from_user.id)
                if exists:
                    await c.answer("You already picked a box this matchup.",show_alert=True); return
                kind=str(row["layout"]).split(",")[box_no-1]
                mult=1.2 if kind=="money" else .8 if kind=="empty" else 1.0
                worth=int(round(int(row["base_worth"] or 0)*mult))
                await conn.execute("INSERT INTO mining_team_picks(war_id,matchup_number,player_id,box_number,box_kind,temporary_worth) VALUES($1,$2,$3,$4,$5,$6)",war_id,matchup,c.from_user.id,box_no,kind,worth)
        desc={"money":"Money box: +20% temporary net worth","normal":"Normal box: net worth unchanged","empty":"Empty box: -20% temporary net worth"}[kind]
        await c.answer(desc,show_alert=True)
