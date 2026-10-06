import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('release_resolver', Path(__file__).resolve().parents[3] / 'scripts/resolve_llama_cpp_release.py')
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)


class SemverResolverTests(unittest.TestCase):
    def setUp(self):
        self.pointer = b'b11429\n'
        self.release = {'tag_name': 'v0.6.0', 'assets': [{
            'name': 'nightly-tag.txt', 'size': len(self.pointer),
            'digest': 'sha256:' + hashlib.sha256(self.pointer).hexdigest(),
            'browser_download_url': 'https://github.com/ggml-org/llama.cpp/releases/download/v0.6.0/nightly-tag.txt',
        }]}

    def read(self, url, limit):
        if url.endswith('nightly-tag.txt'):
            return self.pointer
        self.assertEqual(url, resolver.API + 'b11429')
        return json.dumps({'tag_name': 'b11429', 'draft': False, 'assets': []}).encode()

    def test_resolves_verified_pointer_and_retains_semantic_identity(self):
        result = resolver.resolve_release(self.release, self.read)
        self.assertEqual(result['tag_name'], 'b11429')
        self.assertEqual(result['semantic_release']['tag'], 'v0.6.0')

    def test_rejects_changed_pointer_without_matching_digest(self):
        self.pointer = b'b11430\n'
        with self.assertRaisesRegex(ValueError, 'checksum'):
            resolver.resolve_release(self.release, self.read)

    def test_rejects_external_pointer_and_path_injection(self):
        self.release['assets'][0]['browser_download_url'] = 'https://example.org/nightly-tag.txt'
        with self.assertRaisesRegex(ValueError, 'Invalid nightly pointer'):
            resolver.resolve_release(self.release, self.read)
        self.setUp()
        self.pointer = b'../main'
        self.release['assets'][0]['size'] = len(self.pointer)
        self.release['assets'][0]['digest'] = 'sha256:' + hashlib.sha256(self.pointer).hexdigest()
        with self.assertRaisesRegex(ValueError, 'Invalid binary nightly'):
            resolver.resolve_release(self.release, self.read)

    def test_rejects_mismatched_binary_metadata(self):
        with self.assertRaisesRegex(ValueError, 'does not match'):
            resolver.resolve_release(self.release, lambda url, limit: self.pointer if url.endswith('.txt') else b'{"tag_name":"b11430"}')
