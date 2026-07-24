from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Any

from pydantic import Field

from .config import MapElitesConfig
from .evaluation import AggregateEvaluation, FailureMechanism
from .models import SearchModel
from .pareto import is_feasible


class AffectedRobotBucket(str, Enum):
    ZERO = "0"
    ONE = "1"
    TWO_PLUS = "2+"
    UNKNOWN = "unknown"


class OnsetBucket(str, Enum):
    NONE = "none"
    EARLY = "early"
    MIDDLE = "middle"
    LATE = "late"
    UNKNOWN = "unknown"


class IncompleteTaskBucket(str, Enum):
    ZERO = "0"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ArchiveInsertionReason(str, Enum):
    INSERTED_EMPTY = "inserted_empty"
    REPLACED_LOWER_QUALITY = "replaced_lower_quality"
    REJECTED_LOWER_QUALITY = "rejected_lower_quality"
    INELIGIBLE = "ineligible"
    UNKNOWN_TELEMETRY = "unknown_telemetry"
    DUPLICATE_PHENOTYPE = "duplicate_phenotype"


class MapElitesNiche(SearchModel):
    failure_mechanism: FailureMechanism
    affected_robot_count: AffectedRobotBucket
    onset: OnsetBucket
    incomplete_tasks: IncompleteTaskBucket

    @property
    def key(self) -> str:
        return "|".join(
            (
                self.failure_mechanism.value,
                self.affected_robot_count.value,
                self.onset.value,
                self.incomplete_tasks.value,
            )
        )

    @property
    def has_unknown_telemetry(self) -> bool:
        return (
            self.affected_robot_count == AffectedRobotBucket.UNKNOWN
            or self.onset == OnsetBucket.UNKNOWN
            or self.incomplete_tasks == IncompleteTaskBucket.UNKNOWN
        )


