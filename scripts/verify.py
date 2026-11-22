"""Run the complete proof, refusing silently skipped database or UI coverage."""
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    if not os.environ.get('TEST_DATABASE_URL'):
        sys.exit('Set TEST_DATABASE_URL to a PostgreSQL database with CREATE SCHEMA and CREATEROLE permissions.')
    if not shutil.which('node'):
        sys.exit('Node.js is required for the shipped JavaScript renderer smoke tests.')
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='frontdesk-proof-') as folder:
        report=Path(folder)/'results.xml'
        result=subprocess.run([sys.executable,'-m','pytest','-q',f'--junitxml={report}'],cwd=root,check=False)
        if result.returncode:return result.returncode
        skipped=sum(int(s.get('skipped',0)) for s in ET.parse(report).iter('testsuite'))
        if skipped:
            print(f'Incomplete proof: {skipped} tests skipped.',file=sys.stderr)
            return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
