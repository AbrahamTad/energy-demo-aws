// SDK doubles are confined to tests. The application has no fake auth path.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  confirmResetPassword,
  confirmSignIn,
  confirmSignUp,
  fetchAuthSession,
  fetchMFAPreference,
  fetchUserAttributes,
  getCurrentUser,
  resendSignUpCode,
  resetPassword,
  signIn,
  signOut,
  signUp,
  setUpTOTP,
  verifyTOTPSetup,
  updateMFAPreference,
  updatePassword,
  updateUserAttributes,
} from "aws-amplify/auth";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { sharedInMemoryStorage } from "aws-amplify/utils";
import App from "./App";

vi.mock("aws-amplify/auth", () => ({
  fetchAuthSession: vi.fn(),
  fetchUserAttributes: vi.fn(),
  getCurrentUser: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  signUp: vi.fn(),
  confirmSignUp: vi.fn(),
  resendSignUpCode: vi.fn(),
  resetPassword: vi.fn(),
  confirmResetPassword: vi.fn(),
  confirmSignIn: vi.fn(),
  updateUserAttributes: vi.fn(),
  updatePassword: vi.fn(),
  fetchMFAPreference: vi.fn(),
  setUpTOTP: vi.fn(),
  verifyTOTPSetup: vi.fn(),
  updateMFAPreference: vi.fn(),
}));
vi.mock("aws-amplify/auth/cognito", () => ({
  cognitoUserPoolsTokenProvider: { setKeyValueStorage: vi.fn() },
}));

const snapshot = {
  project: "Fixture",
  status: "working",
  records: [
    { source: "Solar", production: 125, unit: "kWh" },
    { source: "Wind", production: 80, unit: "kWh" },
  ],
};
function enter(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: true }), {
    target: { value },
  });
}
function click(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
}
function session() {
  vi.mocked(fetchAuthSession).mockResolvedValue({
    tokens: { accessToken: { toString: () => "fixture", payload: {} } },
  });
}
async function open(path: string) {
  window.history.replaceState(null, "", `/#${path}`);
  render(<App />);
  await waitFor(() =>
    expect(
      screen.queryByText("Checking your session…"),
    ).not.toBeInTheDocument(),
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchAuthSession).mockResolvedValue({});
  vi.mocked(fetchUserAttributes).mockResolvedValue({
    sub: "fixture-subject",
    name: "Test Reader",
    email: "reader@example.invalid",
    email_verified: "true",
  });
  vi.mocked(getCurrentUser).mockResolvedValue({
    userId: "fixture-subject",
    username: "reader@example.invalid",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot }),
  );
  localStorage.clear();
});

describe("public pages and energy", () => {
  it("renders endpoint values, filters sources, and retains error feedback", async () => {
    await open("/energy");
    expect(
      await screen.findByRole("cell", { name: "125" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter energy source"), {
      target: { value: "Wind" },
    });
    expect(screen.getByRole("figure")).toHaveTextContent("Wind");
    expect(screen.getByRole("figure")).not.toHaveTextContent("Solar");
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 429,
    } as Response);
    click("Refresh energy data");
    expect(await screen.findByRole("alert")).toHaveTextContent("Wait a moment");
    expect(screen.getByRole("table")).toHaveTextContent("125");
  });
  it("handles initial failure and retries", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("Connection interrupted"));
    await open("/energy");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Connection interrupted",
    );
    click("Try again");
    expect(
      await screen.findByRole("cell", { name: "125" }),
    ).toBeInTheDocument();
  });
  it("routes anonymous profile access to login", async () => {
    await open("/profile");
    expect(
      await screen.findByRole("heading", { name: "Welcome back." }),
    ).toBeInTheDocument();
    expect(screen.queryByText("fixture-subject")).not.toBeInTheDocument();
  });
});

