import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { api, errorMessage } from "../services/api";
import { ErrorMessage } from "../components/common/UI";
import {
  getInvitationToken,
  removeInvitationTokenFromUrl,
} from "../utils/invitationToken";

export default function AcceptInvitationPage() {
  const [token] = useState(() =>
    getInvitationToken(window.location.search, window.location.hash),
  );
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    const safeUrl = removeInvitationTokenFromUrl(window.location.href);
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (safeUrl !== currentUrl) {
      window.history.replaceState(window.history.state, "", safeUrl);
    }
  }, []);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (password !== confirmation) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.acceptInvitation(token, password);
      setComplete(true);
    } catch (err) {
      setError(
        [400, 422].includes(err?.status)
          ? "This invitation link is invalid or expired. Ask your workspace administrator to send a new invitation."
          : errorMessage(err),
      );
    } finally {
      setBusy(false);
    }
  };

  return <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
    <section className="card w-full max-w-md p-6 sm:p-8">
      <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-ink-50 text-ink-700"><KeyRound size={21} /></div>
      <h1 className="text-xl font-bold text-ink-900">Accept your invitation</h1>
      {complete ? <div className="mt-4">
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm leading-6 text-emerald-900" role="status">Your account is active. Sign in using the password you just created.</p>
        <Link className="btn-primary mt-5 w-full justify-center" to="/login">Continue to sign in</Link>
      </div> : <>
        <p className="mt-1 text-sm leading-6 text-slate-500">Set a password to activate your InkLoom workspace account. Passwords must be at least 12 characters.</p>
        {!token && <p className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">The invitation link is missing or malformed. Ask your workspace administrator to send a new invitation.</p>}
        {error && <div className="mt-5"><ErrorMessage>{error}</ErrorMessage></div>}
        <form onSubmit={submit} className="mt-6 space-y-4">
          <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="invite-password">Create password</label><input id="invite-password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} className="field" /></div>
          <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="invite-password-confirm">Confirm password</label><input id="invite-password-confirm" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="field" /></div>
          <button className="btn-primary w-full justify-center" type="submit" disabled={busy || !token}>{busy ? "Activating…" : "Set password and activate account"}</button>
        </form>
      </>}
      <Link className="mt-5 inline-block text-sm text-slate-500 underline hover:text-ink-700" to="/login">Back to sign in</Link>
    </section>
  </main>;
}
