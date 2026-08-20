"""The ``sift`` console script — the one entry point nothing had ever run.

At 0% coverage this was the only user-facing surface in the codebase where "does
it import" was an open question. Nothing here is clever; the point is that these
paths execute at all, in CI, before someone types the command.

``serve`` is exercised only as far as its argument wiring. Past that it hands
control to uvicorn and blocks for ever, which is not a thing to do inside a test.
"""

from __future__ import annotations

import sift.cli as cli


def test_the_parser_accepts_every_documented_command():
    """A subcommand added without wiring `func` raises AttributeError in `main`,
    which nothing else would notice until someone typed it."""
    parser = cli.build_parser()
    for argv in (["serve"], ["scan"], ["init"]):
        args = parser.parse_args(argv)
        assert callable(args.func), f"{argv[0]} has no handler"


def test_version_reports_the_shipped_version(capsys):
    """`--version` exits 0 through SystemExit, which is argparse's normal control
    flow rather than a failure — and reads the same string the API reports."""
    from sift import __version__

    try:
        cli.main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert __version__ in capsys.readouterr().out


def test_NEGATIVE_CONTROL_no_command_is_an_error_not_a_silent_success():
    """NEGATIVE CONTROL: `sift` alone must not exit 0 having done nothing. The
    subparser is `required=True`; a version that dropped that would return
    success from a command that never ran."""
    try:
        cli.main([])
    except SystemExit as exc:
        assert exc.code != 0
    else:  # pragma: no cover - only reached if the guard is removed
        raise AssertionError("bare `sift` should not have succeeded")


def test_init_writes_a_config_and_a_secrets_file(tmp_path, monkeypatch, capsys):
    """The scaffold, end to end, against a real (temporary) filesystem."""
    monkeypatch.setattr(cli, "_example_dir", lambda: tmp_path / "examples")
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "sift.toml.example").write_text("[server]\n")
    (tmp_path / "examples" / ".env.example").write_text("SIFT_SECRET_KEY=\n")

    target = tmp_path / "sift.toml"
    assert cli.main(["--config", str(target), "init"]) == 0

    assert target.read_text() == "[server]\n"
    assert (tmp_path / ".env").read_text() == "SIFT_SECRET_KEY=\n"
    assert "never commit it" in capsys.readouterr().out


def test_init_refuses_to_overwrite_without_force(tmp_path, monkeypatch, capsys):
    """A config already has someone's connection URLs in it. Silently replacing
    it with the template is the kind of help nobody wants."""
    monkeypatch.setattr(cli, "_example_dir", lambda: tmp_path / "examples")
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "sift.toml.example").write_text("[server]\n")

    target = tmp_path / "sift.toml"
    target.write_text("[server]\nhost = 'mine'\n")

    assert cli.main(["--config", str(target), "init"]) == 1
    assert "mine" in target.read_text()
    assert "already exists" in capsys.readouterr().out

    assert cli.main(["--config", str(target), "init", "--force"]) == 0
    assert target.read_text() == "[server]\n"


def test_init_leaves_an_existing_env_file_alone(tmp_path, monkeypatch):
    """The .env holds real keys. `init` scaffolds it when missing and must never
    touch it when it is not — this is the file where overwriting costs the most."""
    monkeypatch.setattr(cli, "_example_dir", lambda: tmp_path / "examples")
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "sift.toml.example").write_text("[server]\n")
    (tmp_path / "examples" / ".env.example").write_text("SIFT_SECRET_KEY=\n")

    env = tmp_path / ".env"
    env.write_text("SIFT_SECRET_KEY=the-real-one\n")

    cli.main(["--config", str(tmp_path / "sift.toml"), "init", "--force"])

    assert env.read_text() == "SIFT_SECRET_KEY=the-real-one\n"


def test_init_says_where_it_looked_when_the_template_is_missing(tmp_path, monkeypatch, capsys):
    """The failure that actually ships. In the Docker image the package is
    installed into site-packages and the example files are not in the image at
    all, so this is the branch a container user hits — and the old message said
    the template was not "next to the package" while the code had looked three
    directories above it. A message that names the wrong place is worse than one
    that names none.
    """
    missing = tmp_path / "nowhere"
    monkeypatch.setattr(cli, "_example_dir", lambda: missing)

    assert cli.main(["--config", str(tmp_path / "sift.toml"), "init"]) == 1
    out = capsys.readouterr().out
    assert str(missing) in out, "the message should name the directory it searched"


def test_scan_runs_a_real_scan_against_a_real_database(tmp_path, monkeypatch, capsys):
    """The headless path, wired end to end.

    ``sift scan`` builds its own engine from the config rather than taking one,
    so nothing else in the suite covers that wiring — the API's scan endpoint
    uses the app's factory. Every source is disabled, so this exercises the
    plumbing rather than the ingest, which has its own tests.
    """
    import sift.config as config_module

    settings = config_module.load_settings(config_path=None)
    for name in ("plex", "radarr", "sonarr", "overseerr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.database.url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setattr(cli, "load_settings", lambda _c: settings)

    assert cli.main(["scan"]) == 0

    out = capsys.readouterr().out
    assert "starting (resume=False)" in out and "finished" in out
    # The per-phase progress lines come through the null hub, which is the only
    # thing standing in for the websocket here. No lines at all would mean the
    # scan reported nothing and this test would still have passed on exit code.
    assert "preflight" in out
    assert (tmp_path / "cli.db").exists()


def test_NEGATIVE_CONTROL_the_scan_wiring_is_what_ran(tmp_path, monkeypatch):
    """NEGATIVE CONTROL: the test above asserts on printed text, which a stubbed
    handler could produce without touching a database. This one requires the run
    to have actually reached the scanner and written a row."""
    from sqlalchemy import func, select

    import sift.config as config_module
    from sift.db.models import ScanRun
    from sift.db.session import make_engine, make_session_factory

    settings = config_module.load_settings(config_path=None)
    for name in ("plex", "radarr", "sonarr", "overseerr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    db = tmp_path / "cli.db"
    settings.database.url = f"sqlite:///{db}"
    monkeypatch.setattr(cli, "load_settings", lambda _c: settings)

    cli.main(["scan"])

    factory = make_session_factory(make_engine(db))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ScanRun)) == 1
