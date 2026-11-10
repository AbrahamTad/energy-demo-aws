import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { adminRequest } from "../lib/admin";
import { CustomerMessages } from "./CustomerMessages";
vi.mock("../lib/admin", () => ({ adminRequest: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
describe("Customer messages", () => {
  it("handles denied access without exposing inquiry data", async () => {
    vi.mocked(adminRequest).mockRejectedValue(new Error("private server details"));
    render(<CustomerMessages />);
    expect(await screen.findByRole("alert")).not.toHaveTextContent("private server details");
    expect(screen.queryByLabelText("Inquiry status")).not.toBeInTheDocument();
  });
  it("loads protected detail and submits versioned status updates", async () => {
    const item = { id: "id", subject: "Question", status: "new", version: 1, created: 1 };
    vi.mocked(adminRequest).mockResolvedValueOnce({ messages: [item], next_cursor: null })
      .mockResolvedValueOnce({ ...item, name: "Reader", email: "reader@example.invalid", message: "<script>plain text</script>", email_status: { customer: "failed" } })
      .mockResolvedValueOnce({ status: "resolved", version: 2 });
    render(<CustomerMessages />);
    fireEvent.click(await screen.findByRole("button", { name: "Question - new" }));
    expect(await screen.findByText("<script>plain text</script>")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Inquiry status"), { target: { value: "resolved" } });
    await waitFor(() => expect(adminRequest).toHaveBeenLastCalledWith("messages/id/status", { status: "resolved", version: 1 }));
    await waitFor(() => expect(screen.getByLabelText("Inquiry status")).toHaveValue("resolved"));
  });
});
