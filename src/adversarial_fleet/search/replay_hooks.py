from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from .archives import MapElitesArchive
from .models import SearchModel


class ReplayVerificationAdapter(Protocol):
    def verify(self, package_dir: Path) -> dict[str, Any]: ...


class EliteReplayResult(SearchModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    niche: str
    package_path: str | None
    status: str
    verification: dict[str, Any] | None = None
    error: str | None = None


class EliteReplayVerificationReport(SearchModel):
    total_elites: int = Field(ge=0)
    references_checked: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    missing_reference_count: int = Field(ge=0)
    results: tuple[EliteReplayResult, ...]


def verify_elite_replays(
    archive: MapElitesArchive,
    *,
    verifier: ReplayVerificationAdapter,
    verify_all_realizations: bool = False,
) -> EliteReplayVerificationReport:
    results: list[EliteReplayResult] = []
    for niche, elite in sorted(archive.elites.items()):
        references = tuple(
            dict.fromkeys(run.run_path for run in elite.runs if run.run_path is not None)
        )
        if not references:
            results.append(
                EliteReplayResult(
                    candidate_id=elite.candidate_id,
                    niche=niche,
                    package_path=None,
                    status="missing_reference",
                )
            )
            continue
        selected = references if verify_all_realizations else references[:1]
        for reference in selected:
            package_path = Path(reference).resolve()
            if not package_path.is_dir():
                results.append(
                    EliteReplayResult(
                        candidate_id=elite.candidate_id,
                        niche=niche,
                        package_path=str(package_path),
                        status="missing_reference",
                    )
                )
                continue
            try:
                verification = verifier.verify(package_path)
                status = "verified" if bool(verification.get("verified")) else "failed"
                results.append(
                    EliteReplayResult(
                        candidate_id=elite.candidate_id,
                        niche=niche,
                        package_path=str(package_path),
                        status=status,
                        verification=verification,
                    )
                )
            except Exception as error:  # verifier is an external integration boundary
                results.append(
                    EliteReplayResult(
                        candidate_id=elite.candidate_id,
                        niche=niche,
                        package_path=str(package_path),
                        status="error",
                        error=f"{type(error).__name__}: {error}",
                    )
                )
    return EliteReplayVerificationReport(
        total_elites=len(archive.elites),
        references_checked=sum(item.package_path is not None for item in results),
        verified_count=sum(item.status == "verified" for item in results),
        failed_count=sum(item.status in {"failed", "error"} for item in results),
        missing_reference_count=sum(item.status == "missing_reference" for item in results),
        results=tuple(results),
    )
