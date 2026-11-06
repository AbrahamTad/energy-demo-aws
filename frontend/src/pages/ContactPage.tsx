import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Field } from "../components/Forms";
import "./contact.css";

type Turnstile = {
  render: (element: HTMLElement, options: Record<string, unknown>) => string;
  remove: (id: string) => void;
  reset: (id: string) => void;
};
declare global { interface Window { turnstile?: Turnstile } }
const TEST_KEY = "1x00000000000000000000AA";

export function ContactPage() {
  const [botToken, setBotToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reference, setReference] = useState("");
  const [botError, setBotError] = useState("");
  const [retry, setRetry] = useState(0);
  const tokenIssued = useRef(0);
  const submitting = useRef(false);
  const [id, setId] = useState(() => crypto.randomUUID());
  const widget = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | null>(null);
  const key = import.meta.env.VITE_TURNSTILE_SITE_KEY || (import.meta.env.DEV ? TEST_KEY : "");
  const configured = !!key && (import.meta.env.DEV || !/^[123]x0{20}[A-Z]{2}$/.test(key));
  useEffect(() => {
    if (!configured) return;
    let disposed = false;
    const failure = () => { if (!disposed) { setBotToken(""); tokenIssued.current = 0; setBotError("Bot check unavailable. Please try again."); } };
    const render = () => {
      if (disposed || !widget.current || !window.turnstile || widgetId.current) return;
      const invalidate = (message: string) => { tokenIssued.current = 0; setBotToken(""); setBotError(message); };
      try {
        widgetId.current = window.turnstile.render(widget.current, { sitekey: key, action: "contact",
        // Managed mode is configured on the existing Cloudflare widget. Keep its
        // token out of FormData: the API accepts only our explicit botToken field.
        "response-field": false, size: "flexible",
        callback: (token: string) => { tokenIssued.current = Date.now(); setBotToken(token); setBotError(""); },
        "expired-callback": () => invalidate("Bot check expired. Please complete a new check."),
        "timeout-callback": () => invalidate("Bot check timed out. Please try again."),
        "error-callback": () => { invalidate("Bot check unavailable. Please try again."); return true; } });
      } catch { failure(); }
    };
    let script = document.querySelector<HTMLScriptElement>('script[data-contact-turnstile]');
    if (!script) {
      script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true; script.defer = true; script.dataset.contactTurnstile = "true";
      document.head.appendChild(script);
    }
    script.addEventListener("load", render); render();
    script.addEventListener("error", failure);
    return () => {
      disposed = true; script.removeEventListener("load", render); script.removeEventListener("error", failure);
      if (widgetId.current) window.turnstile?.remove(widgetId.current);
      widgetId.current = null;
    };
  }, [configured, key, retry]);
  function retryBot() {
    setBotToken(""); tokenIssued.current = 0; setBotError("");
    if (!window.turnstile) document.querySelector('script[data-contact-turnstile]')?.remove();
    setRetry(value => value + 1);
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || !botToken || !configured) return;
    // Also check age at submit: background tabs can delay expiry callbacks.
    if (Date.now() - tokenIssued.current >= 240_000) {
      setBotToken(""); tokenIssued.current = 0;
      setBotError("Bot check expired. Please complete a new check.");
      if (widgetId.current) window.turnstile?.reset(widgetId.current);
      return;
    }
    const form = event.currentTarget;
    const values = new FormData(form);
    submitting.current = true; tokenIssued.current = 0;
    setBusy(true); setBotToken(""); setError("");
    try {
      const result = await fetch("/api/contact", { method: "POST", credentials: "omit", cache: "no-store",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ ...Object.fromEntries(values), id, botToken }) });
      if (!result.ok) throw new Error(result.status === 429 ? "Contact limit reached. Please try later."
        : result.status === 400 ? "Check your fields and complete a fresh bot check."
        : "We could not confirm receipt. Retry with the same form to avoid duplicates.");
      const data = await result.json();
      if (data.id !== id || data.status !== "saved") throw new Error("Receipt could not be confirmed. Retry this form.");
      setReference(id); form.reset(); setId(crypto.randomUUID());
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to submit. Retry this form later.");
    } finally {
      submitting.current = false;
      setBusy(false); setBotToken(""); tokenIssued.current = 0;
      if (widgetId.current) window.turnstile?.reset(widgetId.current);
    }
  }
  return <section className="panel contact-panel">
    <h1>Contact us</h1>
    <p>Ask the EnergyDemo team a question. Do not include passwords, financial, health or other sensitive information.</p>
    <p>We use these details to answer your inquiry. Planned retention: 90 days, subject to privacy review; protected backups may persist longer. Email delivery is separate from saving your inquiry.</p>
    {!configured && <p role="alert">Contact submissions are not configured yet.</p>}
    {reference && <p role="status">Your inquiry was saved. Reference: {reference}. A confirmation email may arrive separately.</p>}
    <form className="form" onSubmit={submit}>
      <Field label="Name" name="name" autoComplete="name" required maxLength={100} />
      <Field label="Email" name="email" type="email" autoComplete="email" required maxLength={254} />
      <Field label="Subject" name="subject" required maxLength={150} />
      <div className="field"><label htmlFor="contact-message">Message</label>
        <textarea id="contact-message" name="message" required maxLength={5000} rows={7} /></div>
      <div className="contact-honeypot" aria-hidden="true"><label>Leave blank<input name="website" tabIndex={-1} autoComplete="off" /></label></div>
      <div ref={widget} aria-label="Bot protection" />
      {botError && <><p role="alert">{botError}</p>
        <button type="button" className="button" disabled={busy} onClick={retryBot}>Retry bot check</button></>}
      {error && <p role="alert">{error}</p>}
      <button className="button primary" disabled={!configured || !botToken || busy}>{busy ? "Saving..." : "Send inquiry"}</button>
    </form>
  </section>;
}
