"""
Reviewer Agent — Scores and selects the best candidate.

Evaluates each code candidate on:
  - Correctness (does it address the subtask?)
  - Code quality (readability, patterns, naming)
  - Safety (no obvious bugs, injection, etc.)
  - Completeness (handles edge cases mentioned in subtask)

Phase 0: Uses a single LLM call to score all candidates.
Future: Could use structured rubrics, AST analysis, etc.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from . import _gateway_auth

logger = logging.getLogger(__name__)


@dataclass
class ReviewScore:
    candidate_idx: int
    correctness: float  # 0-10
    quality: float  # 0-10
    safety: float  # 0-10
    completeness: float  # 0-10
    overall: float  # 0-10
    feedback: str


@dataclass
class ReviewResult:
    subtask_id: str
    scores: list[ReviewScore]
    selected_idx: int
    selected_score: float
    feedback_summary: str


REVIEWER_SYSTEM_PROMPT = """\
You are a code reviewer. Given a subtask description and one or more candidate \
implementations, score each on these dimensions (0-10):

1. correctness: Does it correctly implement the subtask?
2. quality: Is the code clean, readable, well-structured?
3. safety: Are there security issues, bugs, or bad practices?
4. completeness: Does it handle edge cases and requirements?
5. overall: Weighted average (correctness 40%, quality 20%, safety 20%, completeness 20%)

Respond in this exact JSON format:
{
  "scores": [
    {
      "candidate_idx": 0,
      "correctness": 8.0,
      "quality": 7.5,
      "safety": 9.0,
      "completeness": 7.0,
      "overall": 7.9,
      "feedback": "brief explanation"
    }
  ],
  "selected_idx": 0,
  "feedback_summary": "why this candidate was selected"
}
"""


class Reviewer:
    def __init__(self, gateway_url: str, accept_threshold: float = 7.0) -> None:
        self._gateway_url = gateway_url
        self._accept_threshold = accept_threshold

    async def review(
        self,
        *,
        subtask_id: str,
        subtask_description: str,
        candidates: list[str],
        context: str = "",
    ) -> ReviewResult:
        """Score candidates and select the best one."""
        # Build the review prompt
        parts = [f"## Subtask\n{subtask_description}\n"]
        for i, candidate in enumerate(candidates):
            parts.append(f"## Candidate {i}\n```\n{candidate}\n```\n")

        prompt = "\n".join(parts)
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "system", "content": REVIEWER_SYSTEM_PROMPT})
        messages.append({"role": "user", "content": prompt})

        client = await _gateway_auth.gateway_client()
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "conductor",
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.3,  # Low temp for consistent scoring
            },
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return self._parse_review(subtask_id, content, len(candidates))

    def _parse_review(
        self, subtask_id: str, raw: str, n_candidates: int
    ) -> ReviewResult:
        """Parse LLM review output into structured scores."""
        try:
            cleaned = raw.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]

            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            logger.warning("Failed to parse reviewer output, failing closed")
            # Fail closed: parsing failure should not quietly approve a candidate.
            scores = [  # type: ignore[assignment]
                ReviewScore(
                    candidate_idx=i,
                    correctness=0.0,
                    quality=0.0,
                    safety=0.0,
                    completeness=0.0,
                    overall=0.0,
                    feedback="(unparseable review)",
                )
                for i in range(n_candidates)
            ]
            return ReviewResult(
                subtask_id=subtask_id,
                scores=scores,  # type: ignore[arg-type]
                selected_idx=0,
                selected_score=0.0,
                feedback_summary="Review parse failed — no candidate trusted",
            )

        scores: list[ReviewScore] = []  # type: ignore[no-redef]
        for s in parsed.get("scores", []):
            correctness = self._normalize_score(s.get("correctness", 5.0))
            quality = self._normalize_score(s.get("quality", 5.0))
            safety = self._normalize_score(s.get("safety", 5.0))
            completeness = self._normalize_score(s.get("completeness", 5.0))
            overall = s.get("overall")
            if overall is None:
                overall = (
                    correctness * 0.4
                    + quality * 0.2
                    + safety * 0.2
                    + completeness * 0.2
                )
            overall = self._normalize_score(overall)
            scores.append(  # type: ignore[attr-defined]
                ReviewScore(
                    candidate_idx=s.get("candidate_idx", 0),
                    correctness=correctness,
                    quality=quality,
                    safety=safety,
                    completeness=completeness,
                    overall=overall,
                    feedback=s.get("feedback", ""),
                )
            )

        selected_idx = parsed.get("selected_idx", 0)
        selected_score = 0.0
        if scores:
            if not isinstance(selected_idx, int) or not (0 <= selected_idx < len(scores)):
                best = max(scores, key=lambda score: score.overall)
                selected_idx = best.candidate_idx
                selected_score = best.overall
            else:
                selected_score = scores[selected_idx].overall

        return ReviewResult(
            subtask_id=subtask_id,
            scores=scores,  # type: ignore[arg-type]
            selected_idx=selected_idx,
            selected_score=selected_score,
            feedback_summary=parsed.get("feedback_summary", ""),
        )

    @staticmethod
    def _normalize_score(value: object) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 5.0
        return max(0.0, min(10.0, score))

    @property
    def accept_threshold(self) -> float:
        return self._accept_threshold

    async def close(self) -> None:
        pass  # Shared client closed by conductor
