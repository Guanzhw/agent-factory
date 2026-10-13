import { useState } from 'react';
import type { ComposerSeed } from '../../../web/ApplicationComposer.js';
import type { Artifact } from '../../../web/models.js';
import { TaskDetail, type TaskDetailProps } from '../../../web/TaskWorkspace.js';
import { researchApi } from './api.js';
import { ComparisonReport } from './ComparisonPanel.js';
import { EvaluationEvidence } from './EvaluationEvidence.js';
import { LiteratureEvidencePanel } from './LiteratureEvidence.js';
import { jobDisplayTitle } from './nativeCommandDisplay.js';
import { NativeCommandResult, personalCommandRequest, taskResultSource } from './NativeCommandResult.js';
import { OrxExperimentPanel } from './OrxExperiment.js';
import { orxExperimentState } from './orxExperimentState.js';
import { SynthesisJourney } from './SynthesisJourney.js';
import type { SynthesisSnapshot } from './synthesisJourneyState.js';
import { SynthesisReport } from './SynthesisReport.js';

export function ResearchTaskDetail(props: TaskDetailProps) {
  const { detail, busy, ownerId, onCompose } = props;
  const { job } = detail;
  const [capturedArtifacts, setCapturedArtifacts] = useState<Artifact[]>([]);
  const artifacts = [...new Map([...capturedArtifacts, ...detail.artifacts].map(artifact => [artifact.id, artifact])).values()];
  const orxState = orxExperimentState(detail);
  const orxApproval = job.approvalDetail?.toolName === 'orx_experiment_run';
  const launchProofVerified = !orxApproval || orxState.kind === 'verified' && orxState.sourceVerified && orxState.experiment.taskId === job.id && !!orxState.experiment.projectId && !!orxState.experiment.experimentId;

  function onSourceSnapshot(snapshot: SynthesisSnapshot) {
    const seed: ComposerSeed = {
      key: snapshot.id,
      applicationId: 'source-grounded-synthesis-fixture-v1',
      goal: snapshot.question,
      sourceSnapshotRef: { id: snapshot.id, fingerprint: snapshot.fingerprint },
    };
    onCompose?.(seed, '来源已固定到装配输入，请检查应用与本人连接，再生成方案。');
    document.getElementById('composer-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const evidenceAfter = <>
    <LiteratureEvidencePanel detail={detail}/>
    {onCompose && job.status === 'completed' && detail.literatureEvidence !== undefined && <SynthesisJourney key={job.id} ownerId={ownerId} sourceTaskId={job.id} api={researchApi.synthesis} onSnapshot={onSourceSnapshot} disabled={!!busy}/>}
    <SynthesisReport evidence={detail.synthesisEvidence}/>
    <ComparisonReport evidence={detail.comparisonEvidence} ownerId={ownerId} taskId={job.id} planId={job.planId ?? ''} artifacts={artifacts}/>
    <OrxExperimentPanel detail={detail}/>
    {detail.orxExperiment === undefined && <EvaluationEvidence detail={detail}/>}
  </>;

  return <TaskDetail
    {...props}
    title={jobDisplayTitle(job)}
    source={taskResultSource(detail)}
    artifacts={artifacts}
    evidenceBefore={<NativeCommandResult detail={detail} onArtifacts={setCapturedArtifacts}/>}
    evidenceAfter={evidenceAfter}
    approvalAllowed={launchProofVerified}
    approvalNotice={orxApproval ? <p className="quiet">本次请求将运行任务自有的真实 ORX toy 实验。先<a href="#orx-experiment-evidence">核对下方固定源码、命令与数据哈希</a>；任务预算与停止记录由服务端保持。{!launchProofVerified && ' 当前来源凭据尚未完整核对，暂不能同意运行。'}</p> : undefined}
    completedNotice={personalCommandRequest(detail) ? '命令任务已结束，研究回复与错误见下方原会话记录。' : <>执行已完成。研究结论是否通过验证：{job.validationStatus ?? '后端尚未提供验证结论'}。</>}
  />;
}
