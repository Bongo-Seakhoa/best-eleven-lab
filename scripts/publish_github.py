"""Publish only the reviewed manifest to a new personal public GitHub repository."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args, check=True):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=check)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner',required=True)
    parser.add_argument('--name',default='best-eleven-lab')
    parser.add_argument('--publish',action='store_true',help='Actually create a public repository and push; otherwise validate only')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',args.owner) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',args.name):
        raise ValueError('Invalid owner or repository name')
    manifest=json.loads((ROOT/'PUBLISH_MANIFEST.json').read_text())['files']
    for relative, expected in manifest.items():
        path=ROOT/relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError(f'Manifest mismatch: {relative}. Review edits and regenerate the manifest before publication.')
    print(f'Validated {len(manifest)} public-package files. Destination: {args.owner}/{args.name} (PUBLIC).')
    if not args.publish:
        print('Validation only. Add --publish after reviewing the public package and outstanding assurance gates.')
        return 0
    for command in ['git','gh']:
        if not shutil.which(command):raise RuntimeError(f'Install {command} before publication')
    account=run('gh','api','user','--jq','.login').stdout.strip()
    if account.lower()!=args.owner.lower():
        raise RuntimeError('Authenticated GitHub account does not match the requested personal owner. Switch accounts explicitly.')
    if not (ROOT/'.git').exists():run('git','init','-b','main')
    if run('git','remote').stdout.strip():raise RuntimeError('Refusing to operate on a repository with an existing remote')
    top=Path(run('git','rev-parse','--show-toplevel').stdout.strip()).resolve()
    if top!=ROOT.resolve():raise RuntimeError('The Git root is not this project directory')
    allowed=set(manifest)|{'PUBLISH_MANIFEST.json'}
    tracked=set(run('git','ls-files').stdout.splitlines())
    if tracked-allowed:raise RuntimeError('Tracked files outside the reviewed manifest were found')
    for key in ['user.name','user.email']:
        if not run('git','config','--get',key,check=False).stdout.strip():
            raise RuntimeError(f'Set your Git {key} before committing. No identity will be invented.')
    # Explicit paths keep unrelated local files out of the commit.
    paths=sorted(allowed)
    for start in range(0,len(paths),30):run('git','add','--',*paths[start:start+30])
    staged=set(run('git','diff','--cached','--name-only').stdout.splitlines())
    if staged-allowed:raise RuntimeError('The index contains unreviewed paths')
    if staged:run('git','commit','-m','Add Best Eleven research prototype and verified synthetic demonstration')
    result=run('gh','repo','create',f'{args.owner}/{args.name}','--public','--source','.','--remote','origin','--push')
    print(result.stdout.strip())
    print('Published as a research prototype. Publication does not close the outstanding scientific or independent-review gates.')
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,RuntimeError,OSError,subprocess.CalledProcessError) as exc:
        print(f'Publication stopped: {exc}',file=sys.stderr)
        if isinstance(exc,subprocess.CalledProcessError):print(exc.stderr.strip(),file=sys.stderr)
        raise SystemExit(2)
