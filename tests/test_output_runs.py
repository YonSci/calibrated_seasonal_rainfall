import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from output_runs import staged_output

class OutputTests(unittest.TestCase):
    def test_success_preserves_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'training';out.mkdir();(out/'old.txt').write_text('old')
            with staged_output(out,True) as stage:(stage/'new.txt').write_text('new')
            self.assertEqual((out/'new.txt').read_text(),'new')
            backups=list(Path(tmp).glob('training_backup_*'))
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'old.txt').read_text(),'old')
    def test_failed_regeneration_preserves_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'training';out.mkdir();(out/'old.txt').write_text('old')
            with self.assertRaises(RuntimeError):
                with staged_output(out,True) as stage:
                    (stage/'partial.txt').write_text('partial');raise RuntimeError('simulated failure')
            self.assertEqual((out/'old.txt').read_text(),'old')
            self.assertEqual(list(Path(tmp).iterdir()),[out])
    def test_without_flag_protects_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'training';out.mkdir()
            with self.assertRaises(FileExistsError):
                with staged_output(out):pass
    def test_first_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'training'
            with staged_output(out) as stage:(stage/'result.txt').write_text('complete')
            self.assertTrue((out/'result.txt').exists())

if __name__=='__main__':unittest.main()
