"""화장품 트랙만 조립한다. 향수 노드는 아직 넣지 않는다."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.graph.agents.commentary import commentary
from app.graph.agents.conflict_checker import conflict_checker
from app.graph.agents.ingredient_matcher import ingredient_matcher
from app.graph.state import CurationState


def _has_candidates(state: CurationState) -> str:
    return "go" if state.get("candidates") else "skip"


def build_graph():
    builder = StateGraph(CurationState)
    builder.add_node("ingredient_matcher", ingredient_matcher)
    builder.add_node("conflict_checker", conflict_checker)
    builder.add_node("commentary", commentary)

    builder.add_edge(START, "ingredient_matcher")
    builder.add_edge("ingredient_matcher", "conflict_checker")
    builder.add_conditional_edges(
        "conflict_checker",
        _has_candidates,
        {"go": "commentary", "skip": END},
    )
    builder.add_edge("commentary", END)
    return builder.compile()


graph = build_graph()
