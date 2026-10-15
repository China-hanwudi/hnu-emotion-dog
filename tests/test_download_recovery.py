import hashlib
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'download_chunks', Path(__file__).resolve().parents[1] / 'scripts/download_chunks.py')
downloads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloads)


def fake_session(monkeypatch, payload):
    calls = []

    class Response:
        status_code = 206
        headers = {'Content-Range': f'bytes 0-{len(payload)-1}/{len(payload)}'}

        def __enter__(self): return self
        def __exit__(self, *_): pass
        def raise_for_status(self): pass
        def iter_content(self, _): return iter([payload])

    class Session:
        def mount(self, *_args, **_kwargs): pass
        def close(self): pass
        def get(self, *_args, **kwargs):
            calls.append(kwargs['headers']['Range'])
            return Response()

    monkeypatch.setattr(downloads.requests, 'Session', Session)
    return calls


def test_corrupt_completed_range_is_downloaded_again(tmp_path, monkeypatch):
    payload = b'official artifact content'
    checksum = hashlib.sha256(payload).hexdigest()
    target = tmp_path / 'model'
    chunks = tmp_path / 'model.chunks'
    chunks.mkdir()
    (chunks / '00000.part').write_bytes(b'x' * len(payload))
    (chunks / '00000.sha256').write_text(checksum)
    calls = fake_session(monkeypatch, payload)

    downloads.download_chunks('https://example.test/blob', target, checksum, len(payload))

    assert target.read_bytes() == payload
    assert calls == [f'bytes=0-{len(payload)-1}']


def test_storage_failure_stops_without_retry(tmp_path, monkeypatch):
    payload = b'valid network response'
    calls = fake_session(monkeypatch, payload)

    def broken_storage(_fd):
        raise OSError('device disconnected')

    monkeypatch.setattr(downloads.os, 'fsync', broken_storage)
    with pytest.raises(OSError, match='device disconnected'):
        downloads.download_chunks('https://example.test/blob', tmp_path / 'model',
                                  hashlib.sha256(payload).hexdigest(), len(payload))
    assert len(calls) == 1
    assert not (tmp_path / 'model').exists()
    assert not (tmp_path / 'model.chunks/00000.sha256').exists()
