"""Optional demo data: python seed.py"""
from datetime import date, timedelta
from main import SessionLocal, Vendor
t = date.today()
rows = [("Zoho", 400, 60, "Net 30", "Low"), ("Razorpay", 95, 45, "Net 15", "Medium"),
        ("Security Audit Co", 40, 30, "Net 45", "High"), ("Marketing Agency", 200, 30, "Net 30", "Medium")]
with SessionLocal() as db:
    for n, end, notice, pay, risk in rows:
        db.add(Vendor(name=n, contract_end=t + timedelta(days=end), contract_start=t - timedelta(days=365 - end if end < 365 else 0),
                      notice_days=notice, payment_terms=pay, risk_level=risk))
    db.commit()
print("seeded")
