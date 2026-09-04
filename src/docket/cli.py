"""Argument parsing and dispatch for the `docket` console entry point."""

from __future__ import annotations

import argparse
import sys

from docket import __version__
from docket.config import DocketError, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docket", description="A lab notebook your coding agent reads."
    )
    parser.add_argument("--version", action="version", version=f"docket {__version__}")
    parser.add_argument(
        "--config",
        help="path to config.toml (default: $DOCKET_CONFIG or ~/.docket/config.toml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("capture", help="append a dated bullet to the scratch block")
    p.add_argument("text", nargs="+")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("gotcha", help="record a gotcha note in the context vault")
    p.add_argument("--symptom", required=True)
    p.add_argument("--cause", required=True)
    p.add_argument("--fix", required=True)
    p.add_argument("--scope", required=True, help="comma-separated scope tags")
    p.add_argument("--project", required=True, help="project anchor name")
    p.add_argument("--note", help="free-text context appended as a body section")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser(
        "recall", help="search the context vault, and the personal vault read-only"
    )
    p.add_argument("query", nargs="?", help="words that must all appear")
    p.add_argument("--full", metavar="ID", help="print one whole context record")

    p = sub.add_parser("idea", help="idea notes")
    idea_sub = p.add_subparsers(dest="idea_command", required=True)
    q = idea_sub.add_parser("import", help="one idea note per git branch")
    q.add_argument(
        "--repo", required=True, help="directory name under the projects root"
    )
    q.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("dash", help="regenerate the focus block in Dashboard.md")
    p.add_argument("--md", action="store_true", help="write into Dashboard.md")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("list", help="list records in the context vault")
    p.add_argument("--category")
    p.add_argument("--status")
    p.add_argument("--project")

    sub.add_parser("check", help="validate the context vault (exit 1 on problems)")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.command == "capture":
        from docket.commands.capture import run_capture

        print(run_capture(cfg, " ".join(args.text), dry_run=args.dry_run))
        return 0
    if args.command == "gotcha":
        from docket.commands.gotcha import run_gotcha

        print(
            run_gotcha(
                cfg,
                symptom=args.symptom,
                cause=args.cause,
                fix=args.fix,
                scope=args.scope,
                project=args.project,
                note=args.note,
                dry_run=args.dry_run,
            )
        )
        return 0
    if args.command == "recall":
        from docket.commands.recall import run_recall

        print(run_recall(cfg, args.query, full=args.full))
        return 0
    if args.command == "idea":
        from docket.commands.idea import run_idea_import

        print(run_idea_import(cfg, args.repo, dry_run=args.dry_run))
        return 0
    if args.command == "dash":
        from docket.commands.dash import run_dash

        print(run_dash(cfg, md=args.md, dry_run=args.dry_run))
        return 0
    if args.command == "list":
        from docket.commands.listing import run_list

        print(
            run_list(
                cfg, category=args.category, status=args.status, project=args.project
            )
        )
        return 0
    if args.command == "check":
        from docket.commands.check import run_check

        text, code = run_check(cfg)
        print(text)
        return code
    raise DocketError(f"unknown command {args.command}")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except DocketError as exc:
        print(f"docket: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
