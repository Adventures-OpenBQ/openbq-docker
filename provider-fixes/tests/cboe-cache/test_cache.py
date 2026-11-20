import subprocess,sys,unittest
from pathlib import Path
class Concurrency(unittest.TestCase):
    def test_multiple_threads_and_loops(self):
        try:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('concurrency.py'))],capture_output=True,text=True,timeout=25)
        except subprocess.TimeoutExpired as error:
            self.fail('cross-loop cache requests failed to complete within 25 seconds: '+str(error.stderr))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print(result.stdout)
if __name__=='__main__': unittest.main(verbosity=2)
