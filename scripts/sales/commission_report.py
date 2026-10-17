"""Commission report for a sales pilot code (2026-10-16): what the accounts that
signed up from `src=pilot-<code>` paid us, by month, straight from Stripe.

Run on the VPS from apps/api (read-only; prints no secrets):

    .venv/bin/python /opt/RegKnots/scripts/sales/commission_report.py jordan [--rate 0.25] [--months N]

Accounts: users whose signup_attribution->>'src' is pilot-<code>, their own
subscription and the workspaces they own (workspaces.stripe_subscription_id).
Revenue: Stripe invoices with amount_paid > 0 on those subscriptions, by paid
month; refunds come off the month they're issued. Commission: rate × revenue, for as
long as the customer pays (--months limits the window).
"""
import argparse
import datetime as dt
import os
import subprocess
from collections import defaultdict

import stripe

for line in open("/opt/RegKnots/.env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.rstrip("\r\n").split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]


def psql(sql: str) -> list[list[str]]:
    out = subprocess.run(["docker", "exec", "regknots-postgres", "psql", "-U", "regknots", "-d", "regknots", "-At", "-F", "\t", "-c", sql],
                         capture_output=True, text=True, check=True).stdout
    return [ln.split("\t") for ln in out.splitlines() if ln]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--rate", type=float, default=0.25)
    ap.add_argument("--months", type=int, default=0, help="commission window per customer; 0 = for as long as they pay (Blake, 2026-10-16)")
    a = ap.parse_args()
    src = f"pilot-{a.code}"
    rows = psql(f"""
        SELECT u.email, u.created_at::date, 'account', u.stripe_subscription_id
          FROM users u WHERE u.signup_attribution->>'src' = '{src}'
        UNION ALL
        SELECT u.email, w.created_at::date, 'fleet: ' || w.name, w.stripe_subscription_id
          FROM workspaces w JOIN users u ON u.id = w.owner_user_id
         WHERE u.signup_attribution->>'src' = '{src}'
        ORDER BY 2""")
    print(f"{src}: {len(rows)} account(s) / fleet(s)")
    by_month = defaultdict(float)
    for email, created, what, sub_id in rows:
        label = f"{email.split('@')[0][:2]}*** {what}"
        if not sub_id:
            print(f"  {created}  {label:40} no subscription yet")
            continue
        invoices = [i for i in stripe.Invoice.list(subscription=sub_id, limit=100).auto_paging_iter() if i.amount_paid]
        first = min((i.status_transitions.paid_at for i in invoices), default=None)
        total = 0
        for inv in invoices:
            paid = dt.datetime.fromtimestamp(inv.status_transitions.paid_at, dt.UTC)
            if a.months and first and paid > dt.datetime.fromtimestamp(first, dt.UTC) + dt.timedelta(days=30 * a.months + 15):
                continue        # past the commission window
            amount = inv.amount_paid / 100
            for ref in stripe.Refund.list(charge=inv.charge, limit=20).auto_paging_iter() if inv.charge else []:
                amount -= ref.amount / 100
            by_month[paid.strftime("%Y-%m")] += amount
            total += amount
        print(f"  {created}  {label:40} {len(invoices)} paid invoice(s), ${total:,.2f} in window")
    print()
    print(f"{'month':8} {'revenue':>10} {'commission':>12}")
    for m in sorted(by_month):
        print(f"{m:8} {by_month[m]:>10,.2f} {by_month[m] * a.rate:>12,.2f}")
    print(f"{'total':8} {sum(by_month.values()):>10,.2f} {sum(by_month.values()) * a.rate:>12,.2f}")


if __name__ == "__main__":
    main()
