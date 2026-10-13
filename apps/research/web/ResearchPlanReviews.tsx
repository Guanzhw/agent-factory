import type { ComponentProps } from 'react';
import { PlanReviews, type PlanReviewScope } from '../../../web/PlanReviews.js';
import { ProjectCreationReview, projectCreationSummary, needsProjectCreationSummary } from './ProjectCreationReview.js';

export const researchReviewScope: PlanReviewScope = {
  canApprove: review => !needsProjectCreationSummary(review) || !!projectCreationSummary(review),
  render: review => {
    const value = projectCreationSummary(review);
    return value ? <ProjectCreationReview value={value}/> : needsProjectCreationSummary(review) ? <p role="alert" className="error-message">固定项目创建输入与费用范围无法核对，暂不能同意方案。请刷新审查。</p> : null;
  },
  error: '固定项目创建范围无法核对，请刷新后审阅。',
};

export function ResearchPlanReviews(props: Omit<ComponentProps<typeof PlanReviews>, 'scope'>) {
  return <PlanReviews {...props} scope={researchReviewScope}/>;
}
