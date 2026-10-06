"""Inert upstream source provenance. No imports, downloads or execution of source."""
from copy import deepcopy
import hashlib

REPOSITORY = "https://github.com/karpathy/autoresearch"
COMMIT = "228791fb499afffb54b46200aca536f79142f117"
SOURCE_SHA256 = {'README.md': '3958fd4195ac2f98ed35c4eaa4f3028a335165ee24945e96426c408d25793a41', 'prepare.py': '4f2ba9cbb8ba8c4a3d35be405a913e2f3be3af9aea103ed52ef7b2a662058150', 'train.py': '2954175f4ac42ad65164aef40910ef953789abcd05a5cc886ac9ba5a00814414', 'program.md': '86cf987a5c381e46eefe0d0a82765223fd766d8d7acdc2afacfbbce15ecacece', 'pyproject.toml': '675c150a9e0769f0e39a43eb7d836934266fa348d6e2403521f1ff99f9b9f1af', 'uv.lock': '03174c5cce6387418c5b6cc9bbe8f71ad0ae1e1d6fedeaecae5cdcf7321da0a3'}


def source_profile():
    """Return source facts, explicitly separate from unverified runtime identities."""
    return deepcopy({
        "schema": 1,
        "evidenceKind": "offline_research_source_profile",
        "repository": REPOSITORY,
        "commit": COMMIT,
        "sourceSha256": SOURCE_SHA256,
        "allowedChanges": ["train.py"],
        "trainingBudgetSeconds": 300,
        "metric": {"id": "val_bpb", "direction": "minimize"},
        "licenseEvidence": "README declares MIT; no LICENSE file retrieved",
        "executionVerified": False,
        "scientificConclusionVerified": False,
        "executionBlockers": [
            "license_notice_review",
            "dataset_revision_and_shard_hashes",
            "tokenizer_and_token_bytes_hashes",
            "runtime_kernel_revision_and_license",
            "installed_environment_identity",
            "trusted_independent_evaluation",
            "same_device_baseline_identity",
            "gpu_admission_and_positive_release",
            "native_long_running_execution",
        ],
    })


def verify_upstream_source(files):
    """Hash supplied source bytes, never open paths or execute upstream code.

    Requires the six pinned files exactly. A separate reviewed local adaptation
    may change train.py only; this check always refers to the original upstream.
    """
    if type(files) is not dict or set(files) != set(SOURCE_SHA256):
        raise ValueError("RESEARCH_SOURCE_INVALID")
    for path, expected in SOURCE_SHA256.items():
        data = files[path]
        if (type(data) is not bytes or len(data) > 4 * 1024 * 1024
                or hashlib.sha256(data).hexdigest() != expected):
            raise ValueError("RESEARCH_SOURCE_INVALID")
    return source_profile()
