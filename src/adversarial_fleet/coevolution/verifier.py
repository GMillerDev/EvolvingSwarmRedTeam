from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import Field

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities
from adversarial_fleet.search.models import SearchModel

from .config import CoevolutionFileConfig
from .evaluator import CompetitiveFakeCrossplayEvaluator
from .models import CrossplayPayoff, ParticipantRegistry


class CrossplayVerificationReport(SearchModel):
    verified: bool
    total_payoff_count: int = Field(ge=0)
    matched_payoff_count: int = Field(ge=0)
    mismatch_count: int = Field(ge=0)
    mismatches: tuple[str, ...]
    package_directory: str


class CrossplayVerifier:
    def verify(self, package_directory: Path) -> CrossplayVerificationReport:
        root = package_directory.resolve()
        config = CoevolutionFileConfig.model_validate(
            yaml.safe_load((root / "coevolution_config.yaml").read_text(encoding="utf-8"))
        )
        capabilities = ScenarioCapabilities.model_validate(
            json.loads((root / "capabilities.json").read_text(encoding="utf-8"))
        )
        participants = ParticipantRegistry.model_validate(
            json.loads((root / "participants.json").read_text(encoding="utf-8"))
        )
        records = [
            CrossplayPayoff.model_validate(json.loads(line))
            for line in (root / "payoff_matrix.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        evaluator = CompetitiveFakeCrossplayEvaluator(
            capabilities=capabilities,
            defender_bounds=config.defender,
        )
        mismatches: list[str] = []
        matched = 0
        for index, expected in enumerate(records, 1):
            scenario = participants.scenarios.get(expected.scenario_id)
            defender = participants.defenders.get(expected.defender_id)
            if scenario is None or defender is None:
                mismatches.append(f"payoff {index}: participant missing from registry")
                continue
            actual = evaluator.evaluate(
                scenario,
                defender,
                generation=expected.generation,
                scenario_role=expected.scenario_role,
                defender_role=expected.defender_role,
                realization_seeds=expected.realization_seeds,
            )
            if actual != expected:
                mismatches.append(
                    f"payoff {index}: expected {expected.replay_digest}, "
                    f"recomputed {actual.replay_digest}"
                )
                continue
            matched += 1
        return CrossplayVerificationReport(
            verified=not mismatches and matched == len(records),
            total_payoff_count=len(records),
            matched_payoff_count=matched,
            mismatch_count=len(mismatches),
            mismatches=tuple(mismatches),
            package_directory=str(root),
        )
