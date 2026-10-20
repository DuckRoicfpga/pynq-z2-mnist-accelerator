"""Prepare generated build inputs without training or changing tracked model files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
CHECKPOINT_SHA256="2f658607173cdc71280b43d811ea2f1d9238e160ba945207d745e18754e97e60"

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path)
    args=parser.parse_args()
    model=ROOT/'camera_demo/model'
    spec=json.loads((model/'model.json').read_text(encoding='utf-8'))
    for name,expected in spec['sha256'].items():
        if sha(model/name)!=expected:
            raise RuntimeError('Model SHA256 mismatch: '+name)
    if args.checkpoint and sha(args.checkpoint)!=CHECKPOINT_SHA256:
        raise RuntimeError('Checkpoint SHA256 differs from the recorded release.')
    out=ROOT/'output/fpga_mem'
    out.mkdir(parents=True,exist_ok=True)
    for name in spec['sha256']:
        shutil.copyfile(model/name,out/name)
    shutil.copyfile(ROOT/'evidence/fpga_export_summary.txt',ROOT/'output/fpga_export_summary.txt')
    if args.checkpoint:
        target=ROOT/'output/model/mlp_mnist_float32.pth'
        target.parent.mkdir(parents=True,exist_ok=True)
        if args.checkpoint.resolve()!=target.resolve():
            shutil.copyfile(args.checkpoint,target)
    print('PASS: generated build inputs prepared; tracked sources unchanged.')

if __name__=='__main__':main()