class ArchiveDecision(SearchModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    niche: MapElitesNiche | None
    inserted: bool
    reason: ArchiveInsertionReason
    replaced_candidate_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class MapElitesCell(SearchModel):
    niche: MapElitesNiche
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    robust_severity: float = Field(ge=0, le=10)
    reproducibility: float = Field(ge=0, le=1)
    complexity: float = Field(ge=0, le=1)
    replay_reference_count: int = Field(ge=0)


class MapElitesArchiveReport(SearchModel):
    occupied_cell_count: int = Field(ge=0)
    standard_cell_count: int = Field(ge=0)
    total_standard_cells: int = Field(ge=1)
    coverage_ratio: float = Field(ge=0, le=1)
    quality_diversity_score: float = Field(ge=0)
    coverage_by_mechanism: dict[str, int]
    unknown_telemetry_cell_count: int = Field(ge=0)
    insertion_count: int = Field(ge=0)
    replacement_count: int = Field(ge=0)
    cells: tuple[MapElitesCell, ...]


def map_elites_niche(
    evaluation: AggregateEvaluation,
    *,
    robot_count: int,
    config: MapElitesConfig,
) -> MapElitesNiche:
    descriptor = evaluation.descriptor
    fraction = descriptor.affected_robot_fraction
    if fraction is None or robot_count <= 0:
        affected = AffectedRobotBucket.UNKNOWN
    else:
        affected_count = round(fraction * robot_count)
        if affected_count <= 0:
            affected = AffectedRobotBucket.ZERO
        elif affected_count == 1:
            affected = AffectedRobotBucket.ONE
        else:
            affected = AffectedRobotBucket.TWO_PLUS

    onset_ratio = descriptor.failure_onset_ratio
    if descriptor.failure_mechanism == FailureMechanism.NONE:
        onset = OnsetBucket.NONE
    elif onset_ratio is None:
        onset = OnsetBucket.UNKNOWN
    elif onset_ratio < config.early_onset_upper:
        onset = OnsetBucket.EARLY
    elif onset_ratio < config.middle_onset_upper:
        onset = OnsetBucket.MIDDLE
    else:
        onset = OnsetBucket.LATE

    incomplete_ratio = descriptor.incomplete_task_ratio
    if incomplete_ratio is None:
        incomplete = IncompleteTaskBucket.UNKNOWN
    elif incomplete_ratio == 0:
        incomplete = IncompleteTaskBucket.ZERO
    elif incomplete_ratio <= config.low_loss_upper:
        incomplete = IncompleteTaskBucket.LOW
    elif incomplete_ratio <= config.medium_loss_upper:
        incomplete = IncompleteTaskBucket.MEDIUM
    else:
        incomplete = IncompleteTaskBucket.HIGH
    return MapElitesNiche(
        failure_mechanism=descriptor.failure_mechanism,
        affected_robot_count=affected,
        onset=onset,
        incomplete_tasks=incomplete,
    )


def _quality(evaluation: AggregateEvaluation) -> tuple[float, float, float]:
    return (
        evaluation.robust_severity,
        evaluation.reproducibility.score,
        -evaluation.complexity,
    )


class MapElitesArchive:
    def __init__(
        self,
        *,
        robot_count: int,
        config: MapElitesConfig,
    ) -> None:
        if robot_count < 1:
            raise ValueError("robot_count must be positive")
        self.robot_count = robot_count
        self.config = config
        self.elites: dict[str, AggregateEvaluation] = {}
        self.niches: dict[str, MapElitesNiche] = {}
        self.seen_phenotype_hashes: set[str] = set()
        self.decisions: list[ArchiveDecision] = []

    def consider(self, evaluation: AggregateEvaluation) -> ArchiveDecision:
        if not evaluation.archive_eligible or not is_feasible(evaluation):
            return self._record(
                ArchiveDecision(
                    candidate_id=evaluation.candidate_id,
                    niche=None,
                    inserted=False,
                    reason=ArchiveInsertionReason.INELIGIBLE,
                )
            )
        niche = map_elites_niche(
            evaluation,
            robot_count=self.robot_count,
            config=self.config,
        )
        if niche.has_unknown_telemetry and not self.config.include_unknown_telemetry_niches:
            return self._record(
                ArchiveDecision(
                    candidate_id=evaluation.candidate_id,
                    niche=niche,
                    inserted=False,
                    reason=ArchiveInsertionReason.UNKNOWN_TELEMETRY,
                )
            )
        phenotype_hashes = {run.phenotype_hash for run in evaluation.runs}
        if phenotype_hashes & self.seen_phenotype_hashes:
            return self._record(
                ArchiveDecision(
                    candidate_id=evaluation.candidate_id,
                    niche=niche,
                    inserted=False,
                    reason=ArchiveInsertionReason.DUPLICATE_PHENOTYPE,
                )
            )
        self.seen_phenotype_hashes.update(phenotype_hashes)

        incumbent = self.elites.get(niche.key)
        should_insert = incumbent is None or _quality(evaluation) > _quality(incumbent)
        if (
            incumbent is not None
            and _quality(evaluation) == _quality(incumbent)
            and evaluation.candidate_id < incumbent.candidate_id
        ):
            should_insert = True
        if not should_insert:
            return self._record(
                ArchiveDecision(
                    candidate_id=evaluation.candidate_id,
                    niche=niche,
                    inserted=False,
                    reason=ArchiveInsertionReason.REJECTED_LOWER_QUALITY,
                )
            )

        reason = (
            ArchiveInsertionReason.INSERTED_EMPTY
            if incumbent is None
            else ArchiveInsertionReason.REPLACED_LOWER_QUALITY
        )
        annotated = evaluation.model_copy(
            update={
                "archive_niche": niche.key,
                "archive_inserted": True,
            }
        )
        self.elites[niche.key] = annotated
        self.niches[niche.key] = niche
        return self._record(
            ArchiveDecision(
                candidate_id=evaluation.candidate_id,
                niche=niche,
                inserted=True,
                reason=reason,
                replaced_candidate_id=None if incumbent is None else incumbent.candidate_id,
            )
        )

    def _record(self, decision: ArchiveDecision) -> ArchiveDecision:
        self.decisions.append(decision)
        return decision

    def report(self) -> MapElitesArchiveReport:
        cells = tuple(
            MapElitesCell(
                niche=self.niches[key],
                candidate_id=evaluation.candidate_id,
                robust_severity=evaluation.robust_severity,
                reproducibility=evaluation.reproducibility.score,
                complexity=evaluation.complexity,
                replay_reference_count=sum(run.run_path is not None for run in evaluation.runs),
            )
            for key, evaluation in sorted(self.elites.items())
        )
        unknown_count = sum(cell.niche.has_unknown_telemetry for cell in cells)
        standard_count = len(cells) - unknown_count
        failure_mechanism_count = len(FailureMechanism) - 1
        total_standard_cells = failure_mechanism_count * 3 * 4 * 4
        mechanism_coverage = Counter(cell.niche.failure_mechanism.value for cell in cells)
        return MapElitesArchiveReport(
            occupied_cell_count=len(cells),
            standard_cell_count=standard_count,
            total_standard_cells=total_standard_cells,
            coverage_ratio=standard_count / total_standard_cells,
            quality_diversity_score=sum(cell.robust_severity for cell in cells),
            coverage_by_mechanism=dict(sorted(mechanism_coverage.items())),
            unknown_telemetry_cell_count=unknown_count,
            insertion_count=sum(item.inserted for item in self.decisions),
            replacement_count=sum(
                item.reason == ArchiveInsertionReason.REPLACED_LOWER_QUALITY
                for item in self.decisions
            ),
            cells=cells,
        )

    def state_dict(self) -> dict[str, Any]:
        return {
            "robot_count": self.robot_count,
            "config": self.config.model_dump(mode="json"),
            "elites": [
                {
                    "niche": self.niches[key].model_dump(mode="json"),
                    "evaluation": evaluation.model_dump(mode="json"),
                }
                for key, evaluation in sorted(self.elites.items())
            ],
            "seen_phenotype_hashes": sorted(self.seen_phenotype_hashes),
            "decisions": [item.model_dump(mode="json") for item in self.decisions],
        }

    @classmethod
    def from_state_dict(cls, state: dict[str, Any]) -> "MapElitesArchive":
        archive = cls(
            robot_count=int(state["robot_count"]),
            config=MapElitesConfig.model_validate(state["config"]),
        )
        for item in state.get("elites", []):
            niche = MapElitesNiche.model_validate(item["niche"])
            evaluation = AggregateEvaluation.model_validate(item["evaluation"])
            if niche.key in archive.elites:
                raise ValueError(f"checkpoint contains duplicate niche {niche.key}")
            if evaluation.archive_niche != niche.key or not evaluation.archive_inserted:
                raise ValueError("checkpoint elite annotation does not match its niche")
            archive.niches[niche.key] = niche
            archive.elites[niche.key] = evaluation
        archive.seen_phenotype_hashes = set(state.get("seen_phenotype_hashes", []))
        elite_hashes = {
            run.phenotype_hash for evaluation in archive.elites.values() for run in evaluation.runs
        }
        if not elite_hashes <= archive.seen_phenotype_hashes:
            raise ValueError("checkpoint is missing phenotype hashes for retained elites")
        archive.decisions = [
            ArchiveDecision.model_validate(item) for item in state.get("decisions", [])
        ]
        return archive
