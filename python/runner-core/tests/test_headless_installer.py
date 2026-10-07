"""Exercise installer control flow with local downloads and deterministic runtimes."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(os.name == 'posix', 'Unix installer')
class HeadlessInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.commands = self.root / 'commands'
        self.downloads = self.root / 'downloads'
        self.commands.mkdir()
        self.downloads.mkdir()
        self.env = dict(os.environ, PATH=str(self.commands) + os.pathsep + '/usr/bin:/bin',
                        INFERGRADE_VERSION='0.3.64', INFERGRADE_INSTALL_DIR=str(self.root / 'install'),
                        INFERGRADE_BIN_DIR=str(self.root / 'bin'),
                        INFERGRADE_RUNTIME_CACHE_DIR=str(self.root / 'runtime-cache'))
        (self.commands / 'python3').symlink_to(shutil.which('python3'))
        (self.commands / 'sha256sum').symlink_to(shutil.which('sha256sum'))
        for key in ('INFERGRADE_LLAMA_CPP_CLI', 'INFERGRADE_LLAMA_CPP_SERVER'):
            self.env.pop(key, None)
        self.write_executable(self.commands / 'uname', '#!/bin/sh\nif [ "$1" = -s ]; then echo Linux; else echo x86_64; fi\n')
        self.write_executable(self.commands / 'apt-get', '#!/bin/sh\nexit 99\n')
        self.write_executable(self.commands / 'dpkg-query', '#!/bin/sh\nprintf "install ok installed"\n')
        self.write_executable(self.commands / 'curl', '#!/usr/bin/env python3\n'
            'import pathlib,shutil,sys\nargs=sys.argv[1:]\n'
            f'source=pathlib.Path({str(self.downloads)!r}) / args[args.index("-o")-1].split("/")[-1]\n'
            'shutil.copyfile(source,args[args.index("-o")+1])\n')
        files = {'runner/python/runner-core/src/infergrade/__init__.py': b'',
                 'runner/python/runner-core/src/infergrade/runtimes.py': (ROOT / 'python/runner-core/src/infergrade/runtimes.py').read_bytes()}
        files['bin/infergrade-runner'] = b'''#!/usr/bin/env python3
import json,os,pathlib
root=pathlib.Path(os.environ['INFERGRADE_RUNTIME_CACHE_DIR'])/'llama.cpp'
root.mkdir(parents=True,exist_ok=True)
binaries={}
for kind in ('cli','server'):
    path=root/('llama-'+kind)
    failure=kind=='server' and os.environ.get('INFERGRADE_TEST_SERVER_FAIL')=='1'
    path.write_text('#!/bin/sh\\necho "runtime test"\\nexit '+('1' if failure else '0')+'\\n')
    path.chmod(0o755)
    binaries[kind]=str(path)
selection={'runtime_id':'test', 'binaries':binaries}
(root/'selected_runtime.json').write_text(json.dumps(selection))
print(json.dumps({'selection':selection}))
'''
        archive = self.downloads / 'infergrade-runner-0.3.64-linux-x86_64.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for name, contents in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(contents)
                info.mode = 0o755 if name.startswith('bin/') else 0o644
                tar.addfile(info, io.BytesIO(contents))
        self.archive = archive
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (self.downloads / 'SHA256SUMS').write_text(f'{digest}  {archive.name}\n')

    @staticmethod
    def write_executable(path, body):
        path.write_text(body)
        path.chmod(0o755)

    def install(self):
        return subprocess.run(['bash', str(ROOT / 'scripts/install.sh')], env=self.env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def test_install_and_repeat_prepare_runtime_and_expose_exact_pair_command(self):
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        command = self.root / 'bin/infergrade'
        self.assertTrue(command.is_symlink())
        target = command.resolve()
        self.assertIn(str(command) + ' pair --start', first.stdout)
        second = self.install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(command.resolve(), target)
        self.assertNotIn('First-start setup may download', second.stdout)

    def test_checksum_failure_preserves_existing_command(self):
        command = self.root / 'bin/infergrade'
        command.parent.mkdir()
        self.write_executable(command, '#!/bin/sh\necho old-working-runner\n')
        self.archive.write_bytes(self.archive.read_bytes() + b'tampered')
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum', result.stderr)
        self.assertIn('old-working-runner', command.read_text())

    def test_runtime_failure_does_not_expose_new_command(self):
        self.env['INFERGRADE_TEST_SERVER_FAIL'] = '1'
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('could not start', result.stderr)
        self.assertFalse((self.root / 'bin/infergrade').exists())

    def test_command_directory_failure_preserves_previous_command(self):
        command = self.root / 'bin/infergrade'
        command.parent.mkdir()
        self.write_executable(command, '#!/bin/sh\necho old-working-runner\n')
        (command.parent / 'infergrade-runner').mkdir()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('command directory', result.stderr)
        self.assertIn('old-working-runner', command.read_text())
        self.assertFalse((self.root / 'runtime-cache').exists())
