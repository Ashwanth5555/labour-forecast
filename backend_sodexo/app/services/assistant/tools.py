"""Structured-fact retrieval for the AI Assistant - each tool calls into an
already-built application service and returns a small, curated dict, never
the raw database. The LLM (or template fallback) only ever sees these
facts, never raw rows - matching the instruction to use tool/service
retrieval rather than putting all data into the prompt.

The dicts are deliberately a little richer than the headline number: a
question like "who is most likely to leave?" or "which site is worst on
cost?" can only be answered accurately if the named rows behind the KPI are
in the facts, not just the count.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModelPrediction, ModelRun, TrainingJob


def _latest_job(db: Session) -> TrainingJob | None:
    return db.execute(select(TrainingJob).order_by(TrainingJob.started_at.desc())).scalars().first()


def _trend_for_run(db: Session, run: ModelRun) -> dict | None:
    """Recent-actual vs. future-forecast average, computed from the same
    persisted ModelPrediction rows the Forecast Explorer chart uses - a real
    number for trend/graph-shaped questions, not a description."""
    predictions = db.execute(select(ModelPrediction).where(ModelPrediction.model_run_id == run.id)).scalars().all()
    recent_actual = [p.actual for p in predictions if not p.is_future and p.actual is not None][-24:]
    future = [p.predicted for p in predictions if p.is_future]
    if not recent_actual or not future:
        return None
    avg_recent = sum(recent_actual) / len(recent_actual)
    avg_future = sum(future) / len(future)
    if not avg_recent:
        return None
    pct_change = round((avg_future - avg_recent) / avg_recent * 100, 1)
    direction = "flat" if abs(pct_change) < 5 else ("rising" if pct_change > 0 else "falling")
    return {"avg_recent_actual": round(avg_recent, 2), "avg_forecast_next_7d": round(avg_future, 2), "pct_change": pct_change, "direction": direction}


# Department and location are matched separately so "the cafe at Community
# Hospital" narrows to exactly one series instead of matching all three
# series that mention either word.
_DEPARTMENT_ALIASES = {
    "CAFE": ("cafe", "cafes", "café", "retail", "coffee", "kiosk"),
    "FOOD_NUTRITION": ("food", "nutrition", "kitchen", "catering", "food & nutrition", "food and nutrition"),
}
_LOCATION_ALIASES = {
    "LOC01": ("community hospital", "community", "loc01", "loc 01", "location 1", "site 1"),
    "LOC02": ("regional medical", "regional", "loc02", "loc 02", "location 2", "site 2"),
}


def _alias_hits(question: str, aliases: dict[str, tuple[str, ...]]) -> set[str]:
    q = question.lower()
    words = set(_words(q))
    hit = set()
    for code, terms in aliases.items():
        for term in terms:
            if (term in q) if " " in term else (term in words):
                hit.add(code)
                break
    return hit


# dim_department: DEP01 = Food & Nutrition Services, DEP02 = Retail & Cafe Services.
_DEPARTMENT_IDS = {"FOOD_NUTRITION": "DEP01", "CAFE": "DEP02"}


def _scope_employees(question: str, rows: list[dict]) -> list[dict]:
    """Narrow employee-level rows to the site/department the question names.

    Without this, a "who is highest risk at the cafe?" question was answered
    from the global top-N, so the right employee was only ever included by
    luck. Falls back to the unfiltered rows when the filter empties the list,
    so a scoped question still gets an answer rather than silence.
    """
    locations = _alias_hits(question, _LOCATION_ALIASES)
    departments = {_DEPARTMENT_IDS[d] for d in _alias_hits(question, _DEPARTMENT_ALIASES) if d in _DEPARTMENT_IDS}
    if not locations and not departments:
        return rows
    scoped = [
        r for r in rows
        if (not locations or r.get("location_id") in locations)
        and (not departments or r.get("department_id") in departments)
    ]
    return scoped or rows


_SCOPE_NAMES = {
    "LOC01": "Community Hospital", "LOC02": "Regional Medical Center",
    "CAFE": "Retail & Cafe Services", "FOOD_NUTRITION": "Food & Nutrition Services",
}


def _scope_label(question: str) -> str:
    """What the question narrowed to, in words. The site-level payloads carry
    every department so a ranking question can be answered, which means the
    answer needs telling which row the user actually asked about - otherwise a
    scoped question gets answered with the company-wide total."""
    codes = sorted(_alias_hits(question, _LOCATION_ALIASES)) + sorted(_alias_hits(question, _DEPARTMENT_ALIASES))
    if not codes:
        return "all sites and departments"
    return ", ".join(_SCOPE_NAMES[c] for c in codes)


def _mentioned_series(question: str, series_list) -> list:
    """If the question names a specific location and/or department (e.g. "the
    cafe", "community hospital", "the cafe at Regional Medical"), scope facts
    to just those series instead of dumping all 4 - keeps answers on-topic and
    short. Falls back to every series when nothing specific is named."""
    departments = _alias_hits(question, _DEPARTMENT_ALIASES)
    locations = _alias_hits(question, _LOCATION_ALIASES)
    if not departments and not locations:
        return list(series_list)
    matched = [
        s for s in series_list
        if (not departments or any(d in s.key for d in departments))
        and (not locations or s.location_id in locations)
    ]
    return matched or list(series_list)


def forecast_facts(db: Session, question: str = "") -> dict:
    job = _latest_job(db)
    if not job:
        return {"status": "No training run yet - Labor Forecasting has not been trained."}

    from app.services.forecasting import workspace
    from app.services.forecasting.contract import SERIES

    scoped_series = _mentioned_series(question, SERIES)
    scoped_keys = {s.key for s in scoped_series}
    champions = db.execute(
        select(ModelRun).where(ModelRun.job_id == job.job_id, ModelRun.is_champion.is_(True), ModelRun.series_key.in_(scoped_keys))
    ).scalars().all()

    staffing = []
    for series in scoped_series:
        impact = workspace.get_staffing_impact(db, series.key, days=1)
        if impact.get("points"):
            staffing.append({"series": series.label, **impact["points"][-1]})

    label_by_key = {s.key: s.label for s in SERIES}
    return {
        # Tells the model whether it is looking at one named site or all of
        # them, so it does not describe a scoped answer as company-wide.
        "scope": [s.label for s in scoped_series] if len(scoped_series) < len(SERIES) else "all sites and departments",
        "champions": [
            {"series": label_by_key.get(c.series_key, c.series_key), "model": c.model_label, "mape": c.mape, "accuracy": c.accuracy, "trend": _trend_for_run(db, c)}
            for c in champions
        ],
        "latest_staffing_gap": staffing,
    }


def labor_cost_facts(db: Session, question: str = "") -> dict:
    from app.services.analytics import labor_analytics

    summary = labor_analytics.compute(db)
    if summary.get("error"):
        return {"status": summary["error"]}
    # The full per-department rows, ranked worst-to-best on budget variance.
    # Without these, a "which department is worst on cost?" question had only
    # the company-wide KPI total to work from and could not be answered.
    departments = sorted(
        (
            {
                "location": m["location_name"], "department": m["department_name"],
                "labor_cost": m["labor_cost"], "vs_budget_pct": m["labor_cost_vs_budget_pct"],
                "overtime_pct_of_hours": m["overtime_control_pct"],
                "schedule_adherence_pct": m["schedule_adherence_pct"],
                "headcount": m["headcount"], "hours_worked": m["actual_hours"],
                "scorecard_rank": m["rank"],
            }
            for m in summary["manager_performance"]
        ),
        key=lambda d: d["vs_budget_pct"] if d["vs_budget_pct"] is not None else -999,
        reverse=True,
    )
    return {
        "scope": _scope_label(question),
        "window": summary.get("window"),
        "kpis": summary["kpis"],
        "departments_ranked_by_budget_variance": departments,
        "over_budget_departments": [d for d in departments if (d["vs_budget_pct"] or 0) > 10],
    }


def punch_facts(db: Session, question: str = "") -> dict:
    from app.services.punch_analytics import rules

    result = rules.detect_anomalies(db)
    if result.get("error"):
        return {"status": result["error"]}
    anomalies = result.get("anomalies") or []
    # Which exception types actually drive the exception rate, plus the named
    # repeat offenders - a "who keeps missing punches?" question needs rows,
    # not just the KPI count.
    by_type: dict[str, int] = {}
    by_employee: dict[str, dict] = {}
    for a in anomalies:
        by_type[a["exception_type"]] = by_type.get(a["exception_type"], 0) + 1
        entry = by_employee.setdefault(a["employee_id"], {
            "employee": a["employee_name"], "location": a["location_name"], "department": a["department_name"],
            "location_id": a["location_id"], "department_id": a["department_id"], "exceptions": 0,
        })
        entry["exceptions"] += 1
    flagged = _scope_employees(question, sorted(by_employee.values(), key=lambda e: -e["exceptions"]))
    return {
        "scope": _scope_label(question),
        "window": result.get("window"),
        "kpis": result["kpis"],
        "total_exceptions": len(anomalies),
        "exceptions_by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        # The ids exist only to drive the scoping above; the names carry the
        # same information for a reader.
        "most_flagged_employees": [{k: v for k, v in e.items() if not k.endswith("_id")} for e in flagged[:5]],
    }


def risk_facts(db: Session, question: str = "") -> dict:
    from app.services.predictions import engine as predictions_engine

    result = predictions_engine.compute_all(db)
    summary = []
    for m in result["employee_models"]:
        if m.get("status") == "completed":
            high = [e for e in m["employees"] if e["risk_level"] == "High"]
            scoped = _scope_employees(question, m["employees"])
            summary.append({
                "model": m["model_label"],
                "high_risk_employee_count": len(high),
                "roc_auc": m["metrics"]["roc_auc"],
                # Named employees, so "who is most at risk?" is answerable from
                # the facts instead of only "how many". Already sorted by
                # descending risk by the prediction service.
                "highest_risk_employees": [
                    {
                        "employee": e["employee_name"], "location": e["location_name"],
                        "department": e["department_name"], "risk_pct": round(e["risk_probability"] * 100),
                        "risk_level": e["risk_level"],
                    }
                    for e in scoped[:5]
                ],
                "top_drivers": m.get("top_drivers"),
            })
        else:
            summary.append({"model": m["model_id"], "status": "not_applicable", "reason": m.get("reason")})
    return {"risk_models": summary, "turnover_risk": result["turnover_risk"]["reason"]}


def recommendation_facts(db: Session, question: str = "") -> dict:
    from app.services.recommendations import engine as recommendations_engine

    recs = recommendations_engine.compute_recommendations(db, limit=8)
    return {
        "total_open_actions": len(recs),
        "high_priority_count": sum(1 for r in recs if r["priority"] == "High"),
        # `id` is a routing key for the UI and means nothing to a reader, so it
        # is dropped rather than spent as prompt text.
        "top_recommendations": [{k: v for k, v in r.items() if k != "id"} for r in recs],
    }


def model_performance_facts(db: Session, question: str = "") -> dict:
    forecast = forecast_facts(db, question)
    from app.services.predictions import engine as predictions_engine

    predictive = predictions_engine.compute_all(db)
    classifier_metrics = [{"model": m["model_label"], "metrics": m.get("metrics"), "top_drivers": m.get("top_drivers")} for m in predictive["employee_models"] if m.get("status") == "completed"]
    return {"forecast_champions": forecast.get("champions"), "predictive_models": classifier_metrics}


TOOLS = {
    "forecast": forecast_facts,
    "labor_cost": labor_cost_facts,
    "punch": punch_facts,
    "risk": risk_facts,
    "recommendations": recommendation_facts,
    "model_performance": model_performance_facts,
}

# Shown to the LLM router so it can pick tools by meaning rather than by
# keyword overlap. Keep in step with TOOLS.
TOOL_DESCRIPTIONS = {
    "forecast": "labor demand forecast, forecast trend and direction, required vs scheduled headcount, staffing gaps, under/overstaffed shifts",
    "labor_cost": "labor cost, spend against budget, per-department budget variance, overtime hours and cost, hours worked, headcount",
    "punch": "clock-in/clock-out punches, missed punches, late arrivals, buddy punching, timecard exceptions, attendance anomalies",
    "risk": "per-employee predictive risk scores and who is highest risk: overtime risk, absenteeism risk, schedule adherence risk, payroll anomaly risk, turnover",
    "recommendations": "the ranked list of recommended actions to take now, what to prioritise, what needs immediate attention, estimated savings",
    "model_performance": "how accurate or trustworthy the models are: champion model per series, backtest accuracy, MAPE, ROC-AUC, feature drivers",
}


# Word sets, not substrings. The previous version used
# `q.startswith(keyword)`, so "highest cost department" started with "hi" and
# was answered as a greeting, and anything starting with "help" was too.
_GREETING_WORDS = {
    "hi", "hii", "hiya", "hey", "heya", "hello", "helo", "yo", "howdy", "sup",
    "good", "morning", "afternoon", "evening", "there", "thanks", "thank", "you",
    "ok", "okay", "cool", "nice", "please",
}
_CAPABILITY_PHRASES = (
    "what can you do", "who are you", "what do you do", "how do you work",
    "what can i ask", "what should i ask", "what are you",
)

# Each topic scores by how many of its terms the question hits; the best
# topics win. One shared keyword no longer drags in a whole extra topic, and a
# question that hits nothing is declined rather than answered with whatever
# matched first.
_TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "labor_cost": (
        "cost", "costs", "budget", "budgets", "spend", "spending", "expense", "expenses",
        "payroll", "overtime", "over time", "ot hours", "utilisation", "utilization",
        "cost per hour", "under budget", "over budget", "money", "dollars",
    ),
    "forecast": (
        "forecast", "forecasts", "forecasting", "demand", "staffing gap", "staff gap",
        "required", "understaffed", "overstaffed", "short of staff", "shortfall",
        "trend", "trending", "graph", "chart", "pattern", "rising", "falling",
        "increase", "increasing", "decrease", "decreasing",
        "how many staff", "headcount", "roster", "rota", "schedule", "scheduled",
        "staff", "staffing", "cover", "shift", "shifts",
        # Deliberately NOT "tomorrow" / "next week" on their own - "what's the
        # weather tomorrow" was matching forecast on the date word alone.
    ),
    "punch": (
        "punch", "punches", "punching", "attendance", "late", "lateness", "missed",
        "anomaly", "anomalies", "buddy", "clock in", "clock out", "clocking",
        "exception", "exceptions", "absent", "absence", "absenteeism", "timecard",
    ),
    "risk": ("risk", "risks", "risky", "at risk", "turnover", "attrition", "likely to", "predict", "prediction"),
    "recommendations": (
        "recommend", "recommends", "recommended", "recommendation", "recommendations",
        "action", "actions", "should i", "what should", "how should", "how do i",
        "reduce", "cut", "improve", "fix", "advice", "advise", "suggest", "suggestion",
        "how can", "priority", "priorities", "prioritise", "prioritize", "next step",
        "needs attention", "immediate attention",
    ),
    "model_performance": (
        "model", "models", "accuracy", "accurate", "mape", "champion", "backtest",
        "how reliable", "can i trust", "trustworthy", "model performance",
    ),
}
MAX_TOPICS = 3

# A whole-picture question deserves the whole picture, not the two topics that
# happened to share a word with it.
_OVERVIEW_PHRASES = (
    "overview", "summary", "summarise", "summarize", "everything", "overall",
    "how are we doing", "state of play", "full picture", "brief me", "walk me through",
)
_OVERVIEW_TOPICS = ["recommendations", "forecast", "labor_cost"]


def _words(text: str) -> list[str]:
    return re.findall("[a-z0-9']+", text.lower())


def _term_hits(question: str, terms: tuple[str, ...]) -> int:
    """Whole-word for single terms, plain containment for phrases.

    A multi-word phrase counts double: matching "over budget" is far stronger
    evidence of intent than matching the bare word "budget", and without the
    weighting a topic with many single words always outranked a precise
    phrase match.
    """
    q = question.lower()
    words = set(_words(q))
    hits = 0
    for term in terms:
        if " " in term:
            if term in q:
                hits += 2
        elif term in words:
            hits += 1
    return hits


def select_tools(question: str) -> list[str]:
    """No fallback to a default topic - if nothing matches, the question is
    genuinely out of scope for this app and service.py declines rather than
    answering with unrelated facts."""
    q = " ".join(_words(question))
    if any(phrase in q for phrase in _OVERVIEW_PHRASES):
        return list(_OVERVIEW_TOPICS)
    scored = [(topic, _term_hits(question, terms)) for topic, terms in _TOPIC_TERMS.items()]
    ranked = sorted((t for t in scored if t[1] > 0), key=lambda t: -t[1])
    if not ranked:
        return []
    # Only keep the topics that are genuinely competitive with the best match,
    # so a single incidental keyword no longer pulls in a third topic.
    best = ranked[0][1]
    return [topic for topic, hits in ranked[:MAX_TOPICS] if hits * 2 >= best]


def is_greeting(question: str) -> bool:
    """True only for a message that is *entirely* pleasantries, or a genuine
    "what can you do" - never for a real question that merely opens with one."""
    words = _words(question)
    if not words:
        return False
    if all(word in _GREETING_WORDS for word in words):
        return True
    q = " ".join(words)
    return any(phrase in q for phrase in _CAPABILITY_PHRASES) and not select_tools(question)


FOLLOW_UP_MAX_WORDS = 6

# Words that point back at something already said. A question containing one
# of these cannot be scoped on its own words alone.
_REFERENTIAL_WORDS = {"there", "that", "it", "its", "them", "they", "their", "those", "same"}


def is_follow_up(question: str) -> bool:
    """A short message that carries no subject of its own ("why?", "and the
    food service?") only makes sense against the previous turn, so its topic
    has to be inherited rather than parsed out of these few words.

    Deliberately keyed on "has no topic of its own" rather than on the opening
    word: "Which department is over budget?" and "What is the demand trend?"
    both open with a question word but stand perfectly well alone, and
    treating them as follow-ups dragged the previous site into a question that
    was asking about all of them.
    """
    words = _words(question)
    if not words or len(words) > FOLLOW_UP_MAX_WORDS:
        return False
    return not select_tools(question)


def scope_text(question: str, history: list[dict] | None = None) -> str:
    """The text the fact tools should read for site/department scoping.

    "What about overtime there?" names no site, so the site has to come from
    what was already being discussed. The previous user turns are only folded
    in when the question actually points back at them - either it names no
    subject of its own, or it uses a referential word like "there". A
    self-contained question such as "which department is over budget?" stays
    company-wide, which is what it is asking.
    """
    if not history:
        return question
    if _alias_hits(question, _DEPARTMENT_ALIASES) or _alias_hits(question, _LOCATION_ALIASES):
        return question
    if not (set(_words(question)) & _REFERENTIAL_WORDS or is_follow_up(question)):
        return question
    previous = " ".join(t.get("content", "") for t in history if t.get("role") == "user")
    return f"{previous} {question}".strip()
