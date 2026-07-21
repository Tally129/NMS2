import React from "react";
import { Link } from "react-router-dom";
import { ClipboardList, AlertTriangle, Clock3, Pause } from "lucide-react";
import api from "../lib/api";

/**
 * Compact "My Tasks" widget for dashboards. Polls the summary endpoint every
 * 30s. Renders a set of counter tiles + a "notification badge" style pill for
 * overdue items. No email/SMS — badge only, per spec.
 */
export default function TasksWidget({ linkTo = "/portal/staff/tasks" }) {
  const [summary, setSummary] = React.useState(null);

  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/tasks/dashboard/summary");
      setSummary(r.data || {});
    } catch {
      setSummary({ my_tasks: 0, overdue: 0, due_today: 0, waiting: 0 });
    }
  }, []);

  React.useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  if (!summary) return null;

  const tiles = [
    { key: "my_tasks", label: "My tasks", value: summary.my_tasks, icon: ClipboardList,
      tone: "bg-[#eaf2ec] text-[#2f6a4a] border-[#cfe0d3]" },
    { key: "overdue", label: "Overdue", value: summary.overdue, icon: AlertTriangle,
      tone: summary.overdue > 0
        ? "bg-[#fdecec] text-[#7a2a2a] border-[#f0b4b4]"
        : "bg-[#f4f7f2] text-slate-500 border-[#e2ebe4]" },
    { key: "due_today", label: "Due today", value: summary.due_today, icon: Clock3,
      tone: summary.due_today > 0
        ? "bg-[#fdf3d0] text-[#8a6a3c] border-[#e6d38a]"
        : "bg-[#f4f7f2] text-slate-500 border-[#e2ebe4]" },
    { key: "waiting", label: "Waiting", value: summary.waiting, icon: Pause,
      tone: "bg-[#f4f7f2] text-slate-500 border-[#e2ebe4]" },
  ];

  return (
    <Link
      to={linkTo}
      data-testid="tasks-widget"
      className="block rounded-2xl border border-[#e2ebe4] bg-white p-5 hover:shadow-md transition-shadow"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="eyebrow text-[#3d6b52]">My tasks</div>
        {summary.overdue > 0 && (
          <span
            className="inline-flex items-center gap-1 text-[11px] font-medium bg-[#7a2a2a] text-white px-2 py-0.5 rounded-full"
            data-testid="tasks-widget-overdue-badge"
          >
            <AlertTriangle size={11} /> {summary.overdue} overdue
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {tiles.map(({ key, label, value, icon: Icon, tone }) => (
          <div
            key={key}
            className={`rounded-xl border ${tone} p-3`}
            data-testid={`tasks-widget-tile-${key}`}
          >
            <div className="flex items-center gap-2">
              <Icon size={13} />
              <span className="text-[11px] uppercase tracking-wider">{label}</span>
            </div>
            <div className="text-2xl font-display mt-1">{value ?? 0}</div>
          </div>
        ))}
      </div>
    </Link>
  );
}
