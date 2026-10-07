-- Pinned Factory/Agno 3.1 root-only research profile. Read docs before use.
-- Required psql variables: original_task_id, original_owner_id, original_request_id.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '2s';
SET LOCAL search_path = pg_catalog;
WITH
pin AS (
 SELECT :'original_task_id'::text task_id, :'original_owner_id'::text owner_id,
        :'original_request_id'::text request_id
),
root AS (
 SELECT t.* FROM public.af_tasks t, pin p WHERE t.id=p.task_id
),
-- No owner filter here: conflicting/cross-owner records must be detected.
plan AS (
 SELECT p.* FROM public.af_plans p JOIN root r ON r.plan_id=p.id
),
links AS (
 SELECT l.* FROM public.af_delegation_links l, pin p
 WHERE l.root_id=p.task_id OR l.parent_id=p.task_id OR l.child_id=p.task_id
),
runs AS (
 SELECT r.* FROM ai.agno_runs r, pin p
 WHERE r.session_id=p.task_id OR r.run_id IN (SELECT run_id FROM root)
    OR r.run_data #>> '{session_state,factory_envelope,task_id}'=p.task_id
    OR (r.run_data #>> '{session_state,factory_envelope,user_id}'=p.owner_id
        AND r.run_data #>> '{session_state,factory_envelope,request_id}'=p.request_id)
),
jobs AS (
 SELECT j.*, j.payload #> '{kwargs,session_state,factory_envelope}' AS envelope
 FROM ai.agno_jobs j, pin p
 WHERE j.session_id=p.task_id OR j.id IN (SELECT run_id FROM root)
    OR j.id IN (SELECT run_id FROM runs)
    OR j.payload #>> '{kwargs,session_state,factory_envelope,task_id}'=p.task_id
    OR (j.payload #>> '{kwargs,session_state,factory_envelope,user_id}'=p.owner_id
        AND j.payload #>> '{kwargs,session_state,factory_envelope,request_id}'=p.request_id)
),
-- A first edge is enough to disprove this root-only profile. Includes cycles,
-- dangling parents, foreign-session children and edges originating in tickets
-- for which no run row was persisted yet. No LIMIT or latest-row selection.
edges AS (
 SELECT r.run_id FROM ai.agno_runs r
 WHERE (r.run_id IN (SELECT run_id FROM runs UNION SELECT id FROM jobs)
        AND r.parent_run_id IS NOT NULL)
    OR r.parent_run_id IN (SELECT run_id FROM runs UNION SELECT id FROM jobs)
    OR (r.run_id IN (SELECT run_id FROM runs UNION SELECT id FROM jobs)
        AND jsonb_path_exists(r.run_data,'$.**.parent_run_id ? (@ != null)'))
    OR EXISTS(SELECT 1 FROM jsonb_path_query(r.run_data,'$.**.parent_run_id') v
        WHERE v #>> '{}' IN (SELECT run_id FROM runs UNION SELECT id FROM jobs))
 UNION ALL
 SELECT j.id FROM ai.agno_jobs j WHERE
   (j.id IN (SELECT id FROM jobs) AND
       jsonb_path_exists(j.payload,'$.**.parent_run_id ? (@ != null)'))
   OR EXISTS(SELECT 1 FROM jsonb_path_query(j.payload,'$.**.parent_run_id') v
       WHERE v #>> '{}' IN (SELECT run_id FROM runs UNION SELECT id FROM jobs))
),
sessions AS (
 SELECT s.* FROM ai.agno_sessions s, pin p
 WHERE s.session_id=p.task_id
    OR s.session_data #>> '{session_state,factory_envelope,task_id}'=p.task_id
),
checks AS (
 SELECT 'exact_original_terminal_task' name,
   (SELECT count(*)=1 FROM root r, pin p WHERE r.owner_id=p.owner_id
      AND r.request_id=p.request_id AND r.terminal IS TRUE
      AND r.run_id IS NOT NULL) ok
 UNION ALL SELECT 'persisted_plan_is_exact_root_only_profile',
   (SELECT count(*)=1 FROM plan q CROSS JOIN pin p WHERE q.owner_id=p.owner_id
    AND q.body->>'id'=q.id AND q.body->>'ownerId'=p.owner_id
    AND q.body->>'application'='research-process-fixture-v1'
    AND q.body #>> '{applicationRef,id}'='research-process-fixture-v1'
    AND q.body->>'mode'='controlled-fixture'
    AND q.body->'tools'='["research_process_run"]'::jsonb
    AND q.body->'capabilities'='["compute:local"]'::jsonb
    AND (NOT q.body ? 'delegation' OR q.body->'delegation' IN ('null'::jsonb,'{}'::jsonb))
    AND (NOT q.body ? 'remoteHandoff' OR q.body->'remoteHandoff' IN ('null'::jsonb,'{}'::jsonb)))
 UNION ALL SELECT 'no_factory_delegation_or_unresolved_intent', NOT EXISTS(SELECT 1 FROM links)
 UNION ALL SELECT 'original_ticket_present', EXISTS(
   SELECT 1 FROM jobs j JOIN root r ON j.id=r.run_id)
 UNION ALL SELECT 'all_related_tickets_terminal_and_exact',
   NOT EXISTS(SELECT 1 FROM jobs j CROSS JOIN pin p CROSS JOIN root r WHERE
     j.session_id IS DISTINCT FROM p.task_id OR j.user_id IS DISTINCT FROM p.owner_id
     OR j.component_type IS DISTINCT FROM 'agent' OR j.component_id IS DISTINCT FROM 'factory-executor'
     OR j.job_type IS DISTINCT FROM 'run'
     OR j.status NOT IN ('completed','failed','cancelled') OR j.status IS NULL
     OR j.envelope IS DISTINCT FROM jsonb_build_object('plan_ref',r.plan_id,
       'user_id',p.owner_id,'task_id',p.task_id,'request_id',p.request_id))
 UNION ALL SELECT 'no_native_parent_or_child_edges', NOT EXISTS(SELECT 1 FROM edges)
 UNION ALL SELECT 'persisted_runs_terminal_owned_and_ticketed',
   NOT EXISTS(SELECT 1 FROM runs r CROSS JOIN pin p WHERE
     r.session_id IS DISTINCT FROM p.task_id OR r.user_id IS DISTINCT FROM p.owner_id
     OR r.agent_id IS DISTINCT FROM 'factory-executor' OR r.run_type IS DISTINCT FROM 'agent'
     OR upper(r.status) NOT IN ('COMPLETED','ERROR','CANCELLED') OR r.status IS NULL
     OR NOT EXISTS(SELECT 1 FROM jobs j WHERE j.id=r.run_id))
 UNION ALL SELECT 'session_provenance_if_created',
   NOT EXISTS(SELECT 1 FROM sessions s CROSS JOIN pin p WHERE
     s.session_id IS DISTINCT FROM p.task_id OR s.user_id IS DISTINCT FROM p.owner_id
     OR s.agent_id IS DISTINCT FROM 'factory-executor' OR s.session_type IS DISTINCT FROM 'agent')
   AND (NOT EXISTS(SELECT 1 FROM runs) OR EXISTS(SELECT 1 FROM sessions))
)
SELECT jsonb_build_object(
 'schemaVersion',1,
 'profile','factory-research-root-only',
 'status',CASE WHEN bool_and(ok) THEN 'PASS' ELSE 'UNKNOWN' END,
 'checks',jsonb_object_agg(name,ok),
 'taskCount',(SELECT count(*) FROM root),
 'relatedTicketCount',(SELECT count(*) FROM jobs),
 'persistedRunCount',(SELECT count(*) FROM runs),
 'factoryLinkCount',(SELECT count(*) FROM links),
 'nativeEdgeCount',(SELECT count(*) FROM edges),
 'descendants',CASE WHEN bool_and(ok) THEN 'NO_DESCENDANTS_OF_ORIGINAL_ROOT' ELSE 'NOT_ESTABLISHED' END,
 'resourceReleaseVerified',false,
 'newAttemptAuthorizedByThisQuery',false
) AS readonly_queue_audit FROM checks;
ROLLBACK;
