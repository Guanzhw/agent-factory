"""Trusted research adapter compatibility hooks.

Domain names, historical effect keys and research-shaped response fields live
here, never in Factory custody/accounting. These hooks observe or stop existing
work only; original identity, authorization and idempotency checks stay in the
existing adapters. No user-supplied module paths or callback registration.
"""
from fastapi import HTTPException


class ResearchRuntimeHooks:
    effect_suffix = ":orx-experiment-launch-v1"

    @staticmethod
    def policy_projection(plan):
        return {"allowExperiment": bool({"run_experiment", "orx_experiment_run"} & set(plan.get("tools", [])))}

    @classmethod
    def effect_held(cls, effect):
        if not str(effect.get("effect_key", "")).endswith(cls.effect_suffix):
            return False
        result = effect.get("result")
        proof = result.get("stopEvidence") if isinstance(result, dict) else None
        return not isinstance(proof, dict) or proof.get("allStopped") is not True

    @classmethod
    def reconcile_capacity(cls, store):
        # Upgrade safety: preserve immutable effect hashes and re-hold capacity.
        store.sql("""UPDATE af_tasks task SET terminal=FALSE WHERE task.terminal AND EXISTS(
            SELECT 1 FROM af_effects effect WHERE effect.task_id=task.id
            AND effect.effect_key=task.run_id || :suffix
            AND effect.result->'stopEvidence'->'allStopped' IS DISTINCT FROM 'true'::jsonb)""",
            suffix=cls.effect_suffix)

    @classmethod
    def ended_reason(cls, store, task):
        exact = (task.get("run_id") or "") + cls.effect_suffix
        if any(effect.get("effect_key") == exact and
               (effect.get("status") not in {"DONE", "CANCELLED"} or cls.effect_held(effect))
               for effect in store.effects(task["id"])):
            return "native-ended-unresolved-experiment"
        return None

    @staticmethod
    async def cancel(store, task):
        from .orx_experiment_tools import reclaim_orx_experiment
        await reclaim_orx_experiment(store.settings, store, task["id"])

    @staticmethod
    def project(settings, store, task, plan, events, job):
        evaluation = next((event["data"] for event in reversed(events) if event["type"] == "experiment_completed"), None)
        from .orx_experiment_tools import inspect_orx_experiment
        experiment = inspect_orx_experiment(store, task["owner_id"], task["id"])
        from .literature_evidence import APPLICATION_TOOLS, inspect_literature_evidence
        literature = (inspect_literature_evidence(store, task["owner_id"], task["id"])
                      if plan.get("application") in APPLICATION_TOOLS else None)
        from .synthesis_runtime import inspect_synthesis_evidence
        synthesis = inspect_synthesis_evidence(store, task["owner_id"], task["id"])
        comparison = store.comparisons.inspect(task["owner_id"], task["id"]) if store.comparisons is not None else None
        if synthesis is not None:
            job.update(validationStatus="受控综合；引用结构检查不等于科研结论验证", evidenceKind="controlled_model_synthesis")
        if comparison is not None:
            job.update(validationStatus="合成开发数据的受控比较；未验证科学结论", evidenceKind="controlled_comparison")
        if literature is not None:
            labels = {"ready": "书目与摘录已保存；不代表科研结论", "no-sources": "执行已结束，但未取得文献来源",
                      "pending": "等待文献证据产物", "invalid": "文献证据未通过完整性核对"}
            job.update(validationStatus=labels[literature["status"]], evidenceKind=literature["evidenceKind"])
        if experiment is not None:
            job.update(validationStatus="ORX 本地 toy 实验执行凭据；科学结论未验证", evidenceKind="toy_local_evaluation")
            if job.get("approvalDetail", {}).get("toolName") == "orx_experiment_run":
                provenance = experiment.get("provenance", {})
                limits = provenance.get("environment", {})
                scope = ("运行已封存的任务自有 ORX toy 实验："
                         f"最长 {limits.get('timeoutSeconds', '?')} 秒，"
                         f"输出上限 {limits.get('outputBytes', '?')} 字节；"
                         "源码和命令哈希见下方实验凭证。金额批准为零，无模型服务调用。")
                job["approvalDetail"]["scope"] = scope
                job["approval"]["scope"] = scope
        if experiment is not None:
            job["executionKind"] = "local-process"
            job["verificationStatus"] = "process-stop-confirmed" if (experiment.get("stopEvidence") or {}).get("allStopped") is True else "unverified"
        elif literature is not None:
            job["verificationStatus"] = "artifact-integrity-checked" if literature["status"] == "ready" else "unverified"
        return {**({"comparisonEvidence": comparison} if comparison is not None else {}),
                **({"synthesisEvidence": synthesis} if synthesis is not None else {}),
                **({"literatureEvidence": literature} if literature is not None else {}),
                "orxExperiment": experiment}, evaluation

    @staticmethod
    async def requirement(store, task, requirement, version, status, job, actions):
        tool = requirement.get("tool_execution") or {}
        if tool.get("tool_name") == "autoresearch_session_run" and tool.get("external_execution_required"):
            control = getattr(store, "autoresearch_session_control", None)
            if control is not None and status == "waiting_approval":
                try:
                    await control.completion(task, requirement)
                except (ValueError, HTTPException):
                    pass
                else:
                    scope = "原 ORX 会话和受管子任务已结束；继续同一原生运行，接收原始结果。"
                    job.update(approvalDetail={"id": requirement["id"], "version": version,
                        "scope": scope, "toolName": "autoresearch_session_run", "arguments": {}}, approval={"scope": scope})
                    actions.append("approve")
        elif tool.get("tool_name") == "research_process_run" and tool.get("external_execution_required"):
            runtime = getattr(store, "research_runtime", None)
            original = runtime._original(task["id"]) if runtime is not None else None
            if original is not None and runtime is not None:
                lease = runtime.resources.inspect(task["owner_id"], original["lease_id"])
                job["researchExecution"] = {"leaseId": lease["id"], "state": lease["state"],
                    "capacityHeld": lease["capacityHeld"], "gpuExecutionVerified": False,
                    "scientificConclusionVerified": False}
                if (status == "waiting_approval" and lease["state"] == "RECLAIMED"
                        and lease.get("executionStatus") == "COMPLETED" and lease.get("exitCode") == 0
                        and lease.get("gpuEvidence", {}).get("state") == "RELEASED"):
                    scope = "原研究进程已停止并释放租约；继续同一运行，仅接收执行凭据，不代表科研评分已验证。"
                    job.update(approvalDetail={"id": requirement["id"], "version": version,
                        "scope": scope, "toolName": "research_process_run", "arguments": {}}, approval={"scope": scope})
                    actions.append("approve")
        else:
            return False
        return True

    @staticmethod
    async def recovery(commands, task, snapshot, requirements, job, actions):
        if (str((snapshot.get("run", snapshot)).get("status")).lower() in {"paused", "runstatus.paused"}
                and (snapshot.get("queue") or {}).get("status") == "paused"
                and any((r.get("tool_execution") or {}).get("tool_name") == "orx_experiment_run"
                        for r in requirements)):
            try:
                recovery = await commands.approved_recovery(task, snapshot)
            except Exception:
                # Eligibility is advisory; absent/unverifiable original proof
                # cannot grant a repair or erase the existing paused receipt.
                pass
            else:
                job["recoveryDetail"] = recovery["recoveryDetail"]
                actions[:] = [action for action in actions if action != "approve"]
                actions.append("resume_approved")
