import asyncio, os, sqlite3
from datetime import datetime, timezone
from urllib.parse import quote_plus
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
ACCESS_IDS = {int(x.strip()) for x in os.getenv("ACCESS_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "osint_bot.db")
if not TOKEN: raise RuntimeError("BOT_TOKEN is required")
if not ADMIN_IDS: raise RuntimeError("ADMIN_IDS must contain your Telegram numeric ID")
dp, state = Dispatcher(), {}

def connect():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c
def init_db():
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS access_users(user_id INTEGER PRIMARY KEY, added_by INTEGER, added_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS searches(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,created_at TEXT,description TEXT)")
        for uid in ADMIN_IDS | ACCESS_IDS:
            c.execute("INSERT OR IGNORE INTO access_users VALUES(?,?,?)",(uid,next(iter(ADMIN_IDS)),datetime.now(timezone.utc).isoformat()))
def allowed(uid):
    if uid in ADMIN_IDS: return True
    with connect() as c: return c.execute("SELECT 1 FROM access_users WHERE user_id=?",(uid,)).fetchone() is not None
def menu(uid):
    b=InlineKeyboardBuilder(); b.button(text="🔎 Новый поиск",callback_data="new"); b.button(text="🗂 История",callback_data="history")
    if uid in ADMIN_IDS: b.button(text="🔐 Доступ",callback_data="access")
    b.adjust(1); return b.as_markup()
def cancel_kb():
    b=InlineKeyboardBuilder(); b.button(text="Отмена",callback_data="home"); return b.as_markup()
def access_kb():
    b=InlineKeyboardBuilder()
    for t,d in [("➕ Добавить ID","add"),("➖ Удалить ID","remove"),("📋 Список доступа","list"),("⬅️ Назад","home")]: b.button(text=t,callback_data="access_"+d)
    b.adjust(1); return b.as_markup()
def links(q):
    return [
      ("Google — открытый веб","https://www.google.com/search?q="+quote_plus(q)),
      ("Bing — открытый веб","https://www.bing.com/search?q="+quote_plus(q)),
      ("Telegram, публичные страницы","https://www.google.com/search?q="+quote_plus("site:t.me "+q)),
      ("Instagram, публичные страницы","https://www.google.com/search?q="+quote_plus("site:instagram.com "+q)),
      ("TikTok, публичные страницы","https://www.google.com/search?q="+quote_plus("site:tiktok.com "+q)),
      ("VK, публичные страницы","https://www.google.com/search?q="+quote_plus("site:vk.com "+q))]
@dp.message(CommandStart())
async def start(m:Message):
    if not allowed(m.from_user.id): return await m.answer("🔒 Доступ закрыт. Попросите владельца добавить ваш Telegram ID.")
    await m.answer("OSINT • Минималистичный поиск\n\nПоиск только по открытым источникам. Результаты нужно проверять вручную. Не используйте для преследования и не отправляйте пароли или документы.",reply_markup=menu(m.from_user.id))
@dp.message(Command("id"))
async def getid(m:Message): await m.answer(f"Ваш Telegram ID: {m.from_user.id}")
@dp.callback_query(F.data=="home")
async def home(c:CallbackQuery):
    state.pop(c.from_user.id,None)
    if allowed(c.from_user.id): await c.message.edit_text("OSINT • Выберите действие",reply_markup=menu(c.from_user.id))
    else: await c.message.edit_text("🔒 Доступ закрыт.")
    await c.answer()
@dp.callback_query(F.data=="new")
async def new(c:CallbackQuery):
    if not allowed(c.from_user.id): return await c.answer("Доступ закрыт",show_alert=True)
    state[c.from_user.id]="search"
    await c.message.edit_text("🔎 Отправьте известный публичный ник, имя или другой поисковый запрос. Я создам ссылки для поиска по открытым сайтам. Не вводите чувствительные данные.",reply_markup=cancel_kb()); await c.answer()
@dp.message()
async def text_handler(m:Message):
    uid=m.from_user.id
    if not allowed(uid): return await m.answer("🔒 Доступ закрыт.")
    txt=(m.text or "").strip()
    if state.get(uid)=="search":
        if not txt or len(txt)>180: return await m.answer("Запрос должен быть от 1 до 180 символов.",reply_markup=cancel_kb())
        state.pop(uid,None)
        with connect() as c: c.execute("INSERT INTO searches(user_id,created_at,description) VALUES(?,?,?)",(uid,datetime.now(timezone.utc).isoformat(),f"Запрос ({len(txt)} символов)"))
        out=["🔎 Ссылки для проверки открытых источников:","", "Поисковые результаты не подтверждают личность. Сверяйте несколько независимых источников."]
        out += [f"• {name}: {url}" for name,url in links(txt)]
        out += ["","Это ссылки на поисковые запросы, а не подтверждённые сведения."]
        return await m.answer("\n".join(out),reply_markup=menu(uid),disable_web_page_preview=True)
    if state.get(uid) in ("add","remove") and uid in ADMIN_IDS:
        if not txt.isdigit(): return await m.answer("Отправьте числовой Telegram ID.",reply_markup=cancel_kb())
        target=int(txt)
        if target in ADMIN_IDS: state.pop(uid,None); return await m.answer("Нельзя удалить владельца.",reply_markup=access_kb())
        with connect() as c:
            if state[uid]=="add":
                c.execute("INSERT OR IGNORE INTO access_users VALUES(?,?,?)",(target,uid,datetime.now(timezone.utc).isoformat())); msg=f"ID {target} добавлен или уже разрешён."
            else:
                c.execute("DELETE FROM access_users WHERE user_id=?",(target,)); msg=f"Доступ для ID {target} удалён."
        state.pop(uid,None); return await m.answer(msg,reply_markup=access_kb())
    await m.answer("Выберите действие в меню.",reply_markup=menu(uid))
@dp.callback_query(F.data=="history")
async def history(c:CallbackQuery):
    if not allowed(c.from_user.id): return await c.answer("Доступ закрыт",show_alert=True)
    with connect() as db: rows=db.execute("SELECT id,created_at,description FROM searches WHERE user_id=? ORDER BY id DESC LIMIT 10",(c.from_user.id,)).fetchall()
    msg="🗂 История (введённые запросы не сохраняются):\n\n"+"\n".join(f"#{r['id']} · {r['created_at'][:16].replace('T',' ')} · {r['description']}" for r in rows) if rows else "История пока пуста."
    await c.message.edit_text(msg,reply_markup=menu(c.from_user.id)); await c.answer()
@dp.callback_query(F.data=="access")
async def access(c:CallbackQuery):
    if c.from_user.id not in ADMIN_IDS: return await c.answer("Только владелец",show_alert=True)
    await c.message.edit_text("🔐 Управление доступом",reply_markup=access_kb()); await c.answer()
@dp.callback_query(F.data.in_({"access_add","access_remove"}))
async def access_change(c:CallbackQuery):
    if c.from_user.id not in ADMIN_IDS: return await c.answer("Только владелец",show_alert=True)
    state[c.from_user.id]="add" if c.data=="access_add" else "remove"
    await c.message.edit_text("Отправьте числовой Telegram ID пользователя.",reply_markup=cancel_kb()); await c.answer()
@dp.callback_query(F.data=="access_list")
async def access_list(c:CallbackQuery):
    if c.from_user.id not in ADMIN_IDS: return await c.answer("Только владелец",show_alert=True)
    with connect() as db: rows=db.execute("SELECT user_id FROM access_users ORDER BY user_id").fetchall()
    await c.message.edit_text("📋 Разрешённые ID:\n\n"+"\n".join(str(r["user_id"]) for r in rows),reply_markup=access_kb()); await c.answer()
async def main():
    init_db(); bot=Bot(TOKEN)
    try: await dp.start_polling(bot)
    finally: await bot.session.close()
if __name__=="__main__": asyncio.run(main())
