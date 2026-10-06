#!/usr/bin/env python3
"""Score the Platform Knowledge Agent against the approved evaluation dataset.

Runs every case in `evals/datasets/*.yaml` through the real agent and reports a
grounding / refusal scorecard. Deterministic evaluators always run and cost
nothing beyond the agent calls; `--judge` adds the Strands LLM-as-judge
faithfulness and refusal evaluators, which make extra model calls.

    python -m scripts.evaluate --datasets /path/to/approved/datasets
    python -m scripts.evaluate --datasets /path/to/approved/datasets --judge
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from strands_evals import Case, Experiment, TracedHandler, eval_task
from strands_evals.evaluators import Evaluator
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import is_refusal, public_answer  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import build_application, configure_logging  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _meta(case: EvaluationData[str, str], key: str, default: Any) -> Any:
    return (case.metadata or {}).get(key, default)


class RefusalDiscipline(Evaluator[str, str]):
    """The agent must refuse exactly when the dataset says it should."""

    def evaluate(self, evaluation_case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        answer = (evaluation_case.actual_output or "").strip()
        refused = is_refusal(answer)
        expected = bool(_meta(evaluation_case, "expect_refusal", False))
        passed = refused == expected
        return [
            EvaluationOutput(
                score=1.0 if passed else 0.0,
                test_pass=passed,
                label="refused" if refused else "answered",
                reason=(
                    "Refusal behaviour matched the dataset."
                    if passed
                    else f"Expected {'a refusal' if expected else 'an answer'}, got the opposite."
                ),
            )
        ]


class ForbiddenClaims(Evaluator[str, str]):
    """The agent must never assert live infrastructure state or ownership."""

    def evaluate(self, evaluation_case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        answer = (evaluation_case.actual_output or "").casefold()
        forbidden = [str(p) for p in _meta(evaluation_case, "forbidden_keywords", [])]
        leaked = [phrase for phrase in forbidden if phrase.casefold() in answer]
        return [
            EvaluationOutput(
                score=0.0 if leaked else 1.0,
                test_pass=not leaked,
                label=f"{len(leaked)} leaked" if leaked else "clean",
                reason=(
                    f"Answer contained forbidden claim(s): {', '.join(leaked)}"
                    if leaked
                    else "No forbidden claims present."
                ),
            )
        ]


class ExpectedCoverage(Evaluator[str, str]):
    """A supported answer should mention the terms the dataset expects."""

    def evaluate(self, evaluation_case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        expected = [str(k) for k in _meta(evaluation_case, "expected_keywords", [])]
        if not expected:
            return [
                EvaluationOutput(
                    score=1.0,
                    test_pass=True,
                    label="n/a",
                    reason="No expected keywords for this case.",
                )
            ]
        answer = (evaluation_case.actual_output or "").casefold()
        hits = [term for term in expected if term.casefold() in answer]
        score = len(hits) / len(expected)
        return [
            EvaluationOutput(
                score=score,
                test_pass=score >= 0.5,
                label=f"{len(hits)}/{len(expected)}",
                reason=f"Matched {len(hits)} of {len(expected)} expected terms.",
            )
        ]


class NoInternalLeakage(Evaluator[str, str]):
    """Public answers must not expose grounding identifiers or backend wording."""

    BANNED = (
        "[s1]",
        "[s2]",
        "[s3]",
        "retrieval",
        "the passages",
        "the registry lists",
        "the registry shows",
        "the documentation says",
        "based on the information provided",
        "indexed",
    )

    def evaluate(self, evaluation_case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        answer = (evaluation_case.actual_output or "").casefold()
        leaked = [term for term in self.BANNED if term in answer]
        return [
            EvaluationOutput(
                score=0.0 if leaked else 1.0,
                test_pass=not leaked,
                label=f"{len(leaked)} leaked" if leaked else "clean",
                reason=(
                    f"Leaked internal wording: {', '.join(leaked)}" if leaked else "No leakage."
                ),
            )
        ]


def load_cases(directory: Path) -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for path in sorted(directory.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in document.get("cases", ()):
            cases.append(
                Case[str, str](
                    name=str(raw["id"]),
                    input=str(raw["question"]),
                    metadata={
                        "category": raw.get("category", "uncategorised"),
                        "expect_refusal": bool(raw.get("expect_refusal", False)),
                        "expected_keywords": raw.get("expected_keywords", []),
                        "forbidden_keywords": raw.get("forbidden_keywords", []),
                        "dataset": path.stem,
                    },
                )
            )
    if not cases:
        raise ValueError(f"No evaluation cases found in {directory}")
    return cases


def collect_rows(report: Any) -> list[dict[str, Any]]:
    """Flatten the report into one row per case-evaluation.

    `to_dict()` returns the case detail and the outcomes in separate parallel
    lists: `cases` carries name, evaluator and metadata, while `scores`,
    `test_passes` and `reasons` are index-aligned alongside it.
    """
    document = report.to_dict()
    cases = list(document.get("cases", []))
    scores = list(document.get("scores", []))
    passes = list(document.get("test_passes", []))
    reasons = list(document.get("reasons", []))
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        rows.append(
            {
                "name": case.get("name"),
                "evaluator": case.get("evaluator", "unknown"),
                "metadata": case.get("metadata") or {},
                "score": float(scores[index]) if index < len(scores) else 0.0,
                "test_pass": bool(passes[index]) if index < len(passes) else False,
                "reason": str(reasons[index]) if index < len(reasons) else "",
            }
        )
    return rows


def render_report(report: Any, *, judged: bool) -> str:
    rows = collect_rows(report)
    by_evaluator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_evaluator[str(row.get("evaluator", "unknown"))].append(row)
        by_category[str((row.get("metadata") or {}).get("category", "uncategorised"))].append(row)

    def summarise(group: list[dict[str, Any]]) -> tuple[float, float]:
        if not group:
            return 0.0, 0.0
        passed = sum(1 for r in group if r.get("test_pass"))
        scored = [float(r.get("score", 0.0)) for r in group]
        return passed / len(group) * 100, sum(scored) / len(scored)

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Platform Knowledge Agent — evaluation scorecard",
        "",
        f"Generated {generated} · {len(rows)} case-evaluations"
        + (" · LLM judges enabled" if judged else " · deterministic evaluators only"),
        "",
        "## By evaluator",
        "",
        "| Evaluator | Pass rate | Mean score | Cases |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, group in sorted(by_evaluator.items()):
        rate, mean = summarise(group)
        lines.append(f"| {name} | {rate:.0f}% | {mean:.2f} | {len(group)} |")

    lines += [
        "",
        "## By question category",
        "",
        "| Category | Pass rate | Mean score | Cases |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, group in sorted(by_category.items()):
        rate, mean = summarise(group)
        lines.append(f"| {name} | {rate:.0f}% | {mean:.2f} | {len(group)} |")

    overall_rate, overall_mean = summarise(rows)
    lines += [
        "",
        "## Overall",
        "",
        f"- Pass rate: **{overall_rate:.0f}%**",
        f"- Mean score: **{overall_mean:.2f}**",
        "",
        "## Failures",
        "",
    ]
    failures = [r for r in rows if not r.get("test_pass")]
    if not failures:
        lines.append("None.")
    else:
        lines += ["| Case | Evaluator | Score | Reason |", "| --- | --- | ---: | --- |"]
        for row in failures:
            reason = str(row.get("reason", "")).replace("|", "/").replace("\n", " ")[:160]
            score = float(row.get("score", 0.0))
            lines.append(f"| {row.get('name')} | {row.get('evaluator')} | {score:.2f} | {reason} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "evals/reports/platform_knowledge.md",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="add LLM-as-judge faithfulness and refusal evaluators",
    )
    arguments = parser.parse_args()

    configure_logging()
    settings = get_settings()
    application = build_application(settings)

    @eval_task(TracedHandler())
    def run_case(case: Case[str, str]) -> str:
        try:
            result = application.agent.answer(str(case.input))
        except Exception as exc:
            print(f"  case {case.name} raised {type(exc).__name__}: {exc}", flush=True)
            raise
        return public_answer(result.answer)

    evaluators: list[Evaluator[str, str]] = [
        RefusalDiscipline(name="refusal-discipline"),
        ForbiddenClaims(name="forbidden-claims"),
        ExpectedCoverage(name="expected-coverage"),
        NoInternalLeakage(name="no-internal-leakage"),
    ]
    if arguments.judge:
        from strands.models import BedrockModel
        from strands_evals.evaluators import FaithfulnessEvaluator, RefusalEvaluator

        judge = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
        )
        evaluators += [
            FaithfulnessEvaluator(model=judge, name="faithfulness"),
            RefusalEvaluator(model=judge, name="refusal-judge"),
        ]

    cases = load_cases(arguments.datasets)
    print(f"Running {len(cases)} cases through the agent...", flush=True)
    report = Experiment[str, str](cases=cases, evaluators=evaluators).run_evaluations(run_case)

    markdown = render_report(report, judged=arguments.judge)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Report written to {arguments.output}")


if __name__ == "__main__":
    main()
