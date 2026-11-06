"""VendorGuard - vendor renewal & risk tracker. No AI inside: Claude connects via MCP."""
import contextlib
import os
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from sqlalchemy import Column, Date, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# ---------- database ----------
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./vendorguard.db")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
MCP_KEY = os.getenv("MCP_KEY", "dev-key")
RISKS = ("Low", "Medium", "High")


class Vendor(Base):
    __tablename__ = "vendors"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    contract_start = Column(Date, nullable=True)
    contract_end = Column(Date, nullable=False)
    notice_days = Column(Integer, default=30)
    payment_terms = Column(String(100), default="")
    risk_level = Column(String(10), default="Medium")
    notes = Column(Text, default="")


Base.metadata.create_all(engine)


# ---------- business logic (plain code, no AI) ----------
def parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date '{s}'. Use YYYY-MM-DD.")


def norm_risk(r: str) -> str:
    r = (r or "Medium").strip().capitalize()
    if r not in RISKS:
        raise ValueError("risk_level must be Low, Medium or High")
    return r


def to_dict(v: Vendor) -> dict:
    today = date.today()
    act_by = v.contract_end - timedelta(days=v.notice_days or 0)
    days_to_act = (act_by - today).days
    days_to_end = (v.contract_end - today).days
    if days_to_end < 0:
        status = "Expired"
    elif days_to_act < 0:
        status = "Notice window missed"
    elif days_to_act <= 30:
        status = "Act now"
    elif days_to_act <= 90:
        status = "Upcoming"
    else:
        status = "Active"
    return {
        "id": v.id, "name": v.name,
        "contract_start": v.contract_start.isoformat() if v.contract_start else None,
        "contract_end": v.contract_end.isoformat(),
        "notice_days": v.notice_days, "payment_terms": v.payment_terms,
        "risk_level": v.risk_level, "notes": v.notes,
        "act_by": act_by.isoformat(), "days_to_act": days_to_act,
        "days_to_end": days_to_end, "status": status,
    }


def all_vendors(db: Session):
    return sorted((to_dict(v) for v in db.query(Vendor).all()), key=lambda d: d["act_by"])


def dashboard(db: Session) -> dict:
    vs = all_vendors(db)
    live = [v for v in vs if v["days_to_end"] >= 0]
    upcoming = [v for v in live if 0 <= v["days_to_act"] <= 60]
    nxt = next((v for v in live if v["days_to_act"] >= 0), None)
    return {
        "total": len(vs),
        "act_soon": len(upcoming),
        "high_risk": len([v for v in live if v["risk_level"] == "High"]),
        "missed": len([v for v in live if v["status"] == "Notice window missed"]),
        "next_deadline": {"name": nxt["name"], "days": nxt["days_to_act"], "act_by": nxt["act_by"]} if nxt else None,
    }


# ---------- MCP server (the plug Claude uses) ----------
mcp = FastMCP("VendorGuard", stateless_http=True, json_response=True)
mcp.settings.streamable_http_path = "/"


@mcp.tool()
def create_vendor(name: str, contract_end: str, notice_days: int = 30,
                  contract_start: str = "", payment_terms: str = "",
                  risk_level: str = "Medium", notes: str = "") -> dict:
    """Create a vendor record in VendorGuard. Dates as YYYY-MM-DD.
    notice_days = days before contract_end by which the vendor must be told about non-renewal.
    risk_level = Low, Medium or High. Put key obligations/risks in notes."""
    with SessionLocal() as db:
        v = Vendor(name=name, contract_end=parse_date(contract_end),
                   contract_start=parse_date(contract_start), notice_days=notice_days,
                   payment_terms=payment_terms, risk_level=norm_risk(risk_level), notes=notes)
        db.add(v); db.commit(); db.refresh(v)
        return to_dict(v)


@mcp.tool()
def update_vendor(vendor_id: int, name: str = "", contract_end: str = "",
                  notice_days: int = -1, contract_start: str = "", payment_terms: str = "",
                  risk_level: str = "", notes: str = "") -> dict:
    """Update a vendor. Only pass the fields that change (blank/-1 means unchanged)."""
    with SessionLocal() as db:
        v = db.get(Vendor, vendor_id)
        if not v:
            return {"error": f"Vendor {vendor_id} not found"}
        if name: v.name = name
        if contract_end: v.contract_end = parse_date(contract_end)
        if contract_start: v.contract_start = parse_date(contract_start)
        if notice_days >= 0: v.notice_days = notice_days
        if payment_terms: v.payment_terms = payment_terms
        if risk_level: v.risk_level = norm_risk(risk_level)
        if notes: v.notes = notes
        db.commit(); db.refresh(v)
        return to_dict(v)


@mcp.tool()
def list_vendors() -> dict:
    """List all vendors sorted by the date action is needed, plus dashboard totals."""
    with SessionLocal() as db:
        return {"summary": dashboard(db), "vendors": all_vendors(db)}


# ---------- web app + REST API (for the human editing in the browser) ----------
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="VendorGuard", lifespan=lifespan)


def get_db():
    with SessionLocal() as db:
        yield db


class VendorIn(BaseModel):
    name: str
    contract_start: Optional[str] = None
    contract_end: str
    notice_days: int = 30
    payment_terms: str = ""
    risk_level: str = "Medium"
    notes: str = ""


def apply(v: Vendor, d: VendorIn):
    try:
        v.name = d.name
        v.contract_start = parse_date(d.contract_start)
        v.contract_end = parse_date(d.contract_end)
        v.notice_days = d.notice_days
        v.payment_terms = d.payment_terms
        v.risk_level = norm_risk(d.risk_level)
        v.notes = d.notes
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/dashboard")
def api_dashboard(db: Session = Depends(get_db)):
    return dashboard(db)


@app.get("/api/vendors")
def api_list(db: Session = Depends(get_db)):
    return all_vendors(db)


@app.post("/api/vendors")
def api_create(d: VendorIn, db: Session = Depends(get_db)):
    v = Vendor(); apply(v, d); db.add(v); db.commit(); db.refresh(v)
    return to_dict(v)


@app.put("/api/vendors/{vid}")
def api_update(vid: int, d: VendorIn, db: Session = Depends(get_db)):
    v = db.get(Vendor, vid)
    if not v:
        raise HTTPException(404, "Not found")
    apply(v, d); db.commit(); db.refresh(v)
    return to_dict(v)


@app.delete("/api/vendors/{vid}")
def api_delete(vid: int, db: Session = Depends(get_db)):
    v = db.get(Vendor, vid)
    if not v:
        raise HTTPException(404, "Not found")
    db.delete(v); db.commit()
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse("static/index.html")


# MCP mounted at /mcp, protected by ?key=... so only you/your customer can use it
class KeyGuard:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            qs = scope.get("query_string", b"").decode()
            if f"key={MCP_KEY}" not in qs.split("&"):
                r = JSONResponse({"error": "invalid key"}, status_code=401)
                return await r(scope, receive, send)
        await self.inner(scope, receive, send)


app.mount("/mcp", KeyGuard(mcp.streamable_http_app()))
