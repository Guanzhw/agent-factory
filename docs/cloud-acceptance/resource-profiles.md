# Whole-process-tree resource planning

These files are **conservative, synthetic planning examples**, not deployment settings,
benchmarks, measured concurrency limits, or claims that a host supports a particular
number of agents. No Agno, PostgreSQL, browser, model, or remote execution service is
started by this validator. Passing only establishes that the declared arithmetic fits.

The selected application baseline is Agno AgentOS **3.1.0** plus PostgreSQL. Remote
compute/sandbox execution remains a separate integration and acceptance concern;
selecting AgentOS does not implement a sandbox provider. A separate remote host needs
its own budget and admission checks. Never treat local headroom as a grant to remote
compute, or omit local client, proxy, or retained child-process costs because their
work also uses a remote service.

## Run without provisioning

Python 3.11 or newer, standard library only, from the repository root:

```sh
python3 cloud-validation/resource_profile.py cloud-validation/profiles/standard-32core-64gb.json
python3 cloud-validation/resource_profile.py cloud-validation/profiles/upper-54core-192gb.json
python3 -m unittest discover -s cloud-validation -p 'test_resource_profile.py' -v
```

The command reads local JSON files and writes a JSON report to standard output. It
does not install dependencies, contact services, start child processes, collect
credentials, modify cgroups, or provision/deploy anything. Exit 0 means valid
arithmetic; exit 2 means invalid input or overcommit. Invalid reports go to standard
error. No runtime/load evidence is implied by either the profile or the unit tests.

## Units and illustrative reservations

- CPU is expressed in scheduling cores, with at most six decimal places. Do not
  infer physical cores, dedicated cores, frequency, or performance from this number
- Host `memory_gb` is **decimal GB**: one GB = 1,000,000,000 bytes
- Reservations use whole **MiB**: one MiB = 1,048,576 bytes
- Therefore 64 GB = 61,035.15625 MiB, and 192 GB = 183,105.46875 MiB;
  neither is 64/192 GiB
- Positive numbers are required. Counts and MiB are integers; booleans, strings,
  NaN, infinity, duplicates, unknown fields, and unsupported versions are rejected

| Synthetic profile | Nominal CPU / memory | OS reserve | PostgreSQL reserve | Control reserve | Example worker tree grants | Unallocated after all grants |
| --- | --- | --- | --- | --- | --- | --- |
| Standard | 32 cores / 64 GB | 2 cores / 4,096 MiB | 2 cores / 8,192 MiB | 2 cores / 4,096 MiB | 4 replicas × (4 cores / 8,192 MiB) | 10 cores / 12,460,392,448 bytes |
| Upper | 54 cores / 192 GB | 4 cores / 8,192 MiB | 4 cores / 16,384 MiB | 2 cores / 8,192 MiB | 8 replicas × (4 cores / 12,288 MiB) | 12 cores / 54,561,046,528 bytes |

Replica counts are arithmetic fixtures. They are **not supported concurrency**. The
unallocated amount is a planning margin, not permission to schedule additional work.
The OS/PostgreSQL/control numbers are also unmeasured assumptions, not PostgreSQL
configuration guidance. Reserve connection pools, per-query/process memory, page
cache, WAL/checkpoints, backups, metrics/logging, and peaks when replacing these
assumptions. If services move to other hosts, document their independent allocations
rather than silently spending their former reserve.

## Strict schema and accounting rules

Use the JSON examples as schema-complete templates. Version 1 accepts only:

- Top level: `schema_version`, `name`, `purpose`, `runtime`, `host`, `reserved`, `workers`
- `purpose`: exactly `synthetic-planning-example`; outputs always keep the
  synthetic-arithmetic label
- `runtime`: the pinned engine/version/persistence and boolean
  `remote_compute_separate` shown in the examples. This is selection metadata,
  not an import, install, or compatibility test
- `host`: positive `cpu_cores` and decimal `memory_gb`
- `reserved`: exactly `os`, `postgres`, and `control`; each has positive `cpu_cores`
  and whole `memory_mib`
- Each worker group: unique `name`, positive integer `replicas`, `tree_budget`, and
  a `process_tree` whose root `kind` is `runtime`
- Each process node: unique `name` within its worker tree, `kind`, `state`, own
  `reservation`, `children`, and optional `subtree_budget`
- Kinds: `runtime`, `tool`, `browser`, `mcp`, `experiment`. State: `running` or `waiting`
- Every budget/reservation: exactly `cpu_cores` and `memory_mib`

Each process node represents one budgeted operating-system process, including
external tools, browser helpers/renderers, MCP subprocesses, and experiment
processes. Expand the inventory for the real process topology; do not mistake a
single browser launcher for all processes it creates. The examples explicitly
include a browser child but do not claim that this is a complete real browser tree.
A real fork, helper, or concurrent experiment cannot be omitted just because the
logical agent is waiting. Removed/terminated processes may be removed from a later
snapshot only after teardown has been verified; `waiting` does not mean terminated.

For each worker replica:

1. Sum every node's **own reservation**, including all descendants in every state
2. Require the sum to fit the worker's `tree_budget`
3. At every optional `subtree_budget`, require that node and all its descendants
   together to fit that shared cap
4. A child cap never adds resources to an ancestor cap. Every ancestor remains
   binding. Nested caps are not added to inventory or host grants

For the host:

