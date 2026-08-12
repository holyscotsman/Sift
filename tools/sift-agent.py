#!/usr/bin/env python3
"""Sift's file agent — the only thing that ever touches your media.

Sift runs somewhere your files are not. It decides *what* should happen and
records your approval; this script runs on the machine that actually holds the
media and carries approved jobs out. Nothing here acts on its own judgement — if
Sift has not handed it a job, it does nothing.

Run it on the box with your library:

    export SIFT_URL=https://your-sift.onrender.com
    export SIFT_AGENT_TOKEN=<the token you pasted into Settings > Connections>
    python3 sift-agent.py

Add --once to run a single pass, or --dry-run to see what it would do and touch
nothing. Deletes move files to a trash folder rather than removing them, so a
mistake is recoverable for as long as you leave it there.

Only the standard library is used, so there is nothing to install.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("sift-agent")

POLL_SECONDS = 60

# Deleted files land here rather than being removed. The whole point of the
# approval gate is that you meant it; the whole point of this is that meaning it
# and being right are different things.
TRASH_DIRNAME = ".sift-trash"

# An encode is accepted only if it runs within this many seconds of its source.
# A truncated encode is the failure that matters: it looks like a success, it is
# much smaller, and swapping it in destroys the episode quietly.
DURATION_TOLERANCE_SECONDS = 5.0

# And it must be at least this fraction of the original. An encode that comes
# back at 2% of the source did not work, whatever its duration says.
MIN_OUTPUT_FRACTION = 0.05


class Agent:
    def __init__(self, base_url: str, token: str, *, dry_run: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.dry_run = dry_run

    # ------------------------------------------------------------------ transport

    def _post(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload or {}).encode()
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Sift-Agent-Token": self.token,
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return dict(json.loads(response.read() or b"{}"))

    def claim(self) -> dict | None:
        try:
            return self._post("/api/agent/claim").get("job")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                log.error("Sift rejected the token. Check SIFT_AGENT_TOKEN matches Settings.")
            elif exc.code == 400:
                log.error("No agent token is configured in Sift yet — paste one into Settings.")
            else:
                log.error("Sift returned HTTP %s when claiming work", exc.code)
            return None
        except urllib.error.URLError as exc:
            log.warning("Couldn't reach Sift (%s) — will try again", exc.reason)
            return None

    def report(self, job_id: int, payload: dict) -> None:
        try:
            self._post(f"/api/agent/{job_id}/result", payload)
        except urllib.error.URLError as exc:
            # The work is done either way; losing the report only means Sift shows
            # the job as still claimed until the next scan reconciles it.
            log.error("Couldn't report job %s back to Sift: %s", job_id, exc)

    # --------------------------------------------------------------------- probing

    @staticmethod
    def duration_seconds(path: Path) -> float | None:
        """Length of a video, via ffprobe. None when it can't be determined."""
        try:
            out = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            return float(out.stdout.strip())
        except (subprocess.SubprocessError, ValueError, FileNotFoundError):
            return None

    # ------------------------------------------------------------------------ work

    def run_job(self, job: dict) -> dict:
        kind = job.get("kind", "transcode")
        path = Path(job["source_path"])

        if not path.exists():
            # Already gone is the outcome that was wanted, so this is not a
            # failure — but it is worth saying, because it usually means the
            # snapshot is stale.
            log.info("%s is already gone", path)
            return {"ok": True, "output_path": None, "error": "file was already absent"}

        if kind == "delete":
            return self._delete(path)
        if kind == "transcode":
            return self._transcode(job, path)
        return {"ok": False, "error": f"unknown job kind {kind!r}"}

    def _delete(self, path: Path) -> dict:
        trash = path.parent / TRASH_DIRNAME
        target = trash / path.name
        log.info("removing %s (%.1f GB)", path, path.stat().st_size / 1e9)
        if self.dry_run:
            log.info("  [dry run] would move it to %s", target)
            return {"ok": True, "output_path": str(target)}
        trash.mkdir(exist_ok=True)
        # Moved, not unlinked. Empty the trash yourself once you are happy — that
        # delay is the only thing standing between a wrong approval and a
        # re-download.
        shutil.move(str(path), str(target))
        return {"ok": True, "output_path": str(target)}

    def _transcode(self, job: dict, path: Path) -> dict:
        target_codec = job.get("target_codec") or "h265"
        encoder = {"h265": "x265", "h264": "x264", "av1": "svt_av1"}.get(target_codec, "x265")
        output = path.with_suffix(f".sift-{target_codec}.mkv")

        command = [
            "HandBrakeCLI", "-i", str(path), "-o", str(output),
            "-e", encoder, "-q", "22", "--all-audio", "--all-subtitles",
        ]
        if job.get("target_resolution") in ("480p", "720p", "1080p"):
            height = {"480p": 480, "720p": 720, "1080p": 1080}[job["target_resolution"]]
            command += ["--maxHeight", str(height)]

        log.info("re-encoding %s -> %s", path, target_codec)
        if self.dry_run:
            log.info("  [dry run] %s", " ".join(command))
            return {"ok": True, "output_path": str(output)}

        try:
            subprocess.run(command, check=True, capture_output=True, timeout=60 * 60 * 12)
        except FileNotFoundError:
            return {"ok": False, "error": "HandBrakeCLI is not installed on this machine"}
        except subprocess.SubprocessError as exc:
            output.unlink(missing_ok=True)
            return {"ok": False, "error": f"HandBrake failed: {exc}"}

        verdict = self._verify(job, path, output)
        if verdict is not None:
            output.unlink(missing_ok=True)
            log.error("  rejected: %s", verdict)
            return {"ok": False, "error": verdict}

        # Only now is the original expendable, and even then it is only moved.
        trash = path.parent / TRASH_DIRNAME
        trash.mkdir(exist_ok=True)
        shutil.move(str(path), str(trash / path.name))
        final = path.with_suffix(output.suffix)
        shutil.move(str(output), str(final))
        size = final.stat().st_size
        log.info("  done — %.1f GB (was %.1f GB)", size / 1e9, (job.get("source_size") or 0) / 1e9)
        return {
            "ok": True,
            "output_path": str(final),
            "output_size": size,
            "output_duration_ms": int((self.duration_seconds(final) or 0) * 1000),
        }

    def _verify(self, job: dict, source: Path, output: Path) -> str | None:
        """Why the new file must not be trusted. None means it passed.

        This is the load-bearing part of the whole agent. An encode that fails
        halfway produces a file that plays, is much smaller, and is not the
        episode — and every one of those properties reads as success.
        """
        if not output.exists():
            return "HandBrake produced no output"
        size = output.stat().st_size
        source_size = source.stat().st_size
        if size < source_size * MIN_OUTPUT_FRACTION:
            return f"output is {size / source_size:.1%} of the original — that is not an encode"
        expected_max = job.get("expected_max_bytes")
        if expected_max and size > expected_max:
            return f"output grew to {size / 1e9:.1f} GB, which is larger than asked for"

        source_seconds = self.duration_seconds(source)
        output_seconds = self.duration_seconds(output)
        if source_seconds and output_seconds:
            drift = abs(source_seconds - output_seconds)
            if drift > DURATION_TOLERANCE_SECONDS:
                return (
                    f"output runs {output_seconds / 60:.1f} min against "
                    f"{source_seconds / 60:.1f} min — it is truncated"
                )
        elif output_seconds is None:
            return "output could not be probed, so it cannot be verified"
        return None

    # ------------------------------------------------------------------------ loop

    def tick(self) -> bool:
        job = self.claim()
        if not job:
            return False
        label = job.get("label") or job["source_path"]
        log.info("claimed job %s: %s", job["id"], label)
        try:
            result = self.run_job(job)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal to the loop
            log.exception("job %s blew up", job["id"])
            result = {"ok": False, "error": str(exc)}
        if not self.dry_run:
            self.report(job["id"], result)
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("SIFT_URL"))
    parser.add_argument("--token", default=os.environ.get("SIFT_AGENT_TOKEN"))
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would happen and touch nothing"
    )
    parser.add_argument("--interval", type=int, default=POLL_SECONDS)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

    if not args.url or not args.token:
        parser.error("set SIFT_URL and SIFT_AGENT_TOKEN (or pass --url and --token)")

    agent = Agent(args.url, args.token, dry_run=args.dry_run)
    if args.dry_run:
        log.info("dry run — nothing will be moved, encoded or reported")

    if args.once:
        agent.tick()
        return 0

    log.info("watching %s for approved work every %ss", args.url, args.interval)
    while True:
        try:
            # Keep going while there is work; sleep only once it runs dry.
            while agent.tick():
                pass
        except KeyboardInterrupt:
            log.info("stopping")
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
