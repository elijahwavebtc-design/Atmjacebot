"""Bot Telegram d'inscription et de diffusion.

Variables d'environnement :
  BOT_TOKEN  : token donné par @BotFather
  ADMIN_IDS  : ton identifiant Telegram (plusieurs possibles, séparés par des virgules)
  DB_PATH    : chemin de la base (ex. /data/bot.db sur Railway avec un volume)
"""
import asyncio
import functools
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("bot")
# httpx écrit l'URL de Telegram (donc le token) dans les logs : on le fait taire
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()
}

THANKS = (
    "✅ Merci pour votre inscription ! Vous êtes bien inscrit.\n"
    "Les signaux vous seront communiqués ici dès que possible."
)
ASK_CODE = (
    "Avant de finaliser votre inscription : disposez-vous d'un code d'affiliation ?\n\n"
    "🎁 Le code d'affiliation vous donne droit à un signal de trading supplémentaire "
    "lors de la prochaine session."
)
ENTER_CODE = "Parfait. Veuillez saisir votre code d'affiliation :"
CODE_OK = (
    "🎁 Votre code d'affiliation a bien été enregistré. "
    "Vous bénéficierez d'un signal de trading supplémentaire lors de la prochaine session."
)
CODE_BAD = (
    "Ce code d'affiliation n'est pas valide. Veuillez le vérifier et le saisir à nouveau, "
    "ou poursuivre votre inscription sans code."
)
LABELS = {"A": "le groupe A", "B": "le groupe B", "TOUS": "tous les inscrits", "AFFILIES": "les affiliés"}
ALIASES = {"AFFILIÉS": "AFFILIES", "AFFILIE": "AFFILIES", "AFFILIÉ": "AFFILIES", "TOUT": "TOUS"}

BG_TASKS = set()  # envois en cours


def busy():
    return any(not t.done() for t in BG_TASKS)


def admin_only(fn):
    """Les non-admins sont ignorés en silence : les inscrits ne voient aucune commande."""

    @functools.wraps(fn)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            return
        return await fn(update, ctx)

    return wrapper


def confirm_kb(action):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Confirmer", callback_data=f"ok:{action}"),
          InlineKeyboardButton("❌ Annuler", callback_data="cancel")]]
    )


# ====================== côté inscrits ======================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("await_code", None)
    if ctx.args:  # lien d'affiliation : t.me/TonBot?start=CODE
        code = db.norm(ctx.args[0])
        if db.code_exists(code):
            ctx.user_data["pending_code"] = code
    user = update.effective_user
    if db.is_registered(user.id):
        rows = []
        if not db.has_code(user.id):
            rows.append([InlineKeyboardButton("🎁 J'ai un code d'affiliation", callback_data="have_code")])
        await update.message.reply_text(
            "Vous êtes déjà inscrit ✅\nLes signaux vous seront communiqués ici.",
            reply_markup=InlineKeyboardMarkup(rows) if rows else None,
        )
    else:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ S'inscrire", callback_data="register")]])
        await update.message.reply_text("Bienvenue ! Appuyez sur le bouton pour vous inscrire.", reply_markup=kb)
    if user.id in ADMIN_IDS:
        await update.message.reply_text("Tu es admin : tape /aide pour voir les commandes.")


def finish_signup(user, code):
    """Enregistre l'inscrit (avec son code s'il y en a un) et renvoie le message final."""
    db.register(user.id, user.username, user.first_name)
    if code:
        db.apply_code(user.id, code)
    return THANKS + ("\n\n" + CODE_OK if code and db.has_code(user.id) else "")


async def edit_or_ignore(q, text, markup=None):
    try:
        await q.edit_message_text(text, reply_markup=markup)
    except BadRequest:
        pass


NO_CODE_KB = InlineKeyboardMarkup([[InlineKeyboardButton("Poursuivre sans code", callback_data="register_no")]])


