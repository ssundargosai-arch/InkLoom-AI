
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  History,
  MessageSquare,
  Radio,
  ShieldCheck,
  Send,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import {
  API_BASE_URL,
  api,
  errorMessage,
  unwrapList,
} from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorMessage,
  ErrorState,
  LoadingState,
  PageHeader,
  SuccessMessage,
} from "../components/common/UI";
import { useAuth } from "../contexts/AuthContext";
import {
  applySuggestionToContent,
  getSafeReplacement,
} from "../utils/applySuggestion";
import { getApprovalWarnings } from "../utils/reviewApproval";
import {
  canStartReviewCollaboration,
  isReviewerAssignedToStage,
} from "../utils/reviewCollaboration";
import {
  canInitiatePublish,
  canOverridePublish,
} from "../utils/publishPermissions";
import { getReviewContentSegments } from "../utils/reviewHighlights";
import {
  filterReviewFindings,
  getEvidenceStatus,
  getReviewContentVersions,
  summarizeEvidenceStatuses,
} from "../utils/reviewFindings";
import {
  formatVerificationMatchScore,
  getCitationSourceLabel,
  getEvidenceExcerptLabel,
} from "../utils/evidencePresentation";
import {
  getBrandVoiceFindingLabel,
  getBrandVoiceFindings,
} from "../utils/brandVoiceFindings";

function changedParts(before, after) {
  let start = 0;

  while (
    start < before.length &&
    start < after.length &&
    before[start] === after[start]
  ) {
    start += 1;
  }

  while (
    start > 0 &&
    start < before.length &&
    !/\s/.test(before[start - 1])
  ) {
    start -= 1;
  }

  let beforeEnd = before.length;
  let afterEnd = after.length;

  while (
    beforeEnd > start &&
    afterEnd > start &&
    before[beforeEnd - 1] === after[afterEnd - 1]
  ) {
    beforeEnd -= 1;
    afterEnd -= 1;
  }

  return {
    prefix: before.slice(0, start),
    removed: before.slice(start, beforeEnd),
    added: after.slice(start, afterEnd),
    suffix: before.slice(beforeEnd),
  };
}

function formatConfidence(value) {
  const number = Number(value);

  if (!Number.isFinite(number)) return null;

  return `${Math.round(number * 100)}%`;
}

function EvidenceCitation({ source, claim, evidenceStatus }) {
  const approvalStatus = source.approval_status;
  const isExternal = source.source_type === "external_trusted_source";

  return (
    <div className="mt-3 rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-800">
          {source.name || "Evidence source"}
        </p>

        <Badge
          tone={
            approvalStatus === "approved"
              ? "approved"
              : "status"
          }
        >
          {getCitationSourceLabel(source)}
        </Badge>
      </div>

      <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
        {claim && (
          <p className="sm:col-span-2">
            <strong>Related claim:</strong> {claim}
          </p>
        )}
        {source.document_type && (
          <p>
            <strong>Source type:</strong> {source.document_type}
          </p>
        )}
        {source.source_id != null && (
          <p>
            <strong>Source ID:</strong> {source.source_id}
          </p>
        )}
        {source.is_active != null && (
          <p>
            <strong>Active at analysis:</strong>{" "}
            {source.is_active ? "yes" : "no"}
          </p>
        )}

        {source.guideline_id != null && (
          <p>
            <strong>Linked guideline ID:</strong> {source.guideline_id}
          </p>
        )}

        {source.source_date && (
          <p>
            <strong>Source date:</strong> {source.source_date}
          </p>
        )}
        {source.valid_from && source.valid_from !== source.source_date && (
          <p>
            <strong>Valid from:</strong> {source.valid_from}
          </p>
        )}

        {source.expiry_date && (
          <p>
            <strong>Valid until:</strong> {source.valid_until || source.expiry_date}
          </p>
        )}
        {source.approval_at && (
          <p>
            <strong>Approved at:</strong>{" "}
            {new Date(source.approval_at).toLocaleString()}
          </p>
        )}
        {source.last_verified_at && (
          <p>
            <strong>Last verified:</strong>{" "}
            {new Date(source.last_verified_at).toLocaleString()}
          </p>
        )}
        {source.retrieved_at && (
          <p>
            <strong>Retrieved at:</strong>{" "}
            {new Date(source.retrieved_at).toLocaleString()}
          </p>
        )}

        {source.freshness && (
          <p>
            <strong>Freshness:</strong> {source.freshness}
          </p>
        )}

        {source.retrieval_method && (
          <p>
            <strong>Retrieval method:</strong> {source.retrieval_method}
          </p>
        )}

        {source.relevance_score != null &&
          Number.isFinite(Number(source.relevance_score)) && (
            <p>
              <strong>Relevance score:</strong>{" "}
              {formatConfidence(source.relevance_score)}
            </p>
          )}
      </div>

      {source.excerpt && (
        <div className="mt-3 rounded-md bg-slate-50 p-3">
          <p className="mb-1 text-xs font-semibold text-slate-700">
            {getEvidenceExcerptLabel(evidenceStatus)}
          </p>

          <p className="whitespace-pre-wrap break-words text-xs leading-5 text-slate-600">
            {source.excerpt}
          </p>
        </div>
      )}

      {source.url && (
        <a
          className="mt-3 inline-block text-xs font-medium text-ink-700 underline"
          href={source.url}
          target="_blank"
          rel="noreferrer"
        >
          Open source document
        </a>
      )}
      {source.source_id != null && !isExternal && (
        <Link
          className="mt-3 ml-4 inline-block text-xs font-medium text-ink-700 underline"
          to={`/sources?source_id=${encodeURIComponent(source.source_id)}&claim=${encodeURIComponent(claim || "")}#source-${encodeURIComponent(source.source_id)}`}
        >
          Inspect source record
        </Link>
      )}
    </div>
  );
}

