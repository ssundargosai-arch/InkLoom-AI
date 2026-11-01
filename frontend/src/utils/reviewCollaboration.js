export function canStartReviewCollaboration({
  loading,
  error,
  loadedReviewId,
  reviewId,
  review,
  user,
}) {
  return (
    !loading &&
    !error &&
    review != null &&
    String(loadedReviewId) === String(reviewId) &&
    ["admin", "reviewer", "contributor"].includes(user?.role)
  );
}

export function isReviewerAssignedToStage(assignments, reviewerId, stageNumber) {
  if (!Array.isArray(assignments) || reviewerId == null || stageNumber == null) {
    return false;
  }

  return assignments.some(
    (assignment) =>
      Number(assignment.id ?? assignment.reviewer_id) === Number(reviewerId) &&
      Number(assignment.stage_number) === Number(stageNumber),
  );
}
