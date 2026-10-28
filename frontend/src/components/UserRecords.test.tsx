import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { fetchAuthSession } from "aws-amplify/auth";
import { AuthContext } from "../auth/context";
import { UserRecords } from "./UserRecords";

vi.mock("aws-amplify/auth", () => ({ fetchAuthSession: vi.fn() }));
const id = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const record = {
  id,
  source: "Solar",
  production: 20,
  unit: "kWh",
  measured_at: "2026-10-27T10:00:00Z",
  updated_at: "2026-10-27T10:00:00Z",
};
const profile = {
  subject: "33333333-3333-4333-8333-333333333333",
  email: "owner@example.invalid",
  name: "Owner",
  emailVerified: true,
};
const fetchMock = vi.fn();
const reply = (value: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => value,
});
function view(subject = profile.subject) {
  return (
    <AuthContext.Provider
      value={{
        profile: { ...profile, subject },
        loading: false,
        configured: true,
        notice: "",
        refresh: vi.fn(),
        logout: vi.fn(),
      }}
    >
      <UserRecords key={subject} />
    </AuthContext.Provider>
  );
}
function enter(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock
    .mockReset()
    .mockResolvedValue(reply({ records: [record], next_cursor: null }));
  vi.mocked(fetchAuthSession).mockResolvedValue({
    tokens: {
      accessToken: { toString: () => "access-token-fixture", payload: {} },
      idToken: { toString: () => "id-token-never-send", payload: {} },
    },
  });
});

describe("private energy records", () => {
  it("loads, creates, edits and deletes records with access tokens and no ownership fields", async () => {
    render(view());
    expect(
      await screen.findByRole("rowheader", { name: "Solar" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/me/energy",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer access-token-fixture",
        }),
        cache: "no-store",
        credentials: "omit",
      }),
    );
    const created = { ...record, id: secondId, source: "Wind", production: 42 };
    fetchMock.mockResolvedValueOnce(reply(created, 201));
    enter("Energy source", "Wind");
    enter("Production (kWh)", "42");
    enter("Recorded at (UTC)", "2026-10-27T10:00");
    fireEvent.click(screen.getByRole("button", { name: "Add record" }));
    expect(
      await screen.findByRole("rowheader", { name: "Wind" }),
    ).toBeInTheDocument();
    const options = fetchMock.mock.lastCall?.[1];
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({
      source: "Wind",
      production: 42,
      unit: "kWh",
      measured_at: "2026-10-27T10:00:00.000Z",
    });
    fireEvent.click(screen.getByRole("button", { name: "Edit Wind record" }));
    enter("Production (kWh)", "12");
    fetchMock.mockResolvedValueOnce(reply({ ...created, production: 12 }));
    fireEvent.click(screen.getByRole("button", { name: "Save record" }));
    expect(
      await screen.findByRole("cell", { name: "12 kWh" }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.lastCall?.[0]).toBe("/api/me/energy/" + secondId);
    expect(fetchMock.mock.lastCall?.[1].method).toBe("PUT");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce(reply(null, 204));
    fireEvent.click(screen.getByRole("button", { name: "Delete Wind record" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("rowheader", { name: "Wind" }),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock.mock.lastCall?.[1].method).toBe("DELETE");
    expect(
      fetchMock.mock.calls.every(([url]) => url.startsWith("/api/me/energy")),
    ).toBe(true);
  });
  it("clears private data on authorization failure", async () => {
    render(view());
    await screen.findByRole("rowheader", { name: "Solar" });
    fireEvent.click(screen.getByRole("button", { name: "Edit Solar record" }));
    fetchMock.mockResolvedValueOnce(reply({}, 401));
    fireEvent.click(screen.getByRole("button", { name: "Refresh records" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("session ended");
    expect(
      screen.queryByRole("rowheader", { name: "Solar" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Energy source")).toHaveValue("");
    expect(screen.getByLabelText("Production (kWh)")).toHaveValue(null);
    expect(screen.queryByRole("button", { name: "Save record" })).not.toBeInTheDocument();
  });
  it("shows errors without inventing records and supports a retry", async () => {
    fetchMock.mockRejectedValueOnce(new Error("Network interrupted"));
    render(view());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Network interrupted",
    );
    expect(
      screen.queryByRole("rowheader", { name: "Solar" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh records" }));
    expect(
      await screen.findByRole("rowheader", { name: "Solar" }),
    ).toBeInTheDocument();
  });
  it("paginates within the current user and drops records when the account changes", async () => {
    fetchMock.mockResolvedValueOnce(
      reply({ records: [record], next_cursor: id }),
    );
    const rendered = render(view());
    await screen.findByRole("rowheader", { name: "Solar" });
    fetchMock.mockResolvedValueOnce(
      reply({
        records: [{ ...record, id: secondId, source: "Hydro" }],
        next_cursor: null,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load more records" }));
    await screen.findByRole("rowheader", { name: "Hydro" });
    expect(fetchMock.mock.lastCall?.[0]).toBe("/api/me/energy?cursor=" + id);
    fetchMock.mockResolvedValueOnce(reply({ records: [], next_cursor: null }));
    rendered.rerender(view("44444444-4444-4444-8444-444444444444"));
    expect(
      screen.queryByRole("rowheader", { name: "Solar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("rowheader", { name: "Hydro" }),
    ).not.toBeInTheDocument();
    expect(await screen.findByText(/No readings yet/)).toBeInTheDocument();
  });
  it("never calls the API without an authenticated access token", async () => {
    vi.mocked(fetchAuthSession).mockResolvedValue({});
    render(view());
    expect(await screen.findByRole("alert")).toHaveTextContent("session ended");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
