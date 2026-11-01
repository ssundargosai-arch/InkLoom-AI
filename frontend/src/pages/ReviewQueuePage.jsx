import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { api, errorMessage, unwrapList } from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "../components/common/UI";
import {
  getReviewQueuePageOffset,
  getReviewQueuePagination,
  updateReviewQueueState,
} from "../utils/reviewQueue";

const PAGE_SIZE = 20;

export default function ReviewQueuePage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState([]);
  const [reviewers, setReviewers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [assignmentError, setAssignmentError] = useState("");
  const [total, setTotal] = useState(0);
  const [queueState, setQueueState] = useState({
    query: "",
    status: "all",
    page: 0,
  });
  const [assigning, setAssigning] = useState("");

  const load = async (active = () => true) => {
    setLoading(true);
    setError("");
    try {
      const offset = getReviewQueuePageOffset(
        queueState.page,
        PAGE_SIZE,
        total,
      );
      const response = await api.reviews({
        offset,
        limit: PAGE_SIZE,
        status: queueState.status,
      });
      if (!active()) return;
      const responseTotal = Number.isFinite(Number(response?.total))
        ? Number(response.total)
        : unwrapList(response).length;
      const lastPage = getReviewQueuePagination(
        responseTotal,
        PAGE_SIZE,
        queueState.page,
      ).page;
      setTotal(responseTotal);
      if (lastPage !== queueState.page) {
        setQueueState((current) =>
          current.page === queueState.page
            ? { ...current, page: lastPage }
            : current,
        );
        return;
      }
      setItems(unwrapList(response));
    } catch (e) {
      if (active()) setError(errorMessage(e));
    } finally {
      if (active()) setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    void load(() => active);
    return () => {
      active = false;
    };
  }, [queueState.page, queueState.status]);

  useEffect(() => {
    if (!isAdmin) return;
    api.reviewers()
      .then((response) => setReviewers(unwrapList(response)))
      .catch((e) => setAssignmentError(errorMessage(e)));
  }, [isAdmin]);

  const visible = useMemo(
    () =>
      items.filter(
        (item) =>
          (item.title || item.name || "")
            .toLowerCase()
            .includes(queueState.query.trim().toLowerCase()),
      ),
    [items, queueState.query],
  );
  const pagination = getReviewQueuePagination(total, PAGE_SIZE, queueState.page);

  const assign = async (item, value) => {
    const reviewerId = value ? Number(value) : null;
    setAssigning(String(item.id));
    setAssignmentError("");
    try {
      const result = await api.assignReviewer(item.id, reviewerId);
      setItems((current) =>
        current.map((review) =>
          review.id === item.id ? { ...review, ...result } : review,
        ),
      );
    } catch (e) {
      setAssignmentError(errorMessage(e));
    } finally {
      setAssigning("");
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Human review"
        title="Review queue"
        description="Make the final call on content. AI findings are advisory; each item needs a human decision."
      />
      <div className="card overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div className="relative w-full sm:max-w-xs">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="field pl-9"
              aria-label="Search reviews"
              placeholder="Search titles on this page..."
              value={queueState.query}
              onChange={(event) =>
                setQueueState((current) =>
                  updateReviewQueueState(current, {
                    query: event.target.value,
                  }),
                )
              }
            />
          </div>
          <div className="flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
            {[
              "all",
              "pending",
              "submitted",
              "in_review",
              "changes_requested",
              "approved",
              "rejected",
            ].map((value) => (
              <button
                key={value}
                aria-pressed={queueState.status === value}
                onClick={() =>
                  setQueueState((current) =>
                    updateReviewQueueState(current, { status: value }),
                  )
                }
                className={`rounded-md px-2.5 py-1.5 text-xs font-medium capitalize ${
                  queueState.status === value
                    ? "bg-white text-ink-700 shadow-sm"
                    : "text-slate-500 hover:text-slate-800"
                }`}
              >
                {value.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        </div>
        {assignmentError && (
          <p role="alert" className="border-b border-rose-100 px-5 py-2 text-sm text-rose-700">
            {assignmentError}
          </p>
        )}
        {loading ? (
          <LoadingState label="Loading review queue..." />
        ) : error ? (
          <div className="p-4">
            <ErrorState message={error} onRetry={() => load()} />
          </div>
        ) : visible.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-5 py-3">Content</th>
                  <th className="px-5 py-3">Submitted</th>
                  <th className="px-5 py-3">Issues</th>
                  <th className="px-5 py-3">Reviewer</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">
                    <span className="sr-only">Open review</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((item) => (
                  <tr key={item.id} className="hover:bg-slate-50/70">
                    <td className="px-5 py-4">
                      <p className="font-semibold text-slate-800">
                        {item.title || item.name || "Untitled content"}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        {item.content_type || item.type || "Content"}
                      </p>
                    </td>
                    <td className="px-5 py-4 text-sm text-slate-500">
                      {item.submitted_at
                        ? new Date(item.submitted_at).toLocaleDateString()
                        : "—"}
                    </td>
                    <td className="px-5 py-4 text-sm text-slate-600">
                      {item.issue_count ?? item.findings?.length ?? "—"}
                    </td>
                    <td className="px-5 py-4 text-sm text-slate-500">
                      {(item.assigned_reviewers || []).length ? (
                        <div className="mb-2 space-y-1">
                          {item.assigned_reviewers.map((assignment) => (
                            <p key={`${item.id}-${assignment.id}-${assignment.stage_number}`}>
                              {assignment.display_name || "Reviewer"}
                              <span className="ml-1 text-xs text-slate-400">
                                · Stage {assignment.stage_number}
                              </span>
                            </p>
                          ))}
                        </div>
                      ) : (
                        <p className="mb-2">
                          {item.assigned_reviewer?.display_name ||
                            item.reviewer ||
                            item.reviewer_name ||
                            "Unassigned"}
                        </p>
                      )}
                      {isAdmin && (
                        <label className="block text-[11px] text-slate-400">
                          Replace with one reviewer
                          <select
                            className="field mt-1 min-w-40 py-2 text-sm"
                            aria-label={`Replace reviewers for ${item.title || "review"}`}
                            value={item.assigned_reviewer_id || ""}
                            disabled={assigning === String(item.id)}
                            onChange={(event) => assign(item, event.target.value)}
                          >
                            <option value="">Unassigned</option>
                            {reviewers.map((reviewer) => (
                              <option key={reviewer.id} value={reviewer.id}>
                                {reviewer.display_name}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                    </td>
                    <td className="px-5 py-4">
                      <Badge tone="status">{item.status || "pending"}</Badge>
                    </td>
                    <td className="px-5 py-4">
                      <Link
                        aria-label={`Open ${item.title || "review"}`}
                        to={`/reviews/${item.id}`}
                        className="inline-flex rounded-lg p-2 text-slate-400 hover:bg-ink-50 hover:text-ink-700"
                      >
                        <ArrowUpRight size={17} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title={
              items.length
                ? "No reviews on this page match your search"
                : "No reviews match this view"
            }
            description={
              items.length
                ? "Clear the title search or move to another page."
                : "Try another status filter or submit new content for review."
            }
          />
        )}
        {!loading && !error && total > 0 && (
          <p className="px-4 pb-3 text-xs text-slate-500 sm:px-5">
            {visible.length} matching titles on this page
          </p>
        )}
        {!loading && !error && total > 0 && (
          <nav
            aria-label="Review queue pagination"
            className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 sm:px-5"
          >
            <p className="text-sm text-slate-500">
              Page {pagination.page + 1} of {pagination.pageCount} · {total} reviews
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-secondary"
                disabled={!pagination.canPrevious}
                onClick={() =>
                  setQueueState((current) => ({
                    ...current,
                    page: Math.max(0, current.page - 1),
                  }))
                }
              >
                Previous
              </button>
              <button
                type="button"
                className="btn-secondary"
                disabled={!pagination.canNext}
                onClick={() =>
                  setQueueState((current) => ({
                    ...current,
                    page: Math.min(
                      pagination.pageCount - 1,
                      current.page + 1,
                    ),
                  }))
                }
              >
                Next
              </button>
            </div>
          </nav>
        )}
      </div>
    </>
  );
}
