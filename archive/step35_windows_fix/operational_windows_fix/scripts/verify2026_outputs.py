"""Publish completed derived-output folders, with bounded Windows-lock retries.

No copy-overwrite fallback: the public destination is always a complete directory.
Failed publication retains the completed staging folder for verified recovery.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import gc
from pathlib import Path
import shutil
import time
import uuid

RETRY_DELAYS = (.25, .5, 1., 2., 3., 5., 5., 5.)


class PublicationError(OSError):
    """Rendering succeeded, but a directory could not be published."""
    def __init__(self, message, stage, destination, backup=None):
        super().__init__(message)
        self.ready_stage = str(Path(stage).resolve())
        self.destination = str(Path(destination).resolve())
        self.backup = str(Path(backup).resolve()) if backup else None


def check_destination(destination, regenerate=False):
    destination = Path(destination)
    if destination.exists() and not regenerate:
        raise FileExistsError(f'{destination} exists. Add --regenerate to rebuild with an automatic backup.')
    if destination.exists() and not destination.is_dir():
        raise ValueError(f'Output destination is not a directory: {destination}')


def retryable(exc):
    return (isinstance(exc, PermissionError) or getattr(exc, 'winerror', None) in {5, 32, 33}
            or getattr(exc, 'errno', None) in {errno.EACCES, errno.EPERM, errno.EBUSY})


def rename_with_retry(source, destination):
    """At most 9 attempts / 21.75 seconds of waiting; never change permissions."""
    source, destination = Path(source), Path(destination)
    gc.collect()
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            source.rename(destination)
            return
        except OSError as exc:
            if not retryable(exc) or attempt == len(RETRY_DELAYS):
                raise
            delay = RETRY_DELAYS[attempt]
            print(f'Output folder busy or access denied; retry {attempt+1}/{len(RETRY_DELAYS)} in {delay:g}s: {destination.name}', flush=True)
            gc.collect()
            time.sleep(delay)


def publish_stage(stage, destination, regenerate=False):
    """Publish a known-complete sibling folder; roll back the old output on failure."""
    stage, destination = Path(stage).resolve(), Path(destination).resolve()
    if stage.parent != destination.parent or not stage.name.startswith(destination.name + '_building_'):
        raise ValueError('Completed staging folder must be a matching sibling of its destination')
    if not stage.is_dir():
        raise FileNotFoundError('Completed staging folder is missing: ' + str(stage))
    check_destination(destination, regenerate)
    token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
    backup = None
    try:
        if destination.exists():
            backup = destination.with_name(destination.name + '_backup_' + token)
            rename_with_retry(destination, backup)
    except OSError as exc:
        raise PublicationError(f'Could not move the previous output to a backup: {exc}\nCompleted new files retained: {stage}\nClose files/previews using this output folder and rerun the same command.', stage, destination) from exc
    try:
        # Refuse an unexpected concurrent writer, including POSIX empty-directory replacement.
        if destination.exists():
            raise FileExistsError('Another process created the output destination: ' + str(destination))
        rename_with_retry(stage, destination)
    except OSError as exc:
        rollback = ''
        if backup is not None and backup.exists():
            if not destination.exists():
                try:
                    rename_with_retry(backup, destination)
                    rollback = '\nPrevious output restored.'
                except OSError as restore_exc:
                    rollback = f'\nPrevious output remains at {backup}; restoration was also blocked: {restore_exc}'
            else:
                rollback = f'\nPrevious output remains at {backup}; a destination appeared during publication.'
        raise PublicationError(f'Could not publish completed output: {exc}{rollback}\nCompleted new files retained: {stage}\nClose files/previews using this output folder and rerun the same command. Persistent access denial may require checking folder permissions.', stage, destination, backup if backup is not None and backup.exists() else None) from exc
    if backup is not None:
        print('Previous results preserved:', backup, flush=True)


@contextmanager
def staged_output(destination, regenerate=False):
    destination = Path(destination)
    check_destination(destination, regenerate)
    destination.parent.mkdir(parents=True, exist_ok=True)
    token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
    stage = destination.with_name(destination.name + '_building_' + token)
    stage.mkdir()
    complete = False
    try:
        yield stage
        complete = True
        publish_stage(stage, destination, regenerate)
    finally:
        # Preserve complete output after publication failures. A rendering error
        # is not a completion certificate and cannot be automatically recovered.
        if not complete and stage.exists():
            try:
                shutil.rmtree(stage)
            except OSError as exc:
                print(f'Incomplete staging folder could not be cleaned: {stage} ({exc}). It will not be used for recovery.', flush=True)