async def on_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Appui sur « S'inscrire » : on demande d'abord s'il y a un code d'affiliation."""
    q = update.callback_query
    await q.answer()
    user = q.from_user
    if db.is_registered(user.id):
        await edit_or_ignore(q, "Vous êtes déjà inscrit ✅\nLes signaux vous seront communiqués ici.")
        return
    pending = ctx.user_data.pop("pending_code", None)  # code déjà fourni par un lien d'affiliation
    if pending:
        await edit_or_ignore(q, finish_signup(user, pending))
        return
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Oui, j'ai un code", callback_data="register_yes"),
          InlineKeyboardButton("❌ Non", callback_data="register_no")]]
    )
    await edit_or_ignore(q, ASK_CODE, kb)


async def on_register_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if db.is_registered(q.from_user.id):
        await edit_or_ignore(q, "Vous êtes déjà inscrit ✅\nLes signaux vous seront communiqués ici.")
        return
    ctx.user_data["await_code"] = "signup"
    await edit_or_ignore(q, ENTER_CODE, NO_CODE_KB)


async def on_register_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("await_code", None)
    user = q.from_user
    if db.is_registered(user.id):
        await edit_or_ignore(q, "Vous êtes déjà inscrit ✅\nLes signaux vous seront communiqués ici.")
        return
    await edit_or_ignore(q, finish_signup(user, None))


async def on_have_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Pour un inscrit qui veut ajouter son code plus tard."""
    q = update.callback_query
    await q.answer()
    if not db.is_registered(q.from_user.id):
        await q.message.reply_text("Appuyez d'abord sur /start pour vous inscrire.")
        return
    ctx.user_data["await_code"] = "later"
    await q.message.reply_text(ENTER_CODE)


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message

    # --- l'admin est en train de préparer un envoi ---
    if user.id in ADMIN_IDS:
        pending = ctx.user_data.get("pending_send")
        if pending and "message_id" not in pending:
            pending["from_chat_id"] = msg.chat_id
            pending["message_id"] = msg.message_id
            n = len(db.recipients(pending["target"]))
            await msg.reply_text(
                f"Envoyer ce message à {n} personne(s) ({LABELS[pending['target']]}) ?",
                reply_markup=confirm_kb("envoyer"),
            )
            return

    # --- un inscrit saisit son code d'affiliation ---
    mode = ctx.user_data.get("await_code")
    if mode and msg.text:
        code = db.norm(msg.text)
        if not db.code_exists(code):
            await msg.reply_text(CODE_BAD, reply_markup=NO_CODE_KB if mode == "signup" else None)
            return
        ctx.user_data.pop("await_code", None)
        if mode == "signup":
            await msg.reply_text(finish_signup(user, code))
        else:
            status = db.apply_code(user.id, code)
            if status == "ok":
                await msg.reply_text(CODE_OK)
            elif status == "already":
                await msg.reply_text("Un code d'affiliation est déjà enregistré pour vous ✅")
            else:
                await msg.reply_text("Appuyez d'abord sur /start pour vous inscrire.")
        return

    if db.is_registered(user.id):
        await msg.reply_text("Vous êtes bien inscrit ✅ Les signaux vous seront communiqués ici.")
    else:
        await msg.reply_text("Appuyez sur /start pour vous inscrire.")


# ====================== côté admin ======================
@admin_only
async def aide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commandes admin (invisibles pour les inscrits) :\n\n"
        "/stats : nombre d'inscrits et de membres par groupe\n"
        "/diviser : répartit au hasard tous les inscrits en groupe A et groupe B (moitié/moitié)\n"
        "/envoyer A : envoie un message au groupe A (idem B, TOUS, AFFILIES)\n"
        "/supprimer A : supprime tous les membres du groupe A (idem B)\n"
        "/annuler : annule un envoi en préparation\n\n"
        "Codes d'affiliation :\n"
        "/code_ajouter CODE\n"
        "/code_supprimer CODE\n"
        "/codes : liste des codes et nombre d'utilisateurs\n\n"
        "Pour /envoyer : tape la commande, puis envoie ton message (texte, ou image avec légende). "
        "Le bot demande confirmation, puis l'envoie à chaque personne une par une."
    )


