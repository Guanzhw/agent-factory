"""Build the fixed public ORX source with official digest-pinned Rust/Docker.

Requires an existing local Docker daemon. Downloads no credentials, changes no
host security settings, and runs no provider/model. The output hash must match
the reviewed Linux pin before this profile can execute it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

REVISION = 'f336b121525d99364e2dee4fe90b2784894a54e6'
ARCHIVE_SHA = '396ef8731e8531f676171640e04b05848c00cb23c9647ccd6cadbcbda9f9a62a'
RUST = 'rust:1.93.1-slim-trixie@sha256:c0a38f5662afdb298898da1d70b909af4bda4e0acff2dc52aea6360a9b9c6956'
BINARY_SHA = 'a847d07e8c4c3f2efc47c3549fd27f52c9999b46a21451d4c07ec12de292b8cd'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path, help='New task-owned build directory')
    parser.add_argument('--ca-bundle', type=Path, help='Optional existing trusted CA bundle, mounted read-only; TLS stays enabled')
    args = parser.parse_args()
    root = args.workspace.resolve()
    root.mkdir(parents=True, exist_ok=False)
    archive = root / 'source.zip'
    urllib.request.urlretrieve('https://codeload.github.com/alphaXiv/OpenResearch/zip/' + REVISION, archive)
    if sha(archive) != ARCHIVE_SHA:
        raise RuntimeError('Upstream archive differs from reviewed bytes')
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not (root / name).resolve().is_relative_to(root):
                raise RuntimeError('Archive path escaped build directory')
        bundle.extractall(root)
    source = root / ('OpenResearch-' + REVISION)
    expected = {'Cargo.toml': 'e430beec668ed34b9c171bc814dfae90bd5362a0ab5c598b6cfdde00a1380dda',
                'Cargo.lock': '5e9f1753089dcdba38ba9f750a0b8b4acc625d6e0f98e4f8f58927ede8719ee6'}
    for name, digest in expected.items():
        if sha(source / name) != digest:
            raise RuntimeError('Reviewed Cargo input changed')
    cache = root / 'cargo-cache'; cache.mkdir()
    command = ['docker', '--host', 'unix:///var/run/docker.sock', 'run', '--rm', '--cpus', '3', '--memory', '8g',
               '--user', f'{os.getuid()}:{os.getgid()}', '--workdir', '/src',
               '--mount', f'type=bind,source={source},target=/src',
               '--mount', f'type=bind,source={cache},target=/cargo-cache',
               '--env', 'CARGO_HOME=/cargo-cache', '--env', 'CARGO_BUILD_JOBS=3']
    if args.ca_bundle:
        command += ['--mount', f'type=bind,source={args.ca_bundle.resolve()},target=/cloud-ca.pem,readonly',
                    '--env', 'CARGO_HTTP_CAINFO=/cloud-ca.pem']
    command += [RUST, 'cargo', 'build', '--locked', '--release', '--bin', 'orx']
    subprocess.run(command, check=True)
    binary = source / 'target/release/orx'
    observed = sha(binary)
    result = {'revision': REVISION, 'archiveSha256': ARCHIVE_SHA, 'rustImage': RUST,
              'binarySha256': observed, 'binaryBytes': binary.stat().st_size, 'matchesReviewedPin': observed == BINARY_SHA}
    (root / 'build-receipt.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    if observed != BINARY_SHA:
        raise RuntimeError('Build differs: review provenance; never silently replace the approved runtime pin')


if __name__ == '__main__':
    main()
