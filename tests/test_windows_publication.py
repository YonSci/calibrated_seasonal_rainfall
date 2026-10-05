"""Simulate Windows rename failures without changing permissions or real outputs."""
import errno
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import verify2026_outputs as publication
from operational_core import StageRunner, read


def denied():
    exc = PermissionError(errno.EACCES, 'Simulated Windows directory lock')
    exc.winerror = 5
    return exc


class PublicationTests(unittest.TestCase):
    def test_transient_lock_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp).resolve()/'Sep'
            original = Path.rename
            attempts = []
            def rename(p, target):
                if p.name.startswith('Sep_building_'):
                    attempts.append(1)
                    if len(attempts) < 3:
                        raise denied()
                return original(p, target)
            with patch.object(Path, 'rename', rename), patch.object(publication.time, 'sleep') as sleep:
                with publication.staged_output(dest, True) as stage:
                    (stage/'map.png').write_bytes(b'complete')
            self.assertEqual(len(attempts), 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual((dest/'map.png').read_bytes(), b'complete')

    def test_persistent_lock_retains_new_and_restores_old(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp).resolve()/'Sep';dest.mkdir();(dest/'old.txt').write_text('old')
            original = Path.rename
            def rename(p, target):
                if p.name.startswith('Sep_building_'):
                    raise denied()
                return original(p, target)
            with patch.object(Path, 'rename', rename), patch.object(publication, 'RETRY_DELAYS', (0,)):
                with self.assertRaises(publication.PublicationError) as caught:
                    with publication.staged_output(dest, True) as stage:
                        (stage/'map.png').write_bytes(b'complete')
            self.assertEqual((dest/'old.txt').read_text(), 'old')
            ready = Path(caught.exception.ready_stage)
            self.assertEqual((ready/'map.png').read_bytes(), b'complete')
            publication.publish_stage(ready, dest, True)
            self.assertEqual((dest/'map.png').read_bytes(), b'complete')
            backups = list(Path(temp).resolve().glob('Sep_backup_*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0]/'old.txt').read_text(), 'old')

    def test_blocked_backup_keeps_both(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp).resolve()/'Sep';dest.mkdir();(dest/'old').write_text('old')
            original=Path.rename
            def rename(p,target):
                if p == dest:raise denied()
                return original(p,target)
            with patch.object(Path,'rename',rename),patch.object(publication,'RETRY_DELAYS',()):
                with self.assertRaises(publication.PublicationError) as caught:
                    with publication.staged_output(dest,True) as stage:
                        (stage/'new').write_text('new')
            self.assertTrue((dest/'old').is_file())
            self.assertTrue((Path(caught.exception.ready_stage)/'new').is_file())

    def test_render_error_is_not_recoverable(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp).resolve()/'Sep'
            with self.assertRaisesRegex(ValueError,'rendering failed'):
                with publication.staged_output(dest,True) as stage:
                    (stage/'incomplete').write_text('partial')
                    raise ValueError('rendering failed')
            self.assertFalse(stage.exists())
            self.assertFalse(dest.exists())

    def test_runner_recovers_without_rendering_again(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source=root/'input';source.write_text('same')
            dest=root/'Sep';calls=[]
            def action():
                calls.append(1)
                with publication.staged_output(dest,True) as stage:
                    (stage/'map.png').write_bytes(b'complete')
            original=Path.rename
            def rename(p,target):
                if p.name.startswith('Sep_building_'):raise denied()
                return original(p,target)
            r=StageRunner(root,root/'state',{'test':1})
            with patch.object(Path,'rename',rename),patch.object(publication,'RETRY_DELAYS',()):
                with self.assertRaises(publication.PublicationError):
                    r.stage('forecast_view_Sep',[source],[dest],action=action)
            pending=root/'state/stages/forecast_view_Sep.pending.json'
            self.assertTrue(pending.is_file())
            again=StageRunner(root,root/'state',{'test':1})
            again.stage('forecast_view_Sep',[source],[dest],action=action)
            self.assertEqual(len(calls),1)
            self.assertEqual(again.record['stages'][-1]['status'],'recovered')
            self.assertFalse(pending.exists())
            again.stage('forecast_view_Sep',[source],[dest],action=action)
            self.assertEqual(again.record['stages'][-1]['status'],'reused')

    def test_recovery_rejects_changed_staging_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source=root/'input';source.write_text('same');dest=root/'Sep'
            def action():
                with publication.staged_output(dest,True) as stage:
                    (stage/'map.png').write_bytes(b'complete')
            with patch.object(publication, 'rename_with_retry', side_effect=denied()):
                with self.assertRaises(publication.PublicationError):
                    StageRunner(root,root/'state',{}).stage('s',[source],[dest],action=action)
            pending=read(root/'state/stages/s.pending.json')
            (Path(pending['stage'])/'map.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'staging files changed'):
                StageRunner(root,root/'state',{}).stage('s',[source],[dest],action=action)
            self.assertFalse(dest.exists())


if __name__=='__main__':
    unittest.main(verbosity=2)
