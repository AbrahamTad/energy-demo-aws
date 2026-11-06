import { useEffect, useState } from "react";
import { adminRequest } from "../lib/admin";
import "./contact.css";
type Message = { id: string; subject: string; status: string; created: number; version: number };
type Detail = Message & { name: string; email: string; message: string; email_status: Record<string, string> };
export function CustomerMessages() {
  const [items, setItems] = useState<Message[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void adminRequest<{ messages: Message[]; next_cursor: string | null }>("messages", undefined, controller.signal)
      .then(result => { if (!controller.signal.aborted) { setItems(result.messages); setCursor(result.next_cursor); } })
      .catch(() => { if (!controller.signal.aborted) setError("Customer messages unavailable. Check your admin session."); });
    return () => controller.abort();
  }, []);
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError("");
    try { await action(); } catch { setItems([]); setCursor(null); setDetail(null); setError("Request failed. Recheck admin access and reload before retrying."); }
    finally { setBusy(false); }
  }
  return <section className="panel"><h2>Customer messages</h2>
    {error && <p role="alert">{error}</p>}
    <button className="button secondary" disabled={busy} onClick={() => void run(async () => {
      const result = await adminRequest<{ messages: Message[]; next_cursor: string | null }>("messages");
      setItems(result.messages); setCursor(result.next_cursor); setDetail(null);
    })}>Reload messages</button>
    <ul className="contact-message-list">{items.map(item => <li key={item.id}>
      <button disabled={busy} onClick={() => void run(async () => setDetail(await adminRequest<Detail>(`messages/${item.id}`)))}>
        {item.subject} - {item.status}</button>
    </li>)}</ul>
    {cursor && <button disabled={busy} onClick={() => void run(async () => {
      const result = await adminRequest<{ messages: Message[]; next_cursor: string | null }>(`messages?before=${encodeURIComponent(cursor)}`);
      setItems(previous => [...previous, ...result.messages]); setCursor(result.next_cursor);
    })}>Load more messages</button>}
    {detail && <article><h3>{detail.subject}</h3><p>{detail.name} - {detail.email}</p>
      <p className="contact-message-body">{detail.message}</p>
      <p>Email: {Object.entries(detail.email_status).map(([kind, state]) => `${kind}: ${state}`).join("; ")}</p>
      <label htmlFor="inquiry-status">Inquiry status</label>
      <select id="inquiry-status" value={detail.status} disabled={busy} onChange={e => {
        const status = e.target.value;
        void run(async () => {
          const result = await adminRequest<{ status: string; version: number }>(`messages/${detail.id}/status`, { status, version: detail.version });
          setDetail({ ...detail, ...result });
          setItems(previous => previous.map(item => item.id === detail.id ? { ...item, ...result } : item));
        });
      }}>{["new", "in_progress", "resolved", "spam"].map(value => <option key={value}>{value}</option>)}</select>
    </article>}
  </section>;
}
