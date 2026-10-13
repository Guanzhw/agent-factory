import type { ComponentProps } from 'react';
import { PlanReviews } from '../../../web/PlanReviews.js';
import { ProjectCreationReview, projectCreationSummary } from './ProjectCreationReview.js';

/** Application-owned historical projection; this grants no approval or execution. */
export function ResearchPlanReviews(props: Omit<ComponentProps<typeof PlanReviews>, 'renderScope'>) {
  return <PlanReviews {...props} renderScope={review => {
    const value = projectCreationSummary(review);
    return value ? <ProjectCreationReview value={value}/> : null;
  }}/>;
}
