"""Telegram worker. Set TELEGRAM_BOT_TOKEN to enable polling."""
import logging
import hashlib
import asyncio
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from sqlalchemy import select, func
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters  # type: ignore[reportMissingImports]
from .config import settings
from .db import SessionLocal, Base, engine
from .models import Transaction
from .finance import natural_parse, report_intent, save_transaction, summary
from .llm import LLMError, ask as ask_llm
from .receipt import receipt_fields, groq_receipt_fields

logging.basicConfig(level=logging.INFO); log=logging.getLogger("pishukkan.bot")
Base.metadata.create_all(engine)
def uid(update): return f"telegram:{update.effective_user.id}"
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Namaskaram! I’m Pishukkan, your strict Malayalam kanakku accountant. Send a transaction, ask a question in plain language, or tap /help for the command list. No OTPs, passwords or UPI PINs, please.")
async def help_cmd(update,context):
    await update.message.reply_text(
        "Pishukkan help\n\n"
        "Add transactions:\n"
        "• Spent ₹250 on dinner\n"
        "• Received ₹15000 salary\n"
        "• Send a bill photo, review it, then tap Confirm & save or Cancel\n\n"
        "Reports:\n"
        "/balance — this month's income, expenses and net\n"
        "/expense_today — today's expenses\n"
        "/expense_week — this week's expenses\n"
        "/expense_month — this month's expenses\n"
        "/expense_july — July expenses\n"
        "/expense_till_now — all expenses so far\n"
        "/income_today /income_month /income_july /income_till_now\n"
        "/savings — income and expenses summary\n"
        "/categories — spending by category\n"
        "/top_expenses — largest recent expenses\n"
        "/recent — five recent transactions\n"
        "/transactions — recent transaction list\n"
        "/search — recent transaction search\n"
        "/undo — undo the latest transaction\n\n"
        "Receipt controls:\n"
        "/receipt_save AMOUNT YYYY-MM-DD — save a scan when OCR missed details\n"
        "/receipt_cancel — discard a pending scan\n\n"
        "You can also ask questions naturally, such as “How much did I spend this month?” "
        "when GROQ_API_KEY or GEMINI_API_KEY is configured."
    )
async def add_text(update,context):
    text=update.message.text or ""
    intent=report_intent(text)
    if intent:
        await report(update,context,intent); return
    parsed=natural_parse(text)
    if not parsed:
        answer=await natural_language_answer(update, text)
        await update.message.reply_text(answer)
        return
    db=SessionLocal()
    try:
        tx=save_transaction(db,uid(update),**parsed,source="telegram"); db.commit()
        if parsed["kind"]=="income": response=f"₹{tx.amount} received and logged. Pishukkan is temporarily happy."
        elif parsed["kind"]=="lent": response=f"₹{tx.amount} lent and logged. Now remember to collect it, alle?"
        else: response=f"₹{tx.amount} {tx.category.lower()}inu poyi alle? Kanakku-il cherthittundu."
        await update.message.reply_text(response)
    except Exception:
        db.rollback(); log.exception("transaction parsing failed"); await update.message.reply_text("Kanakku save aayilla. Please try again.")
    finally: db.close()

async def natural_language_answer(update:Update, text:str) -> str:
    """Answer a question from this user's ledger without allowing LLM mutations."""
    db=SessionLocal()
    try:
        today=date.today()
        totals=summary(db,uid(update),date.min,today)
        recent=db.scalars(
            select(Transaction)
            .where(Transaction.user_id==uid(update),Transaction.deleted.is_(False))
            .order_by(Transaction.id.desc()).limit(10)
        ).all()
        ledger=(
            f"All-time income: ₹{totals['income']:.2f}\n"
            f"All-time expenses: ₹{totals['expenses']:.2f}\n"
            f"All-time net: ₹{totals['net']:.2f}\n"
            f"All-time lent: ₹{totals['lent']:.2f}\n"
            f"All-time borrowed: ₹{totals['borrowed']:.2f}\n"
            "Recent transactions:\n"
            + ("\n".join(
                f"- {tx.occurred_on} | {tx.kind} | ₹{tx.amount} | "
                f"{tx.category} | {tx.description}" for tx in recent
            ) or "- none")
        )
    finally:
        db.close()
    prompt=(
        f"Ledger context for today ({date.today().isoformat()}):\n{ledger}\n\n"
        f"User question: {text[:1000]}"
    )
    try:
        return await asyncio.to_thread(ask_llm,prompt)
    except LLMError:
        log.exception("natural-language assistant failed")
        return "I couldn’t answer that right now. Set GROQ_API_KEY or GEMINI_API_KEY, then try again."
    except Exception:
        log.exception("unexpected natural-language assistant failure")
        return "I couldn’t answer that right now. Please try again."

