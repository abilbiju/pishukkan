from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.finance import money, save_transaction, summary, natural_parse, report_intent

@pytest.fixture
def db():
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

def test_money_precise_and_validation():
    assert money("0.10") + money("0.20") == Decimal("0.30")
    with pytest.raises(ValueError): money("-2")

def test_summary_excludes_transfers_and_separates_lending(db):
    save_transaction(db,"u",kind="income",amount="1000",occurred_on=date(2026,1,3))
    save_transaction(db,"u",kind="expense",amount="100.20",occurred_on=date(2026,1,3))
    save_transaction(db,"u",kind="transfer",amount="900",occurred_on=date(2026,1,3))
    save_transaction(db,"u",kind="lent",amount="50",occurred_on=date(2026,1,3))
    db.commit(); result=summary(db,"u",date(2026,1,1),date(2026,1,31))
    assert result["income"]==Decimal("1000.00")
    assert result["expenses"]==Decimal("100.20")
    assert result["net"]==Decimal("899.80")
    assert result["lent"]==Decimal("50.00")

def test_natural_parser_requires_amount_and_handles_yesterday():
    assert natural_parse("spent on dinner") is None
    parsed=natural_parse("Spent ₹350 on groceries yesterday")
    assert parsed["amount"]==Decimal("350.00")
    assert parsed["kind"]=="expense" and parsed["category"]=="Food"

def test_manglish_received_money_is_not_an_expense():
    parsed=natural_parse("Milan enikk 100 thannu")
    assert parsed["kind"]=="income"
    assert parsed["amount"]==Decimal("100.00")

def test_plain_language_report_prompts():
    assert report_intent("total till now")=="balance_all"
    assert report_intent("expense till now")=="expense_till_now"
    assert report_intent("Milan enikk 100 thannu") is None

def test_users_are_isolated(db):
    save_transaction(db,"alice",kind="income",amount=100)
    save_transaction(db,"bob",kind="income",amount=800)
    assert summary(db,"alice",date.today().replace(day=1),date.today())["income"]==Decimal("100.00")
