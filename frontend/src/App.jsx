
import React, { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import RequireAuth from "./components/auth/RequireAuth";
import RequireAdmin from "./components/auth/RequireAdmin";
import AppShell from "./components/layout/AppShell";

// Load each page only when its route is needed.
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const ContentReviewPage = lazy(() => import("./pages/ContentReviewPage"));
const GuidelinesPage = lazy(() => import("./pages/GuidelinesPage"));
const ReviewQueuePage = lazy(() => import("./pages/ReviewQueuePage"));
const ReviewDetailPage = lazy(() => import("./pages/ReviewDetailPage"));
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const SourcesPage = lazy(() => import("./pages/SourcesPage"));
const VisualAssetsPage = lazy(() => import("./pages/VisualAssetsPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const ChangePasswordPage = lazy(() => import("./pages/ChangePasswordPage"));
const ForgotPasswordPage = lazy(() => import("./pages/ForgotPasswordPage"));
const ResetPasswordPage = lazy(() => import("./pages/ResetPasswordPage"));
const AcceptInvitationPage = lazy(
  () => import("./pages/AcceptInvitationPage")
);
const AdminPage = lazy(() => import("./pages/AdminPage"));

function PageLoader() {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "40vh",
        padding: "24px",
      }}
    >
      Loading page...
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="login" element={<LoginPage />} />
        <Route path="forgot-password" element={<ForgotPasswordPage />} />
        <Route path="reset-password" element={<ResetPasswordPage />} />
        <Route
          path="accept-invitation"
          element={<AcceptInvitationPage />}
        />

        <Route element={<RequireAuth />}>
          <Route path="change-password" element={<ChangePasswordPage />} />

          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="content/new" element={<ContentReviewPage />} />
            <Route path="reviews" element={<ReviewQueuePage />} />
            <Route
              path="reviews/:reviewId"
              element={<ReviewDetailPage />}
            />
            <Route path="guidelines" element={<GuidelinesPage />} />
            <Route path="sources" element={<SourcesPage />} />
            <Route path="visual-assets" element={<VisualAssetsPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="settings" element={<SettingsPage />} />

            <Route element={<RequireAdmin />}>
              <Route path="admin" element={<AdminPage />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  );
}
