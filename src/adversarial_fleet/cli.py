from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from adversarial_fleet.config import load_config, load_document
from adversarial_fleet.orchestrator import ExperimentOrchestrator
from adversarial_fleet.orchestrator.rmf_adapter import RmfDemoAdapter
from adversarial_fleet.replay.verifier import ReplayVerifier
from adversarial_fleet.scenarios.genome import ScenarioGenome
from adversarial_fleet.scenarios.validation import validate_scenario


def _scenario(path: Path) -> ScenarioGenome:
    return ScenarioGenome.model_validate(load_document(path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aft")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("health-check", "validate-scenario", "run-scenario"):
        command = subparsers.add_parser(name)
        if name != "validate-scenario":
            command.add_argument("--config", type=Path, required=True)
        if name != "health-check":
            command.add_argument("--scenario", type=Path, required=True)
    replay = subparsers.add_parser("replay")
    replay.add_argument("--package", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-scenario":
            result = validate_scenario(_scenario(args.scenario))
            print(json.dumps({"valid": result.valid, "errors": result.errors}, indent=2))
            return 0 if result.valid else 2
        if args.command == "replay":
            report = ReplayVerifier().verify(args.package)
            print(json.dumps(report, indent=2, default=str))
            return 0 if report["verified"] else 1
        config = load_config(args.config)
        if args.command == "health-check":
            output_dir = config.project.output_dir.resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            checks = RmfDemoAdapter(config, output_dir).health_check()
            print(json.dumps(checks, indent=2, default=str))
            return 0 if checks["healthy"] else 2
        result = ExperimentOrchestrator(config).run(_scenario(args.scenario))
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "run_dir": str(result.run_dir),
                    "status": result.status,
                    "fitness": result.fitness,
                    "failure": result.failure.model_dump(mode="json"),
                },
                indent=2,
            )
        )
        return 0 if result.status in {"completed", "failure"} else 1
    except (OSError, ValueError, RuntimeError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