async def receipt_photo(update:Update,context:ContextTypes.DEFAULT_TYPE):
    photo=update.message.photo[-1]
    tg_file=await context.bot.get_file(photo.file_id)
    data=bytes(await tg_file.download_as_bytearray())
    digest=hashlib.sha256(data).hexdigest()
    folder=Path(settings.receipt_dir)/uid(update).replace(":","_")
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/f"{digest}.jpg"
    duplicate=path.exists()
    if not duplicate: path.write_bytes(data)
    db=SessionLocal()
    try:
        already_logged=db.scalar(select(Transaction.id).where(Transaction.user_id==uid(update),Transaction.receipt_path==str(path),Transaction.deleted.is_(False))) is not None
    finally: db.close()
    if already_logged:
        await update.message.reply_text("This exact bill photo is already attached to a saved transaction. I didn’t add it again.")
        return
    try:
        from PIL import Image
        import pytesseract
        text=pytesseract.image_to_string(Image.open(BytesIO(data)))
    except Exception:
        log.exception("receipt OCR unavailable")
        await update.message.reply_text("I received the bill photo, but OCR isn’t ready on this server. Install Tesseract and the Python OCR packages, then resend it. I haven’t added a transaction.")
        return
    fields=receipt_fields(text); vision_used=False
    if settings.groq_api_key:
        try:
            import asyncio
            vision=await asyncio.to_thread(groq_receipt_fields,data,"image/jpeg")
            if vision:
                vision_used=True
                # Prefer explicit vision extraction where local OCR missed or misread a field.
                for key in ("amount","occurred_on","merchant"):
                    if vision.get(key) is not None: fields[key]=vision[key]
                if vision.get("category")!="Other" or fields.get("category")=="Other": fields["category"]=vision.get("category",fields["category"])
                fields["payment_method"]=vision.get("payment_method")
                fields["gst_amount"]=vision.get("gst_amount")
                fields["items"]=vision.get("items",[])
        except Exception:
            log.exception("Groq receipt vision failed; using local OCR result")
    context.user_data["pending_receipt"]={**fields,"path":str(path),"text":text[:3000]}
    amount=f"₹{fields['amount']:.2f}" if fields["amount"] is not None else "not clear"
    bill_date=fields["occurred_on"].isoformat() if fields["occurred_on"] else "not clear"
    preview=(f"Bill scan{' · Groq Vision + OCR' if vision_used else ' · local OCR'}{' (same photo uploaded before)' if duplicate else ''}\n"
             f"Merchant: {fields['merchant'] or 'not clear'}\nAmount: {amount}\nDate: {bill_date}\nCategory guess: {fields['category']}\n\n")
    if fields.get("gst_amount"): preview+=f"GST: ₹{fields['gst_amount']}\n"
    if fields.get("payment_method"): preview+=f"Payment: {fields['payment_method']}\n"
    if fields.get("items"): preview+="Items: "+", ".join(fields["items"][:8])+"\n"
    if fields["amount"] is not None and fields["occurred_on"]:
        preview+="Check the details, then confirm below."
        keyboard=InlineKeyboardMarkup([[InlineKeyboardButton("Confirm & save",callback_data="receipt_confirm"),InlineKeyboardButton("Cancel",callback_data="receipt_cancel")]])
    else:
        preview+="I won’t guess missing details. Reply /receipt_save AMOUNT YYYY-MM-DD after checking the bill, or /receipt_cancel."
        keyboard=None
    if text.strip(): preview+="\n\nOCR text:\n"+text[:1200]
    else: preview+="\n\nI couldn’t read text in this image. Try a sharper, well-lit photo."
    await update.message.reply_text(preview,reply_markup=keyboard)

