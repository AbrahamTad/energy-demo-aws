import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ContactPage } from "./ContactPage";
let callback: (token: string) => void;
let options: Record<string, unknown>;
beforeEach(() => {
  window.turnstile = { render: vi.fn((_element, config) => { options = config; callback = config.callback as typeof callback; return "widget"; }), reset: vi.fn(), remove: vi.fn() };
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => { delete window.turnstile; vi.unstubAllGlobals(); });
async function fill() {
  render(<ContactPage />);
  for (const [label, value] of [["Name", "Reader"], ["Email", "reader@example.invalid"], ["Subject", "Question"], ["Message", "Hello"]])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  await waitFor(() => expect(window.turnstile?.render).toHaveBeenCalled());
  callback("mock-token");
  await waitFor(() => expect(screen.getByRole("button", { name: "Send inquiry" })).toBeEnabled());
}
describe("Contact form", () => {
  it.each(["", "1x00000000000000000000AA", "2x00000000000000000000AB", "3x00000000000000000000FF"])("disables production submissions for missing or test keys: %s", (key) => {
    vi.stubEnv("DEV", false);
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", key);
    try {
      render(<ContactPage />);
      expect(screen.getByRole("button", { name: "Send inquiry" })).toBeDisabled();
      expect(screen.getByRole("alert")).toHaveTextContent("not configured");
      expect(window.turnstile?.render).not.toHaveBeenCalled();
    } finally { vi.unstubAllEnvs(); }
  });
  it("offers retry after a widget rendering exception", async () => {
    vi.mocked(window.turnstile!.render).mockImplementationOnce(() => { throw new Error("private widget failure"); });
    render(<ContactPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Bot check unavailable");
    expect(screen.queryByText("private widget failure")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry bot check" }));
    callback("recovered-token");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send inquiry" })).toBeEnabled());
  });
  it("uses the configured site key and sends only the API token field", async () => {
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", "public-widget-key");
    try {
      await fill();
      expect(options).toMatchObject({ sitekey: "public-widget-key", action: "contact", "response-field": false, size: "flexible" });
    } finally { vi.unstubAllEnvs(); }
  });
  it.each(["expired-callback", "timeout-callback", "error-callback"])("invalidates the token on %s and allows retry", async (event) => {
    await fill();
    (options[event] as () => void)();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send inquiry" })).toBeDisabled());
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry bot check" }));
    await waitFor(() => expect(window.turnstile?.render).toHaveBeenCalledTimes(2));
    expect(window.turnstile?.remove).toHaveBeenCalledWith("widget");
    callback("new-token");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send inquiry" })).toBeEnabled());
  });
  it("rejects an old token even if the expiry callback has not run", async () => {
    await fill();
    const now = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 240_000);
    try {
      fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("expired");
      expect(fetch).not.toHaveBeenCalled();
      expect(window.turnstile?.reset).toHaveBeenCalledWith("widget");
    } finally { now.mockRestore(); }
  });
  it("recovers from a failed script load and cleans up on unmount", async () => {
    delete window.turnstile;
    const view = render(<ContactPage />);
    const script = document.querySelector('script[data-contact-turnstile]')!;
    fireEvent.error(script);
    fireEvent.click(await screen.findByRole("button", { name: "Retry bot check" }));
    const replacement = document.querySelector('script[data-contact-turnstile]')!;
    expect(replacement).not.toBe(script);
    window.turnstile = { render: vi.fn(() => "recovered"), reset: vi.fn(), remove: vi.fn() };
    fireEvent.load(replacement);
    expect(window.turnstile.render).toHaveBeenCalledOnce();
    view.unmount();
    expect(window.turnstile.remove).toHaveBeenCalledWith("recovered");
  });
  it("requires bot verification and provides accessible fields", () => {
    render(<ContactPage />);
    expect(screen.getByLabelText("Message")).toBeRequired();
    expect(screen.getByRole("button", { name: "Send inquiry" })).toBeDisabled();
  });
  it("keeps missing fields and malformed email from passing form validation", async () => {
    render(<ContactPage />);
    const name = screen.getByLabelText("Name") as HTMLInputElement;
    const email = screen.getByLabelText("Email") as HTMLInputElement;
    expect(name.validity.valueMissing).toBe(true);
    expect((screen.getByLabelText("Subject") as HTMLInputElement).validity.valueMissing).toBe(true);
    expect((screen.getByLabelText("Message") as HTMLTextAreaElement).validity.valueMissing).toBe(true);
    fireEvent.change(email, { target: { value: "invalid-address" } });
    expect(email.validity.typeMismatch).toBe(true);
    await waitFor(() => expect(window.turnstile?.render).toHaveBeenCalled());
    callback("mock-token");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send inquiry" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each([
    [400, "Check your fields and complete a fresh bot check."],
    [429, "Contact limit reached. Please try later."],
  ])("shows a safe message for HTTP %s and requires a fresh bot check", async (status, message) => {
    vi.mocked(fetch).mockResolvedValue({ ok: false, status } as Response);
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send inquiry" })).toBeDisabled();
    expect(window.turnstile?.reset).toHaveBeenCalledWith("widget");
  });
  it("blocks duplicate clicks while a request is pending", async () => {
    let finish!: (response: Response) => void;
    vi.mocked(fetch).mockReturnValue(new Promise<Response>((resolve) => { finish = resolve; }));
    await fill();
    const button = screen.getByRole("button", { name: "Send inquiry" });
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
    fireEvent.click(button);
    expect(fetch).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string);
    expect(sent).toEqual(expect.objectContaining({
      name: "Reader", email: "reader@example.invalid", subject: "Question", message: "Hello", botToken: "mock-token",
    }));
    finish({ ok: true, json: async () => ({ id: sent.id, status: "saved" }) } as Response);
    expect(await screen.findByRole("status")).toHaveTextContent(sent.id);
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });
  it("rejects an inconsistent receipt and retains the reference for retry", async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ id: "wrong-reference", status: "saved" }) } as Response);
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Receipt could not be confirmed");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    const first = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string);
    callback("fresh-token");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send inquiry" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(vi.mocked(fetch).mock.calls[1][1]?.body as string).id).toBe(first.id);
    await screen.findByRole("alert");
  });
  it("handles network failure without claiming that the inquiry was saved", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to fetch");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("Hello");
    expect(screen.getByRole("button", { name: "Send inquiry" })).toBeDisabled();
  });
  it("reports saved inquiry without promising email delivery", async () => {
    vi.mocked(fetch).mockImplementation(async (_url, options) => {
      const values = JSON.parse(options?.body as string);
      return { ok: true, json: async () => ({ id: values.id, status: "saved" }) } as Response;
    });
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Your inquiry was saved");
    expect(screen.getByRole("status")).toHaveTextContent("may arrive separately");
    expect(fetch).toHaveBeenCalledWith("/api/contact", expect.objectContaining({ credentials: "omit" }));
  });
  it("preserves the request ID after ambiguous failure and never renders raw server errors", async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: "private" }) } as Response);
    await fill(); fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent("private");
    const first = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string);
    callback("another-token");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send inquiry" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(vi.mocked(fetch).mock.calls[1][1]?.body as string).id).toBe(first.id);
  });
});
