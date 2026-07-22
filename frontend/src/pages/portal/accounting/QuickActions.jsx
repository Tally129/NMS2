import React from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../../components/ui/button";
import {
  Receipt, FileText, Wallet, ArrowRightLeft, PlusCircle,
  ShoppingCart, Users,
} from "lucide-react";

/**
 * Reusable Quick Actions bar. Every button either dispatches an event other
 * components listen to, or opens an existing page. NO new backend calls.
 */
export function QuickActions({ onOpenNewExpense, onOpenNewTransfer, onOpenNewJournal }) {
  const navigate = useNavigate();
  const items = [
    { key: "new-expense",   label: "New expense",      Icon: Receipt,       onClick: onOpenNewExpense },
    { key: "new-invoice",   label: "New invoice",      Icon: FileText,      onClick: () => navigate("/portal/pos") },
    { key: "receive-payment", label: "Receive payment", Icon: Wallet,        onClick: () => navigate("/portal/pos") },
    { key: "new-transfer",  label: "Transfer funds",   Icon: ArrowRightLeft, onClick: onOpenNewTransfer },
    { key: "record-deposit", label: "Record deposit",  Icon: PlusCircle,    onClick: onOpenNewJournal },
    { key: "pay-vendor",    label: "Pay vendor",       Icon: Users,         onClick: onOpenNewJournal },
    { key: "run-payroll",   label: "Run payroll",      Icon: ShoppingCart,  onClick: onOpenNewJournal },
  ];
  return (
    <div className="rounded-2xl border border-[#e2ebe4] bg-[#f4f7f2] p-3 mb-5" data-testid="quick-actions">
      <div className="text-[10px] uppercase tracking-widest text-[#3d6b52] pl-1 pb-2">Quick actions</div>
      <div className="flex flex-wrap gap-2">
        {items.map(({ key, label, Icon, onClick }) => (
          <Button
            key={key}
            variant="outline"
            size="sm"
            onClick={onClick || (() => {})}
            className="rounded-full border-[#cfe0d3] text-[#2f6a4a] bg-white hover:bg-[#eaf2ec] hover:border-[#2f6a4a] whitespace-nowrap"
            data-testid={`quick-${key}`}
          >
            <Icon size={12} className="mr-1.5" /> {label}
          </Button>
        ))}
      </div>
    </div>
  );
}
