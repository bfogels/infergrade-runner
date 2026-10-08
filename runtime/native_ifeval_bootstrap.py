"""Trusted isolated entry point; evaluated model text is never executed."""
import os
import hashlib
import importlib.metadata
import json
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(root / 'dependencies'))
sys.path.insert(0, str(root / 'source'))
os.environ['NLTK_DATA'] = str(root / 'nltk_data')
def offline_audit(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
        raise RuntimeError('native IFEval evaluator is offline and cannot spawn commands')

sys.addaudithook(offline_audit)
import nltk
nltk.data.path[:] = [str(root / 'nltk_data')]

def reject_download(*args, **kwargs):
    raise RuntimeError('native IFEval requires packaged tokenizer data; downloads are disabled')

nltk.download = reject_download
# Container defaults remain /opt. Only this isolated launcher provides the
# trusted native root; the adapter has no environment-based path override.
namespace = runpy.run_path(str(root / 'source/containers/capability-ifeval/runner.py'),
                          init_globals={'_INFERGRADE_NATIVE_SOURCE_ROOT': str(root / 'source')},
                          run_name='native_ifeval_adapter')
prepare = namespace['prepare']
# NLTK resources are fixed and prechecked by the parent process. Avoid creating
# a writable tokenizer lookup directory among model outputs.
def check_tokenizers(output_dir):
    for resource, _ in namespace['_NLTK_TOKENIZER_RESOURCES']:
        nltk.data.find(resource)

prepare.__globals__['_ensure_nltk_tokenizers'] = check_tokenizers
if sys.argv[1:] == ['probe']:
    manifest_bytes = (root / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    for name, package in manifest['packages'].items():
        if name == 'colorama' and sys.platform != 'win32':
            continue
        if importlib.metadata.version(name) != package['version']:
            raise RuntimeError('packaged evaluator dependency version differs')
    for module in ('absl', 'click', 'cloudpickle', 'defusedxml', 'immutabledict',
                   'joblib', 'langdetect', 'nltk', 'regex', 'six', 'tqdm'):
        __import__(module)
    check_tokenizers(None)
    inputs = namespace['evaluation_lib'].read_prompt_list(str(root / 'source/instruction_following_eval/data/input_data.jsonl'))
    expected = {25:'90e90cc5a7110d1d388a02626478909fdf08251a65830be1e5933db841f684d4',
                100:'396ee19b26c5549e4e11325d55ede667a42cf136ac4f1ab0af0237819c61a8a3',
                541:'45874aab7e499fbb3614697d09eda30682716303bf41ecfc6ea5ea4df153f2a4'}
    for count, digest in expected.items():
        if namespace['_selection_digest'](namespace['_sample_inputs'](inputs, count)) != digest:
            raise RuntimeError('native IFEval case selection differs')
    print(json.dumps({'python_version':sys.version.split()[0], 'fixture_count':len(inputs),
                      'manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest()}))
    raise SystemExit(0)
result = namespace['main']()
if sys.argv[1] == 'prepare':
    output = Path(sys.argv[sys.argv.index('--output-dir') + 1])
    inputs = {str(row['key']):row for row in (json.loads(line) for line in (output / 'input_data.jsonl').read_text().splitlines())}
    cases = [json.loads(line) for line in (output / 'cases.jsonl').read_text().splitlines()]
    for case in cases:
        row = inputs[case['case_id']]
        case['scorer_input_sha256'] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    (output / 'cases.jsonl').write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in cases))
raise SystemExit(result)
