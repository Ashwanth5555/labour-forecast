import warnings, json
warnings.filterwarnings('ignore')
from app.core.database import SessionLocal
from app.services.analytics import labor_analytics
from app.services.punch_analytics import rules
from app.services.recommendations import engine as recs
from app.services.forecasting import workspace
from app.services.forecasting.contract import SERIES
from app.models import ModelRun, TrainingJob, IngestionBatch
from sqlalchemy import select
db = SessionLocal()

print("=== INGESTION ===")
b = db.execute(select(IngestionBatch)).scalars().all()
print(f"sources={len(b)} loaded={sum(x.records_loaded for x in b)} rejected={sum(x.records_rejected for x in b)}")
for x in b[:6]:
    print(f"  {x.source_system:10s} {x.source_endpoint[:34]:34s} {x.status:9s} recv={x.records_received:6d} loaded={x.records_loaded:6d} rej={x.records_rejected}")

print("\n=== LABOR ANALYTICS (daily) ===")
a = labor_analytics.compute(db)
print("window:", a["window"], "grain:", a["grain"])
print("kpis:", json.dumps(a["kpis"]))
print("cost trend pts:", len(a["labor_cost"]["trend"]), "first:", a["labor_cost"]["trend"][0], "last:", a["labor_cost"]["trend"][-1])
print("locations:", a["labor_cost"]["location_names"], "cost centres:", a["labor_cost"]["cost_center_ids"])
print("sched-vs-actual first:", a["scheduled_vs_actual"]["trend"][0])
print("overtime first:", a["overtime"]["trend"][0])
print("efficiency first:", a["efficiency"]["trend"][0])
print("attendance first:", a["attendance"]["trend"][0], "breakdown:", a["attendance"]["breakdown"])
print("productivity:", a["productivity"])
print("shift_util:", a["shift_utilization"])
print("near-OT employees:", len(a["overtime"]["employees_near_overtime"]))
print("scales:", json.dumps(a["manager_scales"]))
for m in a["manager_performance"]:
    print(f'  #{m["rank"]} {m["location_name"]}/{m["department_name"]} score={m["score"]} comp={m["score_components"]} vals={m["metric_values"]} staff={m["headcount"]} hrs={m["actual_hours"]} cost={m["labor_cost"]} worst={m["worst_metric"]}')

print("\n=== LABOR ANALYTICS grain point counts ===")
for g in ("daily","weekly","monthly"):
    r = labor_analytics.compute(db, grain=g)
    print(f'  {g:8s} cost={len(r["labor_cost"]["trend"]):3d} eff={len(r["efficiency"]["trend"]):3d} att={len(r["attendance"]["trend"]):3d}')

print("\n=== TIME PUNCH ===")
p = rules.detect_anomalies(db)
print("window:", p["window"])
print("kpis:", json.dumps(p["kpis"]))
print("anomaly count:", len(p["anomalies"]))
types = {}
sev = {}
for x in p["anomalies"]:
    types[x["exception_type"]] = types.get(x["exception_type"],0)+1
    sev[x["severity"]] = sev.get(x["severity"],0)+1
print("by type:", json.dumps(types))
print("by severity:", json.dumps(sev))
print("alerts:")
for x in p["alerts"]: print("  ", x["level"], "|", x["title"])
print("watchlist:", len(p["watchlist"]))
for x in p["watchlist"][:3]: print("  ", x["employee_name"], x["recent"], "vs", x["earlier"])
print("sample anomaly:", json.dumps({k:v for k,v in p["anomalies"][0].items() if k in ("exception_type","severity","problem","expected_value","actual_value","variance","rule_triggered","root_cause","potential_impact","recommended_action")}, indent=1))
for g in ("hourly","daily","monthly"):
    print(f'  trend {g:8s}: {len(rules.detect_anomalies(db, grain=g)["trend"])} pts')
print("hourly trend sample:", rules.detect_anomalies(db, grain="hourly")["trend"][:3])

print("\n=== RECOMMENDATIONS ===")
rr = recs.compute_recommendations(db, limit=20)
print("total:", len(rr))
cats = {}
for x in rr: cats[x["category"]] = cats.get(x["category"],0)+1
print("by category:", json.dumps(cats))
for x in rr[:3]:
    print(f'  [{x["priority"]}] {x["headline"]} | {x["location_department"]}')
    print(f'      problem: {x["problem"]}')
    print(f'      action : {x["recommended_action"]}')
    print(f'      impact : {x["expected_impact"]} | savings={x["estimated_savings"]} ({x["savings_basis"]})')
db.close()
