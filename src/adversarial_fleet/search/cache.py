from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any

from pydantic import Field

from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities

from .encoding import decode_genome
from .evaluation import CandidateEvaluation
from .evaluator import CandidateEvaluator
from .models import AdversarialGenome, SearchModel


class EvaluationCacheContext(SearchModel):
    environment_image_digest: str = Field(min_length=1)
    metric_configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_detector_configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    defender_id: str = Field(min_length=1)


class EvaluationCacheKey(SearchModel):
    phenotype_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    realization_seed: int = Field(ge=0, le=2**32 - 1)
    environment_image_digest: str = Field(min_length=1)
    metric_configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_detector_configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    defender_id: str = Field(min_length=1)

    def digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def configuration_hash(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def runtime_environment_digest() -> str:
    """Fingerprint the pinned simulator plus the installed AFT implementation."""

    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    digest.update(os.environ.get("AFT_RMF_IMAGE", "unversioned-local-environment").encode("utf-8"))
    digest.update(platform.python_version().encode("utf-8"))
    for path in sorted(package_root.rglob("*.py")):
        digest.update(path.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


class EvaluationCache:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: EvaluationCacheKey) -> CandidateEvaluation | None:
        path = self.root / f"{key.digest()}.json"
        if not path.is_file():
            return None
        evaluation = CandidateEvaluation.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        if not evaluation.state.is_valid_run:
            return None
        if evaluation.run_path is not None and not Path(evaluation.run_path).is_dir():
            return None
        return evaluation

    def put(self, key: EvaluationCacheKey, evaluation: CandidateEvaluation) -> None:
        if not evaluation.state.is_valid_run:
            return
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f"{key.digest()}-",
            suffix=".tmp",
            dir=self.root,
            text=True,
        )
        target = self.root / f"{key.digest()}.json"
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    evaluation.model_dump(mode="json"),
                    stream,
                    indent=2,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)


class CachingEvaluator:
    def __init__(
        self,
        evaluator: CandidateEvaluator,
        *,
        cache: EvaluationCache,
        context: EvaluationCacheContext,
        capabilities: ScenarioCapabilities,
    ) -> None:
        self.evaluator = evaluator
        self.cache = cache
        self.context = context
        self.capabilities = capabilities
        self.cache_hit_count = 0

    def _key(
        self,
        genome: AdversarialGenome,
        *,
        realization_seed: int,
    ) -> EvaluationCacheKey:
        phenotype = decode_genome(
            genome,
            capabilities=self.capabilities,
            realization_seed=realization_seed,
        )
        return EvaluationCacheKey(
            phenotype_hash=phenotype.phenotype_hash,
            realization_seed=realization_seed,
            **self.context.model_dump(),
        )

    def evaluate(
        self,
        genome: AdversarialGenome,
        *,
        realization_seed: int,
        candidate_id: str,
    ) -> CandidateEvaluation:
        try:
            key = self._key(genome, realization_seed=realization_seed)
        except (ValueError, TypeError):
            return self.evaluator.evaluate(
                genome,
                realization_seed=realization_seed,
                candidate_id=candidate_id,
            )
        cached = self.cache.get(key)
        if cached is not None and cached.candidate_id == candidate_id:
            self.cache_hit_count += 1
            return cached
        evaluation = self.evaluator.evaluate(
            genome,
            realization_seed=realization_seed,
            candidate_id=candidate_id,
        )
        self.cache.put(key, evaluation)
        return evaluation
