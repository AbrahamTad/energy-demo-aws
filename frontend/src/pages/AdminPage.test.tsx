import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminPage } from "./AdminPage";
import { adminRequest, AdminError } from "../lib/admin";

vi.mock("../lib/admin", async (original) => ({
  ...(await original<typeof import("../lib/admin")>()),
  adminRequest: vi.fn(),
}));
const request = vi.mocked(adminRequest);
const status = {
  checked_at: "2026-10-29T12:00:00Z",
  services: { cognito: "available", email: "unavailable" },
  api_gateway: "request reached Lambda",
  lambda: "responding",
  private_access: "own records only",
  email_daily_limit: 10,
};

function open() {
  render(
    <MemoryRouter>
      <AdminPage />
    </MemoryRouter>,
  );
}
function click(name: string) {
  fireEvent.click(screen.getByRole("button", { name }));
}

beforeEach(() => {
  vi.clearAllMocks();
  request.mockImplementation(async (path) => {
    if (path === "session") return { verified: true };
    if (path === "status") return status;
    return { records: [], users: [], next_cursor: null };
  });
});

describe("admin access", () => {
  it("hides admin data and actions when backend rejects membership", async () => {
    request.mockRejectedValue(
      new AdminError(403, "Administrator membership is required."),
    );
    open();
    expect(
      await screen.findByText("Admin access unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Admin sections" }),
    ).not.toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("requires password and Cognito TOTP before showing data and clears inputs", async () => {
    let granted = false;
    request.mockImplementation(async (path, values) => {
      if (path === "status") return status;
      if (values && "password" in values)
        return { challenge: "opaque-challenge" };
      if (values && "code" in values) {
        granted = true;
        return { verified_until: 123 };
      }
      if (!granted) throw new AdminError(428, "Confirm admin access.");
      return { verified: true };
    });
    open();
    const password = await screen.findByLabelText("Current password");
    fireEvent.change(password, { target: { value: "private-password" } });
    click("Continue");
    const code = await screen.findByLabelText("Authenticator code");
    expect(
      screen.queryByDisplayValue("private-password"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Admin sections" }),
    ).not.toBeInTheDocument();
    fireEvent.change(code, { target: { value: "123456" } });
    click("Verify authenticator");
    expect(
      await screen.findByRole("navigation", { name: "Admin sections" }),
    ).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith("session", {
      challenge: "opaque-challenge",
      code: "123456",
    });
  });

  it("uses real status responses and displays unavailable service states", async () => {
    open();
    expect(await screen.findByText("unavailable")).toBeInTheDocument();
    expect(screen.getByText("own records only")).toBeInTheDocument();
    expect(screen.queryByText("100% uptime")).not.toBeInTheDocument();
  });

  it("paginates the redacted user directory and never selects another user's records", async () => {
    request.mockImplementation(async (path) => {
      if (path === "status") return status;
      if (path === "users")
        return {
          users: [{ id: "account-one", enabled: true, status: "CONFIRMED" }],
          next_cursor: "opaque-cursor",
        };
      if (path === "users?cursor=opaque-cursor")
        return {
          users: [{ id: "account-two", enabled: false, status: "UNCONFIRMED" }],
          next_cursor: null,
        };
      return { verified: true };
    });
    open();
    await screen.findByRole("navigation", { name: "Admin sections" });
    click("Users");
    await screen.findByText("account-one");
    click("Next");
    await screen.findByText("account-two");
    expect(screen.queryByText("account-one")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit user" }),
    ).not.toBeInTheDocument();
    click("Previous");
    expect(await screen.findByText("account-one")).toBeInTheDocument();
    expect(
      request.mock.calls.every(
        ([path]) => !path.includes("user_sub") && !path.includes("owner="),
      ),
    ).toBe(true);
  });

  it("clears protected content when a later endpoint rejects access", async () => {
    request.mockImplementation(async (path) => {
      if (path === "users")
        throw new AdminError(403, "Administrator membership was removed.");
      if (path === "status") return status;
      return { verified: true };
    });
    open();
    await screen.findByRole("navigation", { name: "Admin sections" });
    click("Users");
    expect(
      await screen.findByText("Admin access unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Admin sections" }),
    ).not.toBeInTheDocument();
  });

  it("retries ambiguous email requests with the same id and shows acceptance separately from delivery", async () => {
    let sends = 0;
    request.mockImplementation(async (path, values) => {
      if (path === "status") return status;
      if (path === "email" && !values)
        return { recipients: ["test@example.invalid"] };
      if (path === "email" && values && "id" in values) {
        sends++;
        if (sends === 1) throw new Error("Network interrupted");
        return { id: values.id, status: "accepted", message_id: "ses-message" };
      }
      return { verified: true };
    });
    open();
    await screen.findByRole("navigation", { name: "Admin sections" });
    click("Email testing");
    await screen.findByRole("option", { name: "test@example.invalid" });
    click("Send test email");
    await screen.findByText("Network interrupted");
    click("Overview");
    click("Email testing");
    await screen.findByRole("option", { name: "test@example.invalid" });
    click("Check same request safely");
    await screen.findByText("Delivery status: accepted");
    const posts = request.mock.calls.filter(
      ([path, values]) => path === "email" && values,
    );
    expect(posts).toHaveLength(2);
    expect(posts[0][1]).toEqual(posts[1][1]);
    expect(
      screen.queryByRole("button", { name: "Start a new test" }),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Refresh delivery status" }),
      ).toBeEnabled(),
    );
  });
});
