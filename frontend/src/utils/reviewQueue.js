export function getReviewQueuePageCount(total, pageSize) {
  const safeTotal = Number.isFinite(Number(total))
    ? Math.max(0, Number(total))
    : 0;
  const safePageSize = Number.isFinite(Number(pageSize))
    ? Math.max(1, Number(pageSize))
    : 1;
  return Math.max(1, Math.ceil(safeTotal / safePageSize));
}

export function getReviewQueuePageOffset(page, pageSize, total) {
  const pageCount = getReviewQueuePageCount(total, pageSize);
  const safePage = Number.isFinite(Number(page))
    ? Math.min(Math.max(0, Number(page)), pageCount - 1)
    : 0;
  return safePage * Math.max(1, Number(pageSize) || 1);
}

export function updateReviewQueueState(current, changes) {
  const next = { ...current, ...changes };
  if (
    (changes.query !== undefined && changes.query !== current.query) ||
    (changes.status !== undefined && changes.status !== current.status)
  ) {
    next.page = 0;
  }
  return next;
}

export function getReviewQueuePagination(total, pageSize, page) {
  const pageCount = getReviewQueuePageCount(total, pageSize);
  const currentPage = Number.isFinite(Number(page))
    ? Math.min(Math.max(0, Number(page)), pageCount - 1)
    : 0;
  return {
    page: currentPage,
    pageCount,
    canPrevious: currentPage > 0,
    canNext: currentPage < pageCount - 1,
  };
}
