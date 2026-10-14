import type { InstalledApplication } from '../../../web/ApplicationCatalog.js';

export const researchApplication = {
  id: 'openresearch',
  name: 'OpenResearch',
  description: '开展研究，管理项目与会话，查看进度和结果。',
  entry: { tab: 'openresearch' },
} as const satisfies InstalledApplication;
