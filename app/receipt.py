"""Conservative receipt text parsing helpers."""
import re
import base64
import json
from datetime import date, datetime
from decimal import Decimal
from .config import settings

def receipt_fields(ocr_text: str):
    """Only accept totals next to an explicit label and dates printed in the text."""
    amount_candidates=[]
    number_re=re.compile(r"(?:₹|rs\.?\s*)?([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+\.[0-9]{2})",re.I)
    for line in ocr_text.splitlines():
        if re.search(r"\b(grand\s*total|net\s*payable|amount\s*paid|total\s*amount|total)\b",line,re.I):
            nums=number_re.findall(line)
            if len(nums)==1:
                try: amount_candidates.append(Decimal(nums[0].replace(",","")).quantize(Decimal(".01")))
                except Exception: pass
    amount=amount_candidates[0] if amount_candidates and len(set(amount_candidates))==1 else None

    found_date=None
    date_patterns=[r"\b(\d{4}[-/ ]\d{1,2}[-/ ]\d{1,2})\b",r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b"]
    for pattern in date_patterns:
        match=re.search(pattern,ocr_text)
        if match:
            value=match.group(1).replace(" ","/")
            formats=("%Y/%m/%d","%d/%m/%Y","%m/%d/%Y") if value[:4].isdigit() else ("%d/%m/%Y","%m/%d/%Y")
            for fmt in formats:
                try: found_date=datetime.strptime(value,fmt).date(); break
                except ValueError: continue
            if found_date: break
    if not found_date:
        month_names="January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
        textual_patterns=[rf"\b(\d{{1,2}}\s+(?:{month_names})\.?[,]?\s+\d{{4}})\b",rf"\b((?:{month_names})\s+\d{{1,2}}[,]?\s+\d{{4}})\b"]
        for pattern in textual_patterns:
            match=re.search(pattern,ocr_text,re.I)
            if match:
                value=re.sub(r"\s+"," ",match.group(1)).replace(",","").replace(".","")
                for fmt in ("%d %B %Y","%d %b %Y","%B %d %Y","%b %d %Y"):
                    try: found_date=datetime.strptime(value,fmt).date(); break
                    except ValueError: continue
                if found_date: break

    lines=[line.strip() for line in ocr_text.splitlines() if line.strip()]
    generic={"restaurant","receipt","invoice","tax invoice","quick bill","bill","cash bill","food bill"}
    merchant=None
    for line in lines[:12]:
        clean=re.sub(r"[^A-Za-z&' -]"," ",line)
        words=re.findall(r"[A-Za-z&']+",clean)
        if (words and any(len(w)>=3 for w in words) and len(clean.strip())>=4
            and not any(ch.isdigit() for ch in line)
            and " ".join(words).lower() not in generic):
            merchant=" ".join(words)[:100]; break
    low=ocr_text.lower()
    category="Food" if any(w in low for w in ("restaurant","cafe","hotel","dining")) else "Fuel" if any(w in low for w in ("petrol","fuel","diesel")) else "Groceries" if any(w in low for w in ("supermarket","grocery")) else "Other"
    return {"amount":amount,"occurred_on":found_date,"merchant":merchant,"category":category}

def groq_receipt_fields(image_bytes: bytes, mime_type: str="image/jpeg"):
    """Read receipt fields from Groq Vision. Returns None when not configured or invalid."""
    if not settings.groq_api_key:
        return None
    from openai import OpenAI
    client=OpenAI(api_key=settings.groq_api_key,base_url="https://api.groq.com/openai/v1",timeout=25.0,max_retries=1)
    image_data=base64.b64encode(image_bytes).decode("ascii")
    prompt=("Read this receipt image. Return only a JSON object with keys: merchant, total_amount, "
            "currency, date, category, payment_method, gst_amount, items. Copy values only when visibly "
            "printed. Do not calculate or infer totals, dates, tax, or merchant. Use null when a field is "
            "unclear or absent. total_amount must be the printed final payable amount, not subtotal. "
            "date must be ISO YYYY-MM-DD only when the printed date is unambiguous. category must be one "
            "of Food, Groceries, Fuel, Transport, Housing, Utilities, Shopping, Other. items must be an "
            "array of short printed item names; return [] if unreadable.")
    result=client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:{mime_type};base64,{image_data}"}}]}],
        response_format={"type":"json_object"},temperature=0.2,max_completion_tokens=1200)
    raw=result.choices[0].message.content
    if not raw: return None
    data=json.loads(raw)
    fields={"amount":None,"occurred_on":None,"merchant":None,"category":"Other","payment_method":None,"gst_amount":None,"items":[]}
    value=data.get("total_amount")
    if value is not None:
        try:
            amount=Decimal(str(value)).quantize(Decimal(".01"))
            if amount>0 and amount<Decimal("1000000000000"): fields["amount"]=amount
        except Exception: pass
    value=data.get("date")
    if isinstance(value,str):
        try: fields["occurred_on"]=date.fromisoformat(value)
        except ValueError: pass
    merchant=data.get("merchant")
    if isinstance(merchant,str) and merchant.strip(): fields["merchant"]=merchant.strip()[:100]
    category=data.get("category")
    if category in {"Food","Groceries","Fuel","Transport","Housing","Utilities","Shopping","Other"}: fields["category"]=category
    for key in ("payment_method","gst_amount"):
        value=data.get(key)
        if isinstance(value,(str,int,float)): fields[key]=str(value)[:100]
    items=data.get("items")
    if isinstance(items,list): fields["items"]=[str(x)[:100] for x in items[:40] if x is not None]
    return fields
