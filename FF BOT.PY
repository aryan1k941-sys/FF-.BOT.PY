import asyncio, os, sqlite3
from datetime import datetime, timezone
from html import escape
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

# FREE TOURNAMENT VERSION
# No deposits, withdrawals, betting, cash prizes, or UPI collection.
# Set BOT_TOKEN and ADMIN_IDS in environment variables.

TOKEN = os.getenv("8952622545:AAGCsPsZIIcx2ZljrH2WO25dnH8kk748Py8", "").strip()
ADMINS = {int(x) for x in os.getenv("8955272657", "").split(",") if x.strip().isdigit()}
DB = os.getenv("DB_PATH", "ff_tournament.db")

if not TOKEN: raise RuntimeError("BOT_TOKEN is missing")
if not ADMINS: raise RuntimeError("ADMIN_IDS is missing")

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
db = sqlite3.connect(DB, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def init():
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT, name TEXT, joined TEXT,
      ref TEXT UNIQUE, referred_by INTEGER, points INTEGER DEFAULT 0,
      banned INTEGER DEFAULT 0, admin INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS tournaments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, mode TEXT,
      start TEXT, description TEXT, max_players INTEGER DEFAULT 48,
      status TEXT DEFAULT 'open', room_id TEXT DEFAULT '',
      room_pass TEXT DEFAULT '', created TEXT
    );
    CREATE TABLE IF NOT EXISTS joins(
      tournament_id INTEGER, user_id INTEGER, joined TEXT,
      PRIMARY KEY(tournament_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS announcements(
      id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    """)
    for aid in ADMINS:
        db.execute("""INSERT INTO users(id,username,name,joined,ref,admin)
                      VALUES(?,?,?,?,?,1)
                      ON CONFLICT(id) DO UPDATE SET admin=1""",
                   (aid,"","Admin",now(),f"ADMIN{aid}"))
    db.commit()

def user(tg):
    r=db.execute("SELECT * FROM users WHERE id=?",(tg.id,)).fetchone()
    if r:
        db.execute("UPDATE users SET username=?,name=? WHERE id=?",
                   (tg.username or "",tg.first_name or "",tg.id)); db.commit()
        return db.execute("SELECT * FROM users WHERE id=?",(tg.id,)).fetchone()
    ref=f"FF{tg.id}"
    db.execute("""INSERT INTO users(id,username,name,joined,ref,admin)
                  VALUES(?,?,?,?,?,?)""",
               (tg.id,tg.username or "",tg.first_name or "",now(),ref,int(tg.id in ADMINS)))
    db.commit()
    return db.execute("SELECT * FROM users WHERE id=?",(tg.id,)).fetchone()

def admin(uid):
    r=db.execute("SELECT admin FROM users WHERE id=?",(uid,)).fetchone()
    return uid in ADMINS or bool(r and r["admin"])

def banned(uid):
    r=db.execute("SELECT banned FROM users WHERE id=?",(uid,)).fetchone()
    return bool(r and r["banned"])

def kb(uid):
    rows=[
      [KeyboardButton(text="🏆 Tournaments"),KeyboardButton(text="🎮 My Tournaments")],
      [KeyboardButton(text="👤 Profile"),KeyboardButton(text="🎁 Referral")],
      [KeyboardButton(text="📢 Announcements"),KeyboardButton(text="ℹ️ Help")]
    ]
    if admin(uid): rows.append([KeyboardButton(text="🛠 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True)

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="➕ Create",callback_data="a:create"),
       InlineKeyboardButton(text="📋 List",callback_data="a:list")],
      [InlineKeyboardButton(text="📊 Stats",callback_data="a:stats"),
       InlineKeyboardButton(text="📢 Broadcast",callback_data="a:broadcast")],
      [InlineKeyboardButton(text="👥 Users",callback_data="a:users"),
       InlineKeyboardButton(text="⚙️ Settings",callback_data="a:settings")]
    ])

def tbuttons(tid,status,adm=False):
    b=[InlineKeyboardButton(text="👥 Players",callback_data=f"players:{tid}")]
    if status=="open": b.insert(0,InlineKeyboardButton(text="✅ Join",callback_data=f"join:{tid}"))
    if adm:
        b.append(InlineKeyboardButton(text="🔒 Close",callback_data=f"close:{tid}"))
        b.append(InlineKeyboardButton(text="🎮 Room",callback_data=f"room:{tid}"))
    return InlineKeyboardMarkup(inline_keyboard=[b])

def tfmt(r):
    n=db.execute("SELECT COUNT(*) n FROM joins WHERE tournament_id=?",(r["id"],)).fetchone()["n"]
    return (f"🏆 <b>{escape(r['title'])}</b>\n🆔 {r['id']}\n"
            f"🎮 {escape(r['mode'])}\n🕒 {escape(r['start'])}\n"
            f"👥 {n}/{r['max_players']}\n📌 {r['status']}\n"
            f"📝 {escape(r['description'] or 'No description')}")

class Create(StatesGroup):
    title=State(); mode=State(); start=State(); desc=State(); maxp=State()

class Broadcast(StatesGroup): text=State()

@dp.message(CommandStart())
async def start(m:Message):
    u=user(m.from_user)
    if banned(u["id"]): return await m.answer("🚫 Your account is blocked.")
    await m.answer("🔥 <b>FF Tournament Hub</b>\n\nFree tournament manager. Use the menu below.",
                   reply_markup=kb(u["id"]))

@dp.message(Command("id"))
async def get_id(m:Message):
    user(m.from_user); await m.answer(f"Your Telegram ID: <code>{m.from_user.id}</code>")

@dp.message(F.text=="🏆 Tournaments")
async def tournaments(m:Message):
    u=user(m.from_user)
    rows=db.execute("SELECT * FROM tournaments WHERE status='open' ORDER BY id DESC LIMIT 30").fetchall()
    if not rows: return await m.answer("🏆 No open tournaments yet.")
    for r in rows: await m.answer(tfmt(r),reply_markup=tbuttons(r["id"],r["status"]))

@dp.message(F.text=="🎮 My Tournaments")
async def mine(m:Message):
    u=user(m.from_user)
    rows=db.execute("""SELECT t.* FROM tournaments t JOIN joins j ON j.tournament_id=t.id
                       WHERE j.user_id=? ORDER BY t.id DESC""",(u["id"],)).fetchall()
    if not rows: return await m.answer("You have not joined any tournament.")
    for r in rows: await m.answer(tfmt(r),reply_markup=tbuttons(r["id"],r["status"]))

@dp.message(F.text=="👤 Profile")
async def profile(m:Message):
    u=user(m.from_user)
    n=db.execute("SELECT COUNT(*) n FROM joins WHERE user_id=?",(u["id"],)).fetchone()["n"]
    await m.answer(f"👤 <b>Profile</b>\n\nName: {escape(u['name'])}\nID: <code>{u['id']}</code>\n"
                   f"Tournaments: {n}\nReferral points: {u['points']}")

@dp.message(F.text=="🎁 Referral")
async def referral(m:Message):
    u=user(m.from_user); me=await bot.get_me()
    link=f"https://t.me/{me.username}?start={u['ref']}"
    n=db.execute("SELECT COUNT(*) n FROM users WHERE referred_by=?",(u["id"],)).fetchone()["n"]
    await m.answer(f"🎁 <b>Referral</b>\nCode: <code>{u['ref']}</code>\n"
                   f"Link: <code>{link}</code>\nReferred users: {n}\nPoints: {u['points']}\n"
                   "Points are non-cash.")

@dp.message(F.text=="📢 Announcements")
async def anns(m:Message):
    user(m.from_user)
    rows=db.execute("SELECT text FROM announcements ORDER BY id DESC LIMIT 10").fetchall()
    await m.answer("📢 <b>Announcements</b>\n\n" + ("\n".join("• "+escape(x["text"]) for x in rows) if rows else "None yet."))

@dp.message(F.text=="ℹ️ Help")
async def help_(m:Message):
    user(m.from_user)
    await m.answer("ℹ️ Use Tournaments to join events. Profile shows your account. Referral gives a non-cash points code. Admins can create events and broadcast notices.")

@dp.callback_query(F.data.startswith("join:"))
async def join(c:CallbackQuery):
    u=user(c.from_user); tid=int(c.data.split(":")[1])
    if banned(u["id"]): return await c.answer("Blocked",show_alert=True)
    t=db.execute("SELECT * FROM tournaments WHERE id=?",(tid,)).fetchone()
    if not t or t["status"]!="open": return await c.answer("Tournament is closed/not found.",show_alert=True)
    n=db.execute("SELECT COUNT(*) n FROM joins WHERE tournament_id=?",(tid,)).fetchone()["n"]
    if n>=t["max_players"]: return await c.answer("Tournament is full.",show_alert=True)
    try:
        db.execute("INSERT INTO joins VALUES(?,?,?)",(tid,u["id"],now()))
        db.commit()
    except sqlite3.IntegrityError: return await c.answer("Already joined.",show_alert=True)
    await c.answer("Joined! 🎮")
    await c.message.answer(f"✅ Joined <b>{escape(t['title'])}</b>. Room details will be published by admin.")

@dp.callback_query(F.data.startswith("players:"))
async def players(c:CallbackQuery):
    tid=int(c.data.split(":")[1])
    rows=db.execute("""SELECT u.* FROM users u JOIN joins j ON j.user_id=u.id
                       WHERE j.tournament_id=? ORDER BY j.joined""",(tid,)).fetchall()
    text="👥 <b>Players</b>\n\n"+("\n".join(f"{i}. {escape(r['name'])}" for i,r in enumerate(rows,1)) or "None")
    await c.message.answer(text[:4000]); await c.answer()

@dp.message(F.text=="🛠 Admin Panel")
async def admin_panel(m:Message):
    user(m.from_user)
    if not admin(m.from_user.id): return await m.answer("⛔ Admin only.")
    await m.answer("🛠 <b>Admin Panel</b>",reply_markup=admin_kb())

@dp.message(Command("admin"))
async def admin_cmd(m:Message): await admin_panel(m)

@dp.callback_query(F.data=="a:create")
async def create(c:CallbackQuery,state:FSMContext):
    if not admin(c.from_user.id): return
    await state.set_state(Create.title); await c.message.answer("Tournament title?"); await c.answer()

@dp.message(Create.title)
async def ct(m:Message,state:FSMContext):
    await state.update_data(title=m.text); await state.set_state(Create.mode); await m.answer("Mode? Solo / Duo / Squad")

@dp.message(Create.mode)
async def cm(m:Message,state:FSMContext):
    await state.update_data(mode=m.text); await state.set_state(Create.start); await m.answer("Start date/time? Example: 2026-10-05 20:00 IST")

@dp.message(Create.start)
async def cs(m:Message,state:FSMContext):
    await state.update_data(start=m.text); await state.set_state(Create.desc); await m.answer("Description?")

@dp.message(Create.desc)
async def cd(m:Message,state:FSMContext):
    await state.update_data(desc=m.text); await state.set_state(Create.maxp); await m.answer("Maximum players?")

@dp.message(Create.maxp)
async def cp(m:Message,state:FSMContext):
    try: maxp=int(m.text)
    except: return await m.answer("Enter a number, e.g. 48.")
    if not 2<=maxp<=10000: return await m.answer("Use 2 to 10000.")
    d=await state.get_data()
    db.execute("""INSERT INTO tournaments(title,mode,start,description,max_players,created)
                  VALUES(?,?,?,?,?,?)""",(d["title"],d["mode"],d["start"],d["desc"],maxp,now()))
    db.commit(); await state.clear(); await m.answer("✅ Tournament created.")

@dp.callback_query(F.data=="a:list")
async def alist(c:CallbackQuery):
    if not admin(c.from_user.id): return
    rows=db.execute("SELECT * FROM tournaments ORDER BY id DESC LIMIT 30").fetchall()
    if not rows: await c.message.answer("No tournaments.")
    for r in rows: await c.message.answer(tfmt(r),reply_markup=tbuttons(r["id"],r["status"],True))
    await c.answer()

@dp.callback_query(F.data.startswith("close:"))
async def close(c:CallbackQuery):
    if not admin(c.from_user.id): return
    tid=int(c.data.split(":")[1]); db.execute("UPDATE tournaments SET status='closed' WHERE id=?",(tid,)); db.commit()
    await c.answer("Closed"); await c.message.answer("🔒 Tournament closed.")

@dp.callback_query(F.data.startswith("room:"))
async def room(c:CallbackQuery):
    if not admin(c.from_user.id): return
    r=db.execute("SELECT * FROM tournaments WHERE id=?",(int(c.data.split(":")[1]),)).fetchone()
    await c.message.answer("Room is not configured in this free starter version. Add your room workflow to the backend before publishing credentials.")
    await c.answer()

@dp.callback_query(F.data=="a:stats")
async def stats(c:CallbackQuery):
    if not admin(c.from_user.id): return
    u=db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    t=db.execute("SELECT COUNT(*) n FROM tournaments").fetchone()["n"]
    j=db.execute("SELECT COUNT(*) n FROM joins").fetchone()["n"]
    await c.message.answer(f"📊 <b>Stats</b>\nUsers: {u}\nTournaments: {t}\nJoins: {j}"); await c.answer()

@dp.callback_query(F.data=="a:users")
async def users(c:CallbackQuery):
    if not admin(c.from_user.id): return
    rows=db.execute("SELECT id,name,username,points,banned FROM users ORDER BY joined DESC LIMIT 30").fetchall()
    text="👥 <b>Users</b>\n\n"
    for r in rows:
        text+=f"{'🚫' if r['banned'] else '✅'} <code>{r['id']}</code> {escape(r['name'] or '')} @{escape(r['username'] or '-')}\n"
    await c.message.answer(text[:4000]); await c.answer()

@dp.callback_query(F.data=="a:settings")
async def settings(c:CallbackQuery):
    if not admin(c.from_user.id): return
    await c.message.answer("⚙️ Settings are stored in SQLite. Keep secrets such as BOT_TOKEN in environment variables, never in public code.")
    await c.answer()

@dp.callback_query(F.data=="a:broadcast")
async def broadcast(c:CallbackQuery,state:FSMContext):
    if not admin(c.from_user.id): return
    await state.set_state(Broadcast.text); await c.message.answer("Send announcement text."); await c.answer()

@dp.message(Broadcast.text)
async def do_broadcast(m:Message,state:FSMContext):
    if not admin(m.from_user.id): await state.clear(); return
    text=m.text.strip()
    db.execute("INSERT INTO announcements(text,created) VALUES(?,?)",(text,now())); db.commit()
    rows=db.execute("SELECT id FROM users WHERE banned=0").fetchall()
    ok=bad=0
    for r in rows:
        try:
            await bot.send_message(r["id"],"📢 <b>Announcement</b>\n\n"+escape(text)); ok+=1
            await asyncio.sleep(.05)
        except Exception: bad+=1
    await state.clear(); await m.answer(f"✅ Broadcast done. Sent: {ok}, failed: {bad}")

@dp.message()
async def fallback(m:Message):
    u=user(m.from_user)
    if banned(u["id"]): return await m.answer("🚫 Your account is blocked.")
    await m.answer("Use the menu buttons below.",reply_markup=kb(u["id"]))

async def main():
    init()
    print("FF Tournament Bot running...")
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
    