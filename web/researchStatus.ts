import type { PersonalSession } from './personalAgentApi.js';

export interface ResearchStatusInput {
  ready: boolean;
  submitting: boolean;
  commandPending: boolean;
  attachmentPending: boolean;
  session?: PersonalSession;
  connectionUnavailable: boolean;
  canRun: boolean;
}

export function researchStatus(input: ResearchStatusInput) {
  const state = (tone: string, title: string, explanation: string) => ({ tone, title, explanation });
  if (!input.ready) return state('neutral', '正在读取研究连接', '正在核对你的项目与会话，尚未提交研究。');
  if (input.submitting) return state('waiting', '正在提交研究目标', '正在等待本次提交的回执，请勿重复提交。');
  if (input.commandPending || input.session?.state === 'ack_unknown') return state('unknown', '研究请求待核对', '本次提交结果尚未确认。保留原请求只读核对；页面同步成功或看到旧回复都不能证明本次已受理。');
  if (input.attachmentPending) return state('unknown', '会话关联待核对', '只读关联结果尚未确认，没有因此发送研究目标。');
  if (input.connectionUnavailable) return state('unavailable', '研究连接待恢复', '已有回复和草稿保留；恢复连接前不能发送新的研究目标。');
  if (input.session?.activeRequestId) return state('waiting', '等待远端回复', '沿原会话只读查看回复。本轮结果尚未确认，不重复发送目标。');
  const latest = input.session?.observation?.messages.filter(message => message.role === 'assistant').at(-1);
  if (latest) {
    if (!latest.events.some(event => event.type === 'text' && event.text.trim())) return latest.events.some(event => event.type === 'tool')
      ? state('waiting', '已观察到工具记录', '还没有可阅读的研究回复；工具记录不代表研究结论已完成。')
      : state('waiting', '等待远端回复', '远端消息尚无可阅读内容，也没有工具记录。');
    if (!latest.completed) return state('waiting', '回复正在更新', '已看到部分远端回复，服务尚未报告本条回复完成。');
    return state('observed', '已观察到回复', '这是远端会话回复。研究结论仍需结合原始材料核实。');
  }
  if (input.session && !input.canRun) return state('neutral', '只能查看已有研究', '此连接尚不能发送新的研究目标；已有记录仍可查看。');
  if (input.session) return state('neutral', '尚未取得研究回复', '可以填写下一步目标，或只读刷新查看原会话记录。');
  if (input.canRun) return state('ready', '可以开始研究', '填写目标并点击开始后，才会创建会话并发送目标。');
  return state('neutral', '首次设置待完成', '先选择你的服务与研究项目。空服务需要明确保存位置和服务上的模型；目标草稿会保留。');
}
