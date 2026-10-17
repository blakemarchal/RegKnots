"""2026-10-17 — Admin > Sales: the credit rule and the data checks."""
from datetime import datetime, timezone

from app.routers import admin_sales
from app.sales_credit import CREDIT_CODE_SQL, credit_code_sql


def test_credit_rule_prefers_the_admin_then_the_link():
    sql = credit_code_sql("o")
    assert sql.startswith("NULLIF(COALESCE(o.credited_sales_code,")
    assert "lower(o.signup_attribution->>'src') LIKE 'pilot-%'" in sql
    assert "substr(lower(o.signup_attribution->>'src'), 7)" in sql   # after 'pilot-'
    assert sql.endswith(", '')")                                      # '' = credited to no one
    assert CREDIT_CODE_SQL == credit_code_sql("u")


def test_month_keys():
    assert admin_sales.month_keys(datetime(2026, 10, 17, tzinfo=timezone.utc)) == ("2026-10", "2026-09")
    assert admin_sales.month_keys(datetime(2027, 1, 3, tzinfo=timezone.utc)) == ("2027-01", "2026-12")


def _fleet(**kw):
    base = dict(id="w", name="Bay Towing", status="trialing", boats=3, paying=False, invoiced=False,
                internal_only=False, trial_ends_at=None, trial_custom=False)
    return admin_sales.SalesFleet(**{**base, **kw})


def _account(fleets, credit="link", code="jordan"):
    return admin_sales.SalesAccount(
        user_id="u1", name="Pat", email="pat@bay.example", created_at=datetime.now(timezone.utc), code=code,
        credit=credit, signup_src="pilot-jordan", stage="trial", questions=2, paying_plan=False, internal=False,
        fleets=fleets, paid_total=0)


def _person(**kw):
    base = dict(name="Jordan Hall", email="j@example.com", code="jordan", access=True, pilot_active=True,
                paying_accounts=0)
    return {**base, **kw}


def test_no_issues_when_everything_lines_up():
    acct = _account([_fleet(trial_custom=True), _fleet(status="active", paying=True, invoiced=True)])
    assert admin_sales.build_issues([_person()], [acct], [], [], [], {"jordan": 90}) == []


def test_salesperson_checks():
    out = admin_sales.build_issues(
        [_person(code=None), _person(name="Sam", code="sam", pilot_active=None),
         _person(name="Lee", code="lee", pilot_active=False),
         _person(name="Ex", code="ex", access=False, paying_accounts=2)], [], [], [], [], {})
    levels = [(i.level, i.code) for i in out]
    assert levels == [("error", None), ("error", "sam"), ("warn", "lee"), ("info", "ex")]
    assert "standard 30-day trial" in out[1].text and "paused" in out[2].text and "still owed" in out[3].text


def test_fleet_checks():
    acct = _account([_fleet(), _fleet(status="active", paying=True, invoiced=False)])
    out = admin_sales.build_issues([_person()], [acct], [], [], [], {"jordan": 90})
    assert [i.level for i in out] == ["warn", "warn"]
    assert "not 90 days" in out[0].text and "no invoice is recorded" in out[1].text
    # a hand-credited account never had the link's trial, so no trial warning
    out = admin_sales.build_issues([_person()], [_account([_fleet()], credit="admin")], [], [], [], {"jordan": 90})
    assert out == []


def test_link_lead_and_member_checks():
    out = admin_sales.build_issues(
        [_person()], [], [("jordn", 2)], [("Bay Towing LLC", ["Jordan Hall", "Sam"])],
        [{"code": "jordan", "member_email": "deck@bay.example", "workspace": "Bay Towing",
          "owner_email": "owner@bay.example", "owner_id": "o1"}], {})
    assert [i.code for i in out] == ["jordn", None, "jordan"]
    assert "2 accounts signed up with pilot code 'jordn'" in out[0].text
    assert "Jordan Hall and Sam" in out[1].text
    assert out[2].fix == "credit_owner" and out[2].user_id == "o1"
