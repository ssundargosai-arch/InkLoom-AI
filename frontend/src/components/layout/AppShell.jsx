import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Activity, BookOpenText, CheckCheck, ChevronLeft, ChevronRight, FileText, LayoutDashboard, LogOut, Menu, Settings2, ShieldCheck, X, LibraryBig, Users, Images } from "lucide-react";
import { MOCK_MODE } from "../../services/api";
import { useAuth } from "../../contexts/AuthContext";

const links = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/content/new", label: "New review", icon: FileText },
  { to: "/reviews", label: "Review queue", icon: CheckCheck },
  { to: "/guidelines", label: "Brand guidelines", icon: BookOpenText },
  { to: "/sources", label: "Evidence sources", icon: LibraryBig },
  { to: "/visual-assets", label: "Visual assets", icon: Images },
  { to: "/analytics", label: "Analytics", icon: Activity },
];

export default function AppShell() {
  const { user, signOut } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const onSignOut = async () => {
    setSignOutError("");
    try {
      await signOut();
    } catch {
      setSignOutError("Sign out failed. Check the API connection and try again.");
    }
  };
  const aside = <aside className={`fixed inset-y-0 left-0 z-40 flex w-[260px] flex-col border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"} ${collapsed ? "lg:w-[76px]" : ""}`}>
    <div className="flex h-[76px] items-center gap-3 border-b border-slate-100 px-5">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ink-900 text-white"><ShieldCheck className="h-5 w-5" /></div>
      {!collapsed && <div className="min-w-0"><div className="font-bold tracking-tight text-ink-900">InkLoom <span className="text-ink-600">AI</span></div><div className="text-[10px] font-semibold uppercase tracking-[.15em] text-slate-400">Brand governance</div></div>}
      <button className="ml-auto rounded p-1 text-slate-400 hover:bg-slate-100 lg:hidden" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X size={18} /></button>
    </div>
    <nav className="flex-1 space-y-1 px-3 py-5" aria-label="Main navigation">
      {!collapsed && <p className="mb-3 px-3 text-[10px] font-bold uppercase tracking-[.16em] text-slate-400">Workspace</p>}
      {[...links, ...(user?.role === "admin" ? [{ to: "/admin", label: "Admin dashboard", icon: Users }] : [])].map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} title={collapsed ? label : undefined} onClick={() => setMobileOpen(false)} className={({ isActive }) => `group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${isActive ? "bg-ink-50 text-ink-700" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"} ${collapsed ? "justify-center" : ""}`}><Icon size={18} strokeWidth={1.8} /><span className={collapsed ? "lg:hidden" : ""}>{label}</span></NavLink>)}
    </nav>
    <div className="border-t border-slate-100 p-3">
      <NavLink to="/settings" title={collapsed ? "Settings" : undefined} className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium ${isActive ? "bg-ink-50 text-ink-700" : "text-slate-500 hover:bg-slate-50"} ${collapsed ? "justify-center" : ""}`}><Settings2 size={18} /><span className={collapsed ? "lg:hidden" : ""}>Settings</span></NavLink>
      {MOCK_MODE && !collapsed && <div className="mx-1 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2"><p className="text-[11px] font-bold uppercase tracking-wide text-amber-800">Demo mode</p><p className="mt-1 text-xs leading-4 text-amber-700">Showing clearly labeled mock data.</p></div>}
      <button className="mt-3 hidden w-full items-center justify-center rounded-lg p-2 text-slate-400 hover:bg-slate-100 lg:flex" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>{collapsed ? <ChevronRight size={17} /> : <ChevronLeft size={17} />}</button>
    </div>
  </aside>;

  return <div className="min-h-screen lg:flex">
    {mobileOpen && <button aria-label="Close navigation overlay" onClick={() => setMobileOpen(false)} className="fixed inset-0 z-30 bg-slate-950/30 lg:hidden" />}
    {aside}
    <div className="min-w-0 flex-1">
      <header className="sticky top-0 z-20 flex h-[76px] items-center justify-between border-b border-slate-200/80 bg-white/95 px-4 backdrop-blur sm:px-8">
        <button className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 lg:hidden" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={20} /></button>
        <div className="hidden text-sm text-slate-500 sm:block">A clearer standard for every story.</div>
        <div className="ml-auto flex items-center gap-3"><div className="hidden text-right sm:block"><p className="text-xs font-semibold text-slate-700">{user?.display_name || "Workspace member"}</p><p className="text-[10px] capitalize text-slate-400">{user?.is_mock ? "demo · no authentication" : user?.role || "member"}</p></div>{!MOCK_MODE && <><Link to="/change-password" className="hidden text-xs font-medium text-slate-500 hover:text-ink-700 sm:block">Change password</Link><button className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink-700" aria-label="Sign out" title="Sign out" onClick={onSignOut}><LogOut size={17} /></button></>}</div>
      </header>
      {signOutError && <p role="alert" className="border-b border-rose-200 bg-rose-50 px-5 py-2 text-sm text-rose-800">{signOutError}</p>}
      {MOCK_MODE && <p className="border-b border-amber-200 bg-amber-50 px-5 py-2 text-xs text-amber-900">Demo mode: authentication and role enforcement are disabled; this is not a secured workspace.</p>}
      <main className="mx-auto w-full max-w-[1440px] p-4 sm:p-7 lg:p-9"><Outlet /></main>
    </div>
  </div>;
}
