"""Bounded local inventory and explicit Safetensors-to-GGUF conversion.

Discovery never imports checkpoint code, loads weights, or uploads local paths.
A GGUF header is a format observation, not verified benchmark identity.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

MAX_ENTRIES = 20000
MAX_MODELS = 500
MAX_JSON = 4 * 1024 * 1024


def _regular(path, root):
    resolved = path.resolve(strict=True)
    resolved.relative_to(root.resolve(strict=True))
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError('Not a regular file')
    return resolved


def _json(path, root):
    resolved = _regular(path, root)
    if resolved.stat().st_size > MAX_JSON:
        raise ValueError('Metadata exceeds scan limit')
    # Nonblocking protects a metadata path raced into a FIFO.
    fd = os.open(resolved, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Not a regular file')
        value = json.loads(stream.read(MAX_JSON + 1))
    if not isinstance(value, dict):
        raise ValueError('Expected object metadata')
    return value


def default_roots():
    home = Path.home()
    hf = Path(os.environ.get('HF_HUB_CACHE') or Path(os.environ.get('HF_HOME') or home / '.cache/huggingface') / 'hub')
    return [hf, home / '.lmstudio/models', home / '.cache/lm-studio/models',
            Path(os.environ.get('OLLAMA_MODELS') or home / '.ollama/models/blobs')]


def supported_architectures(converter):
    """Only an explicitly selected local converter can establish support."""
    script = Path(converter).resolve(strict=True)
    if not script.is_file() or script.name != 'convert_hf_to_gguf.py':
        raise ValueError('Select a local llama.cpp convert_hf_to_gguf.py script')
    result = subprocess.run([sys.executable, str(script), '--print-supported-models'],
                            capture_output=True, text=True, timeout=60, cwd=script.parent,
                            env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
    if result.returncode:
        raise ValueError('Converter support check failed. Install its requirements in this Python environment first.')
    # llama.cpp writes its supported class names to stdout or its logging stderr.
    names = set(re.findall(r'\b[A-Za-z][A-Za-z0-9_]*(?:ForCausalLM|Model|LMHeadModel|ForConditionalGeneration)\b', result.stdout + result.stderr))
    if not names:
        raise ValueError('Converter did not report any supported architectures')
    return names


def checkpoint(folder, root=None, supported=None):
    folder = Path(folder).resolve(strict=True)
    cache_root = folder.parent.parent.parent if folder.parent.name == 'snapshots' and folder.parent.parent.name.startswith('models--') else folder
    root = Path(root or cache_root).resolve(strict=True)
    folder.relative_to(root)
    config = _json(folder / 'config.json', root)
    architectures = config.get('architectures') or []
    if not isinstance(architectures, list) or not all(isinstance(a, str) for a in architectures):
        architectures = []
    row = dict(name=folder.name, path=str(folder), format='safetensors',
               architecture=architectures[0] if architectures else None,
               status='needs_compatibility_check', read_only=True, identity_status='unverified', size_bytes=0)
    if config.get('quantization_config'):
        row['reason'] = 'Quantized checkpoint (for example AWQ or GPTQ): conversion is not established.'
        return row
    index = folder / 'model.safetensors.index.json'
    if index.exists():
        weights = _json(index, root).get('weight_map')
        if not isinstance(weights, dict) or not weights or not all(isinstance(v, str) for v in weights.values()):
            raise ValueError('Invalid Safetensors shard index')
        names = set(weights.values())
    else:
        names = {'model.safetensors'}
    if len(names) > 1000 or any('/' in n or '\\' in n or not n.endswith('.safetensors') for n in names):
        raise ValueError('Unsafe or excessive Safetensors shard index')
    missing = []
    for name in names:
        try:
            file = _regular(folder / name, root)
            if file.stat().st_size == 0:
                raise ValueError('Empty weights')
            row['size_bytes'] += file.stat().st_size
        except (OSError, ValueError):
            missing.append(name)
    tokenizer = False
    for name in ('tokenizer.json', 'tokenizer.model', 'vocab.json'):
        try:
            tokenizer = _regular(folder / name, root).stat().st_size > 0
            if tokenizer:
                break
        except (OSError, ValueError):
            pass
    if missing or not tokenizer:
        row.update(status='incomplete', reason='Missing weights or tokenizer files.', missing_weights=sorted(missing))
    elif supported is not None and architectures and architectures[0] in supported:
        row.update(status='needs_conversion', reason='Architecture supported by the selected converter. Convert to GGUF before using llama.cpp.')
    else:
        row['reason'] = 'Complete checkpoint files detected. Check this architecture against the selected llama.cpp converter.'
    return row


def discover(roots=None, converter=None):
    supported = supported_architectures(converter) if converter else None
    rows, seen, visited, partial, unreadable = [], set(), 0, False, 0
    for candidate in roots or default_roots():
        try:
            root = Path(candidate).resolve(strict=True)
            if not root.is_dir() or root.parent == root:
                continue
        except OSError:
            continue
        todo = [(root, 0)]
        while todo and len(rows) < MAX_MODELS and visited < MAX_ENTRIES:
            folder, depth = todo.pop()
            try:
                with os.scandir(folder) as iterator:
                    entries = []
                    for entry in iterator:
                        if len(entries) >= MAX_ENTRIES - visited:
                            partial = True; break
                        entries.append(Path(entry.path))
            except OSError:
                unreadable += 1
                continue
            if (folder / 'config.json').exists() and ((folder / 'model.safetensors').exists() or (folder / 'model.safetensors.index.json').exists()):
                try:
                    row = checkpoint(folder, root, supported)
                    key = ('checkpoint', str(folder))
                    if key not in seen:
                        seen.add(key); rows.append(row)
                except (OSError, ValueError, json.JSONDecodeError):
                    unreadable += 1
            for path in entries:
                visited += 1
                if visited > MAX_ENTRIES or len(rows) >= MAX_MODELS:
                    partial = True; break
                try:
                    if path.is_dir() and not path.is_symlink():
                        if depth < 8:
                            todo.append((path, depth + 1))
                        else:
                            partial = True
                        continue
                    file = _regular(path, root)
                    if str(file) in seen:
                        continue
                    fd = os.open(file, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
                    with os.fdopen(fd, 'rb') as stream:
                        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read(4) != b'GGUF':
                            continue
                        size = os.fstat(stream.fileno()).st_size
                    seen.add(str(file))
                    rows.append(dict(name=path.name, path=str(file), format='gguf', status='gguf_detected',
                                     reason='GGUF header detected; architecture, artifact identity and memory fit are unverified.',
                                     size_bytes=size, read_only=True, identity_status='unverified'))
                except (OSError, ValueError):
                    continue
        if todo:
            partial = True
    return dict(files=sorted(rows, key=lambda r: r['name']), scan_complete=not partial and not unreadable,
                scan_limit_reached=partial, unreadable_locations=unreadable, visited_entries=min(visited, MAX_ENTRIES))


def _sha(path):
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Source must be a regular file')
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest(folder):
    cache_root = folder.parent.parent.parent if folder.parent.name == 'snapshots' and folder.parent.parent.name.startswith('models--') else folder
    files = {}
    visited = 0
    for directory, dirs, names in os.walk(folder, followlinks=False):
        relative = Path(directory).relative_to(folder)
        if len(relative.parts) > 8:
            raise ValueError('Checkpoint directory exceeds conversion manifest depth')
        visited += len(dirs) + len(names)
        if visited > MAX_ENTRIES:
            raise ValueError('Checkpoint exceeds conversion manifest limit')
        if any((Path(directory) / name).is_symlink() for name in dirs):
            raise ValueError('Linked checkpoint directories are not supported for conversion')
        for name in names:
            path = Path(directory) / name
            validated = _regular(path, cache_root)
            files[str(path.relative_to(folder))] = _sha(validated)
    return files


def convert(folder, converter, output, outtype='f16'):
    """Explicit local action. Source stays unchanged; output cannot overwrite."""
    if outtype not in ('f16', 'bf16', 'f32'):
        raise ValueError('Choose f16, bf16 or f32 output')
    script = Path(converter).resolve(strict=True)
    supported = supported_architectures(script)
    model = checkpoint(folder, supported=supported)
    if model['status'] != 'needs_conversion':
        raise ValueError(model['reason'])
    destination = Path(output).expanduser().absolute()
    if destination.suffix.lower() != '.gguf' or destination.exists():
        raise ValueError('Choose a new .gguf output file; existing files are never replaced')
    destination.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = Path(str(destination) + '.conversion.json')
    if receipt_path.exists():
        raise ValueError('Conversion receipt already exists')
    source_sha = _sha(script)
    source_root = Path(model['path'])
    if source_root == destination.parent.resolve() or source_root in destination.parent.resolve().parents:
        raise ValueError('Choose an output folder outside the source checkpoint')
    source_hashes = _source_manifest(source_root)
    with tempfile.TemporaryDirectory(prefix='.infergrade-convert-', dir=destination.parent) as temp:
        staged = Path(temp) / 'model.gguf'
        command = [sys.executable, str(script), model['path'], '--outfile', str(staged), '--outtype', outtype]
        result = subprocess.run(command, cwd=script.parent, check=False,
                                env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        if result.returncode:
            raise ValueError('Conversion failed; source files were preserved and no output was published')
        with open(_regular(staged, Path(temp)), 'rb') as stream:
            if stream.read(4) != b'GGUF':
                raise ValueError('Converter output does not have a GGUF header')
        if _sha(script) != source_sha:
            raise ValueError('Converter changed during conversion')
        if _source_manifest(source_root) != source_hashes:
            raise ValueError('Source checkpoint changed during conversion')
        sha = _sha(staged)
        receipt = dict(format_version=1, source_directory=model['path'], architecture=model['architecture'],
                       converter_sha256=source_sha, source_files_sha256=source_hashes, output_sha256=sha, outtype=outtype,
                       identity_status='local_conversion_unverified', source_preserved=True)
        staged_receipt = Path(temp) / 'receipt.json'
        with open(staged_receipt, 'x') as stream:
            json.dump(receipt, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # Both artifacts are fully staged. Exclusive links refuse raced outputs.
        os.link(staged, destination)
        try:
            os.link(staged_receipt, receipt_path)
        except Exception:
            destination.unlink()
            raise
    return dict(output=str(destination), receipt=str(receipt_path), sha256=sha,
                notice='Local converted artifact. Successful loading and benchmark identity remain unverified.')
