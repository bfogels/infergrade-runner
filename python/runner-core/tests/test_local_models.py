import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from infergrade import local_models as models


class LocalModelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'checkpoint'
        self.folder.mkdir()
        (self.folder / 'config.json').write_text(json.dumps({'architectures': ['LlamaForCausalLM']}))
        (self.folder / 'model.safetensors').write_bytes(b'fixture weights')
        (self.folder / 'tokenizer.json').write_text('{}')

    def test_discovery_requires_explicit_converter_support(self):
        row = models.discover([self.root])['files'][0]
        self.assertEqual(row['status'], 'needs_compatibility_check')
        self.assertEqual(models.checkpoint(self.folder, supported={'LlamaForCausalLM'})['status'], 'needs_conversion')
        self.assertEqual(models.checkpoint(self.folder, supported={'QwenForCausalLM'})['status'], 'needs_compatibility_check')

    def test_quantized_and_incomplete_are_not_convertible(self):
        (self.folder / 'config.json').write_text(json.dumps({'architectures': ['LlamaForCausalLM'], 'quantization_config': {'quant_method': 'awq'}}))
        self.assertEqual(models.checkpoint(self.folder, supported={'LlamaForCausalLM'})['status'], 'needs_compatibility_check')
        (self.folder / 'config.json').write_text(json.dumps({'architectures': ['LlamaForCausalLM']}))
        (self.folder / 'tokenizer.json').unlink()
        self.assertEqual(models.checkpoint(self.folder, supported={'LlamaForCausalLM'})['status'], 'incomplete')

    def test_shard_index_paths_cannot_escape_checkpoint(self):
        (self.folder / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'x': '../model.safetensors'}}))
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            models.checkpoint(self.folder)

    def test_hf_snapshot_symlinks_within_cache_and_gguf_header(self):
        hub = self.root / 'hub'
        repo = hub / 'models--org--name'
        snapshot = repo / 'snapshots' / 'revision'
        blobs = repo / 'blobs'
        snapshot.mkdir(parents=True)
        blobs.mkdir()
        for name in ['config.json', 'tokenizer.json', 'model.safetensors']:
            blob = blobs / ('blob-' + name)
            blob.write_bytes((self.folder / name).read_bytes())
            (snapshot / name).symlink_to(blob)
        (hub / 'misnamed.bin').write_bytes(b'GGUFfixture')
        (hub / 'fake.gguf').write_bytes(b'not gguf')
        outside = self.root / 'outside.gguf'
        outside.write_bytes(b'GGUF')
        (hub / 'escaped.gguf').symlink_to(outside)
        payload = models.discover([hub])
        self.assertEqual(len(payload['files']), 2)
        self.assertIn('org/name', [r['name'] for r in payload['files']])
        self.assertEqual(models.checkpoint(snapshot, supported={'LlamaForCausalLM'})['status'], 'needs_conversion')

    def test_partial_limit_is_reported(self):
        with mock.patch.object(models, 'MAX_ENTRIES', 1):
            self.assertFalse(models.discover([self.root])['scan_complete'])

    def test_conversion_preserves_source_and_records_hashes_no_overwrite(self):
        converter = self.root / 'convert_hf_to_gguf.py'
        converter.write_text("import sys\nfrom pathlib import Path\nif '--print-supported-models' in sys.argv: print('LlamaForCausalLM')\nelse: Path(sys.argv[sys.argv.index('--outfile')+1]).write_bytes(b'GGUFfixture')\n")
        output = self.root / 'out.gguf'
        original = (self.folder / 'model.safetensors').read_bytes()
        result = models.convert(self.folder, converter, output)
        self.assertEqual((self.folder / 'model.safetensors').read_bytes(), original)
        receipt = json.loads(Path(result['receipt']).read_text())
        self.assertEqual(receipt['output_sha256'], models._sha(output))
        self.assertIn('model.safetensors', receipt['source_files_sha256'])
        with self.assertRaisesRegex(ValueError, 'existing files'):
            models.convert(self.folder, converter, output)

    def test_failed_converter_does_not_publish_output(self):
        converter = self.root / 'convert_hf_to_gguf.py'
        converter.write_text("import sys\nif '--print-supported-models' in sys.argv: print('LlamaForCausalLM')\nelse: sys.exit(2)\n")
        with self.assertRaisesRegex(ValueError, 'Conversion failed'):
            models.convert(self.folder, converter, self.root / 'out.gguf')
        self.assertFalse((self.root / 'out.gguf').exists())

    def test_default_roots_respect_hf_and_vllm_overrides(self):
        with mock.patch.dict(os.environ, {'HF_HUB_CACHE': '/tmp/vllm-cache'}):
            self.assertEqual(models.default_roots()[0], Path('/tmp/vllm-cache'))

    def test_conversion_refuses_extra_link_escape_and_fifo(self):
        outside = self.root / 'secret'
        outside.write_text('private')
        (self.folder / 'extra.safetensors').symlink_to(outside)
        with self.assertRaises(ValueError):
            models._source_manifest(self.folder.resolve())
        (self.folder / 'extra.safetensors').unlink()
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.folder / 'extra.safetensors')
            with self.assertRaises(ValueError):
                models._source_manifest(self.folder.resolve())

    def test_manifest_includes_index_and_vocab_and_detects_change(self):
        (self.folder / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'x': 'model.safetensors'}}))
        (self.folder / 'vocab.json').write_text('{}')
        converter = self.root / 'convert_hf_to_gguf.py'
        converter.write_text("import sys\nfrom pathlib import Path\nif '--print-supported-models' in sys.argv: print('LlamaForCausalLM')\nelse:\n Path(sys.argv[1], 'vocab.json').write_text('changed')\n Path(sys.argv[sys.argv.index('--outfile')+1]).write_bytes(b'GGUFfixture')\n")
        manifest = models._source_manifest(self.folder.resolve())
        self.assertIn('model.safetensors.index.json', manifest)
        self.assertIn('vocab.json', manifest)
        with self.assertRaisesRegex(ValueError, 'changed during conversion'):
            models.convert(self.folder, converter, self.root / 'out.gguf')
        self.assertFalse((self.root / 'out.gguf').exists())

    def test_failed_receipt_write_leaves_no_published_artifacts(self):
        converter = self.root / 'convert_hf_to_gguf.py'
        converter.write_text("import sys\nfrom pathlib import Path\nif '--print-supported-models' in sys.argv: print('LlamaForCausalLM')\nelse: Path(sys.argv[sys.argv.index('--outfile')+1]).write_bytes(b'GGUFfixture')\n")
        with mock.patch.object(models.json, 'dump', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                models.convert(self.folder, converter, self.root / 'out.gguf')
        self.assertFalse((self.root / 'out.gguf').exists())
        self.assertFalse((self.root / 'out.gguf.conversion.json').exists())
