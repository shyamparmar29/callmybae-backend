from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from database import get_db
from models import User, CallSession, Companion, Subscription, WhatsAppSession
from datetime import datetime, timedelta, timezone

router = APIRouter()

@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Analytics data for dashboard."""
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Total users
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    users_today = (await db.execute(select(func.count(User.id)).where(User.created_at >= today))).scalar()
    users_week = (await db.execute(select(func.count(User.id)).where(User.created_at >= week_ago))).scalar()

    # Calls
    total_calls = (await db.execute(select(func.count(CallSession.id)))).scalar()
    free_calls = (await db.execute(select(func.count(CallSession.id)).where(CallSession.is_free_call == True))).scalar()
    calls_today = (await db.execute(select(func.count(CallSession.id)).where(CallSession.created_at >= today))).scalar()

    # Plans
    spark_users = (await db.execute(select(func.count(User.id)).where(User.plan == "spark"))).scalar()
    soulmate_users = (await db.execute(select(func.count(User.id)).where(User.plan == "soulmate"))).scalar()

    # Active subscriptions
    active_subs = (await db.execute(
        select(func.count(Subscription.id)).where(
            Subscription.status == "active",
            Subscription.expires_at >= now
        )
    )).scalar()

    # WhatsApp sessions
    wa_sessions = (await db.execute(select(func.count(WhatsAppSession.id)))).scalar()

    # Total call minutes
    total_mins_result = (await db.execute(select(func.sum(CallSession.duration_secs)))).scalar()
    total_minutes = int((total_mins_result or 0) / 60)

    # Recent calls
    recent_calls_result = await db.execute(
        select(CallSession).order_by(CallSession.created_at.desc()).limit(10)
    )
    recent_calls = recent_calls_result.scalars().all()

    return {
        "users": {
            "total": total_users,
            "today": users_today,
            "this_week": users_week,
        },
        "calls": {
            "total": total_calls,
            "free_calls": free_calls,
            "paid_calls": total_calls - free_calls,
            "today": calls_today,
            "total_minutes": total_minutes,
        },
        "revenue": {
            "spark_users": spark_users,
            "soulmate_users": soulmate_users,
            "active_subscriptions": active_subs,
            "mrr_estimate_inr": (spark_users * 499) + (soulmate_users * 1499),
        },
        "whatsapp": {
            "total_sessions": wa_sessions,
        },
        "recent_calls": [
            {
                "id": c.id[:8],
                "phone": c.caller_phone[-4:].rjust(10, "*"),
                "duration": f"{c.duration_secs}s",
                "status": c.status,
                "free": c.is_free_call,
                "time": c.created_at.isoformat() if c.created_at else "",
                "recording": bool(c.recording_url),
            }
            for c in recent_calls
        ]
    }

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(db: AsyncSession = Depends(get_db)):
    """Admin analytics dashboard."""
    stats = await get_stats(db)
    u = stats["users"]
    c = stats["calls"]
    r = stats["revenue"]
    w = stats["whatsapp"]

    rows = ""
    for call in stats["recent_calls"]:
        rec = "🔴 REC" if call["recording"] else ""
        free = "Free" if call["free"] else "Paid"
        rows += f"""<tr>
            <td>{call['id']}</td>
            <td>{call['phone']}</td>
            <td>{call['duration']}</td>
            <td>{call['status']}</td>
            <td>{free}</td>
            <td>{rec}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<title>CallMyBae Admin</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#06040e; color:#f0e4d0; font-family:'Segoe UI',sans-serif; padding:2rem; }}
h1 {{ font-size:1.8rem; margin-bottom:0.3rem; color:#ff6b8a; }}
.sub {{ color:#7a6e8a; font-size:0.9rem; margin-bottom:2rem; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:1rem; margin-bottom:2rem; }}
.card {{ background:rgba(255,255,255,0.05); border:1px solid rgba(255,107,138,0.2); border-radius:12px; padding:1.5rem; }}
.card .num {{ font-size:2.5rem; font-weight:700; color:#ff6b8a; line-height:1; }}
.card .label {{ font-size:0.78rem; color:#7a6e8a; text-transform:uppercase; letter-spacing:0.1em; margin-top:0.3rem; }}
.card .sub-num {{ font-size:0.85rem; color:#c8b8a0; margin-top:0.5rem; }}
table {{ width:100%; border-collapse:collapse; background:rgba(255,255,255,0.03); border-radius:12px; overflow:hidden; }}
th {{ background:rgba(255,107,138,0.15); padding:0.8rem 1rem; text-align:left; font-size:0.8rem; text-transform:uppercase; letter-spacing:0.08em; color:#ff6b8a; }}
td {{ padding:0.75rem 1rem; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.88rem; }}
tr:last-child td {{ border-bottom:none; }}
h2 {{ margin-bottom:1rem; font-size:1.1rem; color:#f5c85a; }}
.mrr {{ color:#4ade80; }}
</style>
</head>
<body>
<h1>CallMyBae Dashboard</h1>
<div class="sub">Live analytics · Auto-refreshes every 60s</div>

<div class="grid">
  <div class="card">
    <div class="num">{u['total']}</div>
    <div class="label">Total Users</div>
    <div class="sub-num">+{u['today']} today · +{u['this_week']} this week</div>
  </div>
  <div class="card">
    <div class="num">{c['total']}</div>
    <div class="label">Total Calls</div>
    <div class="sub-num">{c['free_calls']} free · {c['paid_calls']} paid · {c['today']} today</div>
  </div>
  <div class="card">
    <div class="num">{c['total_minutes']}</div>
    <div class="label">Minutes Talked</div>
    <div class="sub-num">Across all calls</div>
  </div>
  <div class="card">
    <div class="num mrr">₹{r['mrr_estimate_inr']:,}</div>
    <div class="label">MRR Estimate</div>
    <div class="sub-num">{r['spark_users']} Spark · {r['soulmate_users']} Soulmate</div>
  </div>
  <div class="card">
    <div class="num">{r['active_subscriptions']}</div>
    <div class="label">Active Subscribers</div>
    <div class="sub-num">Paid plans</div>
  </div>
  <div class="card">
    <div class="num">{w['total_sessions']}</div>
    <div class="label">WhatsApp Users</div>
    <div class="sub-num">Active conversations</div>
  </div>
</div>

<h2>Recent Calls</h2>
<table>
  <thead><tr><th>ID</th><th>Phone</th><th>Duration</th><th>Status</th><th>Type</th><th>Rec</th></tr></thead>
  <tbody>{rows}</tbody>
</table>

<script>setTimeout(()=>location.reload(), 60000)</script>
</body>
</html>"""
