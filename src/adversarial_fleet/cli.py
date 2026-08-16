from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from adversarial_fleet.benchmarks.config import load_benchmark_config
from adversarial_fleet.benchmarks.runner import BenchmarkRunner
from adversarial_fleet.coevolution.config import load_coevolution_config
from adversarial_fleet.coevolution.runner import CoevolutionRunner
from adversarial_fleet.coevolution.verifier import CrossplayVerifier
from adversarial_fleet.config import load_config, load_document
from adversarial_fleet.orchestrator import ExperimentOrchestrator
from adversarial_fleet.orchestrator.rmf_adapter import RmfDemoAdapter
from adversarial_fleet.replay.verifier import ReplayVerifier
from adversarial_fleet.scenarios.capabilities import ScenarioCapabilities, load_capabilities
from adversarial_fleet.scenarios.genome import ScenarioGenome
from adversarial_fleet.scenarios.validation import validate_scenario
from adversarial_fleet.search.config import load_search_config
from adversarial_fleet.search.runner import SearchRunner


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
            command.add_argument("--capabilities", type=Path)
    replay = subparsers.add_parser("replay")
    replay.add_argument("--package", type=Path, required=True)
    search = subparsers.add_parser("search")
    search_source = search.add_mutually_exclusive_group(required=True)
    search_source.add_argument("--search-config", type=Path)
    search_source.add_argument("--resume", type=Path)
    search.add_argument("--config", type=Path)
    search.add_argument("--capabilities", type=Path)
    inspect_archive = subparsers.add_parser("inspect-archive")
    inspect_archive.add_argument("--search", type=Path, required=True)
    inspect_archive.add_argument("--format", choices=("json", "markdown"), default="json")
    benchmark = subparsers.add_parser("benchmark")
    benchmark.add_argument("--benchmark-config", type=Path, required=True)
    benchmark.add_argument("--config", type=Path, required=True)
    benchmark.add_argument("--output", type=Path)
    benchmark.add_argument("--capabilities", type=Path)
    coevolve = subparsers.add_parser("coevolve")
    coevolve.add_argument("--coevolution-config", type=Path, required=True)
    coevolve.add_argument("--config", type=Path, required=True)
    coevolve.add_argument("--output", type=Path)
    coevolve.add_argument("--capabilities", type=Path)
    verify_crossplay = subparsers.add_parser("verify-crossplay")
    verify_crossplay.add_argument("--package", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-scenario":
            capabilities = (
                load_capabilities(args.capabilities)
                if args.capabilities is not None
                else ScenarioCapabilities()
            )
            result = validate_scenario(_scenario(args.scenario), capabilities)
            print(json.dumps({"valid": result.valid, "errors": result.errors}, indent=2))
            return 0 if result.valid else 2
        if args.command == "replay":
            report = ReplayVerifier().verify(args.package)
            print(json.dumps(report, indent=2, default=str))
            return 0 if report["verified"] else 1
        if args.command == "inspect-archive":
            archive = json.loads(
                (args.search.resolve() / "archive.json").read_text(encoding="utf-8")
            )
            if args.format == "json":
                print(json.dumps(archive, indent=2, default=str))
            else:
                posthoc = archive["posthoc"]
                print("# Search archive")
                print()
                print(f"- Occupied cells: {posthoc['occupied_cell_count']}")
                print(f"- Coverage ratio: {posthoc['coverage_ratio']:.6f}")
                print(f"- Quality-diversity score: {posthoc['quality_diversity_score']:.6f}")
                print("- Failure mechanisms:")
                for mechanism, count in posthoc["coverage_by_mechanism"].items():
                    print(f"  - {mechanism}: {count}")
            return 0
        if args.command == "search":
            if args.resume is not None:
                runner = SearchRunner.resume(args.resume)
                report = runner.run(resume=True)
            else:
                if args.config is None:
                    raise ValueError("--config is required with --search-config")
                runner = SearchRunner(
                    app_config=load_config(args.config),
                    search_config=load_search_config(args.search_config),
                    capabilities=(
                        load_capabilities(args.capabilities)
                        if args.capabilities is not None
                        else None
                    ),
                )
                report = runner.run()
            print(json.dumps(report.model_dump(mode="json"), indent=2))
            return 0 if report.status == "completed" else 1
        if args.command == "benchmark":
            report = BenchmarkRunner(
                app_config=load_config(args.config),
                benchmark_config=load_benchmark_config(args.benchmark_config),
                capabilities=(
                    load_capabilities(args.capabilities) if args.capabilities is not None else None
                ),
                benchmark_directory=args.output,
            ).run()
            print(json.dumps(report.model_dump(mode="json"), indent=2))
            return 0 if report.status == "completed" else 1
        if args.command == "coevolve":
            report = CoevolutionRunner(
                app_config=load_config(args.config),
                coevolution_config=load_coevolution_config(args.coevolution_config),
                capabilities=(
                    load_capabilities(args.capabilities) if args.capabilities is not None else None
                ),
                experiment_directory=args.output,
            ).run()
            print(json.dumps(report.model_dump(mode="json"), indent=2))
            return 0 if report.status == "completed" else 1
        if args.command == "verify-crossplay":
            report = CrossplayVerifier().verify(args.package)
            print(json.dumps(report.model_dump(mode="json"), indent=2))
            return 0 if report.verified else 1
        config = load_config(args.config)
        if args.command == "health-check":
            output_dir = config.project.output_dir.resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            checks = RmfDemoAdapter(config, output_dir).health_check()
            print(json.dumps(checks, indent=2, default=str))
            return 0 if checks["healthy"] else 2
        capabilities = (
            load_capabilities(args.capabilities)
            if args.capabilities is not None
            else ScenarioCapabilities()
        )
        result = ExperimentOrchestrator(config, capabilities=capabilities).run(
            _scenario(args.scenario)
        )
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
