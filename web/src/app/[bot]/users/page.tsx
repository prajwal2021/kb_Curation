"use client";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, useApi } from "@/lib/api";
import { Button, Card, ErrorNote, inputCls, Label, Loading, Modal, Page, PageHeader, useToast } from "@/components/ui";

type User = { id: number; name: string; is_admin: boolean; kb_ids: number[] };
type Bot = { id: number; key: string; name: string };

/** One checkbox per knowledge base; `value` holds the chatbot ids that are ticked. */
function KbBoxes({ bots, value, onChange }: { bots: Bot[]; value: number[]; onChange: (ids: number[]) => void }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
      {bots.map((b) => (
        <label key={b.id} className="flex items-center gap-1.5 text-[13px]">
          <input type="checkbox" checked={value.includes(b.id)} onChange={(e) => onChange(e.target.checked ? [...value, b.id] : value.filter((x) => x !== b.id))} />
          {b.name}
        </label>
      ))}
    </div>
  );
}

export default function UsersPage() {
  const toast = useToast();
  const { data: users, error, reload } = useApi<User[]>("/api/admin/users");
  const { data: bots } = useApi<Bot[]>("/api/chatbots");
  const { data: me } = useApi<{ id: number }>("/api/me");
  const [adding, setAdding] = useState(false);

  const patch = async (u: User, body: Partial<User>, done: string) => {
    try { await api(`/api/admin/users/${u.id}`, { method: "PATCH", body }); reload(); toast(done); } catch (e) { toast((e as Error).message, true); }
  };
  const remove = async (u: User) => {
    if (!confirm(`Delete ${u.name}?\n\nThey are signed out everywhere. To give them a new password, add them again with the same name.`)) return;
    try { await api(`/api/admin/users/${u.id}`, { method: "DELETE" }); reload(); toast(`${u.name} deleted.`); } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <Page>
      <PageHeader title="Users" description="Who can sign in, and which knowledge bases each person can open. Admins open every knowledge base and manage users."
        actions={<Button variant="primary" onClick={() => setAdding(true)}><Plus className="size-4" /> Add user</Button>} />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!error && (!users || !bots) ? <Loading /> : users && bots && (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-[13px]">
            <thead className="border-b border-line bg-subtle text-xs text-muted">
              <tr><th className="py-2.5 pl-5 pr-3 font-medium">Name</th><th className="px-3 font-medium">Knowledge bases</th><th className="w-24 px-3 font-medium">Admin</th><th className="w-14" /></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {users.map((u) => {
                const self = u.id === me?.id;
                return (
                  <tr key={u.id} className="hover:bg-subtle">
                    <td className="py-3 pl-5 pr-3 font-medium">{u.name}{self && <span className="ml-1.5 text-xs font-normal text-muted">(you)</span>}</td>
                    <td className="px-3 py-3">
                      {u.is_admin ? <span className="text-muted">All knowledge bases</span>
                        : <KbBoxes bots={bots} value={u.kb_ids} onChange={(ids) => patch(u, { kb_ids: ids }, `Access updated for ${u.name}.`)} />}
                    </td>
                    <td className="px-3 py-3">
                      <input type="checkbox" aria-label={`${u.name} is an admin`} checked={u.is_admin} disabled={self}
                        title={self ? "You can't remove your own admin access." : undefined}
                        onChange={(e) => patch(u, { is_admin: e.target.checked }, e.target.checked ? `${u.name} is now an admin.` : `${u.name} is no longer an admin.`)} />
                    </td>
                    <td className="px-3 py-2.5">
                      {!self && <button aria-label={`Delete ${u.name}`} onClick={() => remove(u)} className="rounded-lg p-1.5 text-neutral-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="size-3.5" /></button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
      {adding && bots && <AddUser bots={bots} onClose={() => setAdding(false)} onDone={(name) => { setAdding(false); reload(); toast(`${name} added.`); }} />}
    </Page>
  );
}

function AddUser({ bots, onClose, onDone }: { bots: Bot[]; onClose: () => void; onDone: (name: string) => void }) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [kbIds, setKbIds] = useState<number[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const u = await api<User>("/api/admin/users", { body: { name, password, is_admin: isAdmin, kb_ids: kbIds } });
      onDone(u.name);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title="Add user" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!name.trim() || password.length < 8} onClick={save}>Add user</Button></>}>
      <Label>Name</Label>
      <input autoFocus className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Jane Doe" />
      <div className="h-3" />
      <Label>Starting password</Label>
      <input type="password" autoComplete="new-password" className={inputCls} value={password} onChange={(e) => setPassword(e.target.value)} />
      <p className="mt-1.5 text-xs text-muted">At least 8 characters. Give it to them; they can change it in Settings.</p>
      <div className="h-4" />
      <label className="flex items-center gap-1.5 text-[13px] font-medium"><input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} /> Admin</label>
      {!isAdmin && <><div className="h-3" /><Label>Knowledge bases</Label><KbBoxes bots={bots} value={kbIds} onChange={setKbIds} /></>}
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}