export default function ReviewDetailPage() {
  const { user } = useAuth();

  const canDecide =
    user?.role === "admin" || user?.role === "reviewer";
  const isAdmin = user?.role === "admin";

  const { reviewId } = useParams();

  const [item, setItem] = useState(null);
  const [publishAssessment, setPublishAssessment] = useState(null);
  const [publishHistory, setPublishHistory] = useState({ publications: [], events: [] });
  const [publishLoading, setPublishLoading] = useState(false);
  const [publishError, setPublishError] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadedReviewId, setLoadedReviewId] = useState(null);
  const [comment, setComment] = useState("");
  const [internalNote, setInternalNote] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [replyTo, setReplyTo] = useState(null);
  const [reviewers, setReviewers] = useState([]);
  const [selectedAssignments, setSelectedAssignments] = useState([]);
  const [assignmentError, setAssignmentError] = useState("");
  const [participants, setParticipants] = useState([]);
  const [selectedFromVersion, setSelectedFromVersion] = useState("0");
  const [selectedToVersion, setSelectedToVersion] = useState("");
  const [versionComparison, setVersionComparison] = useState(null);
  const [versionComparisonError, setVersionComparisonError] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [selectedFindingIndex, setSelectedFindingIndex] = useState(0);
  const [previewPage, setPreviewPage] = useState(1);
  const [severityFilter, setSeverityFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [evidenceFilter, setEvidenceFilter] = useState("all");
  const [reviewStatusFilter, setReviewStatusFilter] = useState("all");
  const [confidenceFilter, setConfidenceFilter] = useState("all");
  const [findingSearch, setFindingSearch] = useState("");

  const [showReviewerGuidance] = useState(
    () =>
      window.localStorage.getItem("inkloom-review-options") !==
      "false"
  );

  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");

  const [activity, setActivity] = useState([]);
  const [activityError, setActivityError] = useState("");
  const [liveState, setLiveState] = useState("connecting");

  const socketRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const draftTimerRef = useRef(null);
  const currentDraftRef = useRef(null);
  const collaborationEnabled = canStartReviewCollaboration({
    loading,
    error,
    loadedReviewId,
    reviewId,
    review: item,
    user,
  });

  const loadPublishData = async () => {
    setPublishLoading(true);
    setPublishError("");
    try {
      const [assessment, history] = await Promise.all([
        api.publishReadiness(reviewId),
        api.publishHistory(reviewId),
      ]);
      setPublishAssessment(assessment?.data || assessment);
      setPublishHistory(history?.data || history || { publications: [], events: [] });
    } catch (e) {
      setPublishError(errorMessage(e));
    } finally {
      setPublishLoading(false);
    }
  };

  const load = async () => {
    setLoading(true);
    setError("");
    setLoadedReviewId(null);
    setItem(null);

    try {
      const response = await api.review(reviewId);
      const data = response?.data || response;

      if (!data) {
        throw new Error("Review was not found.");
      }

      setSelectedFindingIndex(0);
      setSeverityFilter("all");
      setCategoryFilter("all");
      setEvidenceFilter("all");
      setReviewStatusFilter("all");
      setConfidenceFilter("all");
      setItem(data);
      setLoadedReviewId(reviewId);
      setDraftContent(data.content || data.text || "");
      setSelectedAssignments(
        (data.assigned_reviewers || []).map((assignment) => ({
          reviewer_id: assignment.id,
          stage_number: assignment.stage_number || 1,
        })),
      );
      setSelectedToVersion(
        data.versions?.length
          ? String(data.versions[data.versions.length - 1].id)
          : "",
      );
      void loadPublishData();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  const refreshReview = async () => {
    try {
      const response = await api.review(reviewId);
      setItem(response?.data || response);
      await loadPublishData();
    } catch (err) {
      setActionError(errorMessage(err));
    }
  };

  const refreshActivity = () => {
    api.reviewActivity(reviewId)
      .then((response) => {
        setActivity(unwrapList(response));
        setActivityError("");
      })
      .catch((err) => {
        setActivityError(errorMessage(err));
      });
  };

  const publishContent = async () => {
    if (!window.confirm(
      `Publish this approved revision? Risk is estimated as ${publishAssessment?.risk?.level || "unknown"} (${publishAssessment?.risk?.score ?? "—"}/100).`,
    )) return;
    setBusy(true);
    setActionError("");
    try {
      const response = await api.publishReview(reviewId);
      setPublishAssessment(response?.data || response);
      setNotice("This revision was published and its risk snapshot was recorded.");
      await refreshReview();
      refreshActivity();
    } catch (e) {
      setActionError(errorMessage(e));
      void loadPublishData();
    } finally {
      setBusy(false);
    }
  };

  const publishWithOverride = async (event) => {
    event.preventDefault();
    if (overrideReason.trim().length < 10) {
      setActionError("Override justification must contain at least 10 characters.");
      return;
    }
    if (!window.confirm("Publish with the listed eligible risks overridden? This action is recorded in the audit history.")) return;
    setBusy(true);
    setActionError("");
    try {
      const response = await api.overridePublish(reviewId, overrideReason.trim());
      setPublishAssessment(response?.data || response);
      setOverrideReason("");
      setNotice("Published with an Admin risk override. The reason and overridden blockers were recorded.");
      await refreshReview();
      refreshActivity();
    } catch (e) {
      setActionError(errorMessage(e));
      void loadPublishData();
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    load();
  }, [reviewId]);

  useEffect(() => {
    if (!isAdmin) return;
    api.reviewers()
      .then((response) => setReviewers(unwrapList(response)))
      .catch((err) => setAssignmentError(errorMessage(err)));
  }, [isAdmin]);

  useEffect(() => {
    let active = true;
    let reconnectAttempts = 0;
    let socket;

    if (!collaborationEnabled) {
      setParticipants([]);
      return () => {
        active = false;
        window.clearTimeout(reconnectTimerRef.current);
      };
    }

    api.reviewActivity(reviewId)
      .then((response) => {
        if (active) {
          setActivity(unwrapList(response));
          setActivityError("");
        }
      })
      .catch((err) => {
        if (active) {
          setActivityError(errorMessage(err));
        }
      });

    const connect = () => {
      if (!active) return;
      const socketUrl = `${API_BASE_URL.replace(
        /^http/,
        "ws"
      )}/api/reviews/${encodeURIComponent(reviewId)}/collaboration`;
      socket = new WebSocket(socketUrl);
      socketRef.current = socket;

      socket.onopen = () => {
        reconnectAttempts = 0;
        setLiveState("connected");
      };
      socket.onclose = (event) => {
        if (socketRef.current === socket) socketRef.current = null;
        if (!active) return;
        if ([4401, 4403, 4404].includes(event.code)) {
          setLiveState("unavailable");
          return;
        }
        setLiveState("disconnected");
        reconnectAttempts += 1;
        const delay = Math.min(1000 * (2 ** (reconnectAttempts - 1)), 15000);
        reconnectTimerRef.current = window.setTimeout(connect, delay);
      };
      socket.onerror = () => {
        if (active) setLiveState("unavailable");
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "presence") {
            setParticipants(message.payload?.participants || []);
            setLiveState("connected");
          } else if (message.type === "comment_created" && message.payload) {
            setItem((current) =>
              current
                ? { ...current, comments: [...(current.comments || []), message.payload] }
                : current
            );
          } else if (message.type === "status_changed" && message.payload?.status) {
            setItem((current) =>
              current
                ? {
                    ...current,
                    status: message.payload.status,
                    reviewer: message.payload.reviewer || current.reviewer,
                  }
                : current
            );
          } else if (message.type === "revision_created" && message.payload) {
            setItem((current) =>
              current
                ? {
                    ...current,
                    content: message.payload.content || current.content,
                    revisions: [...(current.revisions || []), message.payload],
                  }
                : current
            );
            if (message.payload.content) setDraftContent(message.payload.content);
            refreshReview();
          } else if (
            message.type === "draft_changed" &&
            typeof message.payload?.content === "string"
          ) {
            setDraftContent(message.payload.content);
          } else if (
            ["assignment_changed", "approval_decision", "approval_bypassed", "review_updated"].includes(message.type)
          ) {
            refreshReview();
          }

          if (
            [
              "comment_created",
              "status_changed",
              "revision_created",
              "assignment_changed",
              "approval_decision",
              "approval_bypassed",
              "review_updated",
            ].includes(message.type)
          ) refreshActivity();
        } catch {
          setLiveState("unavailable");
        }
      };
    };

    connect();

    return () => {
      active = false;
      window.clearTimeout(reconnectTimerRef.current);

      if (socketRef.current === socket) {
        socketRef.current = null;
      }

      window.clearTimeout(draftTimerRef.current);
      socket?.close();
    };
  }, [reviewId, collaborationEnabled]);

  const updateDraft = (value) => {
    setDraftContent(value);

    window.clearTimeout(draftTimerRef.current);

    draftTimerRef.current = window.setTimeout(() => {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(
          JSON.stringify({
            type: "draft_changed",
            content: value,
            user: item?.reviewer || "Anonymous reviewer",
          })
        );
      }
    }, 180);
  };

  const updateStatus = async (status) => {
    let acknowledgeWarnings = false;
    let reason = "";

    if (status === "rejected" || status === "changes_requested") {
      const requestedReason = window.prompt(
        status === "rejected"
          ? "Why is this content being rejected?"
          : "What changes are required?",
      );
      if (requestedReason === null || !requestedReason.trim()) {
        setActionError("A reason is required for this decision.");
        return;
      }
      reason = requestedReason.trim();
      if (
        !window.confirm(
          status === "rejected"
            ? "Reject this content? This is a human review decision."
            : "Request changes for this content?",
        )
      ) {
        return;
      }
    } else if (status === "approved") {
      const approvalReason = window.prompt(
        "Approval reason (optional):",
        "",
      );
      if (approvalReason === null) return;
      reason = approvalReason.trim();
    }

    if (status === "approved") {
      const currentFindings = unwrapList(
        item?.findings || item?.issues
      );

      const warnings = getApprovalWarnings(currentFindings);

      if (warnings.length > 0) {
        const warningDetails = warnings
          .map((finding, index) => {
            const claim =
              finding.claim ||
              finding.matched_text ||
              finding.title ||
              finding.description ||
              "Unspecified factual claim";

            const explanation =
              finding.verification_explanation ||
              finding.explanation ||
              "This unresolved finding requires human review.";

            const citations = Array.isArray(finding.citations)
              ? finding.citations
                  .map((citation) => {
                    const sourceName =
                      citation.name ||
                      citation.source_name ||
                      citation.title ||
                      citation.url ||
                      "Evidence source";

                    const excerpt = citation.excerpt
                      ? ` — ${citation.excerpt}`
                      : "";

                    return `${sourceName}${excerpt}`;
                  })
                  .filter(Boolean)
              : [];

            return [
              `${index + 1}. ${claim}`,
              `Severity: ${finding.severity || "unknown"}`,
              `Category: ${finding.category || "finding"}`,
              `Status: ${finding.verification_status}`,
              `Explanation: ${explanation}`,
              citations.length
                ? `Evidence: ${citations.join("; ")}`
                : "",
            ]
              .filter(Boolean)
              .join("\n");
          })
          .join("\n\n");

        acknowledgeWarnings = window.confirm(
          "WARNING: Unresolved critical findings or claims requiring human verification were found.\n\n" +
            warningDetails +
            "\n\nDo you acknowledge these risks and still want to approve this content?"
        );

        if (!acknowledgeWarnings) {
          return;
        }
      } else {
        if (
          !window.confirm(
            "Approve this content for publication? Approval is a human decision and cannot be undone here."
          )
        ) {
          return;
        }
      }
    }

    setBusy(true);
    setActionError("");
    setNotice("");

    try {
      const useStagedDecision =
        item.assigned_reviewers?.length > 0 &&
        user?.role === "reviewer" &&
        ["approved", "rejected", "changes_requested"].includes(status);
      if (useStagedDecision) {
        await api.submitApprovalDecision(reviewId, {
          decision: status,
          reason: reason || undefined,
          acknowledge_warnings: acknowledgeWarnings,
        });
        await refreshReview();
      } else {
        const response = await api.updateStatus(
          reviewId,
          status,
          acknowledgeWarnings,
          reason,
        );
        setItem((current) => ({
          ...current,
          ...(response?.data || response || {}),
          status,
        }));
      }

      setNotice(
        status === "approved"
          ? "Content marked approved."
          : status === "rejected"
            ? "Content rejected."
            : status === "submitted"
              ? "Revision submitted for review."
              : status === "changes_requested"
                ? "Changes requested."
                : "Review status updated."
      );

      refreshActivity();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const addComment = async (event) => {
    event.preventDefault();

    if (!comment.trim()) return;

    setBusy(true);
    setActionError("");

    try {
      await api.addComment(reviewId, comment.trim(), {
        is_internal: internalNote,
      });

      setComment("");
      setInternalNote(false);
      setNotice(internalNote ? "Internal note added." : "Comment added.");

      await load();
      refreshActivity();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const addReply = async (event) => {
    event.preventDefault();
    if (!replyText.trim() || !replyTo) return;
    setBusy(true);
    setActionError("");
    try {
      await api.addComment(reviewId, replyText.trim(), {
        is_internal: replyTo.is_internal,
        parent_id: replyTo.id,
      });
      setReplyText("");
      setReplyTo(null);
      setNotice("Reply added.");
      await load();
      refreshActivity();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const saveAssignments = async () => {
    setBusy(true);
    setAssignmentError("");
    try {
      await api.assignReviewers(reviewId, selectedAssignments);
      await refreshReview();
      refreshActivity();
    } catch (err) {
      setAssignmentError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const bypassApproval = async () => {
    const reason = window.prompt(
      "Provide a justification for bypassing the required approval stages:",
    );
    if (!reason?.trim()) {
      setActionError("A bypass justification is required.");
      return;
    }
    const warnings = getApprovalWarnings(findings);
    const acknowledgeWarnings = warnings.length
      ? window.confirm(
          `${warnings.length} unresolved critical finding(s) or unverified claim(s) remain. Acknowledge these warnings and continue with the bypass?`,
        )
      : false;
    if (warnings.length && !acknowledgeWarnings) return;
    if (
      !window.confirm(
        "Record an Admin-only approval bypass? The reason and actor will be permanently added to the review timeline.",
      )
    ) return;

    setBusy(true);
    setActionError("");
    try {
      await api.bypassApprovalStages(reviewId, {
        reason: reason.trim(),
        acknowledge_warnings: acknowledgeWarnings,
      });
      await refreshReview();
      refreshActivity();
      setNotice("Approval stage bypass recorded in the activity timeline.");
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const compareVersions = async () => {
    setVersionComparisonError("");
    setVersionComparison(null);
    if (!selectedFromVersion || !selectedToVersion) return;
    try {
      const result = await api.compareReviewVersions(
        reviewId,
        Number(selectedFromVersion),
        Number(selectedToVersion),
      );
      setVersionComparison(result);
    } catch (err) {
      setVersionComparisonError(errorMessage(err));
    }
  };

  const findings = unwrapList(item?.findings || item?.issues);
  const activeVisualPage = previewPage;
  const activeVisualFinding = findings[selectedFindingIndex];
  const activeVisualRegion = activeVisualFinding?.visual_data?.region;
  const originalImage = item?.visual_attachment?.analysis;
  const comments = unwrapList(item?.comments);
  const revisions = unwrapList(item?.revisions);
  const versions = unwrapList(item?.versions);
  const currentApprovalStage = item?.active_approval_stage || 1;
  const mayPublish = canInitiatePublish(user?.role);
  const isCurrentAssignedReviewer = isReviewerAssignedToStage(
    item?.assigned_reviewers,
    user?.id,
    currentApprovalStage,
  );
  const analysisRuns = unwrapList(item?.analysis_runs);
  const contentVersions = getReviewContentVersions(
    versions,
    item?.current_version_id,
    item?.content ?? item?.text,
  );
  const currentRevisionContent = contentVersions.currentContent || "";
  const evidenceSummary = summarizeEvidenceStatuses(findings);
  const filteredFindings = filterReviewFindings(findings, {
    severity: severityFilter,
    category: categoryFilter,
    evidence: evidenceFilter,
    reviewStatus: reviewStatusFilter,
    confidence: confidenceFilter,
    search: findingSearch,
  });
  const selectedVisibleIndex = filteredFindings.findIndex(
    ({ index }) => index === selectedFindingIndex,
  );
  const highlightSegments = getReviewContentSegments(
    currentRevisionContent,
    findings,
  );
  const exactMatchCount = findings.reduce((count, finding) => {
    const phrase = finding?.matched_text;
    if (typeof phrase !== "string" || !phrase.length) return count;
    let fromIndex = 0;
    let matches = 0;
    while (fromIndex <= currentRevisionContent.length - phrase.length) {
      const start = currentRevisionContent.indexOf(phrase, fromIndex);
      if (start === -1) break;
      matches += 1;
      fromIndex = start + 1;
    }
    return count + matches;
  }, 0);

  useEffect(() => {
    const findingPage = findings[selectedFindingIndex]?.visual_data?.page_number;
    if (findingPage) setPreviewPage(findingPage);
  }, [selectedFindingIndex, findings]);

  useEffect(() => {
    if (selectedVisibleIndex < 0 && filteredFindings.length > 0) {
      setSelectedFindingIndex(filteredFindings[0].index);
      return;
    }
    if (selectedVisibleIndex < 0) return;
    const selectedMark = Array.from(
      currentDraftRef.current?.querySelectorAll("[data-finding-index]") || [],
    ).find((element) =>
      element.dataset.findingIndex
        .split(",")
        .includes(String(selectedFindingIndex)),
    );
    selectedMark?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [selectedFindingIndex, selectedVisibleIndex]);

  const saveRevision = async (event) => {
    event.preventDefault();

    if (!draftContent.trim()) return;

    setBusy(true);
    setActionError("");
    setNotice("");

    try {
      const response = await api.reanalyze(reviewId, {
        content: draftContent.trim(),
        title: `Revision ${revisions.length + 1}`,
      });

      setItem(response?.data || response);

      setDraftContent(
        (response?.data || response)?.content ||
          draftContent.trim()
      );

      setNotice(
        "Revision saved and deterministic checks rerun. Human review is required again."
      );

      await load();
      refreshActivity();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const applySuggestion = (finding) => {
    const matched = finding.matched_text;
    const suggestion = finding.suggestion;
    const category = finding.category || finding.type;

    if (!matched || !suggestion) {
      setActionError(
        "This finding does not contain usable text and guidance."
      );
      return;
    }

    const safe = getSafeReplacement(
      String(matched),
      String(suggestion),
      category
    );

    if (!safe.ok) {
      setActionError(
        "This suggestion is guidance, not ready-to-insert replacement text. Edit the draft manually."
      );
      return;
    }

    const result = applySuggestionToContent(
      draftContent,
      String(matched),
      safe.replacement
    );

    if (!result.ok) {
      const messages = {
        "not-found":
          "The flagged text is not present in the current draft. Edit manually.",
        ambiguous: `“${matched}” appears more than once. Edit the intended occurrence manually.`,
        "missing-text":
          "The finding does not contain usable replacement text.",
        "invalid-input":
          "This suggestion cannot be applied automatically.",
      };

      setActionError(
        messages[result.reason] ||
          "This suggestion cannot be applied automatically."
      );

      return;
    }

    updateDraft(result.content);

    setNotice(
      "Approved terminology replacement applied. Review and save the draft before rerunning checks."
    );

    setActionError("");
  };

  const comparison =
    draftContent !== item?.content
      ? changedParts(item?.content || "", draftContent)
      : null;

  if (loading) {
    return <LoadingState label="Loading review..." />;
  }

  if (error || !item) {
    return (
      <>
        <Link
          to="/reviews"
          className="mb-5 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-ink-700"
        >
          <ArrowLeft size={16} />
          Review queue
        </Link>

        <ErrorState
          message={error || "Review not found."}
          onRetry={load}
        />
      </>
    );
  }

  return (
    <>
      <Link
        to="/reviews"
        className="mb-5 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-ink-700"
      >
        <ArrowLeft size={16} />
        Review queue
      </Link>

      <PageHeader
        eyebrow={item.content_type || item.type || "Content review"}
        title={item.title || "Untitled review"}
        description={`Submitted ${
          item.submitted_at
            ? new Date(item.submitted_at).toLocaleString()
            : "date unavailable"
        } · ${
          item.reviewer ||
          item.reviewer_name ||
          "No reviewer assigned"
        }`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="status">{item.status || "pending"}</Badge>
            {item.approval_bypasses?.some(
              (bypass) => bypass.version_id === item.current_version_id,
            ) && (
              <Badge tone="warning">Admin approval bypass</Badge>
            )}
          </div>
        }
      />

      {showReviewerGuidance && (
        <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
          <strong>Human decision required.</strong> AI findings are
          advisory and do not approve or reject content. Review the
          draft and evidence before taking action.
        </div>
      )}

      {notice && (
        <div className="mb-4">
          <SuccessMessage>{notice}</SuccessMessage>
        </div>
      )}

      {actionError && (
        <div className="mb-4">
          <ErrorMessage>{actionError}</ErrorMessage>
        </div>
      )}

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(350px,.8fr)]">
        <div className="space-y-5">
          <section className="card p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold text-ink-900">
                Collaborative editing canvas
              </h2>

              <span
                className={`text-xs ${
                  liveState === "connected"
                    ? "text-emerald-700"
                    : "text-slate-400"
                }`}
              >
                {liveState === "connected"
                  ? "Draft changes sync live"
                  : "Live sync unavailable"}
              </span>
            </div>

            <p className="mt-1 text-xs leading-5 text-slate-500">
              Changes sync with connected reviewers but remain
              unsaved until you save and rerun checks.
            </p>

            <label
              className="sr-only"
              htmlFor="shared-review-draft"
            >
              Collaboratively edit content
            </label>

            <textarea
              id="shared-review-draft"
              className="field mt-4 resize-y leading-7"
              rows={12}
              value={draftContent}
              onChange={(event) =>
                updateDraft(event.target.value)
              }
            />

            {comparison && (
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="rounded-lg border border-slate-200 p-3">
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Current version
                  </h3>

                  <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
                    {comparison.prefix}
                    <del className="rounded bg-rose-100 text-rose-900">
                      {comparison.removed}
                    </del>
                    {comparison.suffix}
                  </p>
                </div>

                <div className="rounded-lg border border-emerald-200 p-3">
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-emerald-700">
                    Proposed revision
                  </h3>

                  <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
                    {comparison.prefix}
                    <ins className="rounded bg-emerald-100 text-emerald-900 no-underline">
                      {comparison.added}
                    </ins>
                    {comparison.suffix}
                  </p>
                </div>
              </div>
            )}

            <div className="mt-3 flex items-center justify-between gap-3">
              <span className="text-xs text-slate-400">
                {draftContent.length.toLocaleString()} characters ·
                current findings refresh after re-analysis
              </span>

              <button
                className="btn-secondary shrink-0"
                type="button"
                onClick={saveRevision}
                disabled={
                  busy ||
                  !draftContent.trim() ||
                  draftContent.trim() === item.content
                }
              >
                {busy ? "Checking…" : "Save revision & rerun checks"}
              </button>
            </div>
          </section>

          {/* Evidence-grounded findings and provenance */}
          <section className="card">
            <div className="border-b border-slate-100 px-5 py-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold text-ink-900">
                  Flagged findings
                </h2>

                <p className="mt-1 text-xs text-slate-500">
                  {findings.length} advisory items
                </p>
              </div>
                <div className="flex items-center gap-2">
                  <button
                    className="btn-secondary !px-2.5 !py-1.5 !text-xs"
                    type="button"
                    aria-label="Previous finding"
                    disabled={filteredFindings.length === 0}
                    onClick={() => {
                      const next =
                        selectedVisibleIndex <= 0
                          ? filteredFindings.length - 1
                          : selectedVisibleIndex - 1;
                      setSelectedFindingIndex(filteredFindings[next].index);
                    }}
                  >
                    <ChevronUp size={14} />
                    Previous
                  </button>
                  <span className="text-xs tabular-nums text-slate-500">
                    {selectedVisibleIndex >= 0
                      ? `${selectedVisibleIndex + 1} / ${filteredFindings.length}`
                      : `0 / ${filteredFindings.length}`}
                  </span>
                  <button
                    className="btn-secondary !px-2.5 !py-1.5 !text-xs"
                    type="button"
                    aria-label="Next finding"
                    disabled={filteredFindings.length === 0}
                    onClick={() => {
                      const next =
                        selectedVisibleIndex < 0 ||
                        selectedVisibleIndex === filteredFindings.length - 1
                          ? 0
                          : selectedVisibleIndex + 1;
                      setSelectedFindingIndex(filteredFindings[next].index);
                    }}
                  >
                    Next
                    <ChevronDown size={14} />
                  </button>
                </div>
              </div>

              <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                <label className="text-xs font-medium text-slate-500 sm:col-span-2 lg:col-span-5">
                  Search findings
                  <input
                    className="field mt-1"
                    type="search"
                    aria-label="Search findings"
                    placeholder="Search title, explanation, flagged text, or evidence excerpt..."
                    value={findingSearch}
                    onChange={(event) => setFindingSearch(event.target.value)}
                  />
                </label>
                <label className="text-xs font-medium text-slate-500">
                  Severity
                  <select
                    className="input mt-1"
                    value={severityFilter}
                    onChange={(event) => setSeverityFilter(event.target.value)}
                  >
                    <option value="all">All severities</option>
                    <option value="critical_high">Critical and High</option>
                    {["critical", "high", "medium", "low"].map((value) => (
                      <option key={value} value={value}>
                        {value[0].toUpperCase() + value.slice(1)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="flex items-end gap-2">
                  <button
                    type="button"
                    className={`btn-secondary w-full ${severityFilter === "critical_high" ? "border-rose-300 bg-rose-50 text-rose-800" : ""}`}
                    aria-pressed={severityFilter === "critical_high"}
                    onClick={() =>
                      setSeverityFilter((current) =>
                        current === "critical_high" ? "all" : "critical_high",
                      )
                    }
                  >
                    Critical &amp; High
                  </button>
                  {severityFilter !== "all" && (
                    <button
                      type="button"
                      className="btn-secondary w-full"
                      onClick={() => setSeverityFilter("all")}
                    >
                      All severities
                    </button>
                  )}
                </div>
                <label className="text-xs font-medium text-slate-500">
                  Category
                  <select
                    className="input mt-1"
                    value={categoryFilter}
                    onChange={(event) => setCategoryFilter(event.target.value)}
                  >
                    <option value="all">All categories</option>
                    {[...new Set(
                      findings.map((finding) =>
                        String(
                          finding?.category || finding?.type || "other",
                        ).toLowerCase(),
                      ),
                    )].map((value) => (
                      <option key={value} value={value}>
                        {value.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-medium text-slate-500">
                  Evidence
                  <select
                    className="input mt-1"
                    value={evidenceFilter}
                    onChange={(event) => setEvidenceFilter(event.target.value)}
                  >
                    <option value="all">All evidence states</option>
                    {[...new Set(findings.map(getEvidenceStatus))].map((value) => (
                      <option key={value} value={value}>
                        {value.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-medium text-slate-500">
                  Review status
                  <select
                    className="input mt-1"
                    value={reviewStatusFilter}
                    onChange={(event) =>
                      setReviewStatusFilter(event.target.value)
                    }
                  >
                    <option value="all">All review states</option>
                    {[...new Set(
                      findings.map((finding) =>
                        String(
                          finding?.review_status ||
                            finding?.status ||
                            "pending",
                        ).toLowerCase(),
                      ),
                    )].map((value) => (
                      <option key={value} value={value}>
                        {value.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-medium text-slate-500">
                  Confidence
                  <select
                    className="input mt-1"
                    value={confidenceFilter}
                    onChange={(event) =>
                      setConfidenceFilter(event.target.value)
                    }
                  >
                    <option value="all">All confidence levels</option>
                    <option value="high">High (80%+)</option>
                    <option value="medium">Medium (50–79%)</option>
                    <option value="low">Low (under 50%)</option>
                    <option value="unknown">Not provided</option>
                  </select>
                </label>
              </div>

              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                {["critical", "high", "medium", "low"].map((severity) => (
                  <span key={severity}>
                    {findings.filter(
                      (finding) =>
                        String(finding.severity || "").toLowerCase() === severity,
                    ).length}{" "}
                    {severity}
                  </span>
                ))}
                <span>{evidenceSummary.supported} supported</span>
                <span>{evidenceSummary.unsupported} unsupported</span>
                <span>{evidenceSummary.conflicting} conflicting</span>
                <span>{evidenceSummary.expired_evidence} expired evidence</span>
                <span>{evidenceSummary.unverified} unverified</span>
                <span>{evidenceSummary.not_assessed} not assessed</span>
              </div>
            </div>

            {(contentVersions.originalContent !== null ||
              contentVersions.currentContent !== null) && (
              <div
                className="border-b border-slate-100 px-5 py-4"
              >
                {contentVersions.originalContent !== null ? (
                  <div className="mb-4">
                    <h3 className="mb-2 text-sm font-semibold text-slate-700">
                      Original submission
                    </h3>
                    <p className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-4 text-sm leading-6 text-slate-700">
                      {contentVersions.originalContent}
                    </p>
                  </div>
                ) : (
                  <p className="mb-3 text-xs text-slate-500">
                    Original submission is unavailable in the preserved version history.
                  </p>
                )}
                {contentVersions.currentContent !== null && (
                  <div ref={currentDraftRef}>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold text-slate-700">
                        Current revision · {exactMatchCount} exact phrase matches
                      </h3>
                      <span className="text-xs text-slate-500">
                        Selected finding is emphasized; duplicate and overlapping phrases are all shown.
                      </span>
                    </div>
                    <p className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-4 text-sm leading-6 text-slate-700">
                      {highlightSegments.map((segment, segmentIndex) => {
                        if (!segment.findingIndices.length) {
                          return <span key={segmentIndex}>{segment.text}</span>;
                        }
                        const selected = segment.findingIndices.includes(
                          selectedFindingIndex,
                        );
                        return (
                          <mark
                            key={segmentIndex}
                            data-finding-index={segment.findingIndices.join(",")}
                            className={`rounded px-0.5 ${
                              selected
                                ? "bg-amber-300 text-amber-950 ring-2 ring-amber-500"
                                : "bg-rose-200 text-rose-950"
                            }`}
                          >
                            {segment.text}
                          </mark>
                        );
                      })}
                    </p>
                  </div>
                )}
              </div>
            )}
            {contentVersions.currentContent !== null &&
              exactMatchCount === 0 &&
              findings.length > 0 && (
              <p className="border-b border-slate-100 px-5 py-4 text-sm text-slate-500">
                None of the finding phrases exactly matches the current revision.
                No text has been highlighted or inferred.
              </p>
            )}

            {findings.length ? (
              filteredFindings.length ? (
              <div className="divide-y divide-slate-100">
                {filteredFindings.map(({ finding, index }) => (
                  <article
                    className={`cursor-pointer p-5 ${
                      selectedFindingIndex === index
                        ? "bg-amber-50/60"
                        : ""
                    }`}
                    key={finding.id || index}
                    onClick={() => setSelectedFindingIndex(index)}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>
                        {finding.category ||
                          finding.type ||
                          "Finding"}
                      </Badge>

                      <Badge tone="severity">
                        {finding.severity || "medium"}
                      </Badge>

                      <Badge tone="status">
                        {finding.status || "open"}
                      </Badge>

                      {finding.verification_status && (
                        <Badge
                          tone={
                            finding.verification_status === "verified"
                              ? "approved"
                              : finding.verification_status ===
                                  "contradicted"
                                ? "severity"
                                : "status"
                          }
                        >
                          {finding.verification_status ===
                          "conflicting_evidence"
                            ? "conflicting evidence"
                            : finding.verification_status}
                        </Badge>
                      )}
                    </div>

                    {finding.visual_data && (
                      <div className="mt-3 rounded-lg border border-ink-100 bg-ink-50/50 p-3 text-xs leading-5 text-slate-700">
                        <div className="flex flex-wrap gap-x-4 gap-y-1">
                          {finding.visual_data.page_number && (
                            <span className="font-semibold text-ink-800">
                              Page {finding.visual_data.page_number}
                            </span>
                          )}
                          {finding.visual_data.image_index && (
                            <span>Embedded image {finding.visual_data.image_index}</span>
                          )}
                          {finding.visual_data.detection_method && (
                            <span>Method: {finding.visual_data.detection_method}</span>
                          )}
                        </div>
                        {finding.visual_data.actual_value != null && (
                          <p className="mt-2">
                            <strong>Detected:</strong>{" "}
                            {typeof finding.visual_data.actual_value === "object"
                              ? JSON.stringify(finding.visual_data.actual_value)
                              : finding.visual_data.actual_value}
                          </p>
                        )}
                        {finding.visual_data.expected_value != null && (
                          <p className="mt-1">
                            <strong>Expected:</strong>{" "}
                            {typeof finding.visual_data.expected_value === "object"
                              ? JSON.stringify(finding.visual_data.expected_value)
                              : finding.visual_data.expected_value}
                          </p>
                        )}
                        {typeof finding.visual_data.actual_value === "string" &&
                          /^#[0-9A-Fa-f]{6}$/.test(finding.visual_data.actual_value) && (
                            <span className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2 py-1">
                              <span className="h-3 w-3 rounded-full border border-black/10" style={{ backgroundColor: finding.visual_data.actual_value }} />
                              Detected colour
                            </span>
                          )}
                        {Array.isArray(finding.visual_data.expected_value) && (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {finding.visual_data.expected_value.map((color) => (
                              /^#[0-9A-Fa-f]{6}$/.test(color) && (
                                <span key={color} className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2 py-1">
                                  <span className="h-3 w-3 rounded-full border border-black/10" style={{ backgroundColor: color }} />
                                  {color}
                                </span>
                              )
                            ))}
                          </div>
                        )}
                        {finding.visual_data.region && (
                          <p className="mt-1">
                            Estimated region: x {finding.visual_data.region.x}, y {finding.visual_data.region.y}, {finding.visual_data.region.width} × {finding.visual_data.region.height}px
                          </p>
                        )}
                        {finding.visual_data.asset_candidates?.length > 0 && (
                          <div className="mt-2">
                            <strong>Compared approved assets:</strong>
                            <ul className="mt-1 list-inside list-disc">
                              {finding.visual_data.asset_candidates.map((asset) => (
                                <li key={asset.asset_id || asset.name}>
                                  {asset.file_url ? (
                                    <a className="font-medium text-ink-700 underline" href={`${API_BASE_URL}${asset.file_url}`} target="_blank" rel="noreferrer">
                                      {asset.name}
                                    </a>
                                  ) : asset.name}
                                  {" "}· {asset.similarity_percent}% similar
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {finding.visual_data.confidence != null && (
                          <p className="mt-1">Detection confidence: {formatConfidence(finding.visual_data.confidence)}</p>
                        )}
                      </div>
                    )}

                    {finding.matched_text && (
                      <p className="mt-3 rounded bg-rose-50 px-3 py-2 text-sm text-rose-800">
                        “{finding.matched_text}”
                      </p>
                    )}

                    {finding.claim && (
                      <p className="mt-2 text-sm text-slate-700">
                        <strong>Claim assessed: </strong>
                        {finding.claim}
                      </p>
                    )}

                    <p className="mt-3 text-sm leading-6 text-slate-600">
                      {finding.explanation ||
                        finding.description ||
                        finding.message}
                    </p>

                    {getBrandVoiceFindings(finding).map(
                      (voiceFinding, voiceIndex) => (
                        <section
                          key={`${voiceFinding.finding_type || voiceFinding.brand_voice_category}-${voiceIndex}`}
                          className="mt-3 rounded-md border border-violet-200 bg-violet-50/60 p-3"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <strong className="text-xs text-violet-900">
                              Brand voice · {voiceFinding.brand_voice_category || "Configured voice"}
                            </strong>
                            <Badge
                              tone={
                                voiceFinding.assessment ===
                                "configured_rule_violation"
                                  ? "severity"
                                  : "status"
                              }
                            >
                              {getBrandVoiceFindingLabel(voiceFinding)}
                            </Badge>
                          </div>
                          {voiceFinding.matched_text && (
                            <p className="mt-2 text-xs leading-5 text-violet-950">
                              <strong>Matched content: </strong>
                              {voiceFinding.matched_text}
                            </p>
                          )}
                          {voiceFinding.configuration_rule && (
                            <p className="mt-2 text-xs leading-5 text-violet-900">
                              <strong>Configured rule: </strong>
                              {voiceFinding.configuration_rule}
                            </p>
                          )}
                          <p className="mt-2 text-xs leading-5 text-violet-900">
                            {voiceFinding.explanation}
                          </p>
                          {voiceFinding.suggestion ? (
                            <p className="mt-2 text-xs leading-5 text-violet-900">
                              <strong>Suggestion: </strong>
                              {voiceFinding.suggestion}
                            </p>
                          ) : voiceFinding.suggestion_status ? (
                            <p className="mt-2 text-xs text-violet-700">
                              {voiceFinding.suggestion_status}
                            </p>
                          ) : null}
                        </section>
                      ),
                    )}

                    {finding.verification_explanation && (
                      <p className="mt-2 text-xs leading-5 text-slate-500">
                        {finding.verification_explanation}
                      </p>
                    )}
                    {formatVerificationMatchScore(
                      finding.verification_confidence
                    ) && (
                      <p className="mt-1 text-xs text-slate-500">
                        {formatVerificationMatchScore(
                          finding.verification_confidence
                        )}
                      </p>
                    )}

                    {finding.citations?.map(
                      (source, sourceIndex) => (
                        <EvidenceCitation
                          claim={finding.claim || finding.matched_text}
                          key={`${
                            source.source_id ||
                            source.id ||
                            source.url ||
                            source.name
                          }-${sourceIndex}`}
                          source={source}
                          evidenceStatus={finding.evidence_status || finding.verification_status}
                        />
                      )
                    )}

                    {finding.suggestion && (
                      <div className="mt-3">
                        <p className="text-sm text-emerald-800">
                          <strong>Suggestion:</strong>{" "}
                          {finding.suggestion}
                        </p>

                        {finding.matched_text && (
                          <button
                            className="btn-secondary mt-2 !px-2.5 !py-1.5 !text-xs"
                            type="button"
                            onClick={() =>
                              applySuggestion(finding)
                            }
                          >
                            Use suggestion in draft
                          </button>
                        )}
                      </div>
                    )}

                    <p className="mt-2 text-xs text-slate-400">
                      Guideline:{" "}
                      {finding.guideline || "Not provided"}
                      {finding.source ? ` · Source: ${finding.source}` : ""}
                      {finding.confidence != null
                        ? ` · Confidence ${formatConfidence(
                            finding.confidence
                          )}`
                        : ""}
                    </p>
                  </article>
                ))}
              </div>
              ) : (
                <EmptyState
                  title="No findings match these filters"
                  description="Try widening or resetting the filters to see more findings."
                />
              )
            ) : (
              <EmptyState
                title="No findings supplied"
                description="This review has no analysis findings to display."
              />
            )}
          </section>
        </div>

        <div className="space-y-5">
          {item.visual_attachment && (
            <section className="card overflow-hidden">
              <div className="border-b border-slate-100 px-5 py-4">
                <h2 className="font-semibold text-ink-900">Submitted visual file</h2>
                <p className="mt-1 text-xs text-slate-500">
                  Private review attachment · {item.visual_attachment.filename}
                </p>
              </div>
              {item.visual_attachment.media_type === "application/pdf" ? (
                <>
                  {item.visual_attachment.analysis?.pages?.length > 1 && (
                    <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3">
                      {item.visual_attachment.analysis.pages.map((page) => (
                        <button
                          key={page.page_number}
                          type="button"
                          className={`rounded-md px-2.5 py-1.5 text-xs font-medium ${activeVisualPage === page.page_number ? "bg-ink-100 text-ink-800" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
                          aria-label={`Preview PDF page ${page.page_number}`}
                          aria-current={activeVisualPage === page.page_number ? "page" : undefined}
                          onClick={() => setPreviewPage(page.page_number)}
                        >
                          Page {page.page_number}
                        </button>
                      ))}
                    </div>
                  )}
                  <iframe
                    title="Submitted PDF preview"
                    src={`${API_BASE_URL}${item.visual_attachment.url}#page=${activeVisualPage}`}
                    className="h-[28rem] w-full"
                  />
                </>
              ) : (
                <div
                  className="relative mx-auto w-full max-h-[28rem] bg-slate-50"
                  style={originalImage?.width && originalImage?.height
                    ? { aspectRatio: `${originalImage.width} / ${originalImage.height}` }
                    : undefined}
                >
                  <img
                    src={`${API_BASE_URL}${item.visual_attachment.url}`}
                    alt="Submitted visual asset preview"
                    className="h-full max-h-[28rem] w-full object-contain"
                  />
                  {activeVisualRegion && originalImage?.width && originalImage?.height && (
                    <span
                      aria-label="Approximate detected text region"
                      className="pointer-events-none absolute border-2 border-rose-500 bg-rose-500/10"
                      style={{
                        left: `${(activeVisualRegion.x / originalImage.width) * 100}%`,
                        top: `${(activeVisualRegion.y / originalImage.height) * 100}%`,
                        width: `${(activeVisualRegion.width / originalImage.width) * 100}%`,
                        height: `${(activeVisualRegion.height / originalImage.height) * 100}%`,
                      }}
                    />
                  )}
                </div>
              )}
              <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
                Findings are advisory. Review the source file and the indicated page/region before deciding.
              </p>
            </section>
          )}

          {analysisRuns.length > 0 && (
            <section className="card p-5">
              <div className="mb-3 flex items-center gap-2">
                <History
                  size={17}
                  className="text-ink-600"
                />
                <h2 className="font-semibold text-ink-900">
                  Analysis history
                </h2>
              </div>

              <div className="space-y-2">
                {[...analysisRuns]
                  .reverse()
                  .map((run, index) => (
                    <details
                      className="rounded-lg border border-slate-200 p-3"
                      key={run.id || index}
                    >
                      <summary className="cursor-pointer text-sm font-medium text-slate-800">
                        {run.analysis_engine === "rules"
                          ? "Deterministic checks"
                          : run.analysis_engine || "Analysis"}
                        {" · "}
                        {run.created_at
                          ? new Date(
                              run.created_at
                            ).toLocaleString()
                          : "time unavailable"}
                      </summary>

                      <div className="mt-3 space-y-2 text-xs leading-5 text-slate-600">
                        <p>
                          {unwrapList(run.findings).length} findings ·{" "}
                          {run.evidence_retrieval_method ||
                            "no evidence retrieval"}
                        </p>

                        {run.content && (
                          <p className="whitespace-pre-wrap rounded bg-slate-50 p-2">
                            {run.content}
                          </p>
                        )}

                        {unwrapList(run.warnings).map(
                          (warning, warningIndex) => (
                            <p
                              className="text-amber-800"
                              key={warningIndex}
                            >
                              Warning: {warning}
                            </p>
                          )
                        )}

                        {unwrapList(run.findings).map(
                          (finding, findingIndex) => (
                            <p
                              key={finding.id || findingIndex}
                            >
                              <strong>
                                {finding.title ||
                                  finding.category ||
                                  "Finding"}
                                :
                              </strong>{" "}
                              {finding.explanation ||
                                finding.message}
                            </p>
                          )
                        )}
                      </div>
                    </details>
                  ))}
              </div>
            </section>
          )}

          <section className="card p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <ShieldCheck size={18} className="text-ink-600" />
                <h2 className="font-semibold text-ink-900">Risk & publish readiness</h2>
              </div>
              {publishAssessment?.state && (
                <Badge tone={publishAssessment.state === "Blocked" ? "severity" : "status"}>
                  {publishAssessment.state}
                </Badge>
              )}
            </div>

            {publishLoading && (
              <p className="mt-3 text-sm text-slate-500">Checking the latest revision, approvals, and evidence validity…</p>
            )}
            {publishError && (
              <p role="alert" className="mt-3 text-sm text-rose-700">
                {publishError}{" "}
                <button className="font-medium underline" type="button" onClick={loadPublishData}>
                  Retry
                </button>
              </p>
            )}
            {publishAssessment && (
              <>
                <div className="mt-4 flex flex-wrap items-end gap-x-4 gap-y-1">
                  <p className="text-3xl font-semibold text-ink-900">
                    {publishAssessment.risk?.score ?? "—"}
                    <span className="text-base font-normal text-slate-500"> / 100</span>
                  </p>
                  <p className="pb-1 text-sm font-medium text-slate-700">
                    {publishAssessment.risk?.level || "Risk unavailable"} risk
                  </p>
                  <p className="w-full text-xs text-slate-500">
                    Heuristic estimate based on analysis findings; it is not a verified fact or legal assessment.
                  </p>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {Object.entries(publishAssessment.risk?.breakdown?.category_points || {}).map(([category, points]) => (
                    <div key={category} className="rounded-md bg-slate-50 p-2">
                      <p className="text-[10px] uppercase tracking-wide text-slate-500">
                        {category.replaceAll("_", " ")}
                      </p>
                      <p className="mt-1 text-sm font-semibold text-slate-800">{points} pts</p>
                    </div>
                  ))}
                </div>
                {publishAssessment.analysis && (
                  <p className={`mt-3 text-xs ${publishAssessment.analysis.is_current ? "text-emerald-700" : "text-rose-700"}`}>
                    Analysis {publishAssessment.analysis.is_current ? "matches" : "does not match"} current revision · revision {publishAssessment.revision_id}
                  </p>
                )}
                {!!publishAssessment.blockers?.length && (
                  <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3">
                    <p className="text-sm font-semibold text-rose-900">Publish blockers</p>
                    <ul className="mt-2 list-inside list-disc space-y-1 text-xs leading-5 text-rose-800">
                      {publishAssessment.blockers.map((blocker, index) => (
                        <li key={`${blocker.code}-${blocker.finding_id || blocker.source_id || index}`}>
                          {blocker.message}
                          {blocker.title ? ` — ${blocker.title}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {!!publishAssessment.warnings?.length && (
                  <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                    <p className="text-sm font-semibold text-amber-900">Warnings</p>
                    <ul className="mt-2 list-inside list-disc space-y-1 text-xs leading-5 text-amber-800">
                      {publishAssessment.warnings.map((warning, index) => (
                        <li key={`${warning.code}-${warning.source_id || index}`}>{warning.message}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {publishAssessment.overridden_blockers?.length > 0 && (
                  <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                    <strong>Admin override recorded:</strong> {publishAssessment.override_reason}
                  </div>
                )}
                {canDecide && mayPublish && (
                  <button
                    type="button"
                    className="btn-primary mt-4 w-full"
                    onClick={publishContent}
                    disabled={busy || publishLoading || !publishAssessment.can_publish}
                  >
                    {publishAssessment.state === "Published" ? "Revision published" : "Publish this revision"}
                  </button>
                )}
                {canOverridePublish(user?.role, publishAssessment) && (
                  <form className="mt-4 rounded-lg border border-amber-200 p-3" onSubmit={publishWithOverride}>
                    <label className="block text-sm font-semibold text-amber-900" htmlFor="publish-override-reason">
                      Admin risk override justification
                    </label>
                    <textarea
                      id="publish-override-reason"
                      className="field mt-2 resize-y"
                      rows={3}
                      maxLength={2000}
                      value={overrideReason}
                      onChange={(event) => setOverrideReason(event.target.value)}
                      placeholder="Explain why publishing despite these eligible risks is necessary (minimum 10 characters)."
                    />
                    <button
                      className="btn-secondary mt-2 w-full border-amber-300 text-amber-900"
                      type="submit"
                      disabled={busy || overrideReason.trim().length < 10}
                    >
                      Publish with documented override
                    </button>
                  </form>
                )}
                {!!publishHistory.publications?.length && (
                  <div className="mt-4 border-t border-slate-100 pt-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Publication history</p>
                    <div className="mt-2 space-y-2">
                      {publishHistory.publications.map((publication) => (
                        <div key={publication.id} className="rounded-md bg-slate-50 p-2 text-xs text-slate-700">
                          <p className="font-medium">
                            Revision {publication.revision_id} · Risk {publication.risk_level} ({publication.risk_score}/100)
                          </p>
                          <p className="mt-1">
                            {publication.published_by || "Workspace user"} · {publication.created_at ? new Date(publication.created_at).toLocaleString() : "time unavailable"}
                          </p>
                          {publication.snapshot?.override_reason && (
                            <p className="mt-1 text-amber-800">Override: {publication.snapshot.override_reason}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {!!publishHistory.events?.length && (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs font-medium text-slate-600">Publish attempts and overrides ({publishHistory.events.length})</summary>
                    <div className="mt-2 space-y-2">
                      {publishHistory.events.map((entry) => (
                        <div key={entry.id} className="border-l-2 border-ink-200 pl-3 text-xs text-slate-600">
                          <p className="font-medium">{entry.action.replaceAll("_", " ")} · revision {entry.revision_id}</p>
                          <p>{entry.actor || "System"} · {entry.created_at ? new Date(entry.created_at).toLocaleString() : "time unavailable"} · {entry.risk_level} ({entry.risk_score}/100)</p>
                          {entry.details?.reason && <p>Reason: {entry.details.reason}</p>}
                        </div>
                      ))}
                    </div>
                  </details>
                )}
                {!publishHistory.events?.length && !publishHistory.publications?.length && !publishLoading && (
                  <p className="mt-4 text-xs text-slate-500">No publish attempts or publications have been recorded yet.</p>
                )}
              </>
            )}
          </section>

          {canDecide ? (
            <section className="card p-5">
              <h2 className="font-semibold text-ink-900">
                Reviewer decision
              </h2>

              <p className="mt-1 text-xs leading-5 text-slate-500">
                Use your judgment. These actions record a human
                review decision.
              </p>

              <div className="mt-4 rounded-lg bg-slate-50 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Assigned reviewers and approval stages
                </p>
                {isAdmin ? (
                  <div className="mt-3 space-y-2">
                    {reviewers.length ? reviewers.map((reviewer) => {
                      const assignment = selectedAssignments.find(
                        (entry) => entry.reviewer_id === reviewer.id,
                      );
                      return (
                        <div
                          key={reviewer.id}
                          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-white p-2"
                        >
                          <label className="flex items-center gap-2 text-sm text-slate-700">
                            <input
                              type="checkbox"
                              checked={Boolean(assignment)}
                              disabled={busy}
                              onChange={(event) => {
                                setSelectedAssignments((current) =>
                                  event.target.checked
                                    ? [...current, { reviewer_id: reviewer.id, stage_number: 1 }]
                                    : current.filter((entry) => entry.reviewer_id !== reviewer.id),
                                );
                              }}
                            />
                            {reviewer.display_name}
                          </label>
                          {assignment && (
                            <label className="flex items-center gap-2 text-xs text-slate-500">
                              Stage
                              <select
                                className="field w-20 py-1"
                                value={assignment.stage_number}
                                disabled={busy}
                                onChange={(event) => {
                                  const stage_number = Number(event.target.value);
                                  setSelectedAssignments((current) =>
                                    current.map((entry) =>
                                      entry.reviewer_id === reviewer.id
                                        ? { ...entry, stage_number }
                                        : entry,
                                    ),
                                  );
                                }}
                              >
                                {Array.from({ length: 10 }, (_, index) => index + 1).map((stage) => (
                                  <option key={stage} value={stage}>{stage}</option>
                                ))}
                              </select>
                            </label>
                          )}
                        </div>
                      );
                    }) : (
                      <p className="text-sm text-slate-500">No active reviewers are available.</p>
                    )}
                    <button
                      type="button"
                      className="btn-secondary mt-2 w-full"
                      disabled={busy || selectedAssignments.length === 0}
                      onClick={saveAssignments}
                    >
                      Save reviewer stages
                    </button>
                  </div>
                ) : (
                  <div className="mt-2 space-y-1">
                    {(item.assigned_reviewers || []).length ? (
                      item.assigned_reviewers.map((assignment) => (
                        <p key={`${assignment.id}-${assignment.stage_number}`} className="text-sm text-slate-700">
                          {assignment.display_name || "Reviewer"} · Stage {assignment.stage_number}
                        </p>
                      ))
                    ) : (
                      <p className="text-sm text-slate-700">Unassigned</p>
                    )}
                  </div>
                )}
                {assignmentError && (
                  <p role="alert" className="mt-2 text-xs text-rose-700">
                    {assignmentError}
                  </p>
                )}
              </div>

              <div className="mt-4 grid gap-2">
                <button
                  className="btn-primary w-full"
                  onClick={() => updateStatus("approved")}
                  disabled={
                    busy ||
                    item.status === "approved" ||
                    (item.assigned_reviewers?.length > 0 &&
                      (user?.role === "admin" || !isCurrentAssignedReviewer))
                  }
                >
                  <CheckCircle2 size={16} />
                  {item.assigned_reviewers?.length > 0
                    ? "Approve at my stage"
                    : "Approve content"}
                </button>

                <button
                  className="btn-secondary w-full"
                  onClick={() =>
                    updateStatus("changes_requested")
                  }
                  disabled={
                    busy ||
                    item.status === "changes_requested" ||
                    (item.assigned_reviewers?.length > 0 &&
                      user?.role === "reviewer" &&
                      !isCurrentAssignedReviewer)
                  }
                >
                  Request changes
                </button>

                <button
                  className="btn-secondary w-full"
                  onClick={() => updateStatus("rejected")}
                  disabled={
                    busy ||
                    item.status === "rejected" ||
                    (item.assigned_reviewers?.length > 0 &&
                      user?.role === "reviewer" &&
                      !isCurrentAssignedReviewer)
                  }
                >
                  Reject content
                </button>

                <button
                  className="btn-secondary w-full"
                  onClick={() => updateStatus("in_review")}
                  disabled={busy || item.status === "in_review"}
                >
                  Mark in review
                </button>
                {isAdmin && item.assigned_reviewers?.length > 0 && (
                  <button
                    className="btn-secondary w-full border-amber-300 text-amber-800"
                    onClick={bypassApproval}
                    disabled={busy || ["approved", "rejected"].includes(item.status)}
                  >
                    Admin approval bypass…
                  </button>
                )}
              </div>
              {!!item.approval_stages?.length && (
                <div className="mt-4 rounded-lg border border-slate-200 p-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Approval progress
                  </h3>
                  <div className="mt-2 space-y-2">
                    {item.approval_stages.map((stage) => (
                      <div key={stage.stage_number} className="text-sm">
                        <p className="font-medium text-slate-700">
                          Stage {stage.stage_number}: {stage.status.replaceAll("_", " ")}
                          {" "}({stage.approved}/{stage.required} approvals)
                        </p>
                        <p className="text-xs text-slate-500">
                          {stage.reviewers.map((person) =>
                            `${person.display_name || "Reviewer"} — ${person.decision.replaceAll("_", " ")}`,
                          ).join(" · ")}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          ) : (
            <section className="card p-5">
              <h2 className="font-semibold text-ink-900">
                Reviewer decision
              </h2>

              <p className="mt-1 text-sm leading-6 text-slate-500">
                Your Contributor role can comment and suggest
                revisions. An Admin or Reviewer records the approval
                decision.
              </p>
              <p className="mt-2 text-sm text-slate-600">
                Assigned reviewer:{" "}
                {item.assigned_reviewer?.display_name ||
                  item.reviewer ||
                  "Unassigned"}
              </p>
              {user?.role === "contributor" &&
                ["changes_requested", "draft"].includes(item.status) && (
                  <button
                    className="btn-primary mt-4 w-full"
                    onClick={() => updateStatus("submitted")}
                    disabled={busy}
                  >
                    Submit revision for review
                  </button>
                )}
              {user?.role === "contributor" &&
                ["pending", "submitted"].includes(item.status) && (
                  <button
                    className="btn-secondary mt-4 w-full"
                    onClick={() => updateStatus("draft")}
                    disabled={busy}
                  >
                    Save as draft
                  </button>
                )}
            </section>
          )}

          <section className="card p-5">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <MessageSquare
                  size={17}
                  className="text-ink-600"
                />
                <h2 className="font-semibold text-ink-900">
                  Review comments
                </h2>
              </div>

              <span
                className={`inline-flex items-center gap-1.5 text-xs ${
                  liveState === "connected"
                    ? "text-emerald-700"
                    : "text-slate-400"
                }`}
              >
                <Radio size={13} />
                {liveState === "connected"
                  ? "Live"
                  : liveState === "connecting"
                    ? "Connecting…"
                    : liveState === "disconnected"
                      ? "Reconnecting…"
                      : "Offline"}
              </span>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Viewing now:{" "}
              {participants.length
                ? participants.map((participant) => participant.display_name).join(", ")
                : liveState === "connected"
                  ? "You are the only connected participant."
                  : "Participant list unavailable while disconnected."}
            </p>

            <form className="mt-4" onSubmit={addComment}>
              <label
                className="sr-only"
                htmlFor="review-comment"
              >
                Add a comment
              </label>

              <textarea
                id="review-comment"
                className="field resize-y"
                rows={3}
                value={comment}
                onChange={(event) =>
                  setComment(event.target.value)
                }
                placeholder="Share context or feedback..."
              />

              {canDecide && (
                <label className="mt-3 flex items-center gap-2 text-sm text-slate-600">
                  <input
                    type="checkbox"
                    checked={internalNote}
                    onChange={(event) =>
                      setInternalNote(event.target.checked)
                    }
                  />
                  Internal note (visible only to Admins and Reviewers)
                </label>
              )}

              <button
                className="btn-secondary mt-2 w-full"
                type="submit"
                disabled={busy || !comment.trim()}
              >
                <Send size={15} />
                {internalNote ? "Add internal note" : "Add comment"}
              </button>
            </form>

            <div className="mt-4 space-y-3">
              {comments.length ? (
                comments.map((entry, index) => (
                  <div
                    key={entry.id || index}
                    className="rounded-lg bg-slate-50 p-3"
                  >
                    <div className="flex justify-between gap-2 text-xs">
                      <span className="font-semibold text-slate-700">
                        {entry.author || entry.user || "Reviewer"}
                        {entry.is_internal && (
                          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">
                            Internal
                          </span>
                        )}
                      </span>

                      <span className="text-slate-400">
                        {entry.created_at
                          ? new Date(
                              entry.created_at
                            ).toLocaleString()
                          : ""}
                      </span>
                    </div>

                    <p className="mt-2 whitespace-pre-wrap text-sm leading-5 text-slate-600">
                      {entry.comment || entry.text}
                    </p>
                    {entry.parent_id && (
                      <p className="mt-1 text-[11px] text-slate-400">
                        Threaded reply to comment #{entry.parent_id}
                      </p>
                    )}
                    {(canDecide || !entry.is_internal) && (
                      <button
                        type="button"
                        className="mt-2 text-xs font-medium text-ink-700 hover:underline"
                        onClick={() =>
                          setReplyTo({
                            id: entry.id,
                            author: entry.author || "comment",
                            is_internal: Boolean(entry.is_internal),
                          })
                        }
                      >
                        Reply
                      </button>
                    )}
                    {replyTo?.id === entry.id && (
                      <form className="mt-2" onSubmit={addReply}>
                        <label className="sr-only" htmlFor={`reply-${entry.id}`}>
                          Reply to {replyTo.author}
                        </label>
                        <textarea
                          id={`reply-${entry.id}`}
                          className="field resize-y"
                          rows={2}
                          value={replyText}
                          onChange={(event) => setReplyText(event.target.value)}
                          placeholder="Write a reply..."
                        />
                        {replyTo.is_internal && (
                          <p className="mt-1 text-xs text-amber-800">
                            This reply is internal and only visible to reviewers.
                          </p>
                        )}
                        <div className="mt-2 flex gap-2">
                          <button
                            className="btn-secondary"
                            type="submit"
                            disabled={busy || !replyText.trim()}
                          >
                            Send reply
                          </button>
                          <button
                            className="btn-secondary"
                            type="button"
                            onClick={() => setReplyTo(null)}
                          >
                            Cancel
                          </button>
                        </div>
                      </form>
                    )}
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-400">
                  No comments yet.
                </p>
              )}
            </div>
          </section>

          <section className="card p-5">
            <div className="flex items-center gap-2">
              <History
                size={17}
                className="text-ink-600"
              />
              <h2 className="font-semibold text-ink-900">
                Revision history
              </h2>
            </div>

            {versions.length ? (
              <>
                <div className="mt-4 space-y-3">
                  {versions.map((version, index) => (
                  <div
                    key={version.id ?? index}
                    className="border-l-2 border-ink-200 pl-3"
                  >
                    <p className="text-sm font-medium text-slate-700">
                      {version.title || `Version ${index + 1}`}
                      {index === versions.length - 1 && (
                        <span className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-emerald-700">
                          Current
                        </span>
                      )}
                    </p>

                    <p className="mt-1 text-xs text-slate-400">
                      {version.author ? `${version.author} · ` : ""}
                      {version.created_at
                        ? new Date(
                            version.created_at
                          ).toLocaleString()
                        : "Date unavailable"}
                    </p>
                  </div>
                ))}
                </div>
                {versions.length > 1 && (
                  <div className="mt-4 space-y-2">
                    <label className="block text-xs font-medium text-slate-600">
                      Compare versions
                      <select
                        className="field mt-1"
                        value={selectedFromVersion}
                        onChange={(event) => setSelectedFromVersion(event.target.value)}
                      >
                        {versions.map((version) => (
                          <option key={`from-${version.id}`} value={version.id}>
                            {version.title || `Version ${version.id}`}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block text-xs font-medium text-slate-600">
                      With
                      <select
                        className="field mt-1"
                        value={selectedToVersion}
                        onChange={(event) => setSelectedToVersion(event.target.value)}
                      >
                        {versions.map((version) => (
                          <option key={`to-${version.id}`} value={version.id}>
                            {version.title || `Version ${version.id}`}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className="btn-secondary w-full" onClick={compareVersions}>
                      Compare selected versions
                    </button>
                    {versionComparisonError && (
                      <p role="alert" className="text-xs text-rose-700">
                        {versionComparisonError}
                      </p>
                    )}
                    {versionComparison && (
                      <div className="max-h-80 overflow-auto rounded-lg border border-slate-200 bg-white p-3 text-sm leading-6">
                        {versionComparison.segments.map((segment, index) => (
                          <span
                            key={`${segment.type}-${index}`}
                            className={
                              segment.type === "added"
                                ? "bg-emerald-100 text-emerald-900"
                                : segment.type === "removed"
                                  ? "bg-rose-100 text-rose-900 line-through"
                                  : "text-slate-700"
                            }
                          >
                            {segment.text}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <p className="mt-4 text-xs text-slate-400">
                No preserved versions are available for this review.
              </p>
            )}
          </section>

          <section className="card p-5">
            <div className="flex items-center gap-2">
              <History
                size={17}
                className="text-ink-600"
              />
              <h2 className="font-semibold text-ink-900">
                Activity & audit trail
              </h2>
            </div>

            <p className="mt-1 text-xs leading-5 text-slate-500">
              Append-only application activity log; not a
              cryptographic or tamper-proof audit system.
            </p>

            {activityError ? (
              <p
                role="alert"
                className="mt-3 text-sm text-rose-700"
              >
                {activityError}
              </p>
            ) : activity.length ? (
              <div className="mt-4 space-y-3">
                {activity.map((entry) => (
                  <div
                    key={entry.id}
                    className="border-l-2 border-ink-200 pl-3"
                  >
                    <p className="text-sm font-medium capitalize text-slate-700">
                      {entry.action.replaceAll("_", " ")}
                    </p>

                    <p className="mt-1 text-xs text-slate-400">
                      {entry.actor || "System"}
                      {" · "}
                      {entry.created_at
                        ? new Date(
                            entry.created_at
                          ).toLocaleString()
                        : ""}
                      {entry.details?.status
                        ? ` · ${entry.details.status}`
                        : ""}
                      {entry.details?.reviewer_name
                        ? ` · ${entry.details.reviewer_name}`
                        : ""}
                      {entry.details?.reason
                        ? ` · ${entry.details.reason}`
                        : ""}
                      {entry.details?.comment_id
                        ? ` · Comment #${entry.details.comment_id}`
                        : ""}
                      {entry.details?.issue_count != null
                        ? ` · ${entry.details.issue_count} finding(s)`
                        : ""}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-xs text-slate-400">
                No activity has been recorded yet.
              </p>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
