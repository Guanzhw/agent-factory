"""Fixed synthetic paired evaluator, packaged as inert task-owned process specs.

No process is started here. The caller must verify original process custody,
positive stop receipts and bounded output bytes before claiming actual execution.
The duplicated source argument is hashed as a reviewed source identity; proving
that it matches the executed -c program requires the original pinned ProcessSpec.
"""
from copy import deepcopy
import hashlib
import json

from .comparison_contract import compare_observations, fingerprint, validate_candidate, validate_contract
from .process_enforcement import ProcessLimits, ProcessSpec

REVISION = 'controlled-paired-linear-v1'
CHOICES = ('linear-v1', 'constant-v1', 'offset-v1', 'failure-v1', 'long-running-v1')
_DATA = [{'sampleId': f'sample-{index}', 'x': index - 3, 'y': 2 * (index - 3) + 1} for index in range(7)]
_BASELINE = {'slope': 0, 'intercept': 1, 'mode': 'normal'}
_CANDIDATES = {
    'linear-v1': {'slope': 2, 'intercept': 1, 'mode': 'normal'},
    'constant-v1': {'slope': 0, 'intercept': 1, 'mode': 'normal'},
    'offset-v1': {'slope': 2, 'intercept': 6, 'mode': 'normal'},
    'failure-v1': {'slope': 2, 'intercept': 1, 'mode': 'failure'},
    'long-running-v1': {'slope': 2, 'intercept': 1, 'mode': 'long-running'},
}
_METRIC = {'id': 'mean_squared_error', 'unit': 'squared-target-units', 'direction': 'minimize', 'minimumImprovement': 0}
_DATA_PATH = 'data/synthetic.json'
_EVALUATOR_PATH = 'evaluator.py'
_PREDICTOR_PATH = 'predictor.json'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _bytes(value):
    return _canonical(value).encode('utf-8')


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _choice(choice):
    if type(choice) is not str or choice not in CHOICES:
        raise ValueError('COMPARISON_FIXTURE_INVALID')


# Both source and source-identity bytes are fixed argv in ProcessSpec. The child
# never imports the supplied identity argument, reads a user file, or loads code.
_EVALUATOR_SOURCE = '''import hashlib,json,sys,time
if len(sys.argv)!=3:
    raise SystemExit(2)
choice=sys.argv[1]
data=json.loads(DATA_LITERAL)
predictors=json.loads(PREDICTORS_LITERAL)
baseline=json.loads(BASELINE_LITERAL)
if choice not in predictors:
    raise SystemExit(2)
candidate=predictors[choice]
def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
def digest(raw):
    return hashlib.sha256(raw).hexdigest()
def score(predictor):
    return sum((predictor["slope"]*row["x"]+predictor["intercept"]-row["y"])**2 for row in data)/len(data)
source_hash=digest(sys.argv[2].encode("utf-8"))
files={"data/synthetic.json":digest(canonical(data)),"evaluator.py":source_hash,"predictor.json":digest(canonical(baseline))}
candidate_files={**files,"predictor.json":digest(canonical(candidate))}
if candidate["mode"]=="long-running":
    time.sleep(4)
failed=candidate["mode"]=="failure"
result={"schema":1,"fixtureRevision":"controlled-paired-linear-v1","choice":choice,
"datasetSha256":files["data/synthetic.json"],"evaluatorSha256":source_hash,
"sampleSetSha256":digest(canonical([row["sampleId"] for row in data])),"sampleCount":len(data),
"seed":0,"metricId":"mean_squared_error","unit":"squared-target-units",
"baseline":{"status":"completed","value":score(baseline),"variantSha256":digest(canonical(files))},
"candidate":{"status":"failed" if failed else "completed","value":None if failed else score(candidate),"variantSha256":digest(canonical(candidate_files))}}
print(canonical(result).decode("utf-8"),flush=True)
raise SystemExit(0)
'''.replace('DATA_LITERAL', repr(_canonical(_DATA))).replace('PREDICTORS_LITERAL', repr(_canonical(_CANDIDATES))).replace('BASELINE_LITERAL', repr(_canonical(_BASELINE)))


def _files(predictor):
    return {_DATA_PATH: _digest(_bytes(_DATA)), _EVALUATOR_PATH: _digest(_EVALUATOR_SOURCE.encode()),
            _PREDICTOR_PATH: _digest(_bytes(predictor))}


def fixture_limits():
    return ProcessLimits(cpu_seconds=1, address_space_mb=128, file_size_bytes=16384, wall_seconds=5.0)


