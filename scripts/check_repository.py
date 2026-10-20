"""Host-only checks. Does not load an overlay or access a physical board."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    source_count = 0
    for path in ROOT.rglob('*.py'):
        if not any(part in {'.venv','venv','output','data'} for part in path.relative_to(ROOT).parts):
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
            source_count += 1
    model = json.loads((ROOT/'camera_demo/model/model.json').read_text(encoding='utf-8'))
    evidence = json.loads((ROOT/'evidence/recorded_board_verification.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT/'evidence/implementation_manifest.json').read_text(encoding='utf-8'))
    fingerprint = hashlib.sha256(json.dumps(model,sort_keys=True).encode()).hexdigest()
    assert fingerprint == evidence['model_fingerprint']
    for name, expected in model['sha256'].items():
        # Accept the repository's recorded filename -> SHA256 mapping.
        assert sha(ROOT/'camera_demo/model'/name) == expected, name
    for relative, expected in manifest['source_and_weight_sha256'].items():
        target = ROOT/relative
        if relative.startswith('output/fpga_mem/'):
            target = ROOT/'camera_demo/model'/Path(relative).name
        assert sha(target) == expected, relative
    rows = evidence['reference_results']
    assert len(rows)==120
    assert all(row['digit']==row['expected_prediction'] and row['cycles']==110208 and row['clock_hz']==100000000 for row in rows)
    assert '* -text' in (ROOT/'.gitattributes').read_text()
    for folder, command in [
        (ROOT/'camera_demo',[sys.executable,'-X','utf8','-B','-m','unittest','test_demo','test_verify_board','-v']),
        (ROOT,[sys.executable,'-X','utf8','-B','sim/test_pynq_driver.py']),
    ]:
        subprocess.run(command,cwd=folder,check=True)
    print(json.dumps({'status':'PASS','python_sources_parsed':source_count,
                      'model_fingerprint':fingerprint,'recorded_cases_checked':120,
                      'physical_board_test_run':False},indent=2))

if __name__=='__main__':
    main()
