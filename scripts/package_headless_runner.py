#!/usr/bin/env python3
"""Package native CLI and its Python bridge/resources as one release archive."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    version = (root / 'VERSION').read_text().strip()
    system = platform.system().lower()
    arch = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(platform.machine().lower(), platform.machine().lower())
    name = f'infergrade-runner-{version}-{system}-{arch}.tar.gz'
    with tempfile.TemporaryDirectory() as temporary:
        bundle = Path(temporary)
        (bundle / 'bin').mkdir()
        (bundle / 'runner').mkdir()
        shutil.copy2(args.cli, bundle / 'bin' / 'infergrade-runner')
        (bundle / 'bin' / 'infergrade-runner').chmod(0o755)
        archive = subprocess.check_output(['git', 'archive', 'HEAD'], cwd=root)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            # git archive is a local, tracked source tree, not a downloaded archive.
            source.extractall(bundle / 'runner')
        with tarfile.open(args.output / name, 'w:gz') as output:
            for child in sorted(bundle.iterdir()):
                output.add(child, arcname=child.name)
    digest = hashlib.sha256((args.output / name).read_bytes()).hexdigest()
    shutil.copy2(root / 'scripts' / 'install.sh', args.output / 'install.sh')
    installer_digest = hashlib.sha256((args.output / 'install.sh').read_bytes()).hexdigest()
    (args.output / 'SHA256SUMS.headless').write_text(f'{digest}  {name}\n{installer_digest}  install.sh\n')
    print(args.output / name)


if __name__ == '__main__':
    main()
