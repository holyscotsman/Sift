"""``sift`` command-line entry point: ``serve``, ``scan``, ``init``."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import load_settings
from .db.session import init_db, make_engine, make_session_factory
from .services.scanner import create_scan_run, run_scan


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = load_settings(args.config)
    uvicorn.run(
        "sift.main:create_app",
        factory=True,
        host=args.host or settings.server.host,
        port=args.port or settings.server.port,
        reload=args.reload,
    )
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    engine = make_engine(settings.database.target())
    init_db(engine)
    factory = make_session_factory(engine)

    class _NullHub:
        async def publish(self, *_a: object, **_k: object) -> None: ...
        async def publish_progress(self, progress: object) -> None:
            print(f"  {progress.phase:<10} {progress.status}")  # type: ignore[attr-defined]

    scan_run_id = args.resume or create_scan_run(factory)
    print(f"scan {scan_run_id} starting (resume={bool(args.resume)})")
    asyncio.run(
        run_scan(settings, factory, _NullHub(), scan_run_id, resume=bool(args.resume))
    )
    print(f"scan {scan_run_id} finished")
    return 0


def _example_dir() -> Path:
    """Where the ``*.example`` templates live: the repository root.

    **This only resolves in a source checkout.** Installed as a wheel the package
    sits in ``site-packages``, three levels up is the interpreter's library
    directory, and the templates are not shipped inside the distribution — so
    ``sift init`` cannot work from a ``pip install``, including in this project's
    own Docker image, which installs the package and never copies the templates.

    Left as it is rather than papered over: fixing it properly means either
    shipping the templates inside the package or adding them to the image, and
    both are decisions about packaging rather than about this function. What has
    changed is that the failure now says *where it looked*, so the next person
    can see the problem instead of guessing at it.

    A function, not a module constant, so tests can point it somewhere real.
    """
    return Path(__file__).resolve().parents[2]


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.config)
    templates = _example_dir()
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite)")
        return 1
    example = templates / "sift.toml.example"
    if not example.is_file():
        print(f"no sift.toml.example in {templates}")
        print("`sift init` needs a source checkout; a pip-installed Sift has no templates.")
        return 1
    shutil.copyfile(example, target)
    print(f"wrote {target} — edit connection URLs here")

    # Scaffold the secrets file next to the config if it isn't there yet. Never
    # overwritten, even with --force: this is the file with the real keys in it,
    # and --force is about the config the user asked to replace.
    env_target = target.parent / ".env"
    env_example = templates / ".env.example"
    if env_example.is_file() and not env_target.exists():
        shutil.copyfile(env_example, env_target)
        print(f"wrote {env_target} — put your tokens/keys here (never commit it)")
    print("next: fill both files in, then run `sift scan` and `sift serve`")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sift", description="Sift — Plex/Radarr library refiner")
    parser.add_argument("--version", action="version", version=f"sift {__version__}")
    parser.add_argument("--config", default="sift.toml", help="path to sift.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the web server")
    p_serve.add_argument("--host")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_scan = sub.add_parser("scan", help="run a headless ingestion scan")
    p_scan.add_argument("--resume", type=int, default=None, help="resume an existing scan id")
    p_scan.set_defaults(func=_cmd_scan)

    p_init = sub.add_parser("init", help="scaffold a sift.toml")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=_cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
