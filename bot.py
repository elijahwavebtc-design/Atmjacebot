import os, io, csv, sqlite3, random, asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ["TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
CODES_VALIDES = None   # ou {"AFF001", "AFF002"} pour n'accepter que certains codes

db = sqlite3.connect(os.environ.get("DB_PATH", "bot.db"), check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY, code TEXT, grp TEXT DEFAULT 'T',
    nom TEXT, username TEXT, date TEXT DEFAULT CURRENT_TIMESTAMP)""")
db.commit()

def total(): return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def membres(g):
    if g == "T":
        rows = db.execute("SELECT chat_id FROM users").fetchall()
    else:
        rows = db.execute("SELECT chat_id FROM users WHERE grp LIKE ?", (g + "%",)).fetchall()
    return [r[0] for r in rows]

def admin_only(f):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id == ADMIN_ID:
            await f(update, ctx)
    return wrapper

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(
            "Mode admin.\n/stats : nombre d'inscrits\n/liste : liste des inscrits\n"
            "/choisir A : choisir le groupe cible\n/split A : diviser un groupe\n"
            "/delete A : supprimer un groupe\n/reset : tout remettre dans un seul groupe\n"
            "Ensuite, écris ton message normalement : il part au groupe choisi.")
    else:
        await update.message.reply_text("Bienvenue ! Envoie ton code d'affiliation pour t'inscrire.")

async def diffuser(ctx, ids, texte, cible):
    ok = 0
    for chat_id in ids:
        try:
            await ctx.bot.send_message(chat_id, texte)
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await ctx.bot.send_message(ADMIN_ID, f"✅ Terminé : {ok}/{len(ids)} reçus (groupe {cible}).")

async def texte(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id == ADMIN_ID:
        cible = ctx.bot_data.get("cible")
        if not cible:
            await update.message.reply_text("Choisis d'abord un groupe : /choisir T (tous), /choisir A...")
            return
        ids = membres(cible)
        await update.message.reply_text(f"Envoi à {len(ids)} personnes (groupe {cible})...")
        ctx.application.create_task(diffuser(ctx, ids, update.message.text, cible))
        return
    if db.execute("SELECT 1 FROM users WHERE chat_id=?", (u.id,)).fetchone():
        return
    code = update.message.text.strip().upper()
    if CODES_VALIDES is not None and code not in CODES_VALIDES:
        await update.message.reply_text("Code invalide, réessaie.")
        return
    db.execute("INSERT INTO users (chat_id, code, grp, nom, username) VALUES (?,?,?,?,?)",
               (u.id, code, "T", u.full_name, u.username or ""))
    db.commit()
    await update.message.reply_text("Inscription enregistrée ✅")
    await ctx.bot.send_message(ADMIN_ID, f"Nouvelle inscription : {u.full_name}\nTotal : {total()}")

@admin_only
async def choisir(update, ctx):
    g = ctx.args[0].upper()
    ctx.bot_data["cible"] = g
    await update.message.reply_text(f"Groupe cible : {g} ({len(membres(g))} personnes). Écris ton message.")

@admin_only
async def split(update, ctx):
    g = ctx.args[0].upper()
    ids = [r[0] for r in db.execute("SELECT chat_id FROM users WHERE grp=?", (g,)).fetchall()]
    if not ids:
        await update.message.reply_text("Aucun membre direct dans ce groupe (déjà divisé ?).")
        return
    random.shuffle(ids)
    m = len(ids) // 2
    a, b = ("A", "B") if g == "T" else (g + "A", g + "B")
    db.executemany("UPDATE users SET grp=? WHERE chat_id=?", [(a, i) for i in ids[:m]])
    db.executemany("UPDATE users SET grp=? WHERE chat_id=?", [(b, i) for i in ids[m:]])
    db.commit()
    await update.message.reply_text(f"{g} divisé : {a} = {m}, {b} = {len(ids) - m}")

@admin_only
async def delete(update, ctx):
    g = ctx.args[0].upper()
    db.execute("DELETE FROM users WHERE grp LIKE ?", (g + "%",))
    db.commit()
    ctx.bot_data.pop("cible", None)
    await update.message.reply_text(f"Groupe {g} supprimé. Total restant : {total()}")

@admin_only
async def reset(update, ctx):
    db.execute("UPDATE users SET grp='T'")
    db.commit()
    ctx.bot_data.pop("cible", None)
    await update.message.reply_text(f"Tout le monde est de nouveau dans un seul groupe ({total()} personnes).")

@admin_only
async def stats(update, ctx):
    rows = db.execute("SELECT grp, COUNT(*) FROM users GROUP BY grp ORDER BY grp").fetchall()
    lignes = "\n".join(f"{g} : {n}" for g, n in rows)
    await update.message.reply_text(f"Total inscrits : {total()}\n{lignes}")

@admin_only
async def liste(update, ctx):
    rows = db.execute("SELECT nom, username, code, grp, date FROM users ORDER BY date").fetchall()
    buf = io.StringIO()
    csv.writer(buf).writerows([("nom", "username", "code", "groupe", "date")] + rows)
    f = io.BytesIO(buf.getvalue().encode("utf-8"))
    f.name = "inscrits.csv"
    await update.message.reply_document(f)

app = Application.builder().token(TOKEN).build()
for nom, fn in [("start", start), ("choisir", choisir), ("split", split), ("delete", delete),
                ("reset", reset), ("stats", stats), ("liste", liste)]:
    app.add_handler(CommandHandler(nom, fn))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texte))
app.run_polling()