def input_manifest(choice):
    """Public reviewed input identity; no execution or authority is implied."""
    _choice(choice)
    return {'schema': 1, 'evidenceKind': 'synthetic_comparison_input', 'choice': choice,
            'dataset': {'path': _DATA_PATH, 'sha256': _digest(_bytes(_DATA)), 'origin': 'synthetic',
                'license': 'MIT', 'sampleSetSha256': _digest(_bytes([row['sampleId'] for row in _DATA])), 'sampleCount': 7},
            'evaluator': {'path': _EVALUATOR_PATH, 'sha256': _digest(_EVALUATOR_SOURCE.encode()), 'protocolRevision': REVISION},
            'baselineFiles': _files(_BASELINE), 'candidateFiles': _files(_CANDIDATES[choice]),
            'allowedChanges': [_PREDICTOR_PATH], 'metric': deepcopy(_METRIC), 'seed': 0,
            'resourceLimits': {'cpu': 1, 'memoryMb': 128, 'wallSeconds': 5, 'outputBytes': 16384}}


def fixture_contract(plan_fingerprint, material_refs):
    manifest = input_manifest('linear-v1')
    return validate_contract({'schema': 1, 'evidenceKind': 'offline_comparison_contract',
        'dataset': manifest['dataset'], 'evaluator': manifest['evaluator'],
        'baselineFiles': manifest['baselineFiles'], 'allowedChanges': [_PREDICTOR_PATH], 'metric': deepcopy(_METRIC),
        'seed': 0, 'authority': {'planFingerprint': plan_fingerprint, 'capabilities': ['compute:local'],
            'resourceLimits': {'cpu': 1, 'memoryMb': 128, 'wallSeconds': 5, 'outputBytes': 16384}},
        'materialRefs': deepcopy(material_refs)})


def fixture_candidate(contract, choice):
    _choice(choice)
    checked = validate_contract(contract)
    # A generic compatible-looking contract cannot redefine this fixed fixture.
    expected = fixture_contract(checked['authority']['planFingerprint'], checked['materialRefs'])
    if checked != expected:
        raise ValueError('COMPARISON_FIXTURE_INVALID')
    return validate_candidate(checked, {'schema': 1, 'contractSha256': fingerprint(checked),
        'authoritySha256': fingerprint(checked['authority']), 'files': _files(_CANDIDATES[choice])})


def fixture_spec(executable, sha256, choice):
    _choice(choice)
    return ProcessSpec(executable=executable, sha256=sha256,
        argv=('-I', '-S', '-c', _EVALUATOR_SOURCE, choice, _EVALUATOR_SOURCE))


def _expected_output(choice):
    manifest = input_manifest(choice)
    def score(predictor):
        return sum((predictor['slope'] * row['x'] + predictor['intercept'] - row['y'])**2 for row in _DATA) / len(_DATA)
    failed = choice == 'failure-v1'
    return {'schema': 1, 'fixtureRevision': REVISION, 'choice': choice,
        'datasetSha256': manifest['dataset']['sha256'], 'evaluatorSha256': manifest['evaluator']['sha256'],
        'sampleSetSha256': manifest['dataset']['sampleSetSha256'], 'sampleCount': 7, 'seed': 0,
        'metricId': _METRIC['id'], 'unit': _METRIC['unit'],
        'baseline': {'status': 'completed', 'value': score(_BASELINE), 'variantSha256': fingerprint(manifest['baselineFiles'])},
        'candidate': {'status': 'failed' if failed else 'completed', 'value': None if failed else score(_CANDIDATES[choice]),
                      'variantSha256': fingerprint(manifest['candidateFiles'])}}


def validate_output(raw: bytes, contract, candidate, choice):
    """Check complete fixed evaluator output; caller separately proves custody."""
    _choice(choice)
    expected_candidate = fixture_candidate(contract, choice)
    if candidate != expected_candidate:
        raise ValueError('COMPARISON_FIXTURE_INVALID')
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= 16384:
            raise ValueError
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError
                value[key] = item
            return value
        parsed = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
        expected = _expected_output(choice)
        if _canonical(parsed) != _canonical(expected):
            raise ValueError
        result_hash = _digest(raw)
        records = {}
        for side in ('baseline', 'candidate'):
            result = parsed[side]
            records[side] = {'schema': 1, 'contractSha256': fingerprint(contract),
                **{key: parsed[key] for key in ('datasetSha256', 'evaluatorSha256', 'sampleSetSha256', 'sampleCount', 'seed', 'metricId', 'unit')},
                **result, 'resultSha256': result_hash}
        return {**records, 'assessment': compare_observations(contract, candidate, records['baseline'], records['candidate'])}
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError, RecursionError):
        raise ValueError('COMPARISON_FIXTURE_INVALID') from None
