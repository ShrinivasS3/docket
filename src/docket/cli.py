"""Argument parsing and dispatch for the `docket` console entry point."""

from __future__ import annotations

import argparse
import sys

from docket import __version__
from docket.config import DocketError, load_config


def build_parser() -> argparse.ArgumentParser:
    # Local: every command module is imported lazily, and this is the only
    # thing the parser needs from one.
    from docket.commands.idea import KIND_CHOICES

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
    p.add_argument(
        "--unattended",
        action="store_true",
        help="record attended: false — for scheduled and autonomous writers",
    )
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser(
        "recall", help="search the context vault, and the personal vault read-only"
    )
    p.add_argument("query", nargs="?", help="words that must all appear")
    p.add_argument("--full", metavar="ID", help="print one whole context record")
    p.add_argument("--all", action="store_true", help="bypass the output line cap")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--attended", action="store_true", help="only records a human wrote")
    g.add_argument(
        "--unattended",
        action="store_true",
        help="only records written by a scheduled or autonomous process",
    )

    p = sub.add_parser("idea", help="idea notes")
    idea_sub = p.add_subparsers(dest="idea_command", required=True)
    q = idea_sub.add_parser("import", help="one idea note per git branch")
    q.add_argument(
        "--repo", required=True, help="directory name under the projects root"
    )
    q.add_argument(
        "--unattended",
        action="store_true",
        help="record attended: false — for scheduled and autonomous writers",
    )
    q.add_argument("--dry-run", action="store_true")

    q = idea_sub.add_parser("new", help="file one idea against the branch it lives on")
    q.add_argument(
        "--branch", help="branch to seed from (default: the checked-out one)"
    )
    q.add_argument("--gate", help="the result that would refute this")
    q.add_argument("--decide-by", metavar="YYYY-MM-DD", help="date to decide by")
    q.add_argument("--parent", metavar="ID", help="docket_id this descends from")
    q.add_argument(
        "--inherits", metavar="G0001[,G0002]", help="finding ids this rests on"
    )
    q.add_argument(
        "--from-scratch",
        metavar="LINE",
        help="promote this line of the Dashboard.md scratch block",
    )
    q.add_argument("--kind", choices=KIND_CHOICES)
    q.add_argument(
        "--unattended",
        action="store_true",
        help="record attended: false — for scheduled and autonomous writers",
    )
    q.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("dash", help="regenerate the focus block in Dashboard.md")
    p.add_argument("--md", action="store_true", help="write into Dashboard.md")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("list", help="list records in the context vault")
    p.add_argument("--category")
    p.add_argument("--status")
    p.add_argument("--project")
    p.add_argument(
        "--stubs",
        action="store_true",
        help=(
            "only records docket check warns about: unjudged (Completed, verdict "
            "pending) or no gate (In Progress); kind: scaffold is excluded"
        ),
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--attended", action="store_true", help="only records a human wrote")
    g.add_argument(
        "--unattended",
        action="store_true",
        help="only records written by a scheduled or autonomous process",
    )

    sub.add_parser("check", help="validate the context vault (exit 1 on problems)")

    p = sub.add_parser("init", help="wire a repo into docket; --check only reports")
    p.add_argument(
        "repo",
        nargs="?",
        help="directory under the projects root (default: the current directory; "
        "with --check and no repo, every registered repo)",
    )
    p.add_argument(
        "--namespace", help='branch pattern for [branches], e.g. "experiments/*"'
    )
    p.add_argument("--project-id", help="project_id for .docket.toml and the anchor")
    p.add_argument(
        "--check",
        action="store_true",
        help="report what is missing and write nothing; exit 1 if any repo is "
        "incomplete",
    )

    p = sub.add_parser(
        "identity", help="print the Device/Attended commit trailers for this machine"
    )
    p.add_argument(
        "--unattended",
        action="store_true",
        help="record attended: false — for scheduled and autonomous writers",
    )

    p = sub.add_parser("brief", help="~200-token digest of one project, from files")
    p.add_argument("project", help="repo directory name under the projects root")
    return parser


def _attended(args: argparse.Namespace) -> bool | None:
    """The --attended/--unattended filter as a tri-state; None means no filter."""
    if getattr(args, "attended", False):
        return True
    return False if getattr(args, "unattended", False) else None


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
                unattended=args.unattended,
                dry_run=args.dry_run,
            )
        )
        return 0
    if args.command == "recall":
        from docket.commands.recall import run_recall

        print(
            run_recall(
                cfg,
                args.query,
                full=args.full,
                show_all=args.all,
                attended=_attended(args),
            )
        )
        return 0
    if args.command == "idea":
        if args.idea_command == "new":
            from docket.commands.idea import run_idea_new

            print(
                run_idea_new(
                    cfg,
                    branch=args.branch,
                    gate=args.gate,
                    decide_by=args.decide_by,
                    parent=args.parent,
                    inherits=args.inherits,
                    from_scratch=args.from_scratch,
                    kind=args.kind,
                    unattended=args.unattended,
                    dry_run=args.dry_run,
                )
            )
            return 0
        from docket.commands.idea import run_idea_import

        print(
            run_idea_import(
                cfg, args.repo, unattended=args.unattended, dry_run=args.dry_run
            )
        )
        return 0
    if args.command == "dash":
        from docket.commands.dash import run_dash

        print(run_dash(cfg, md=args.md, dry_run=args.dry_run))
        return 0
    if args.command == "list":
        from docket.commands.listing import run_list

        print(
            run_list(
                cfg,
                category=args.category,
                status=args.status,
                project=args.project,
                stubs=args.stubs,
                attended=_attended(args),
            )
        )
        return 0
    if args.command == "identity":
        from docket.commands.identity import run_identity

        print(run_identity(cfg, unattended=args.unattended))
        return 0
    if args.command == "brief":
        from docket.commands.brief import run_brief

        print(run_brief(cfg, args.project))
        return 0
    if args.command == "init":
        from docket.commands.init import run_init

        text, code = run_init(
            cfg,
            args.repo,
            check=args.check,
            namespace=args.namespace,
            project_id_override=args.project_id,
        )
        print(text)
        return code
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
