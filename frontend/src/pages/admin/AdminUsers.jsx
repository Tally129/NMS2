import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import { UserPlus, Search, UserX, UserCheck, Send } from "lucide-react";
import { getErrorMessage } from "../../lib/errors";

const ROLES = [
  { value: "admin", label: "Administrator" },
  { value: "practitioner", label: "Practitioner" },
  { value: "staff", label: "Staff" },
  { value: "medical_assistant", label: "Medical Assistant" },
  { value: "client", label: "Patient" },
];

export default function AdminUsers() {
  const { toast } = useToast();
  const [users, setUsers] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [creating, setCreating] = React.useState(false);
  const [form, setForm] = React.useState({ full_name: "", email: "", role: "practitioner", phone: "" });
  const [q, setQ] = React.useState("");
  const [roleFilter, setRoleFilter] = React.useState("all");

  const load = () => api.get("/admin/users").then((r) => setUsers(r.data || [])).finally(() => setLoading(false));
  React.useEffect(() => { load(); }, []);

  const filtered = React.useMemo(() => {
    const s = q.trim().toLowerCase();
    return users.filter((u) => {
      if (roleFilter !== "all" && u.role !== roleFilter) return false;
      if (!s) return true;
      return (u.full_name || "").toLowerCase().includes(s) ||
             (u.email || "").toLowerCase().includes(s) ||
             (u.role || "").toLowerCase().includes(s);
    });
  }, [users, q, roleFilter]);

  const create = async () => {
    if (!form.email || !form.full_name) {
      toast({ title: "Enter the user's name and email" });
      return;
    }

    try {
      const { data } = await api.post("/admin/users", form);

      if (data?.invitation_sent) {
        toast({
          title: "Account created",
          description: "A secure account setup email was sent.",
        });
      } else if (data?.delivery === "failed") {
        toast({
          title: "Account created",
          description: "The invitation email could not be sent.",
        });
      } else {
        toast({
          title: "Account created",
          description: "The user can now begin account setup.",
        });
      }

      setForm({
        full_name: "",
        email: "",
        role: "practitioner",
        phone: "",
      });
      setCreating(false);
      load();
    } catch (e) {
      toast({
        title: "Failed",
        description: getErrorMessage(e) || "",
      });
    }
  };

  const deactivateUser = async (u) => {
    const confirmed = window.confirm(
      `Deactivate ${u.full_name || u.email}?\n\n` +
      "They will immediately lose portal access. Their records and audit history will remain."
    );

    if (!confirmed) return;

    try {
      await api.post(`/admin/users/${u.id}/deactivate`);
      toast({
        title: "User deactivated",
        description: `${u.full_name || u.email} can no longer sign in.`,
      });
      load();
    } catch (e) {
      toast({
        title: "Could not deactivate user",
        description: getErrorMessage(e) || "",
      });
    }
  };

  const reactivateUser = async (u) => {
    try {
      await api.post(`/admin/users/${u.id}/reactivate`);
      toast({
        title: "User reactivated",
        description: `${u.full_name || u.email} can continue account setup or sign in.`,
      });
      load();
    } catch (e) {
      toast({
        title: "Could not reactivate user",
        description: getErrorMessage(e) || "",
      });
    }
  };

  const resendInvitation = async (u) => {
    try {
      const { data } = await api.post(
        `/admin/users/${u.id}/resend-invitation`
      );

      if (data?.invitation_sent) {
        toast({
          title: "Invitation sent",
          description: `A new account setup email was sent to ${u.email}.`,
        });
      } else {
        toast({
          title: "Invitation recreated",
          description: "The account setup email could not be delivered.",
        });
      }

      load();
    } catch (e) {
      toast({
        title: "Could not resend invitation",
        description: getErrorMessage(e) || "",
      });
    }
  };

  const changeRole = async (u, role) => {
    try {
      await api.put(`/admin/users/${u.id}/role`, { role });
      toast({ title: `Role set to ${role}` });
      load();
    } catch {
      toast({ title: "Failed" });
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Users & Roles"
        subtitle={`${filtered.length} of ${users.length} users`}
        actions={
          <Button onClick={() => setCreating((v) => !v)} className="btn-lift h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]" data-testid="users-add-btn">
            <UserPlus size={16} className="mr-2" /> Add user
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-3 items-center">
        <div className="relative max-w-md flex-1 min-w-[220px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a6a3c]" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name, email, or role…"
            className="pl-9 bg-[#fbf7ee] border-[#e0d6bc]"
            data-testid="users-search-input"
          />
        </div>
        <Select value={roleFilter} onValueChange={setRoleFilter}>
          <SelectTrigger className="w-40 h-10 bg-[#fbf7ee] border-[#e0d6bc]" data-testid="users-role-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All roles</SelectItem>
            {ROLES.map((role) => (
  <SelectItem key={role.value} value={role.value}>
    {role.label}
  </SelectItem>
))}
          </SelectContent>
        </Select>
      </div>

      {creating && (
        <div className="mb-6 rounded-2xl border border-[#c19a4b] bg-[#fbf7ee] p-5 grid md:grid-cols-2 gap-4">
          <div><Label>Full name</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
          <div><Label>Email</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          <div><Label>Phone</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
          <div><Label>Role</Label>
            <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
              <SelectContent>{ROLES.map((role) => (
  <SelectItem key={role.value} value={role.value}>
    {role.label}
  </SelectItem>
))}</SelectContent>
            </Select>
          </div>
          <div className="md:col-span-2 flex justify-end">
            <Button onClick={create} className="btn-lift rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">Create user</Button>
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Name</th>
              <th className="text-left py-3 px-4">Email</th>
              <th className="text-left py-3 px-4">Role</th>
              <th className="text-left py-3 px-4">Status</th>
              <th className="text-left py-3 px-4">MFA</th>
              <th className="text-left py-3 px-4">Last login</th>
              <th className="text-left py-3 px-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {!loading && filtered.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-[#6a6a6a]">{q || roleFilter !== "all" ? "No users match this filter." : "No users."}</td></tr>}
            {filtered.map((u) => (
              <tr key={u.id} className="border-t border-[#e7dfc9]" data-testid={`user-row-${u.id}`}>
                <td className="py-3 px-4">{u.full_name}</td>
                <td className="py-3 px-4 text-[#3a3a3a]">{u.email}</td>
                <td className="py-3 px-4">
                  <Select value={u.role} onValueChange={(v) => changeRole(u, v)}>
                    <SelectTrigger className="h-8 w-36 bg-[#f6f1e6] border-[#e0d6bc] text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>{ROLES.map((role) => (
  <SelectItem key={role.value} value={role.value}>
    {role.label}
  </SelectItem>
))}</SelectContent>
                  </Select>
                </td>
                <td className="py-3 px-4 text-xs">
                  {!u.is_active ? (
                    <span className="rounded-full bg-red-50 px-2 py-1 text-red-700">
                      Inactive
                    </span>
                  ) : u.onboarding_status === "password_change_required" ? (
                    <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700">
                      Invitation pending
                    </span>
                  ) : u.onboarding_status === "mfa_enrollment_required" ? (
                    <span className="rounded-full bg-yellow-50 px-2 py-1 text-yellow-700">
                      MFA setup pending
                    </span>
                  ) : (
                    <span className="rounded-full bg-green-50 px-2 py-1 text-green-700">
                      Active
                    </span>
                  )}
                </td>

                <td className="py-3 px-4 text-xs">
                  {u.mfa_enabled ? <span className="text-[#2f4a3a]">Enabled</span> : <span className="text-[#8a6a3c]">Off</span>}
                </td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
                </td>

                <td className="py-3 px-4">
                  <div className="flex flex-wrap gap-2">
                    {u.is_active ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => deactivateUser(u)}
                        className="h-8 text-xs border-red-200 text-red-700 hover:bg-red-50"
                      >
                        <UserX size={13} className="mr-1" />
                        Deactivate
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => reactivateUser(u)}
                        className="h-8 text-xs border-green-200 text-green-700 hover:bg-green-50"
                      >
                        <UserCheck size={13} className="mr-1" />
                        Reactivate
                      </Button>
                    )}

                    {u.is_active &&
                      !u.mfa_enabled &&
                      (
                        u.onboarding_status === "password_change_required" ||
                        u.onboarding_status === "mfa_enrollment_required"
                      ) && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => resendInvitation(u)}
                          className="h-8 text-xs border-amber-200 text-amber-700 hover:bg-amber-50"
                        >
                          <Send size={13} className="mr-1" />
                          Resend invite
                        </Button>
                      )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}