@admin_only
async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = db.stats()
    await update.message.reply_text(
        "📊 Statistiques\n"
        f"Inscrits : {s['total']}\n"
        f"Groupe A : {s['a']}\n"
        f"Groupe B : {s['b']}\n"
        f"Sans groupe : {s['sans_groupe']}\n"
        f"Avec code d'affiliation : {s['affilies']}\n"
        f"Ayant bloqué le bot : {s['bloques']}"
    )


@admin_only
async def diviser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if busy():
        await update.message.reply_text("Un envoi est en cours, attends qu'il soit terminé.")
        return
    n = len(db.recipients("TOUS"))
    if n < 2:
        await update.message.reply_text("Il faut au moins 2 inscrits pour diviser.")
        return
    await update.message.reply_text(
        f"Diviser au hasard les {n} inscrits en deux groupes (A et B) ? "
        "Les groupes actuels seront remplacés.",
        reply_markup=confirm_kb("diviser"),
    )


@admin_only
async def envoyer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if busy():
        await update.message.reply_text("Un envoi est déjà en cours, attends qu'il soit terminé.")
        return
    target = db.norm(ctx.args[0]) if ctx.args else ""
    target = ALIASES.get(target, target)
    if target not in LABELS:
        await update.message.reply_text("Utilisation : /envoyer A, /envoyer B, /envoyer TOUS ou /envoyer AFFILIES")
        return
    n = len(db.recipients(target))
    if n == 0:
        await update.message.reply_text(f"Personne dans {LABELS[target]} pour l'instant.")
        return
    ctx.user_data["pending_send"] = {"target": target}
    await update.message.reply_text(
        f"OK, {n} personne(s) dans {LABELS[target]}.\n"
        "Envoie maintenant ton message (texte, ou image avec légende). /annuler pour abandonner."
    )


@admin_only
async def supprimer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if busy():
        await update.message.reply_text("Un envoi est en cours, attends qu'il soit terminé.")
        return
    g = db.norm(ctx.args[0]) if ctx.args else ""
    if g not in ("A", "B"):
        await update.message.reply_text("Utilisation : /supprimer A ou /supprimer B")
        return
    n = len(db.recipients(g))
    if n == 0:
        await update.message.reply_text(f"Le groupe {g} est vide.")
        return
    await update.message.reply_text(
        f"Supprimer définitivement les {n} membres du groupe {g} ? (impossible à annuler)",
        reply_markup=confirm_kb(f"supprimer:{g}"),
    )


@admin_only
async def annuler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("pending_send", None)
    await update.message.reply_text("Envoi annulé.")


@admin_only
async def code_ajouter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Utilisation : /code_ajouter MONCODE")
        return
    db.add_code(ctx.args[0])
    await update.message.reply_text(f"Code {db.norm(ctx.args[0])} ajouté ✅")


@admin_only
async def code_supprimer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Utilisation : /code_supprimer MONCODE")
        return
    ok = db.remove_code(ctx.args[0])
    await update.message.reply_text("Code supprimé ✅" if ok else "Ce code n'existe pas.")


@admin_only
async def codes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db.list_codes()
    if not rows:
        await update.message.reply_text("Aucun code. Ajoutes-en avec /code_ajouter MONCODE")
        return
    await update.message.reply_text("Codes d'affiliation :\n" + "\n".join(f"{c} : {n} inscrit(s)" for c, n in rows))


