import React from "react";
import PortalLayout, { PortalHeader, StatCard } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { useToast } from "../../hooks/use-toast";
import {
  Plus,
  Pencil,
  AlertTriangle,
  Boxes,
  Sliders,
  Calendar as CalendarIcon,
  Search,
  Archive,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { getErrorMessage } from "../../lib/errors";
import { normalizeArray } from "../../lib/collections";

const empty = { name: "", sku: "", category: "", stock: 0, unit_price: 0, low_stock_threshold: 5, active: true };
const emptyLot = { lot_number: "", qty: 1, expires_on: "", note: "" };

export default function Inventory() {
  const { toast } = useToast();
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [edit, setEdit] = React.useState(null);
  const [form, setForm] = React.useState(empty);
  const [adjust, setAdjust] = React.useState(null);
  const [adjustForm, setAdjustForm] = React.useState({ delta: 0, reason: "manual", note: "" });
  const [lotFor, setLotFor] = React.useState(null);
  const [lotForm, setLotForm] = React.useState(emptyLot);
  const [expiring, setExpiring] = React.useState([]);
  const [q, setQ] = React.useState("");
  const [categoryFilter, setCategoryFilter] = React.useState("all");
  const [statusFilter, setStatusFilter] = React.useState("active");
  const [archiveTarget, setArchiveTarget] = React.useState(null);
  const [archiving, setArchiving] = React.useState(false);

  const load = () => {
    api.get("/inventory").then((r) => setItems(normalizeArray(r.data, ["items"]))).finally(() => setLoading(false));
    api.get("/inventory/expiring?days=60").then((r) => setExpiring(normalizeArray(r.data, ["expiring"]))).catch(() => {});
  };
  React.useEffect(() => { load(); }, []);

  const categories = React.useMemo(() => {
    return [...new Set(
      normalizeArray(items)
        .map((item) => (item.category || "").trim())
        .filter(Boolean)
    )].sort((a, b) => a.localeCompare(b));
  }, [items]);

  const filtered = React.useMemo(() => {
    const search = q.trim().toLowerCase();

    return normalizeArray(items).filter((item) => {
      const matchesSearch =
        !search ||
        (item.name || "").toLowerCase().includes(search) ||
        (item.sku || "").toLowerCase().includes(search) ||
        (item.category || "").toLowerCase().includes(search);

      const matchesCategory =
        categoryFilter === "all" ||
        item.category === categoryFilter;

      const isArchived = item.active === false;

      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "active" && !isArchived) ||
        (statusFilter === "archived" && isArchived);

      return matchesSearch && matchesCategory && matchesStatus;
    });
  }, [items, q, categoryFilter, statusFilter]);

  const activeItems = normalizeArray(items).filter(
    (item) => item.active !== false
  );

  const lowStock = activeItems.filter(
    (item) =>
      (item.stock || 0) <=
      (item.low_stock_threshold || 5)
  );

  const openNew = () => { setEdit("new"); setForm(empty); };
  const openEdit = (i) => { setEdit(i.id); setForm({ ...empty, ...i }); };
  const save = async () => {
    if (!form.name) { toast({ title: "Name required" }); return; }
    try {
      const payload = {
        ...form,
        stock: parseInt(form.stock) || 0,
        unit_price: parseFloat(form.unit_price) || 0,
        low_stock_threshold: parseInt(form.low_stock_threshold) || 5,
        sku: form.sku || null,
        category: form.category || null,
      };
      if (edit === "new") await api.post("/inventory", payload);
      else await api.put(`/inventory/${edit}`, payload);
      toast({ title: "Saved" });
      setEdit(null); load();
    } catch (e) {
      toast({ title: "Failed", description: getErrorMessage(e) || "" });
    }
  };

  const doAdjust = async () => {
    if (!adjust) return;
    try {
      await api.post(`/inventory/${adjust.id}/adjust`, {
        delta: parseInt(adjustForm.delta) || 0,
        reason: adjustForm.reason || "manual",
        note: adjustForm.note || null,
      });
      toast({ title: "Stock adjusted" });
      setAdjust(null); setAdjustForm({ delta: 0, reason: "manual", note: "" });
      load();
    } catch (e) {
      toast({ title: "Failed", description: getErrorMessage(e) || "" });
    }
  };

  const addLot = async () => {
    if (!lotFor) return;
    try {
      await api.post(`/inventory/${lotFor.id}/lots`, {
        lot_number: lotForm.lot_number,
        qty: parseInt(lotForm.qty) || 0,
        expires_on: lotForm.expires_on || null,
        note: lotForm.note || "",
      });
      toast({ title: "Lot added" });
      setLotFor(null); setLotForm(emptyLot); load();
    } catch (e) { toast({ title: "Failed", description: getErrorMessage(e) || "" }); }
  };

  const archiveItem = async () => {
    if (!archiveTarget) return;

    setArchiving(true);

    try {
      await api.delete(`/inventory/${archiveTarget.id}`);

      toast({
        title: "Item archived",
        description: `${archiveTarget.name} was removed from active inventory.`,
      });

      setArchiveTarget(null);
      load();
    } catch (error) {
      toast({
        title: "Archive failed",
        description: getErrorMessage(error) || "",
      });
    } finally {
      setArchiving(false);
    }
  };

  const restoreItem = async (item) => {
    try {
      await api.post(`/inventory/${item.id}/restore`);

      toast({
        title: "Item restored",
        description: `${item.name} is active again.`,
      });

      load();
    } catch (error) {
      toast({
        title: "Restore failed",
        description: getErrorMessage(error) || "",
      });
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Inventory"
        subtitle={`${items.length} items · auto-decrements on POS sales`}
        actions={
          <Button onClick={openNew} className="btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="inv-new-btn">
            <Plus size={16} className="mr-2" /> New item
          </Button>
        }
      />

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <StatCard label="Total items" value={items.length} icon={Boxes} />
        <StatCard label="Low stock" value={lowStock.length} icon={AlertTriangle} accent={lowStock.length ? "text-[#7a2a2a]" : ""} />
        <StatCard label="Stock value" value={`$${normalizeArray(items).reduce((s, i) => s + (i.stock || 0) * (i.unit_price || 0), 0).toFixed(2)}`} icon={Boxes} />
      </div>

      {lowStock.length > 0 && (
        <div className="mb-6 rounded-2xl border-2 border-[#7a2a2a] bg-[#fff5f5] p-4 text-sm" data-testid="low-stock-banner">
          <div className="flex items-center gap-2 font-semibold text-[#7a2a2a] mb-2">
            <AlertTriangle size={16} /> Low stock alerts
          </div>
          <div className="text-[#5e1f1f] space-y-1">
            {lowStock.map((i) => (
              <div key={i.id}>· <strong>{i.name}</strong>: {i.stock} left (threshold {i.low_stock_threshold})</div>
            ))}
          </div>
        </div>
      )}

      {expiring.length > 0 && (
        <div className="mb-6 rounded-2xl border-2 border-[#c19a4b] bg-[#fbf3df] p-4 text-sm" data-testid="expiring-banner">
          <div className="flex items-center gap-2 font-semibold text-[#8a6a3c] mb-2">
            <CalendarIcon size={16} /> Expiring within 60 days
          </div>
          <div className="text-[#6a4f1d] space-y-1">
            {normalizeArray(expiring).map((i) => (
              <div key={i.id}>· <strong>{i.name}</strong> · lot {i.expiring_lot?.lot_number || "—"} · qty {i.expiring_lot?.qty} · expires {i.expiring_lot?.expires_on}</div>
            ))}
          </div>
        </div>
      )}

      <div className="mb-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px_180px]">
        <div className="relative">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]"
          />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name, SKU, or category…"
            className="pl-9 bg-[#fbf7ee] border-[#e0d6bc]"
            data-testid="inventory-search-input"
          />
        </div>

        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="h-10 rounded-md border border-[#e0d6bc] bg-[#fbf7ee] px-3 text-sm text-[#1f2a22]"
          data-testid="inventory-category-filter"
        >
          <option value="all">All categories</option>
          {categories.map((category) => (
            <option key={category} value={category}>
              {category}
            </option>
          ))}
        </select>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-10 rounded-md border border-[#e0d6bc] bg-[#fbf7ee] px-3 text-sm text-[#1f2a22]"
          data-testid="inventory-status-filter"
        >
          <option value="active">Active items</option>
          <option value="archived">Archived items</option>
          <option value="all">All statuses</option>
        </select>
      </div>

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden" data-testid="inventory-table">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Item</th>
              <th className="text-left py-3 px-4">SKU</th>
              <th className="text-left py-3 px-4">Category</th>
              <th className="text-left py-3 px-4">Stock</th>
              <th className="text-left py-3 px-4">Threshold</th>
              <th className="text-left py-3 px-4">Price</th>
              <th className="text-right py-3 px-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {!loading && filtered.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-[#6a6a6a]">{q ? `No inventory items match "${q}".` : 'No inventory items yet.'}</td></tr>}
            {filtered.map((i) => {
              const low = (i.stock || 0) <= (i.low_stock_threshold || 5);
              return (
                <tr key={i.id} className="border-t border-[#e7dfc9]" data-testid={`inv-row-${i.id}`}>
                  <td className="py-3 px-4 font-medium text-[#1f2a22]">{i.name}</td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{i.sku || "—"}</td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{i.category || "—"}</td>
                  <td className={`py-3 px-4 font-display text-[18px] ${low ? "text-[#7a2a2a]" : "text-[#2f4a3a]"}`}>
                    {i.stock || 0}{low && <span className="text-xs ml-1">low</span>}
                  </td>
                  <td className="py-3 px-4 text-[#6a6a6a]">{i.low_stock_threshold || 5}</td>
                  <td className="py-3 px-4 font-display text-[#2f4a3a]">${(i.unit_price || 0).toFixed(2)}</td>
                  <td className="py-3 px-4 text-right space-x-1">
                    <Button size="sm" variant="outline" className="h-7 rounded-full text-xs border-[#c19a4b] text-[#8a6a3c]" onClick={() => setLotFor(i)} data-testid={`inv-lot-${i.id}`}>
                      <CalendarIcon size={12} className="mr-1" /> Lot
                    </Button>
                    <Button size="sm" variant="outline" className="h-7 rounded-full text-xs border-[#c19a4b] text-[#8a6a3c]" onClick={() => setAdjust(i)} data-testid={`inv-adjust-${i.id}`}>
                      <Sliders size={12} className="mr-1" /> Adjust
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 rounded-full text-xs border-[#2f4a3a] text-[#2f4a3a]"
                      onClick={() => openEdit(i)}
                      data-testid={`inv-edit-${i.id}`}
                    >
                      <Pencil size={12} />
                    </Button>

                    {i.active === false ? (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 rounded-full text-xs border-[#2f4a3a] text-[#2f4a3a]"
                        onClick={() => restoreItem(i)}
                        data-testid={`inv-restore-${i.id}`}
                      >
                        <RotateCcw size={12} className="mr-1" />
                        Restore
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 rounded-full text-xs border-[#7a2a2a] text-[#7a2a2a]"
                        onClick={() => setArchiveTarget(i)}
                        data-testid={`inv-archive-${i.id}`}
                      >
                        <Archive size={12} className="mr-1" />
                        Archive
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle>{edit === "new" ? "New inventory item" : "Edit item"}</DialogTitle>
            <DialogDescription>Stock items decrement automatically on POS sale.</DialogDescription>
          </DialogHeader>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="md:col-span-2"><Label>Name</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="inv-name" /></div>
            <div><Label>SKU</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} /></div>
            <div><Label>Category</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></div>
            <div><Label>Stock</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} data-testid="inv-stock" /></div>
            <div><Label>Unit price</Label><Input type="number" step="0.01" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} data-testid="inv-price" /></div>
            <div><Label>Low-stock threshold</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.low_stock_threshold} onChange={(e) => setForm({ ...form, low_stock_threshold: e.target.value })} /></div>
            <div className="flex items-end"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Active</label></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEdit(null)}>Cancel</Button>
            <Button onClick={save} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="inv-save-btn">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!adjust} onOpenChange={(o) => !o && setAdjust(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle>Adjust stock — {adjust?.name}</DialogTitle>
            <DialogDescription>Record a manual stock change (restock, shrinkage, count).</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="text-sm text-[#6a6a6a]">Current stock: <strong>{adjust?.stock}</strong></div>
            <div><Label>Change (use negative for shrinkage)</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={adjustForm.delta} onChange={(e) => setAdjustForm({ ...adjustForm, delta: e.target.value })} data-testid="inv-adjust-delta" /></div>
            <div><Label>Reason</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={adjustForm.reason} onChange={(e) => setAdjustForm({ ...adjustForm, reason: e.target.value })} placeholder="restock / shrinkage / count" /></div>
            <div><Label>Note</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={adjustForm.note} onChange={(e) => setAdjustForm({ ...adjustForm, note: e.target.value })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAdjust(null)}>Cancel</Button>
            <Button onClick={doAdjust} className="bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]" data-testid="inv-adjust-confirm">Apply</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!lotFor} onOpenChange={(o) => !o && setLotFor(null)}>
        <DialogContent className="bg-[#fbf7ee] border-[#e7dfc9]">
          <DialogHeader>
            <DialogTitle>Add lot — {lotFor?.name}</DialogTitle>
            <DialogDescription>Track lot number, quantity received, and expiration date.</DialogDescription>
          </DialogHeader>
          <div className="grid sm:grid-cols-2 gap-3">
            <div className="sm:col-span-2"><Label>Lot number</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={lotForm.lot_number} onChange={(e) => setLotForm({ ...lotForm, lot_number: e.target.value })} data-testid="inv-lot-number" /></div>
            <div><Label>Qty received</Label><Input type="number" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={lotForm.qty} onChange={(e) => setLotForm({ ...lotForm, qty: e.target.value })} data-testid="inv-lot-qty" /></div>
            <div><Label>Expires on</Label><Input type="date" className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={lotForm.expires_on} onChange={(e) => setLotForm({ ...lotForm, expires_on: e.target.value })} data-testid="inv-lot-expiry" /></div>
            <div className="sm:col-span-2"><Label>Note</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={lotForm.note} onChange={(e) => setLotForm({ ...lotForm, note: e.target.value })} placeholder="vendor, PO #, etc." /></div>
            {(lotFor?.lots || []).length > 0 && (
              <div className="sm:col-span-2 rounded-lg bg-[#f6f1e6] border border-[#e0d6bc] p-3">
                <div className="eyebrow text-[#8a6a3c] mb-2 text-[10px]">Existing lots</div>
                <ul className="text-xs space-y-1">
                  {(lotFor?.lots || []).map((l) => (
                    <li key={l.id} className="flex justify-between text-[#3a3a3a]">
                      <span>{l.lot_number || "—"}</span>
                      <span>qty {l.qty}</span>
                      <span>{l.expires_on || "no expiry"}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLotFor(null)}>Cancel</Button>
            <Button onClick={addLot} className="bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="inv-lot-save">Add lot</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}