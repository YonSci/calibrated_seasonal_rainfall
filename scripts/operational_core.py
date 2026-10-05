"""Reusable, sequential stage execution with content-based resume and run records.

The engine is year-independent; run_operational.py supplies the supported adapter.
Only trusted, locally constructed argument lists are executed. No shell is used.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    """Same-directory atomic replacement; a killed writer cannot corrupt state."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp_" + uuid.uuid4().hex)
    try:
        temp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_inventory(paths):
    """Hash declared inputs/outputs completely, including every file in directories."""
    records = {}
    for value in paths:
        path = Path(value).resolve()
        if path.is_file():
            records[str(path)] = sha(path)
        elif path.is_dir():
            files = sorted(p for p in path.rglob("*") if p.is_file())
            if not files:
                raise ValueError("Empty stage input/output directory: " + str(path))
            for item in files:
                records[str(item)] = sha(item)
        else:
            raise FileNotFoundError("Stage input/output missing: " + str(path))
    return records


@contextmanager
def exclusive_run(folder):
    """Portable lock. Never silently break a lock from another process."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "RUNNING.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError("Runner lock exists: " + str(lock) +
                         ". Check that no runner is active. After a crash only, remove this lock and rerun; do not delete stage records.") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "host": platform.node(), "started_utc": now()}, stream)
        yield
    finally:
        lock.unlink(missing_ok=True)


class StageRunner:
    """Resume only when stage settings, input bytes and complete output bytes match."""

    def __init__(self, root, folder, context, force=False):
        self.root, self.folder = Path(root), Path(folder)
        self.context, self.force = context, force
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
        self.log_folder = self.folder / "runs" / self.run_id
        self.log_folder.mkdir(parents=True, exist_ok=True)
        self.record = {"run_id": self.run_id, "started_utc": now(), "status": "running",
                       "python": sys.executable, "context": context, "stages": []}
        self.save()

    def save(self):
        write(self.log_folder / "run.json", self.record)
        write(self.folder / "latest_run.json", self.record)

    def finish(self, status="completed", **extra):
        self.record.update(status=status, finished_utc=now(), **extra)
        self.save()

    def stage(self, name, inputs, outputs, command=None, action=None, settings=None):
        if not name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Invalid stage name")
        if (command is None) == (action is None):
            raise ValueError("Supply exactly one command or action")
        state_path = self.folder / "stages" / (name + ".json")
        pending_path = self.folder / "stages" / (name + ".pending.json")
        input_hashes = file_inventory(inputs)
        spec = {"name": name, "inputs": input_hashes, "settings": settings,
                "command": command, "context": self.context}
        fingerprint = digest(spec)
        pending = read(pending_path) if pending_path.is_file() and not self.force else None
        recover = pending is not None and pending.get("fingerprint") == fingerprint
        if state_path.is_file() and not self.force and not recover:
            old = read(state_path)
            if old.get("fingerprint") == fingerprint:
                try:
                    output_hashes = file_inventory(outputs)
                except (OSError, ValueError):
                    output_hashes = None
                if output_hashes and output_hashes == old.get("outputs"):
                    print("RESUME:", name, "(inputs and outputs unchanged)", flush=True)
                    self.record["stages"].append({"name": name, "status": "reused", "fingerprint": fingerprint})
                    self.save()
                    return
        event = {"name": name, "status": "running", "started_utc": now(), "fingerprint": fingerprint}
        self.record["stages"].append(event)
        self.save()
        print("RUN:", name, flush=True)
        log_path = self.log_folder / (name + ".log")
        try:
            if recover:
                from verify2026_outputs import publish_stage
                stage, destination = Path(pending["stage"]), Path(pending["destination"])
                if destination.resolve() not in {Path(p).resolve() for p in outputs}:
                    raise ValueError("Pending publication does not match the declared stage output")
                if stage.parent.resolve() != destination.parent.resolve() or not stage.name.startswith(destination.name + "_building_"):
                    raise ValueError("Pending staging path is invalid")
                expected = pending["files"]
                if stage.is_dir():
                    actual = {str(p.relative_to(stage)): sha(p) for p in stage.rglob("*") if p.is_file()}
                    if actual != expected:
                        raise ValueError("Completed staging files changed; retained for inspection. Use --force to render fresh outputs.")
                    print("RECOVER: publishing completed files for", name, flush=True)
                    publish_stage(stage, destination, regenerate=True)
                elif destination.is_dir():
                    # A rename may have succeeded immediately before interruption.
                    actual = {str(p.relative_to(destination)): sha(p) for p in destination.rglob("*") if p.is_file()}
                    if actual != expected:
                        raise ValueError("Pending staging folder is absent and published files do not match; use --force to rebuild.")
                else:
                    raise ValueError("Pending staging and destination folders are absent; use --force to rebuild.")
                actual = {str(p.relative_to(destination)): sha(p) for p in destination.rglob("*") if p.is_file()}
                if actual != expected:
                    raise ValueError("Recovered output hashes do not match the completed staging files")
                log_path.write_text("Recovered completed publication; no rendering repeated.\n", encoding="utf-8")
            elif command is not None:
                event["command"] = [str(x) for x in command]
                self.save()
                self.subprocess(command, log_path)
            else:
                action()
                log_path.write_text("Python stage completed successfully.\n", encoding="utf-8")
            # Do not certify outputs if inputs changed during a long operation.
            if file_inventory(inputs) != input_hashes:
                raise ValueError("Inputs changed while running stage " + name)
            output_hashes = file_inventory(outputs)
            if not output_hashes:
                raise ValueError("Stage produced no declared outputs: " + name)
            write(state_path, {"name": name, "fingerprint": fingerprint, "specification": spec,
                               "outputs": output_hashes, "completed_utc": now()})
            pending_path.unlink(missing_ok=True)
            event.update(status="recovered" if recover else "completed", finished_utc=now(), log=str(log_path))
            self.save()
        except BaseException as exc:
            ready = getattr(exc, "ready_stage", None)
            destination = getattr(exc, "destination", None)
            if ready and destination and not recover and Path(ready).is_dir():
                # Only in-process presentation actions expose a verified complete
                # stage. Subprocess failures must not be guessed from folder names.
                complete_files = {str(p.relative_to(ready)): sha(p) for p in Path(ready).rglob("*") if p.is_file()}
                if complete_files:
                    write(pending_path, {"fingerprint": fingerprint, "stage": ready,
                                        "destination": destination, "files": complete_files,
                                        "created_utc": now()})
            event.update(status="failed", finished_utc=now(), error=str(exc), log=str(log_path))
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write("\nFAILED: " + str(exc) + "\n")
            self.finish("failed")
            raise

    def subprocess(self, command, log_path):
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen([str(x) for x in command], cwd=self.root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", shell=False)
            try:
                for line in proc.stdout:
                    log.write(line)
                    log.flush()
                    print(line, end="", flush=True)
                code = proc.wait()
                if code:
                    raise subprocess.CalledProcessError(code, command)
            except BaseException:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                raise
            finally:
                proc.stdout.close()
