import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api, MOCK_MODE } from "../services/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => MOCK_MODE ? {
    display_name: "Mock workspace",
    role: "demo",
    is_mock: true,
  } : null);
  const [loading, setLoading] = useState(!MOCK_MODE);
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    if (MOCK_MODE) {
      setUser({
        display_name: "Mock workspace",
        role: "demo",
        is_mock: true,
      });
      return;
    }
    let active = true;
    api.authMe()
      .then((account) => {
        if (active) setUser(account);
      })
      .catch((error) => {
        if (!active) return;
        setUser(null);
        if (error.status === 401) {
          api.health()
            .then((health) => {
              if (active && !health.bootstrap_admin_configured) {
                setAuthError("If this is a new workspace, set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD in the backend environment, then restart the API.");
              }
            })
            .catch((healthError) => {
              if (active) setAuthError(healthError.message || "The API could not be reached.");
            });
        } else {
          setAuthError(error.message || "Could not verify the current session.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const clearSession = () => {
      setUser(null);
      setAuthError("");
    };
    window.addEventListener("inkloom:unauthorized", clearSession);
    return () => window.removeEventListener("inkloom:unauthorized", clearSession);
  }, []);

  const value = useMemo(() => ({
    user,
    loading,
    authError,
    signIn: async (credentials) => {
      const result = await api.login(credentials);
      setAuthError("");
      setUser(result.user);
      return result.user;
    },
    signOut: async () => {
      if (!MOCK_MODE) await api.logout();
      setUser(null);
    },
    setUser,
  }), [user, loading, authError]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