async def persist_pending_receipt(user_id,context,amount=None,occurred_on=None):
    pending=context.user_data.get("pending_receipt")
    if not pending: raise ValueError("No receipt is awaiting confirmation")
    amount=amount if amount is not None else pending["amount"]
    occurred_on=occurred_on if occurred_on is not None else pending["occurred_on"]
    if amount is None or occurred_on is None: raise ValueError("Enter the receipt amount and date")
    db=SessionLocal()
    try:
        tx=save_transaction(db,user_id,kind="expense",amount=amount,category=pending["category"],description=pending["merchant"] or "Receipt purchase",merchant=pending["merchant"],occurred_on=occurred_on,source="telegram_receipt",receipt_path=pending["path"])
        db.commit()
    finally: db.close()
    context.user_data.pop("pending_receipt",None)
    return tx

async def receipt_confirm(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    try:
        tx=await persist_pending_receipt(f"telegram:{update.effective_user.id}",context)
        await query.edit_message_text(f"Confirmed and logged: ₹{tx.amount} at {tx.merchant or tx.category} on {tx.occurred_on}. Kanakku-il cherthittundu.")
    except Exception as exc:
        await query.edit_message_text("I couldn’t save that scan. It’s still safe to enter it manually or upload the photo again.")
        log.exception("receipt confirmation failed",exc_info=exc)

async def receipt_cancel_button(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    context.user_data.pop("pending_receipt",None)
    await query.edit_message_text("Receipt scan cancelled. No transaction was saved.")

async def receipt_save(update,context):
    pending=context.user_data.get("pending_receipt")
    if not pending:
        await update.message.reply_text("Send a bill photo first, then review the scan."); return
    args=context.args
    try:
        if args:
            if len(args)!=2: raise ValueError
            amount=Decimal(args[0].replace(",","")); occurred_on=date.fromisoformat(args[1])
        else:
            amount=pending["amount"]; occurred_on=pending["occurred_on"]
            if amount is None or occurred_on is None: raise ValueError
        tx=await persist_pending_receipt(uid(update),context,amount,occurred_on)
        await update.message.reply_text(f"Confirmed and logged: ₹{tx.amount} on {tx.occurred_on}. Kanakku-il cherthittundu.")
    except Exception:
        await update.message.reply_text("Check the amount and date, then send /receipt_save 123.45 YYYY-MM-DD. Nothing was saved yet.")

async def receipt_cancel(update,context):
    context.user_data.pop("pending_receipt",None)
    await update.message.reply_text("Receipt scan cancelled. No transaction was saved.")
async def set_command_menu(app):
    await app.bot.set_my_commands([
        ("help", "Show help and all commands"),
        ("balance", "Show this month's balance"),
        ("expense_today", "Show today's expenses"),
        ("expense_week", "Show this week's expenses"),
        ("expense_month", "Show this month's expenses"),
        ("income_month", "Show this month's income"),
        ("savings", "Show savings summary"),
        ("categories", "Show spending by category"),
        ("recent", "Show recent transactions"),
        ("transactions", "Show recent transaction list"),
        ("undo", "Undo the latest transaction"),
        ("receipt_cancel", "Cancel a pending receipt"),
    ])
async def report(update,context,name=None):
    name=name or update.message.text.split()[0].lower().lstrip("/"); today=date.today()
    if name in ("expense_today",): start=end=today; field="expenses"
    elif name=="expense_week": start=today-timedelta(days=today.weekday()); end=today; field="expenses"
    elif name in ("income_today",): start=end=today; field="income"
    elif name in ("expense_ytd",): start=date(today.year,1,1); end=today; field="expenses"
    elif name in ("expense_till_now","income_till_now"): start=date.min; end=today; field="income" if name.startswith("income") else "expenses"
    elif name=="balance_all": start=date.min; end=today; field="expenses"
    elif name in ("expense_july","income_july"): start=date(today.year,7,1); end=date(today.year+1,1,1)-timedelta(days=1) if today.month>=7 else date(today.year,7,31); field="income" if name.startswith("income") else "expenses"
    elif name in ("expense_month","income_month","dashboard","balance","savings"): start=today.replace(day=1); end=today; field="income" if name=="income_month" else "expenses"
    elif name=="expense_year": start=date(today.year,1,1); end=today; field="expenses"
    else: start=date(today.year,today.month,1); end=today; field="expenses"
    db=SessionLocal()
    try:
        total=summary(db,uid(update),start,end); recent=db.scalars(select(Transaction).where(Transaction.user_id==uid(update),Transaction.deleted.is_(False)).order_by(Transaction.id.desc()).limit(5)).all()
        if name=="recent": message="\n".join(f"{r.occurred_on} · {r.kind} · ₹{r.amount} · {r.description}" for r in recent) or "No transactions logged yet."
        elif name=="categories":
            rows=db.execute(select(Transaction.category,func.sum(Transaction.amount)).where(Transaction.user_id==uid(update),Transaction.kind=="expense",Transaction.deleted.is_(False),Transaction.occurred_on.between(start,end)).group_by(Transaction.category).order_by(func.sum(Transaction.amount).desc())).all()
            message="\n".join(f"{c}: ₹{a}" for c,a in rows) or "No category spending yet."
        elif name in ("transactions","search"): message="\n".join(f"{r.id}. {r.occurred_on} {r.kind} ₹{r.amount} {r.description}" for r in recent) or "No transactions."
        elif name in ("expense_till_now", "income_till_now"):
            key="income" if name.startswith("income") else "expenses"
            message=f"{name.replace('_',' ').title()}: ₹{total[key]:.2f}"
        elif name=="balance_all": message=f"All-time totals · Income ₹{total['income']:.2f} · Expenses ₹{total['expenses']:.2f} · Net ₹{total['net']:.2f}"
        else: message=f"{name.replace('_',' ').title()} · Income ₹{total['income']:.2f} · Expenses ₹{total['expenses']:.2f} · Net ₹{total['net']:.2f}"
        await update.message.reply_text(message)
    finally: db.close()
async def undo(update,context):
    db=SessionLocal()
    try:
        tx=db.scalar(select(Transaction).where(Transaction.user_id==uid(update),Transaction.deleted.is_(False)).order_by(Transaction.id.desc()).limit(1))
        if tx: tx.deleted=True; db.commit(); msg=f"Undone: ₹{tx.amount} · {tx.description}"
        else: msg="Nothing to undo. Look at that, clean books."
        await update.message.reply_text(msg)
    finally: db.close()
def main():
    if not settings.telegram_bot_token: raise RuntimeError("Set TELEGRAM_BOT_TOKEN first")
    app=Application.builder().token(settings.telegram_bot_token).post_init(set_command_menu).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("help",help_cmd)); app.add_handler(CommandHandler("undo",undo))
    app.add_handler(CommandHandler("receipt_save",receipt_save)); app.add_handler(CommandHandler("receipt_cancel",receipt_cancel))
    app.add_handler(CallbackQueryHandler(receipt_confirm,pattern="^receipt_confirm$"))
    app.add_handler(CallbackQueryHandler(receipt_cancel_button,pattern="^receipt_cancel$"))
    cmds="dashboard balance expense_today expense_week expense_month expense_july expense_till_now expense_ytd income_today income_month income_july income_till_now savings categories budget top_expenses recent transactions search receipts subscriptions lent borrowed export settings".split()
    for cmd in cmds: app.add_handler(CommandHandler(cmd,report))
    app.add_handler(MessageHandler(filters.PHOTO,receipt_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,add_text)); app.run_polling()
if __name__=="__main__": main()
