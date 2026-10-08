"""Offline packaged evaluator custody and subprocess supervision."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import subprocess

PROTOCOL_ID = 'ifeval_native_packaged_v1'
RECEIPT_NAME = 'infergrade-native-ifeval-receipt.json'
# Updated only with a reviewed packaging manifest; never supplied by a job.
MANIFEST_SHA256 = '8416331ef3b540c7dde4adbf3137de6d680857f8a07c3d0be9331533e6783a81'


def _digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def _relative(name):
    if not isinstance(name, str) or not name:
        raise ValueError("invalid evaluator receipt path")
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('invalid evaluator receipt path')
    return path


def bundle_root():
    explicit = os.environ.get('INFERGRADE_NATIVE_IFEVAL_BUNDLE')
    if explicit:
        return Path(explicit).expanduser().resolve()
    source = os.environ.get('INFERGRADE_RUNNER_ROOT')
    if source:
        runner = Path(source).expanduser().resolve()
        return (runner.parent if (runner / 'src/infergrade').is_dir() else runner) / 'native-ifeval'
    # A desktop package sets Runner root to its resource directory. A checkout
    # can prepare assets here explicitly; execution never materializes them.
    module = Path(__file__).resolve()
    if module.parents[2].name == 'runner-core' and module.parents[3].name != 'python':
        return module.parents[3] / 'native-ifeval'
    return module.parents[4] / 'runtime/native-ifeval'


def _target():
    system, machine = platform.system(), platform.machine().lower()
    if system == 'Darwin' and machine in ('arm64', 'aarch64'):
        return 'aarch64-apple-darwin'
    if system == 'Windows' and machine in ('amd64', 'x86_64'):
        return 'x86_64-pc-windows-msvc'
    if system == 'Linux' and machine in ('amd64', 'x86_64'):
        return 'x86_64-unknown-linux-gnu'
    raise ValueError('no reviewed native IFEval bundle for this platform')


def verify_bundle(root=None):
    root = Path(root or bundle_root()).resolve()
    path = root / RECEIPT_NAME
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('packaged native IFEval receipt is missing or too large')
    raw = path.read_bytes()
    try:
        from infergrade._native_ifeval_identity import IDENTITY
    except ImportError as exc:
        raise ValueError('native IFEval trusted package identity is missing') from exc
    if (not isinstance(IDENTITY, dict) or IDENTITY.get('target') != _target()
            or IDENTITY.get('manifest_sha256') != MANIFEST_SHA256
            or IDENTITY.get('receipt_sha256') != hashlib.sha256(raw).hexdigest()):
        raise ValueError('native IFEval inventory differs from trusted package identity')
    receipt = json.loads(raw)
    if (receipt.get('schema_version') != 'infergrade.native_ifeval_receipt.v1'
            or receipt.get('protocol_id') != PROTOCOL_ID
            or receipt.get('container_parity') != 'unqualified_distinct_protocol'
            or receipt.get('python_version') != '3.12.13'
            or receipt.get('manifest_sha256') != MANIFEST_SHA256
            or receipt.get('target') != _target()):
        raise ValueError('native IFEval receipt identity or platform is not reviewed')
    files, links = receipt.get('files'), receipt.get('links')
    if not isinstance(files, dict) or not isinstance(links, dict) or not 1 <= len(files) <= 20000 or len(links) > 2000:
        raise ValueError('invalid native IFEval file inventory')
    for name, expected in files.items():
        candidate = root.joinpath(*_relative(name).parts)
        candidate.resolve().relative_to(root)
        if candidate.is_symlink() or not candidate.is_file() or _digest(candidate) != expected:
            raise ValueError('native IFEval packaged file verification failed')
    for name, expected in links.items():
        candidate = root.joinpath(*_relative(name).parts)
        candidate.resolve().relative_to(root)
        if not candidate.is_symlink() or os.readlink(candidate) != expected:
            raise ValueError('native IFEval packaged link verification failed')
    for candidate in root.rglob('*'):
        if candidate.is_symlink() and candidate.relative_to(root).as_posix() not in links:
            raise ValueError("native IFEval has an unrecorded link")
        if not candidate.is_dir() and candidate.name != RECEIPT_NAME:
            name = candidate.relative_to(root).as_posix()
            if name not in files and name not in links:
                raise ValueError('native IFEval has an unrecorded file')
    manifest_path = root / 'manifest.json'
    if not manifest_path.is_file() or _digest(manifest_path) != MANIFEST_SHA256:
        raise ValueError('native IFEval manifest content differs from reviewed pin')
    manifest = json.loads(manifest_path.read_bytes())
    expected_assets = {'source/instruction_following_eval/data/input_data.jsonl': manifest['dataset']['sha256']}
    for name, sha in manifest['source_files'].items():
        expected_assets['source/' + (name[12:] if name.startswith('third_party/') else name)] = sha
    for name, sha in manifest['nltk_resources'].items():
        expected_assets['nltk_data/' + name] = sha
    for name, sha in expected_assets.items():
        if files.get(name) != sha:
            raise ValueError('native IFEval source or tokenizer pin is not recorded')
    executable = str(_relative(receipt.get('executable')).as_posix())
    if executable not in files or 'bootstrap.py' not in files:
        raise ValueError('native IFEval entry point is not recorded')
    identity = {key: receipt[key] for key in ('protocol_id', 'container_parity', 'python_version', 'manifest_sha256', 'target')}
    identity['bundle_receipt_sha256'] = hashlib.sha256(raw).hexdigest()
    identity['interpreter_sha256'] = files[executable]
    identity['scoring_files_sha256'] = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return root, receipt, identity


def _execute(root, receipt, args, timeout=300):
    # Only OS runtime essentials survive. No HOME/PYTHONPATH/HF/API credentials,
    # proxy settings or host NLTK search paths are supplied to the evaluator.
    environment = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR') if key in os.environ}
    environment.update({'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONNOUSERSITE': '1'})
    command = [str(root / receipt['executable']), '-I', '-B', str(root / 'bootstrap.py')] + list(args)
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except BaseException:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)
        raise
    if child.returncode != 0:
        # stderr can contain evaluated text. Preserve only a fixed diagnosis.
        raise RuntimeError('packaged native IFEval evaluator failed; no score was accepted')
    if len(stdout) > 16384:
        raise ValueError('native IFEval probe output exceeds bound')
    return stdout


def preflight(root=None):
    root, receipt, identity = verify_bundle(root)
    probe = json.loads(_execute(root, receipt, ['probe'], timeout=30))
    if probe.get('python_version') != '3.12.13' or probe.get('fixture_count') != 541:
        raise ValueError('native IFEval interpreter or fixture probe failed')
    if probe.get('manifest_sha256') != MANIFEST_SHA256:
        raise ValueError('native IFEval dependency probe identity failed')
    return identity


def run_evaluator(command, output_dir, limit=None, expected_identity=None):
    if command not in ('prepare', 'evaluate'):
        raise ValueError('unsupported native evaluator command')
    root, receipt, identity = verify_bundle()
    if expected_identity is not None and identity != expected_identity:
        raise ValueError("native IFEval evaluator changed after case preparation")
    args = [command, '--output-dir', str(Path(output_dir).resolve())]
    if command == 'prepare':
        if limit not in (25, 100, 541):
            raise ValueError('unreviewed native IFEval tier')
        args.extend(['--limit', str(limit)])
    _execute(root, receipt, args)
    return identity


def prepared_input_receipt(output_dir, expected_count):
    """Seal exact scorer inputs before generation and verify before evaluation."""
    expected_selections = {
        25:'90e90cc5a7110d1d388a02626478909fdf08251a65830be1e5933db841f684d4',
        100:'396ee19b26c5549e4e11325d55ede667a42cf136ac4f1ab0af0237819c61a8a3',
        541:'45874aab7e499fbb3614697d09eda30682716303bf41ecfc6ea5ea4df153f2a4'}
    if expected_count not in expected_selections:
        raise ValueError('unreviewed native IFEval denominator')
    output = Path(output_dir)
    metadata = json.loads((output / 'benchmark_metadata.json').read_bytes())
    inputs = [json.loads(line) for line in (output / 'input_data.jsonl').read_text().splitlines()]
    cases = [json.loads(line) for line in (output / 'cases.jsonl').read_text().splitlines()]
    if (len(inputs) != expected_count or len(cases) != expected_count
            or metadata.get('case_count') != expected_count
            or metadata.get('selection_sha256') != expected_selections[expected_count]):
        raise ValueError('native IFEval prepared selection differs from reviewed tier')
    selected = hashlib.sha256('\n'.join(sorted(str(row['key']) for row in inputs)).encode()).hexdigest()
    if selected != expected_selections[expected_count] or len({str(row['key']) for row in inputs}) != expected_count:
        raise ValueError('native IFEval prepared task IDs differ from reviewed tier')
    for case, row in zip(cases, inputs):
        sha = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        if (case.get('case_id') != str(row['key']) or case.get('prompt') != row['prompt']
                or case.get('instruction_id_list') != row['instruction_id_list']
                or case.get('scorer_input_sha256') != sha):
            raise ValueError('native IFEval scorer inputs are not bound to task revisions')
    return {'input_files_sha256': {name:_digest(output / name) for name in ('cases.jsonl','input_data.jsonl','benchmark_metadata.json')},
            'case_count':expected_count, 'selection_sha256':selected}
