import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "../App";
import { AuthContext, safeReturnPath } from "../auth/context";
import { EnergyProvider } from "../components/Energy";
import { ThemeProvider } from "../components/Theme";
import { adminRequest, AdminError } from "../lib/admin";

vi.mock("../lib/admin", async (original) => ({
  ...(await original<typeof import("../lib/admin")>()),
  adminRequest: vi.fn(),
}));

function open(signedIn: boolean) {
  render(<MemoryRouter initialEntries={["/admin/messages"]}>
    <ThemeProvider><AuthContext.Provider value={{
      profile: signedIn ? { subject: "test-admin", email: "admin@example.invalid", emailVerified: true, name: "Admin" } : null,
      loading: false, configured: true, notice: "", refresh: vi.fn(), logout: vi.fn(),
    }}><EnergyProvider><AppRoutes /></EnergyProvider></AuthContext.Provider></ThemeProvider>
  </MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ records: [] }) }));
  vi.mocked(adminRequest).mockImplementation(async (path) => {
    if (path === "session") return { verified: true };
    if (path === "messages") return { messages: [], next_cursor: null };
    throw new Error("Unexpected admin request");
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("Contact notification admin link", () => {
  it("opens Customer messages only after the existing admin check", async () => {
    open(true);
    expect(await screen.findByRole("heading", { name: "Customer messages" })).toBeInTheDocument();
    expect(adminRequest).toHaveBeenCalledWith("session", undefined, expect.any(AbortSignal));
    await waitFor(() => expect(adminRequest).toHaveBeenCalledWith("messages", undefined, expect.any(AbortSignal)));
    expect(screen.getByRole("button", { name: "Customer messages" })).toHaveAttribute("aria-current", "page");
  });
  it("requires sign-in and keeps the exact messages path in the return allowlist", async () => {
    open(false);
    expect(await screen.findByLabelText("Email address")).toBeInTheDocument();
    expect(adminRequest).not.toHaveBeenCalled();
    expect(safeReturnPath("/admin/messages")).toBe("/admin/messages");
    expect(safeReturnPath("https://attacker.invalid/admin/messages")).toBe("/dashboard");
    expect(safeReturnPath("/admin/messages?access_token=secret")).toBe("/dashboard");
  });
  it("does not fetch messages for a signed-in user denied admin access", async () => {
    vi.mocked(adminRequest).mockRejectedValue(new AdminError(403, "Administrator membership is required."));
    open(true);
    expect(await screen.findByText("Admin access unavailable")).toBeInTheDocument();
    expect(vi.mocked(adminRequest).mock.calls.map(([path]) => path)).toEqual(["session"]);
  });
  it("keeps the existing step-up requirement before loading messages", async () => {
    vi.mocked(adminRequest).mockRejectedValue(new AdminError(428, "Confirm admin access."));
    open(true);
    expect(await screen.findByLabelText("Current password")).toBeInTheDocument();
    expect(vi.mocked(adminRequest).mock.calls.map(([path]) => path)).toEqual(["session"]);
  });
});
