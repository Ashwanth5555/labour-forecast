from sqlalchemy.orm import Session

from app.services.assistant import llm, tools

# Both replies use the same bullet structure the real answers do, so an
# out-of-scope question or a plain "hi" still looks like part of the product.
_SCOPE_MESSAGE = """That one is outside what I can see - I only read this application's own workforce data.

**I can help with**
- Labor demand forecasts and where demand is heading
- Staffing gaps, where a shift is short of people or overstaffed
- Labor cost against budget, and overtime
- Punch and attendance issues
- Employee risk scores, and what to act on first

**Try**
- "What is the demand trend for the cafe?"
- "Which department is over budget?\""""

_GREETING_MESSAGE = """Hello - good to have you here. I am the workforce assistant for this Sodexo Healthcare build, and every number I give you is read from this application's own data.

**What I can tell you about**
- **Demand forecasts** - where labor demand is heading, and how reliable that forecast is
- **Staffing gaps** - which shifts are short of people, and by how many
- **Cost and overtime** - spend against budget, and where overtime is building
- **Punch and attendance** - flagged issues and what is driving them
- **What to do next** - the current recommendations, ranked by priority

**A good place to start**
- "Which location needs immediate attention?"
- "How can I reduce overtime this week?"
- "What is the demand trend for the cafe?\""""


def _select(question: str, history: list[dict] | None) -> tuple[list[str], str]:
    """Model routing first, keyword routing as the safety net.

    The keyword router is exact but literal - it cannot tell that "who might
    quit?" is a risk question. The model router reads intent, so it leads. If
    it returns nothing (out of scope, or the call failed) the keyword result
    still stands, which keeps an in-scope question answered rather than
    declined on a routing hiccup.
    """
    keyword_topics = tools.select_tools(question)
    if not llm.is_configured():
        return keyword_topics, "keyword"
    routed = llm.route_topics(question, history)
    if routed:
        return routed, "model"
    return keyword_topics, "keyword"


def ask(db: Session, question: str, history: list[dict] | None = None) -> dict:
    if tools.is_greeting(question):
        return {"question": question, "answer": _GREETING_MESSAGE, "tools_used": [], "facts": {}, "llm_used": False}

    # A follow-up like "why?" carries no keywords of its own, so the previous
    # turns decide both the topic and the site being discussed.
    routing_question = question
    if history and tools.is_follow_up(question):
        previous = " ".join(t.get("content", "") for t in history if t.get("role") == "user")
        routing_question = f"{previous} {question}".strip()

    tool_names, routed_by = _select(routing_question, history)
    if not tool_names:
        return {"question": question, "answer": _SCOPE_MESSAGE, "tools_used": [], "facts": {}, "llm_used": False}

    # Site/department scoping reads the conversation too - "what about
    # overtime there?" names no site, so it inherits the one already in play.
    scoping_text = tools.scope_text(question, history)
    facts = {name: tools.TOOLS[name](db, scoping_text) for name in tool_names}
    answer = llm.generate_answer(question, facts, history)
    return {
        "question": question,
        "answer": answer,
        "tools_used": tool_names,
        "routed_by": routed_by,
        "facts": facts,
        "llm_used": llm.is_configured(),
    }
