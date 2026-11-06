from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import csv, io, secrets, logging
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, get_db
from .models import Transaction, Budget, AuditLog
from .finance import save_transaction, summary, natural_parse, KINDS

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("pishukkan")
Base.metadata.create_all(bind=engine)
app=FastAPI(title="Pishukkan API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.allowed_origins.split(",")], allow_methods=["*"], allow_headers=["*"])

def identity(authorization: str|None=Header(default=None), x_telegram_user: str|None=Header(default=None)):
    # Shared-token mode for a personal deployment; Telegram identity is accepted only by internal bot methods.
    expected=settings.dashboard_api_token
    if not authorization or not secrets.compare_digest(authorization, expected): raise HTTPException(401,"Authentication required")
    return "owner"

class TxIn(BaseModel):
    kind: str
    amount: Decimal
    category: str="Other"
    description: str=""
    occurred_on: date|None=None
    merchant: str|None=None

class BudgetIn(BaseModel): category: str="Overall"; month: str=Field(pattern=r"^\d{4}-\d{2}$"); amount: Decimal

@app.get("/api/health")
def health(): return {"ok":True,"service":"pishukkan"}

@app.get("/api/transactions")
def transactions(start: date|None=None,end: date|None=None,kind: str|None=None,q: str|None=None,limit:int=Query(100,ge=1,le=500),db:Session=Depends(get_db),user:str=Depends(identity)):
    stmt=select(Transaction).where(Transaction.user_id==user,Transaction.deleted.is_(False))
    if start: stmt=stmt.where(Transaction.occurred_on>=start)
    if end: stmt=stmt.where(Transaction.occurred_on<=end)
    if kind in KINDS: stmt=stmt.where(Transaction.kind==kind)
    if q: stmt=stmt.where(Transaction.description.ilike(f"%{q[:100]}%"))
    rows=db.scalars(stmt.order_by(Transaction.occurred_on.desc(),Transaction.id.desc()).limit(limit)).all()
    return [{"id":r.id,"kind":r.kind,"amount":str(r.amount),"category":r.category,"description":r.description,"merchant":r.merchant,"date":r.occurred_on.isoformat(),"receipt":bool(r.receipt_path)} for r in rows]

@app.post("/api/transactions")
def create_tx(body:TxIn,db:Session=Depends(get_db),user:str=Depends(identity)):
    try: tx=save_transaction(db,user,kind=body.kind,amount=body.amount,category=body.category,description=body.description,occurred_on=body.occurred_on,merchant=body.merchant)
    except ValueError as e: raise HTTPException(422,str(e))
    db.add(AuditLog(user_id=user,action="create",transaction_id=tx.id)); db.commit(); return {"id":tx.id,"message":"Kanakku-il cherthittundu."}

@app.delete("/api/transactions/{tx_id}")
def delete_tx(tx_id:int,db:Session=Depends(get_db),user:str=Depends(identity)):
    tx=db.scalar(select(Transaction).where(Transaction.id==tx_id,Transaction.user_id==user,Transaction.deleted.is_(False)))
    if not tx: raise HTTPException(404,"Transaction not found")
    tx.deleted=True; db.add(AuditLog(user_id=user,action="delete",transaction_id=tx.id)); db.commit(); return {"ok":True}

@app.get("/api/dashboard")
def dashboard(month:str|None=None,year:int|None=None,db:Session=Depends(get_db),user:str=Depends(identity)):
    today=date.today();
    try: y,m=map(int,month.split("-")) if month else (year or today.year,today.month)
    except Exception: raise HTTPException(422,"Month must be YYYY-MM")
    if not 1<=m<=12: raise HTTPException(422,"Invalid month")
    start=date(y,m,1); end=date(y+1,1,1)-timedelta(days=1) if m==12 else date(y,m+1,1)-timedelta(days=1)
    totals=summary(db,user,start,end)
    cats=db.execute(select(Transaction.category,func.sum(Transaction.amount)).where(Transaction.user_id==user,Transaction.deleted.is_(False),Transaction.kind.in_(["expense","repayment"]),Transaction.occurred_on.between(start,end)).group_by(Transaction.category)).all()
    budgets=db.scalars(select(Budget).where(Budget.user_id==user,Budget.month==start.strftime("%Y-%m"))).all()
    recent=db.scalars(select(Transaction).where(Transaction.user_id==user,Transaction.deleted.is_(False)).order_by(Transaction.occurred_on.desc(),Transaction.id.desc()).limit(8)).all()
    daily=db.execute(select(Transaction.occurred_on,func.sum(Transaction.amount)).where(Transaction.user_id==user,Transaction.deleted.is_(False),Transaction.kind.in_(["expense","repayment"]),Transaction.occurred_on.between(start,end)).group_by(Transaction.occurred_on)).all()
    return {"month":start.strftime("%Y-%m"),"totals":{k:str(v.quantize(Decimal("0.01"))) for k,v in totals.items()},"categories":[{"name":k,"amount":str(v)} for k,v in cats],"daily":[{"date":d.isoformat(),"amount":str(v)} for d,v in daily],"budgets":[{"category":b.category,"amount":str(b.amount)} for b in budgets],"recent":[{"id":r.id,"kind":r.kind,"amount":str(r.amount),"category":r.category,"description":r.description,"date":r.occurred_on.isoformat()} for r in recent]}

@app.put("/api/budgets")
def set_budget(body:BudgetIn,db:Session=Depends(get_db),user:str=Depends(identity)):
    try: amount=Decimal(body.amount).quantize(Decimal(".01"))
    except Exception: raise HTTPException(422,"Invalid amount")
    if amount<=0: raise HTTPException(422,"Budget must be positive")
    b=db.scalar(select(Budget).where(Budget.user_id==user,Budget.category==body.category,Budget.month==body.month))
    if b: b.amount=amount
    else: b=Budget(user_id=user,category=body.category,month=body.month,amount=amount); db.add(b)
    db.commit(); return {"ok":True}

@app.get("/api/export.csv")
def export_csv(start:date|None=None,end:date|None=None,db:Session=Depends(get_db),user:str=Depends(identity)):
    stmt=select(Transaction).where(Transaction.user_id==user,Transaction.deleted.is_(False))
    if start: stmt=stmt.where(Transaction.occurred_on>=start)
    if end: stmt=stmt.where(Transaction.occurred_on<=end)
    out=io.StringIO(); w=csv.writer(out); w.writerow(["date","type","amount","currency","category","description","merchant"])
    for r in db.scalars(stmt.order_by(Transaction.occurred_on)): w.writerow([r.occurred_on,r.kind,r.amount,r.currency,r.category,r.description,r.merchant or ""])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=pishukkan-transactions.csv"})

@app.post("/api/assistant")
def assistant(body:dict,db:Session=Depends(get_db),user:str=Depends(identity)):
    # All returned numbers come from SQL aggregates; no LLM is allowed to calculate balances.
    q=str(body.get("question","")); today=date.today(); start=today.replace(day=1); totals=summary(db,user,start,today)
    biggest=db.scalar(select(Transaction).where(Transaction.user_id==user,Transaction.deleted.is_(False),Transaction.kind=="expense",Transaction.occurred_on.between(start,today)).order_by(Transaction.amount.desc()).limit(1))
    return {"answer":f"This month: ₹{totals['expenses']:.2f} spent, ₹{totals['income']:.2f} received. Biggest expense: {biggest.description} ₹{biggest.amount:.2f}." if biggest else f"This month: ₹{totals['expenses']:.2f} spent and ₹{totals['income']:.2f} received. No expenses logged yet; excellent restraint or suspicious bookkeeping."}

@app.post("/api/receipts")
async def receipt(file:UploadFile=File(...),db:Session=Depends(get_db),user:str=Depends(identity)):
    if file.content_type not in {"image/jpeg","image/png","image/webp","application/pdf"}: raise HTTPException(415,"Upload a JPG, PNG, WebP or PDF")
    data=await file.read(8_000_001)
    if len(data)>8_000_000: raise HTTPException(413,"Receipt must be smaller than 8 MB")
    directory=Path(settings.receipt_dir)/user; directory.mkdir(parents=True,exist_ok=True)
    name=f"{secrets.token_hex(16)}{Path(file.filename or 'receipt').suffix.lower()}"; path=directory/name; path.write_bytes(data)
    extracted=""
    try:
        if file.content_type=="application/pdf":
            import fitz
            extracted="\n".join(p.get_text() for p in fitz.open(stream=data,filetype="pdf"))
        else:
            import pytesseract
            from PIL import Image
            extracted=pytesseract.image_to_string(Image.open(io.BytesIO(data)))
    except Exception: log.info("OCR unavailable or failed")
    # Preview extracted text only. Do not guess amount/date; user must enter and confirm values.
    return {"receipt_id":name,"text":extracted[:5000],"duplicate_candidate":False,"requires_confirmation":True,"amount":None,"date":None,"message":"Receipt stored privately. Check the details and enter the amount/date before saving."}

@app.get("/")
def root(): return FileResponse("web/index.html")