@admin_only
async def on_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action = q.data[3:]

    if action == "diviser":
        if busy():
            await q.edit_message_text("Un envoi est en cours, réessaie plus tard.")
            return
        a, b = db.split()
        await q.edit_message_text(f"✅ Division faite : groupe A = {a}, groupe B = {b}.")

    elif action.startswith("supprimer:"):
        if busy():
            await q.edit_message_text("Un envoi est en cours, réessaie plus tard.")
            return
        g = action.split(":", 1)[1]
        n = db.delete_group(g)
        await q.edit_message_text(f"✅ Groupe {g} supprimé ({n} membres).")

    elif action == "envoyer":
        pending = ctx.user_data.pop("pending_send", None)
        if not pending or "message_id" not in pending:
            await q.edit_message_text("Aucun message en attente. Recommence avec /envoyer.")
            return
        if busy():
            await q.edit_message_text("Un envoi est déjà en cours.")
            return
        ids = db.recipients(pending["target"])
        await q.edit_message_text(f"🚀 Envoi lancé à {len(ids)} personne(s). Je te préviens à la fin.")
        task = asyncio.create_task(
            broadcast(ctx.bot, q.message.chat_id, pending["from_chat_id"], pending["message_id"], ids)
        )
        BG_TASKS.add(task)
        task.add_done_callback(BG_TASKS.discard)


@admin_only
async def on_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("pending_send", None)
    await q.edit_message_text("Annulé.")


# ====================== envoi un par un ======================
async def safe_send(bot, chat_id, text):
    try:
        await bot.send_message(chat_id, text)
    except TelegramError as e:
        log.warning("Message à l'admin impossible : %s", e)


async def broadcast(bot, admin_chat_id, from_chat_id, message_id, user_ids):
    sent = blocked = failed = 0
    total = len(user_ids)
    for i, uid in enumerate(user_ids, 1):
        for _ in range(3):
            try:
                # copy_message garde le texte, l'image, la légende et la mise en forme
                await bot.copy_message(chat_id=uid, from_chat_id=from_chat_id, message_id=message_id)
                sent += 1
                break
            except RetryAfter as e:
                wait = e.retry_after
                wait = wait.total_seconds() if hasattr(wait, "total_seconds") else wait
                await asyncio.sleep(wait + 1)
            except Forbidden:
                db.mark_blocked(uid)
                blocked += 1
                break
            except TelegramError as e:
                log.warning("Échec pour %s : %s", uid, e)
                failed += 1
                break
        else:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 messages/s, sous la limite de Telegram (30/s)
        if i % 1000 == 0 and i != total:
            await safe_send(bot, admin_chat_id, f"Progression : {i}/{total}")
    await safe_send(
        bot,
        admin_chat_id,
        f"✅ Envoi terminé : {sent} envoyés, {blocked} ont bloqué le bot, {failed} échecs (sur {total}).",
    )


# ====================== démarrage ======================
def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN manquant.")
    if not ADMIN_IDS:
        raise SystemExit("ADMIN_IDS manquant (ton identifiant Telegram, obtenu via @userinfobot).")
    db.init()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("aide", aide))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("diviser", diviser))
    app.add_handler(CommandHandler("envoyer", envoyer))
    app.add_handler(CommandHandler("supprimer", supprimer))
    app.add_handler(CommandHandler("annuler", annuler))
    app.add_handler(CommandHandler("code_ajouter", code_ajouter))
    app.add_handler(CommandHandler("code_supprimer", code_supprimer))
    app.add_handler(CommandHandler("codes", codes))

    app.add_handler(CallbackQueryHandler(on_register, pattern=r"^register$"))
    app.add_handler(CallbackQueryHandler(on_register_yes, pattern=r"^register_yes$"))
    app.add_handler(CallbackQueryHandler(on_register_no, pattern=r"^register_no$"))
    app.add_handler(CallbackQueryHandler(on_have_code, pattern=r"^have_code$"))
    app.add_handler(CallbackQueryHandler(on_confirm, pattern=r"^ok:"))
    app.add_handler(CallbackQueryHandler(on_cancel, pattern=r"^cancel$"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_message))

    log.info("Bot démarré (%d admin).", len(ADMIN_IDS))
    app.run_polling()


if __name__ == "__main__":
    main()
