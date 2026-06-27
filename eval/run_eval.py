"""LangSmith evaluation for the NoteGuard agent slice.

Two evaluators that map straight onto the judging story:
  1. zero_phi_to_model  - the hard privacy guarantee (must be 1.0)
  2. faithfulness       - LLM-as-judge: is every claim supported by the note?

Run:  python -m eval.run_eval
Needs: LANGSMITH_API_KEY, GOOGLE_API_KEY, TAVILY_API_KEY (+ LANGSMITH_TRACING=true)

API note: the LangSmith evaluate surface has shifted across versions. This targets
langsmith>=0.1 with dict-style evaluators (inputs/outputs). Adjust signatures if
your installed version differs.
"""
from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langsmith import Client

from agent.graph import build_graph
from noteguard.deid import NoteGuard

KNOWN = {"PERSON": ["Margaret Okafor"], "NHS": ["485 777 3456"]}
EXAMPLES = [
    {
        "note": "Pt Margaret Okafor (NHS 485 777 3456, DOB 14/03/1934) admitted post-fall. Hx AF, on warfarin.",
        "question": "Draft a short discharge summary.",
    },
]

client = Client()
_judge = None


def target(inputs: dict) -> dict:
    graph = build_graph(known=KNOWN)
    state = graph.invoke(
        {"messages": [HumanMessage(content=inputs["note"] + "\n\n" + inputs["question"])]},
        config={"configurable": {"thread_id": "eval"}},
    )
    model_facing = " ".join(getattr(m, "content", "") or "" for m in state["messages"])
    return {"clinician_answer": state.get("clinician_answer", ""), "model_facing": model_facing}


def zero_phi_to_model(inputs: dict, outputs: dict) -> dict:
    hits = NoteGuard(known=KNOWN).residual_identifiers(outputs["model_facing"])
    return {"key": "zero_phi_to_model", "score": 1.0 if not hits else 0.0}


def faithfulness(inputs: dict, outputs: dict) -> dict:
    global _judge
    _judge = _judge or init_chat_model("google_genai:gemini-2.5-flash")
    prompt = (
        f"NOTE:\n{inputs['note']}\n\nSUMMARY:\n{outputs['clinician_answer']}\n\n"
        "Is every clinical claim in SUMMARY supported by NOTE? "
        "Reply with a single number between 0 and 1."
    )
    raw = _judge.invoke(prompt).content.strip()
    try:
        score = max(0.0, min(1.0, float(raw.split()[0])))
    except (ValueError, IndexError):
        score = 0.0
    return {"key": "faithfulness", "score": score}


if __name__ == "__main__":
    dataset_name = "noteguard-discharge-eval"
    try:
        dataset = client.create_dataset(dataset_name)
        client.create_examples(
            dataset_id=dataset.id,
            inputs=[{"note": e["note"], "question": e["question"]} for e in EXAMPLES],
        )
    except Exception:
        pass  # dataset already exists from a previous run

    client.evaluate(
        target,
        data=dataset_name,
        evaluators=[zero_phi_to_model, faithfulness],
        experiment_prefix="noteguard-slice",
    )