```text
reserved OS + reserved PostgreSQL + reserved control
  + sum(worker replicas × complete worker tree_budget)
  <= host budget                    [independently for CPU and memory]
```

Host admission charges the **whole tree grant**, including declared slack, rather
than only today's process inventory. This avoids admitting two workers against
headroom already promised to one. Shared parent/child budgets are subdivisions of
that grant, never independently additive grants. One process must be represented
once; shared cross-worker services belong in infrastructure or a separate explicit
accounting model, not in multiple process trees.

Bounds prevent accidental/unbounded inputs: 1 MiB input file, 32 levels below a
worker root, 4,096 process nodes per tree, 1,000,000 replicas per group, CPU/GB up to
1,000,000, and reservation MiB up to 1,000,000,000. These parser ceilings are not
supported system sizes. Arithmetic uses integer bytes and integer millionths of a
CPU so floating-point rounding cannot admit an overcommitted boundary.

## Read-only existing-host capacity check

Use an already authorized host; do not create a VM, buy capacity, or change access.
Collect a sanitized snapshot through its existing read-only access. Do not copy
credentials, environment dumps, command lines containing secrets, private documents,
process payloads, or account identifiers into this repository.

Useful Linux read-only observations include:

```sh
getconf _NPROCESSORS_ONLN
awk '/^MemTotal:/ {print $2 * 1024}' /proc/meminfo
cat /proc/self/cgroup
cat /proc/self/mountinfo
```

These are **inputs to investigation**, not a ready effective-capacity answer. The
CPU count and MemTotal may describe the physical host while the workload has a much
smaller quota. For the intended workload cgroup, inspect its actual mount/path and
all visible ancestors:

- cgroup v2: `cpu.max`, `cpuset.cpus.effective`, `memory.max`, `memory.current`, and
  any relevant `memory.high`; `max` is unbounded, not zero
- cgroup v1 equivalents: CPU quota/period, effective cpuset, and memory limits;
  account for controller mount layout and inherited limits
- Determine effective CPU from the minimum of the allocation, affinity/cpuset, and
  ancestor quota/period. Determine effective memory from the minimum of usable
  machine memory, allocation, and ancestor hard limits
- Check the scheduler/container/VM allocation through existing read-only access as
  well. A cgroup namespace may hide stricter or shared ancestor allocations. If
  effective limits cannot be established, record the check as blocked
- Separately account for other tenants and host services. A CPU limit is not a CPU
  reservation; memory capacity is not the same as currently available memory.
  Neither a point-in-time reading nor an idle host establishes safe sustained load

Store the verified effective limits outside the repository in a JSON object with
exactly `cpu_cores` (positive number), `memory_bytes` (positive integer), and `source`
(a short, non-sensitive description of how they were established). A schematic
example, deliberately too small for either supplied profile:

```json
{
  "cpu_cores": 8,
  "memory_bytes": 16000000000,
  "source": "synthetic rejection fixture; not a host observation"
}
```

Then compare without connecting to anything or changing the host:

```sh
python3 cloud-validation/resource_profile.py \
  cloud-validation/profiles/standard-32core-64gb.json \
  --capacity /path/to/sanitized-effective-capacity.json
```

The validator requires the entire nominal profile host to fit the snapshot, not
merely the current worker inventory. The sample above must fail. Snapshot data is
operator-supplied and is not authenticated, freshness-checked, or collected by this
CLI. A successful comparison is explicitly labelled as an observation comparison;
it does not prove spare capacity, isolation, fair scheduling, hard-limit enforcement,
or measured throughput. When actual usable capacity is lower than the advertised
machine label, revise planning assumptions and reserve margins before attempting a
runtime test.

## Evidence needed before real admission or capacity claims

Run measurements only in an authorized existing environment with an explicitly
approved test scope and cost ceiling. This document and command do not authorize
paid models/compute, new credentials, persistent access, public exposure, or deployment.

1. Record exact runtime/container/image versions, Python, AgentOS 3.1.0, PostgreSQL,
   browser/MCP/tool versions, effective limits, and sanitized workload configuration
2. Measure the complete process tree/cgroup, not only the Python parent. Capture
   memory current/peak, RSS/PSS where useful, CPU use and throttling, process/PID
   counts, file descriptors, DB connection/query memory, and host/DB/control peaks
3. Exercise representative idle, running, waiting, nested child, browser, MCP,
   tool, and experiment paths. Include concurrent peaks, cancellation, failure,
   reconnect, recovery, and retained processes while an agent awaits input
4. Test actual enforcement and admission races: atomic shared tree allocation,
   no oversubscription during fan-out/retry, rejected excess work, bounded queues,
   teardown/reclaim, and no premature budget release on waiting or parent exit
5. Define a measured success criterion and observation window. Report latency,
   errors/timeouts, throughput, OOM/throttle behavior, and recovery under that exact
   workload and hardware; do not generalize a synthetic pass into “N agents”
6. Revise reservations from measured peaks plus explicit safety margins. Keep raw
   private logs local; publish only original safe code and sanitized evidence summaries

This component does not enforce OS limits, discover an actual process tree, provide
an admission controller, schedule workers, measure remote hosts, or validate live
AgentOS/PostgreSQL compatibility. Network, disk/IOPS, PIDs, descriptors, GPU/VRAM,
model/provider quotas, costs, and cross-host contention need separate bounded checks.
