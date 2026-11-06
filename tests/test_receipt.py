from datetime import date
from decimal import Decimal
from app.receipt import receipt_fields

def test_extracts_receipt_amount_printed_date_and_merchant():
    text="""aw a a
Flame Kitchen
Restaurant
24 May 2025 02:01 PM
Total Qty: Total Amount
4 290.00
Grand Total : Rs 290.00"""
    result=receipt_fields(text)
    assert result["merchant"]=="Flame Kitchen"
    assert result["amount"]==Decimal("290.00")
    assert result["occurred_on"]==date(2025,5,24)
    assert result["category"]=="Food"

def test_does_not_invent_receipt_fields():
    result=receipt_fields("Convenience Shop\nSubtotal 210.00")
    assert result["amount"] is None
    assert result["occurred_on"] is None
