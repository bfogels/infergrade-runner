"""Trusted isolated entry point; evaluated model text is never executed."""
import os
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(root / 'dependencies'))
sys.path.insert(0, str(root / 'source'))
os.environ['NLTK_DATA'] = str(root / 'nltk_data')
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
raise SystemExit(namespace['main']())
