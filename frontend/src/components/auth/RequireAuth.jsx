import React from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { LoadingState } from "../common/UI";
import { useAuth } from "../../contexts/AuthContext";

export default function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingState label="Checking your workspace session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  if (user.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return <Outlet />;
}
