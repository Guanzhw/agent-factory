export interface DemoProject { id: string; title: string; objective: string; status: 'active' | 'decision' | 'ended'; next: string; created: string }
export const projects: DemoProject[] = [
  { id: 'inference', title: '小模型推理加速', objective: '在固定精度约束下减少推理延迟', status: 'active', next: '检查数据划分并复核候选结果', created: '2026-10-18' },
  { id: 'augmentation', title: '数据增强策略', objective: '在相同数据预算下提高模型的泛化表现', status: 'decision', next: '选择数据方案并启动新实验', created: '2026-10-20' },
  { id: 'retrieval', title: '检索质量评估', objective: '评估检索排序对答案相关性的影响', status: 'ended', next: '查看结论与改进建议', created: '2026-10-15' },
];
export const statusNames = { active: '进行中', decision: '需要决定', ended: '已结束 · 未达标' };
export const records = [
  { id: '08', title: '数据划分与评估设置说明', author: '林若溪', date: '2026-10-20', category: '评估条件', text: '训练集与评估集采用不同随机种子分组。跨实验比较前，应核对样本集合、精度阈值及测量批次。', relevant: true },
  { id: '05', title: '小模型量化的负结果', author: '陈安', date: '2026-10-17', category: '负结果', text: '在此合成示例中，更激进的量化降低了延迟，但精度约束未满足。进程成功不等于研究达标。', relevant: true },
  { id: '03', title: '检索指标口径记录', author: '周宁', date: '2026-10-15', category: '实验记录', text: '记录检索任务的评价口径与样本版本。它不直接适用于推理加速项目，不会自动作为该项目的推荐证据。', relevant: false },
];
export type DemoMessage = { role: 'assistant' | 'user'; text: string; reference?: 'experiment' | 'record'; detail?: string };
export const initialMessages: DemoMessage[] = [
  { role: 'assistant', text: '实验12已运行完成，尚不能确认目标达成。', detail: '从当前结果看，候选方案在大部分区间降低了推理延迟，但仍有波动，需要复核数据划分和评估条件。', reference: 'experiment' },
  { role: 'assistant', text: '团队记录08使用了不同数据划分，我已关联供你核对。', reference: 'record' },
  { role: 'user', text: '接下来应该做什么？' },
  { role: 'assistant', text: '先复核评价条件，再决定下一轮实验。', detail: '1. 对比实验 12 与团队记录 08 的数据划分、评估集和指标计算方式，确认是否可以比较；\n2. 如有差异，按统一设置重新跑一次或做消融；\n3. 基于复核结果，决定是否调整方案并启动下一轮实验。' },
];

export function initialProjectMessages(id?: string): DemoMessage[] {
  return id === 'inference' ? initialMessages : [{ role: 'assistant', text: '这里是当前项目的演示讨论。请先明确评价标准与停止条件；本原型不会执行研究。' }];
}
