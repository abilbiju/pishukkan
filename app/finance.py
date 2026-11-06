from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .models import Transaction, Budget

KINDS = {"income", "expense", "transfer", "refund", "lent", "borrowed", "repayment"}
EXPENSE_KINDS = ("expense", "repayment")

def money(value) -> Decimal:
    try: amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError): raise ValueError("Amount must be a valid number")
    if not amount.is_finite() or amount <= 0 or amount > Decimal("999999999999.99"):
        raise ValueError("Amount must be positive and within supported limits")
    return amount

def save_transaction(db: Session, user_id: str, *, kind: str, amount, category="Other", description="", occurred_on=None, source="manual", merchant=None, receipt_path=None):
    if kind not in KINDS: raise ValueError("Unsupported transaction type")
    tx = Transaction(user_id=user_id, kind=kind, amount=money(amount), category=category[:80] or "Other", description=description[:300] or category, occurred_on=occurred_on or date.today(), source=source, merchant=merchant, receipt_path=receipt_path)
    db.add(tx); db.flush(); return tx

def summary(db: Session, user_id: str, start: date, end: date):
    rows = db.execute(select(Transaction.kind, func.sum(Transaction.amount)).where(Transaction.user_id==user_id, Transaction.deleted.is_(False), Transaction.occurred_on.between(start,end)).group_by(Transaction.kind)).all()
    sums = {kind: Decimal(str(total or 0)) for kind,total in rows}
    income = sums.get("income", Decimal(0)) + sums.get("refund", Decimal(0))
    expenses = sum((sums.get(k, Decimal(0)) for k in EXPENSE_KINDS), Decimal(0))
    return {"income": income, "expenses": expenses, "net": income-expenses, "lent": sums.get("lent",Decimal(0)), "borrowed": sums.get("borrowed",Decimal(0)), "savings_rate": (income-expenses)/income*100 if income else Decimal(0)}

def natural_parse(text: str):
    """Conservative fallback parser; no transaction is saved without an explicit amount."""
    import re
    match = re.search(r"(?:₹|rs\.?\s*)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", text, re.I)
    if not match: return None
    amt = money(match.group(1).replace(",", "")); low=text.lower()
    income_words=("received", "salary", "income", "got paid", "refund", "returned", "kitti")
    # In Manglish, “Milan enikk 100 thannu” means Milan gave me 100.
    # Treat “njan ... koduthu” as money lent rather than ordinary spending.
    gave_to_someone=any(w in low for w in ("i gave", "koduthu", "koduth")) or ("njan " in low and "thannu" in low)
    incoming_manglish=any(w in low for w in ("enikk", "enikku")) and any(w in low for w in ("thannu", "thann", "kitti"))
    kind="lent" if gave_to_someone else ("income" if any(w in low for w in income_words) or incoming_manglish else "expense")
    category="Other"
    for keywords, cat in [(("food","dinner","lunch","restaurant","grocer"),"Food"), (("petrol","fuel","diesel"),"Transport"), (("rent",),"Housing"), (("bill","electricity"),"Utilities"), (("salary",),"Salary")]:
        if any(w in low for w in keywords): category=cat; break
    date_value=date.today()-timedelta(days=1) if "yesterday" in low else date.today()
    return {"kind":kind,"amount":amt,"category":category,"description":text[:300],"occurred_on":date_value}

def report_intent(text: str):
    """Map common plain-language report prompts to the bot's report keys."""
    low=" ".join(text.lower().strip().lstrip("/").split())
    if low in {"total till now", "total so far", "balance till now", "balance so far"}: return "balance_all"
    if low in {"expense till now", "expenses till now", "spent till now", "expense so far", "expenses so far"}: return "expense_till_now"
    if low in {"income till now", "income so far"}: return "income_till_now"
    return None
