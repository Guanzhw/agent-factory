"""Fresh original baseline custody reader, never a publication or dispatch path.

The operator supplies a read-only existing-service context factory. It must
reconstruct original targets over the original database without modifying its
policy. No service bootstrap, old package import, or trusted numeric shortcut is
performed here. Current compatible verifier classes authenticate old receipts.
"""
import asyncio
from contextlib import AbstractContextManager
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Callable

from agent_factory.research_evaluation import validate_evaluation_contract
from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_manifest import manifest_fingerprint
from research_candidate_baseline import build_baseline_snapshots, verify_retained_baseline
from run_research_baseline import config_from_bytes, read_private, unique

ERROR = 'AUTORESEARCH_RETAINED_BASELINE_INVALID'


def require(value):
    if not value:
        raise ValueError(ERROR)


def _json(raw):
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError(ERROR)))


class RetainedBaselineReader:
    """Awaitable reader with a fresh service context and original files per call.

    service_factory(captured) returns a synchronous context manager yielding an
    exact ResearchEvaluationService. `captured` includes originalConfig,
    snapshots, contract, receipt and runConfig. The factory must open existing
    original state read-only, preserve its policy, and reconstruct original
    providers from snapshots using explicitly pinned scientific runtime bytes.
    It is operator code, never model-supplied configuration.
    """
    def __init__(self, config_file, evaluation_receipt_file, training_run_config_file, *,
                 expected_manifest_sha256, owner_id,
                 service_factory: Callable[[dict], AbstractContextManager[ResearchEvaluationService]]):
        require(type(expected_manifest_sha256) is str
            and re.fullmatch('[a-f0-9]{64}', expected_manifest_sha256) is not None
            and type(owner_id) is str and 1 <= len(owner_id) <= 200
            and all(ord(c) >= 32 and ord(c) != 127 for c in owner_id)
            and callable(service_factory))
        paths = (config_file, evaluation_receipt_file, training_run_config_file)
        require(all(isinstance(path, (str, Path)) and Path(path).is_absolute()
            and '..' not in Path(path).parts for path in paths))
        self.paths = tuple(Path(path) for path in paths)
        self.fingerprint, self.owner, self.service_factory = expected_manifest_sha256, owner_id, service_factory

    def _load(self):
        original = config_from_bytes(read_private(self.paths[0], 2 * 1024**2))
        workspace = Path(original['workspace'])
        require(self.paths[1] == workspace / 'evaluation-receipt.json'
            and self.paths[2] == workspace / 'training-program' / 'run-config.json')
        receipt = _json(read_private(self.paths[1], 16 * 1024**2))
        run_config = _json(read_private(self.paths[2], 16 * 1024**2))
        # This existing capture reads original seals, interpreter contract and
        # custody journals. Snapshots remain untrusted until the verifier below.
        captured = build_baseline_snapshots(original)
        require(captured['receipt'] == receipt and captured['runConfig'] == run_config)
        contract = validate_evaluation_contract(captured['contract'])
        require(manifest_fingerprint(contract['comparisonManifest']) == self.fingerprint
            and contract['training']['ownerId'] == self.owner
            and contract['evaluatorExecution']['ownerId'] == self.owner)
        return deepcopy({**captured, 'originalConfig': original, 'contract': contract})

    def _verify_once(self):
        captured = self._load()
        with self.service_factory(deepcopy(captured)) as service:
            require(type(service) is ResearchEvaluationService)
            # This entire function runs in a worker thread, so a private event
            # loop never nests in Factory's active event loop. Cancellation of
            # the awaiting task cannot authorize any dispatch from this reader.
            return asyncio.run(verify_retained_baseline(service=service, owner=self.owner,
                contract=captured['contract'], retained_receipt=captured['receipt'],
                expected_manifest_sha256=self.fingerprint))

    async def __call__(self):
        return deepcopy(await asyncio.to_thread(self._verify_once))
