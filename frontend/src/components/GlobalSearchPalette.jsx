import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem,
  CommandList, CommandSeparator,
} from "./ui/command";
import {
  Users, Stethoscope, Boxes, UserCog, CalendarDays, Building2, Search,
} from "lucide-react";
import api from "../lib/api";

const BUCKET_META = {
  patients: { label: "Patients", icon: Users },
  treatments: { label: "Treatments", icon: Stethoscope },
  inventory: { label: "Inventory", icon: Boxes },
  users: { label: "Users & Staff", icon: UserCog },
  appointments: { label: "Appointments", icon: CalendarDays },
  vendors: { label: "Vendors", icon: Building2 },
};

export default function GlobalSearchPalette({ open, onOpenChange }) {
  const [q, setQ] = React.useState("");
  const [results, setResults] = React.useState({});
  const [loading, setLoading] = React.useState(false);
  const navigate = useNavigate();

  // Debounced search
  React.useEffect(() => {
    if (!open) return;
    const query = q.trim();
    if (!query) { setResults({}); return; }
    const handle = setTimeout(async () => {
      setLoading(true);
      try {
        const r = await api.get("/search/global", { params: { q: query, limit: 6 } });
        setResults(r.data?.results || {});
      } catch { setResults({}); }
      finally { setLoading(false); }
    }, 220);
    return () => clearTimeout(handle);
  }, [q, open]);

  // Reset when closing
  React.useEffect(() => { if (!open) { setQ(""); setResults({}); } }, [open]);

  const go = (url) => {
    if (!url) return;
    onOpenChange(false);
    navigate(url);
  };

  const buckets = Object.entries(results);
  const emptyState = !loading && q.trim() && buckets.length === 0;

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} data-testid="global-search-palette">
      <Command shouldFilter={false}>
        <CommandInput
          value={q}
          onValueChange={setQ}
          placeholder="Search patients, treatments, inventory, users, appointments…"
          data-testid="global-search-input"
        />
        <CommandList className="max-h-[420px]">
          {!q.trim() && (
            <div className="py-8 text-center text-sm text-slate-500">
              <Search className="mx-auto mb-2 text-slate-300" size={22} />
              Type to search across the whole practice.
            </div>
          )}
          {loading && <div className="py-4 px-4 text-xs text-slate-500">Searching…</div>}
          {emptyState && <CommandEmpty>No results for “{q}”.</CommandEmpty>}
          {buckets.map(([bucket, items], idx) => {
            const meta = BUCKET_META[bucket] || { label: bucket, icon: Search };
            const Icon = meta.icon;
            return (
              <React.Fragment key={bucket}>
                {idx > 0 && <CommandSeparator />}
                <CommandGroup heading={meta.label}>
                  {items.map((it) => (
                    <CommandItem
                      key={`${bucket}-${it.id}`}
                      value={`${bucket}-${it.id}-${it.label}`}
                      onSelect={() => go(it.url)}
                      className="cursor-pointer"
                      data-testid={`palette-item-${bucket}-${it.id}`}
                    >
                      <Icon size={14} className="mr-2 text-[#8a6a3c]" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm truncate">{it.label}</div>
                        {it.sub && <div className="text-[11px] text-slate-500 truncate">{it.sub}</div>}
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </React.Fragment>
            );
          })}
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
