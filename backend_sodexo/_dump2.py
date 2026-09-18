import warnings, json
warnings.filterwarnings('ignore')
from app.core.database import SessionLocal
from app.services.forecasting import workspace, data as sd
from app.services.forecasting.contract import SERIES, SERIES_BY_KEY, MODEL_SPECS
from app.models import ModelRun, TrainingJob
from sqlalchemy import select
db = SessionLocal()
job = db.execute(select(TrainingJob).order_by(TrainingJob.started_at.desc())).scalars().first()
print("=== TRAINING JOB ===")
print(f"id={job.job_id} status={job.status} steps={job.completed_steps}/{job.total_steps}")
print(f"started={job.started_at} completed={job.completed_at} duration={(job.completed_at-job.started_at) if job.completed_at else 'n/a'}")

print("\n=== DEMAND DRIVERS ===")
d = workspace.get_drivers(db)
s0 = d["series"][0]; s2 = [x for x in d["series"] if "CAFE" in x["series_key"]][0]
print("target:", s0["mapping"]["target_column"])
print("F&N inputs (%d): %s" % (len(s0["exogenous_drivers_used"]), s0["exogenous_drivers_used"]))
print("Cafe inputs (%d): %s" % (len(s2["exogenous_drivers_used"]), s2["exogenous_drivers_used"]))
print("not_in_dataset:", [x["name"] for x in d["not_in_dataset"]])

print("\n=== DATA ANALYSIS (EDA) ===")
e = workspace.get_eda(db, "LOC01_FOOD_NUTRITION")
byh = e["by_hour_of_day"]; peak = max(byh, key=lambda k: byh[k]); low = min(byh, key=lambda k: byh[k])
print(f'daily_trend pts={len(e["daily_trend"])} first={e["daily_trend"][0]} last={e["daily_trend"][-1]}')
print(f'hour peak={peak}:00 ({byh[peak]}) quietest={low}:00 ({byh[low]})')
print("by_day_of_week:", e["by_day_of_week"])
print("season_effect:", e["season_effect"], "holiday_lift_pct:", e["holiday_lift_pct"])
ec = workspace.get_eda(db, "LOC01_CAFE")
print("cafe flag_effects:", json.dumps(ec["flag_effects"]))

print("\n=== DATA PRE-PROCESSING ===")
pp = workspace.get_preprocessing(db, "LOC01_FOOD_NUTRITION")
print({k: v for k, v in pp.items() if k not in ("preview_rows","preview_columns","series_label")})
print("preview cols:", pp["preview_columns"])
print("row 1:", json.dumps(pp["preview_rows"][0]))

print("\n=== LEADERBOARD (all series) ===")
for s in SERIES:
    runs = db.execute(select(ModelRun).where(ModelRun.job_id==job.job_id, ModelRun.series_key==s.key)).scalars().all()
    ok = [r for r in runs if r.status=="completed" and r.accuracy is not None]
    ok.sort(key=lambda r: r.mape)
    ch = [r for r in runs if r.is_champion]
    print(f'\n{s.key}  ({len(ok)}/{len(runs)} completed)  champion={ch[0].model_label if ch else "-"}')
    for r in ok:
        star = " *CHAMPION*" if r.is_champion else ""
        print(f'   {r.model_label:44s} acc={r.accuracy:6.2f}% mape={r.mape:6.2f} mae={r.mae:5.2f} rmse={r.rmse:5.2f} bias={r.bias:7.2f} {r.runtime_seconds:6.2f}s rows={r.train_rows}/{r.test_rows}{star}')
    for r in runs:
        if r.status != "completed":
            print(f'   {r.model_label:44s} [{r.status}] {(r.failure_reason or "")[:60]}')

print("\n=== FORECAST EXPLORER (champion, LOC01_FOOD_NUTRITION) ===")
import app.api.routes.forecast as fr
ch = db.execute(select(ModelRun).where(ModelRun.job_id==job.job_id, ModelRun.series_key=="LOC01_FOOD_NUTRITION", ModelRun.is_champion.is_(True))).scalars().first()
from app.models import ModelPrediction
ps = db.execute(select(ModelPrediction).where(ModelPrediction.model_run_id==ch.id).order_by(ModelPrediction.business_date, ModelPrediction.hour_of_day)).scalars().all()
hist = [p for p in ps if not p.is_future]; fut = [p for p in ps if p.is_future]
print(f'model={ch.model_label} train_rows={ch.train_rows} test_rows={ch.test_rows} mode={ch.evaluation_mode} folds={ch.folds}')
print(f'backtest pts={len(hist)} future pts={len(fut)}')
print(f'last actual={hist[-1].business_date} {hist[-1].hour_of_day:02d}:00 -> forecast {fut[0].business_date} to {fut[-1].business_date}')
print("first 4 future:", [(str(p.business_date), p.hour_of_day, round(p.predicted,1), round(p.lower,1) if p.lower else None, round(p.upper,1) if p.upper else None) for p in fut[:4]])

print("\n=== DRIFT ===")
for s in SERIES:
    try:
        dr = workspace.get_drift(db, s.key, None)
        print(f'{s.key:24s} status={dr["status"]:8s} signal={dr["demand_signal_name"]:18s} r={dr["demand_signal_correlation"]} ({dr["demand_signal_strength"]}) recent={dr["feature_distribution"]["recent_7d_mean"]} prior={dr["feature_distribution"]["prior_30d_mean"]} chg={dr["feature_distribution"]["pct_change"]}% age={dr["model_age_days"]}d')
    except LookupError:
        print(f'{s.key:24s} no model')

print("\n=== STAFFING IMPACT ===")
for s in SERIES:
    si = workspace.get_staffing_impact(db, s.key)
    pts = si.get("points", [])
    if not pts: print(f'{s.key}: {si.get("note")}'); continue
    und = [p for p in pts if p["status"]=="Understaffed"]; over=[p for p in pts if p["status"]=="Overstaffed"]
    print(f'{s.key:24s} pts={len(pts)} understaffed={len(und)} overstaffed={len(over)} balanced={len(pts)-len(und)-len(over)} window={si["window_start"]}..{si["window_end"]}')
print("sample point:", json.dumps(workspace.get_staffing_impact(db,"LOC01_FOOD_NUTRITION")["points"][-1]))
db.close()
