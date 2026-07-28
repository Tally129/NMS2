import React from "react";
import { useSearchParams } from "react-router-dom";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api, { downloadBlob } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { useToast } from "../../hooks/use-toast";
import { Plus, Trash2, Receipt, Stethoscope, Boxes, Pencil, Search } from "lucide-react";
import { getErrorMessage } from "../../lib/errors";

const PAY_METHODS = [
  { v: "chase_pos", label: "Chase POS" },
  { v: "cash", label: "Cash" },
  { v: "check", label: "Check" },
  { v: "card_other", label: "Card (other)" },
  { v: "stripe", label: "Stripe" },
];

export default function PointOfSale() {
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [treatments, setTreatments] = React.useState([]);
  const [inventory, setInventory] = React.useState([]);
  const [clients, setClients] = React.useState([]);
  const [cart, setCart] = React.useState([]);
  const [clientId, setClientId] = React.useState(
    searchParams.get("client_id") || "walkin",
  );
  // Handoff #4: when POS is opened from the front-desk row we carry the
  // appointment id through so the eventual checkout can write back onto
  // the appointment and mark it completed.
  const [appointmentId, setAppointmentId] = React.useState(
    searchParams.get("appointment_id") || null,
  );
  const [paymentMethod, setPaymentMethod] = React.useState("chase_pos");
  const [paymentRef, setPaymentRef] = React.useState("");
  const [discount, setDiscount] = React.useState(0);
  const [tip, setTip] = React.useState(0);
  const [taxRate, setTaxRate] = React.useState(0);
  const [note, setNote] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [customForm, setCustomForm] = React.useState({ name: "", unit_price: "" });
  const [treatmentQ, setTreatmentQ] = React.useState("");
  const [inventoryQ, setInventoryQ] = React.useState("");

  const load = async () => {
    try {
      const [t, i, c] = await Promise.all([
        api.get("/treatments?active_only=true"),
        api.get("/inventory"),
        api.get("/clients"),
      ]);
      setTreatments(t.data || []);
      setInventory((i.data || []).filter((x) => x.active !== false));
      setClients(c.data || []);
    } catch (e) {
      toast({ title: "Failed to load catalog", description: getErrorMessage(e) || "" });
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => { load(); }, []);

  const addTreatment = (t) => {
    const idx = cart.findIndex((l) => l.type === "treatment" && l.ref_id === t.id);
    if (idx >= 0) {
      const next = [...cart]; next[idx] = { ...next[idx], qty: next[idx].qty + 1 }; setCart(next);
    } else {
      setCart([...cart, { type: "treatment", ref_id: t.id, name: t.name, qty: 1, unit_price: t.price }]);
    }
  };
  const addInventory = (i) => {
    const idx = cart.findIndex((l) => l.type === "inventory" && l.ref_id === i.id);
    if (idx >= 0) {
      const next = [...cart]; next[idx] = { ...next[idx], qty: next[idx].qty + 1 }; setCart(next);
    } else {
      setCart([...cart, { type: "inventory", ref_id: i.id, name: i.name, qty: 1, unit_price: i.unit_price }]);
    }
  };
  const addCustom = () => {
    if (!customForm.name || !customForm.unit_price) return;
    setCart([...cart, { type: "custom", ref_id: null, name: customForm.name, qty: 1, unit_price: parseFloat(customForm.unit_price) }]);
    setCustomForm({ name: "", unit_price: "" });
  };
  const updateLine = (i, patch) => {
    const next = [...cart]; next[i] = { ...next[i], ...patch }; setCart(next);
  };
  const remove = (i) => setCart(cart.filter((_, idx) => idx !== i));

  const subtotal = cart.reduce((s, l) => s + l.qty * l.unit_price, 0);
  const afterDiscount = Math.max(0, subtotal - (discount || 0));
  const tax = afterDiscount * (taxRate || 0);
  const total = afterDiscount + tax + (tip || 0);

  const checkout = async () => {
    if (cart.length === 0) {
      toast({ title: "Cart is empty" });
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        client_id: clientId === "walkin" ? null : clientId,
        lines: cart.map((l) => ({ type: l.type, ref_id: l.ref_id, name: l.name, qty: l.qty, unit_price: l.unit_price })),
        discount: parseFloat(discount) || 0,
        tip: parseFloat(tip) || 0,
        tax_rate: parseFloat(taxRate) || 0,
        payment_method: paymentMethod,
        payment_ref: paymentRef || null,
        note: note || null,
        // Handoff #4: when set, backend marks this appointment `completed`
        // and stores `transaction_id` back on the appointment.
        appointment_id: appointmentId || undefined,
      };
      const r = await api.post("/pos/checkout", payload);
      toast({
        title: `Sale recorded · $${r.data.total.toFixed(2)}`,
        description: appointmentId ? "Appointment marked completed." : undefined,
      });
      // Download PDF receipt through the authenticated axios instance —
      // never read the bearer token from localStorage.
      try {
        await downloadBlob(`/transactions/${r.data.id}/receipt`, {
          filename: `receipt-${r.data.id.slice(0, 8)}.pdf`,
        });
      } catch (dlErr) {
        toast({
          title: "Receipt PDF unavailable",
          description: dlErr?.message || "Sale saved — download the receipt from Transactions.",
        });
      }
      // Reset cart
      setCart([]); setDiscount(0); setTip(0); setTaxRate(0); setNote(""); setPaymentRef("");
      // Clear the appointment context so the next sale is independent.
      setAppointmentId(null);
      if (searchParams.get("appointment_id") || searchParams.get("client_id")) {
        const next = new URLSearchParams(searchParams);
        next.delete("appointment_id");
        next.delete("client_id");
        setSearchParams(next, { replace: true });
      }
      load();
    } catch (e) {
      toast({ title: "Checkout failed", description: getErrorMessage(e) || "" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <PortalLayout>
      <PortalHeader title="Point of Sale" subtitle="Sell treatments, products, and custom line items" />

      {appointmentId && (
        <div className="mb-4 rounded-xl border border-[#2f4a3a] bg-[#eaf2ec] px-4 py-3 flex items-center justify-between"
             data-testid="pos-appointment-banner">
          <div className="text-sm text-[#2f4a3a]">
            <span className="font-medium">Appointment checkout</span> —
            completing this sale will mark the appointment as completed and
            record it against this visit.
          </div>
          <button
            type="button"
            onClick={() => {
              setAppointmentId(null);
              const next = new URLSearchParams(searchParams);
              next.delete("appointment_id");
              setSearchParams(next, { replace: true });
            }}
            className="text-xs text-[#2f4a3a] hover:underline"
            data-testid="pos-appointment-banner-clear"
          >
            Sell without linking
          </button>
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Catalog */}
        <div className="lg:col-span-2 rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5">
          <Tabs defaultValue="treatments">
            <TabsList className="bg-[#f1ead8]">
              <TabsTrigger value="treatments" data-testid="pos-tab-treatments"><Stethoscope size={14} className="mr-1" /> Treatments</TabsTrigger>
              <TabsTrigger value="inventory" data-testid="pos-tab-inventory"><Boxes size={14} className="mr-1" /> Inventory</TabsTrigger>
              <TabsTrigger value="custom" data-testid="pos-tab-custom"><Pencil size={14} className="mr-1" /> Custom</TabsTrigger>
            </TabsList>

            <TabsContent value="treatments" className="mt-4">
              <div className="mb-3 relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
                <Input
                  value={treatmentQ}
                  onChange={(e) => setTreatmentQ(e.target.value)}
                  placeholder="Search treatments…"
                  className="pl-9 bg-[#f6f1e6] border-[#e0d6bc] h-9"
                  data-testid="pos-treatments-search"
                />
              </div>
              {(() => {
                const s = treatmentQ.trim().toLowerCase();
                const filteredTx = s
                  ? treatments.filter((t) =>
                      (t.name || "").toLowerCase().includes(s) ||
                      (t.category || "").toLowerCase().includes(s) ||
                      (t.sku || "").toLowerCase().includes(s)
                    )
                  : treatments;
                if (filteredTx.length === 0) {
                  return <p className="text-sm text-[#6a6a6a]">{treatments.length === 0 ? "No active treatments. Add some in the Treatments page." : `No treatments match "${treatmentQ}".`}</p>;
                }
                return (
                  <div className="grid sm:grid-cols-2 gap-3">
                    {filteredTx.map((t) => (
                      <button
                        key={t.id}
                        onClick={() => addTreatment(t)}
                        className="text-left rounded-xl border border-[#e0d6bc] bg-[#f6f1e6] p-3 hover:bg-[#f1ead8] transition"
                        data-testid={`pos-treatment-${t.id}`}
                      >
                        <div className="font-medium text-[#1f2a22] text-sm">{t.name}</div>
                        <div className="text-xs text-[#6a6a6a]">{t.duration_min} min · {t.category || "general"}</div>
                        <div className="text-[#2f4a3a] font-display text-lg mt-1">${t.price.toFixed(2)}</div>
                      </button>
                    ))}
                  </div>
                );
              })()}
            </TabsContent>

            <TabsContent value="inventory" className="mt-4">
              <div className="mb-3 relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
                <Input
                  value={inventoryQ}
                  onChange={(e) => setInventoryQ(e.target.value)}
                  placeholder="Search inventory…"
                  className="pl-9 bg-[#f6f1e6] border-[#e0d6bc] h-9"
                  data-testid="pos-inventory-search"
                />
              </div>
              {(() => {
                const s = inventoryQ.trim().toLowerCase();
                const filteredInv = s
                  ? inventory.filter((i) =>
                      (i.name || "").toLowerCase().includes(s) ||
                      (i.sku || "").toLowerCase().includes(s) ||
                      (i.category || "").toLowerCase().includes(s)
                    )
                  : inventory;
                if (filteredInv.length === 0) {
                  return <p className="text-sm text-[#6a6a6a]">{inventory.length === 0 ? "No inventory items." : `No inventory items match "${inventoryQ}".`}</p>;
                }
                return (
                  <div className="grid sm:grid-cols-2 gap-3">
                    {filteredInv.map((i) => (
                      <button
                        key={i.id}
                        onClick={() => addInventory(i)}
                        disabled={(i.stock || 0) <= 0}
                        className="text-left rounded-xl border border-[#e0d6bc] bg-[#f6f1e6] p-3 hover:bg-[#f1ead8] transition disabled:opacity-50"
                        data-testid={`pos-inventory-${i.id}`}
                      >
                        <div className="font-medium text-[#1f2a22] text-sm">{i.name}</div>
                        <div className="text-xs text-[#6a6a6a]">
                          Stock: <span className={(i.stock || 0) <= (i.low_stock_threshold || 5) ? "text-[#7a2a2a]" : ""}>{i.stock || 0}</span>
                        </div>
                        <div className="text-[#2f4a3a] font-display text-lg mt-1">${(i.unit_price || 0).toFixed(2)}</div>
                      </button>
                    ))}
                  </div>
                );
              })()}
            </TabsContent>

            <TabsContent value="custom" className="mt-4">
              <div className="space-y-3 max-w-md">
                <div>
                  <Label>Description</Label>
                  <Input
                    className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                    value={customForm.name}
                    onChange={(e) => setCustomForm({ ...customForm, name: e.target.value })}
                    data-testid="pos-custom-name"
                  />
                </div>
                <div>
                  <Label>Unit price</Label>
                  <Input
                    type="number" step="0.01"
                    className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"
                    value={customForm.unit_price}
                    onChange={(e) => setCustomForm({ ...customForm, unit_price: e.target.value })}
                    data-testid="pos-custom-price"
                  />
                </div>
                <Button onClick={addCustom} className="rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]" data-testid="pos-custom-add-btn">
                  <Plus size={14} className="mr-1" /> Add to cart
                </Button>
              </div>
            </TabsContent>
          </Tabs>
        </div>

        {/* Cart */}
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 space-y-4" data-testid="pos-cart">
          <div className="eyebrow text-[#8a6a3c]">Cart</div>
          <div>
            <Label>Client</Label>
            <Select value={clientId} onValueChange={setClientId}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="pos-client-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="walkin">Walk-in (no client)</SelectItem>
                {clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.full_name || c.email || c.id}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {cart.length === 0 ? (
            <div className="text-sm text-[#6a6a6a] py-6 text-center">Cart is empty</div>
          ) : (
            <ul className="divide-y divide-[#e7dfc9]">
              {cart.map((l, i) => (
                <li key={i} className="py-2.5 flex items-center gap-2" data-testid={`pos-cart-line-${i}`}>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-[#1f2a22] truncate">{l.name}</div>
                    <div className="text-[11px] text-[#6a6a6a] uppercase tracking-wider">{l.type}</div>
                  </div>
                  <Input
                    type="number" min={1}
                    className="h-8 w-14 bg-[#f6f1e6] border-[#e0d6bc] text-xs"
                    value={l.qty}
                    onChange={(e) => updateLine(i, { qty: Math.max(1, parseInt(e.target.value || "1")) })}
                  />
                  <div className="text-sm w-20 text-right text-[#1f2a22]">${(l.qty * l.unit_price).toFixed(2)}</div>
                  <button onClick={() => remove(i)} className="text-[#7a2a2a]" data-testid={`pos-remove-${i}`}>
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">Discount $</Label>
              <Input type="number" step="0.01" className="mt-1 bg-[#f6f1e6] border-[#e0d6bc] text-sm" value={discount} onChange={(e) => setDiscount(e.target.value)} data-testid="pos-discount" />
            </div>
            <div>
              <Label className="text-xs">Tip $</Label>
              <Input type="number" step="0.01" className="mt-1 bg-[#f6f1e6] border-[#e0d6bc] text-sm" value={tip} onChange={(e) => setTip(e.target.value)} data-testid="pos-tip" />
            </div>
            <div className="col-span-2">
              <Label className="text-xs">Tax rate (e.g. 0.07 = 7%)</Label>
              <Input type="number" step="0.001" className="mt-1 bg-[#f6f1e6] border-[#e0d6bc] text-sm" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} data-testid="pos-taxrate" />
            </div>
          </div>

          <div className="border-t border-[#e7dfc9] pt-3 space-y-1 text-sm">
            <div className="flex justify-between"><span className="text-[#6a6a6a]">Subtotal</span><span>${subtotal.toFixed(2)}</span></div>
            {discount > 0 && <div className="flex justify-between"><span className="text-[#6a6a6a]">Discount</span><span>−${(discount || 0).toFixed(2)}</span></div>}
            {tax > 0 && <div className="flex justify-between"><span className="text-[#6a6a6a]">Tax</span><span>${tax.toFixed(2)}</span></div>}
            {tip > 0 && <div className="flex justify-between"><span className="text-[#6a6a6a]">Tip</span><span>${(tip || 0).toFixed(2)}</span></div>}
            <div className="flex justify-between text-lg font-display text-[#1f2a22] pt-1" data-testid="pos-total">
              <span>Total</span><span>${total.toFixed(2)}</span>
            </div>
          </div>

          <div>
            <Label>Payment method</Label>
            <Select value={paymentMethod} onValueChange={setPaymentMethod}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" data-testid="pos-method-select"><SelectValue /></SelectTrigger>
              <SelectContent>{PAY_METHODS.map((m) => <SelectItem key={m.v} value={m.v}>{m.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Reference / last 4 (optional)</Label>
            <Input className="mt-1 bg-[#f6f1e6] border-[#e0d6bc] text-sm" value={paymentRef} onChange={(e) => setPaymentRef(e.target.value)} data-testid="pos-payment-ref" />
          </div>
          <div>
            <Label className="text-xs">Note</Label>
            <Input className="mt-1 bg-[#f6f1e6] border-[#e0d6bc] text-sm" value={note} onChange={(e) => setNote(e.target.value)} data-testid="pos-note" />
          </div>

          <Button
            onClick={checkout}
            disabled={submitting || cart.length === 0}
            className="w-full btn-lift rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6] h-11"
            data-testid="pos-checkout-btn"
          >
            <Receipt size={16} className="mr-2" />
            {submitting ? "Processing…" : `Charge $${total.toFixed(2)} & generate PDF`}
          </Button>
        </div>
      </div>
    </PortalLayout>
  );
}