describe("Cognito forms", () => {
  it("signs in with SRP, reaches the protected route, and signs out", async () => {
    vi.mocked(signIn).mockImplementation(async () => {
      session();
      return { isSignedIn: true, nextStep: { signInStep: "DONE" } };
    });
    vi.mocked(signOut).mockResolvedValue();
    const writes = vi.spyOn(Storage.prototype, "setItem");
    await open("/login");
    enter("Email address", "reader@example.invalid");
    enter("Password", "Valid-Test-1234");
    click("Log in");
    expect(
      await screen.findByRole("heading", { name: "Welcome, Test Reader." }),
    ).toBeInTheDocument();
    expect(signIn).toHaveBeenCalledWith({
      username: "reader@example.invalid",
      password: "Valid-Test-1234",
      options: { authFlowType: "USER_SRP_AUTH" },
    });
    expect(cognitoUserPoolsTokenProvider.setKeyValueStorage).toBeDefined();
    expect(writes.mock.calls.every(([key]) => key === "energy-theme")).toBe(
      true,
    );
    click("Sign out");
    await waitFor(() => expect(signOut).toHaveBeenCalledWith({ global: true }));
    expect(
      await screen.findByRole("heading", { name: "Welcome back." }),
    ).toBeInTheDocument();
    expect(await sharedInMemoryStorage.getItem("accessToken")).toBeNull();
  });
  it("does not grant access after a rejected login", async () => {
    vi.mocked(signIn).mockRejectedValue(
      Object.assign(new Error(), { name: "NotAuthorizedException" }),
    );
    await open("/login");
    enter("Email address", "reader@example.invalid");
    enter("Password", "wrong");
    click("Log in");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to sign in",
    );
    expect(screen.getByLabelText("Password", { exact: true })).toHaveValue("");
    expect(screen.queryByText("fixture-subject")).not.toBeInTheDocument();
  });
  it("validates matching passwords and confirms a registration code", async () => {
    vi.mocked(signUp).mockResolvedValue({
      isSignUpComplete: false,
      nextStep: { signUpStep: "CONFIRM_SIGN_UP", codeDeliveryDetails: {} },
    });
    vi.mocked(confirmSignUp).mockResolvedValue({
      isSignUpComplete: true,
      nextStep: { signUpStep: "DONE" },
    });
    await open("/register");
    enter("Your name", "Test Reader");
    enter("Email address", "reader@example.invalid");
    enter("Password", "Valid-Test-1234");
    enter("Confirm password", "Different-1234");
    click("Create account");
    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(signUp).not.toHaveBeenCalled();
    enter("Confirm password", "Valid-Test-1234");
    click("Create account");
    expect(
      await screen.findByRole("heading", { name: "Check your inbox." }),
    ).toBeInTheDocument();
    enter("Verification code", "123456");
    click("Verify email");
    expect(
      await screen.findByText("Email verified. You can now sign in."),
    ).toBeInTheDocument();
    expect(confirmSignUp).toHaveBeenCalledWith({
      username: "reader@example.invalid",
      confirmationCode: "123456",
    });
  });
  it("routes unconfirmed sign-ins to verification and handles invalid codes", async () => {
    vi.mocked(signIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: "CONFIRM_SIGN_UP" },
    });
    vi.mocked(confirmSignUp).mockRejectedValueOnce(
      Object.assign(new Error(), { name: "CodeMismatchException" }),
    );
    await open("/login");
    enter("Email address", "reader@example.invalid");
    enter("Password", "Valid-Test-1234");
    click("Log in");
    expect(
      await screen.findByRole("heading", { name: "Check your inbox." }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toHaveValue(
      "reader@example.invalid",
    );
    enter("Verification code", "000000");
    click("Verify email");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That code is incorrect",
    );
    expect(
      screen.getByRole("heading", { name: "Check your inbox." }),
    ).toBeInTheDocument();
  });
  it("resends verification and completes password recovery", async () => {
    vi.mocked(resendSignUpCode).mockResolvedValue({});
    await open("/verify");
    enter("Email address", "reader@example.invalid");
    click("Resend code");
    expect(
      await screen.findByText(/A new code has been requested/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Back to login" }));
    fireEvent.click(
      await screen.findByRole("link", { name: "Forgot your password?" }),
    );
    vi.mocked(resetPassword).mockResolvedValue({
      isPasswordReset: false,
      nextStep: {
        resetPasswordStep: "CONFIRM_RESET_PASSWORD_WITH_CODE",
        codeDeliveryDetails: {},
      },
    });
    vi.mocked(confirmResetPassword).mockResolvedValue();
    enter("Email address", "reader@example.invalid");
    click("Send recovery code");
    expect(await screen.findByLabelText("Recovery code")).toBeInTheDocument();
    enter("Recovery code", "123456");
    enter("New password", "Valid-New-1234");
    click("Update password");
    expect(
      await screen.findByRole("heading", { name: "A fresh start." }),
    ).toBeInTheDocument();
    expect(confirmResetPassword).toHaveBeenCalledWith({
      username: "reader@example.invalid",
      confirmationCode: "123456",
      newPassword: "Valid-New-1234",
    });
  });
  it("handles authenticator challenges before granting access", async () => {
    vi.mocked(signIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: "CONFIRM_SIGN_IN_WITH_TOTP_CODE" },
    });
    vi.mocked(confirmSignIn).mockImplementation(async () => {
      session();
      return { isSignedIn: true, nextStep: { signInStep: "DONE" } };
    });
    await open("/login");
    enter("Email address", "reader@example.invalid");
    enter("Password", "Valid-Test-1234");
    click("Log in");
    expect(
      await screen.findByLabelText("Authenticator code"),
    ).toBeInTheDocument();
    expect(screen.queryByText("fixture-subject")).not.toBeInTheDocument();
    enter("Authenticator code", "123456");
    click("Continue");
    expect(
      await screen.findByRole("heading", { name: "Welcome, Test Reader." }),
    ).toBeInTheDocument();
    expect(confirmSignIn).toHaveBeenCalledWith({ challengeResponse: "123456" });
  });
  it("updates the profile through Cognito with the authenticated session", async () => {
    session();
    vi.mocked(updateUserAttributes).mockImplementation(
      async () =>
        ({
          name: { isUpdated: true, nextStep: { updateAttributeStep: "DONE" } },
        }) as Awaited<ReturnType<typeof updateUserAttributes>>,
    );
    await open("/profile");
    enter("Display name", "Updated Reader");
    click("Save changes");
    expect(
      await screen.findByText("Your profile has been updated."),
    ).toBeInTheDocument();
    expect(updateUserAttributes).toHaveBeenCalledWith({
      userAttributes: { name: "Updated Reader" },
    });
  });
  it("removes protected content when session refresh fails", async () => {
    session();
    await open("/profile");
    expect(await screen.findByText("fixture-subject")).toBeInTheDocument();
    vi.mocked(fetchAuthSession).mockRejectedValueOnce(
      new Error("Refresh expired"),
    );
    fireEvent.focus(window);
    expect(
      await screen.findByRole("heading", { name: "Welcome back." }),
    ).toBeInTheDocument();
    expect(screen.queryByText("fixture-subject")).not.toBeInTheDocument();
  });
  it("clears local session state even when all-device sign-out fails", async () => {
    session();
    vi.mocked(signOut).mockRejectedValue(new Error("Offline"));
    await open("/profile");
    click("Sign out");
    expect(
      await screen.findByText(/could not confirm sign-out on other devices/),
    ).toBeInTheDocument();
    expect(screen.queryByText("fixture-subject")).not.toBeInTheDocument();
  });
  it("changes passwords and verifies TOTP before enabling MFA", async () => {
    session();
    vi.mocked(updatePassword).mockResolvedValue();
    vi.mocked(fetchMFAPreference).mockResolvedValue({ enabled: [] });
    vi.mocked(setUpTOTP).mockResolvedValue({
      sharedSecret: "TEST-ONLY-KEY",
      getSetupUri: () => new URL("otpauth://totp/fixture"),
    });
    vi.mocked(verifyTOTPSetup).mockResolvedValue();
    vi.mocked(updateMFAPreference).mockResolvedValue();
    await open("/settings");
    enter("Current password", "Valid-Old-1234");
    enter("New password", "Valid-New-1234");
    click("Update password");
    expect(
      await screen.findByText("Your password has been updated."),
    ).toBeInTheDocument();
    expect(updatePassword).toHaveBeenCalledWith({
      oldPassword: "Valid-Old-1234",
      newPassword: "Valid-New-1234",
    });
    click("Set up authenticator");
    expect(await screen.findByText("TEST-ONLY-KEY")).toBeInTheDocument();
    expect(updateMFAPreference).not.toHaveBeenCalled();
    enter("Authenticator code", "123456");
    click("Enable authenticator");
    expect(
      await screen.findByText("Authenticator protection is enabled."),
    ).toBeInTheDocument();
    expect(verifyTOTPSetup).toHaveBeenCalledWith({ code: "123456" });
    expect(updateMFAPreference).toHaveBeenCalledWith({ totp: "PREFERRED" });
    expect(screen.queryByText("TEST-ONLY-KEY")).not.toBeInTheDocument();
  });
});
