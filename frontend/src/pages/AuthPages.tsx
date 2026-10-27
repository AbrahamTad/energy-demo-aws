import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  confirmResetPassword,
  confirmSignIn,
  confirmSignUp,
  resendSignUpCode,
  resetPassword,
  signIn,
  signUp,
} from "aws-amplify/auth";
import { safeReturnPath, useAuth } from "../auth/context";
import { passwordError } from "../auth/client";
import { useAction } from "../lib/useAction";
import { AuthPanel, Field, PasswordField } from "../components/Forms";
import { Icon } from "../components/Icon";

function Feedback({ error, success }: { error: string; success: string }) {
  return (
    <>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {success && (
        <p className="form-success" role="status">
          {success}
        </p>
      )}
    </>
  );
}
function clearPasswords(form: HTMLFormElement) {
  form
    .querySelectorAll<HTMLInputElement>(
      'input[autocomplete="current-password"], input[autocomplete="new-password"]',
    )
    .forEach((input) => {
      input.value = "";
    });
}

export function LoginPage() {
  const { profile, loading, configured, refresh } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [step, setStep] = useState<"password" | "totp" | "newPassword">(
    "password",
  );
  const [email, setEmail] = useState(location.state?.email ?? "");
  const action = useAction();
  const target = safeReturnPath(location.state?.from);
  if (loading)
    return (
      <div className="loading-page" role="status">
        Checking your session…
      </div>
    );
  if (profile) return <Navigate to={target} replace />;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const password = String(fields.get("password") ?? "");
    const code = String(fields.get("code") ?? "").trim();
    if (step === "newPassword" && passwordError(password)) {
      action.setError(passwordError(password));
      return;
    }
    clearPasswords(form);
    void action.run(async () => {
      const result =
        step === "password"
          ? await signIn({
              username: email.trim(),
              password,
              options: { authFlowType: "USER_SRP_AUTH" },
            })
          : await confirmSignIn({
              challengeResponse: step === "totp" ? code : password,
            });
      switch (result.nextStep.signInStep) {
        case "DONE":
          await refresh();
          navigate(target, { replace: true });
          break;
        case "CONFIRM_SIGN_IN_WITH_TOTP_CODE":
          setStep("totp");
          break;
        case "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED":
          setStep("newPassword");
          break;
        case "CONFIRM_SIGN_UP":
          navigate("/verify", { state: { email } });
          break;
        case "RESET_PASSWORD":
          navigate("/reset-password", { state: { email } });
          break;
        default:
          action.setError(
            "This account requires an additional sign-in method. Contact your account administrator.",
          );
      }
    });
  }
  return (
    <AuthPanel
      title={
        step === "totp"
          ? "Verify it’s you"
          : step === "newPassword"
            ? "Choose a new password"
            : "Welcome back."
      }
      subtitle={
        step === "totp"
          ? "Enter the six-digit code from your authenticator app."
          : "A clear view of your energy is waiting."
      }
    >
      {location.state?.verified && (
        <p className="form-success" role="status">
          Email verified. You can now sign in.
        </p>
      )}
      <form className="form" onSubmit={submit}>
        <fieldset disabled={!configured || action.busy}>
          {step === "password" && (
            <>
              <Field
                label="Email address"
                name="email"
                type="email"
                autoComplete="username"
                required
                maxLength={254}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
              <PasswordField />
            </>
          )}
          {step === "totp" && (
            <Field
              label="Authenticator code"
              name="code"
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              required
            />
          )}
          {step === "newPassword" && <PasswordField newPassword />}
          <Feedback {...action} />
          <button
            className="button primary"
            disabled={action.busy || !configured}
          >
            {action.busy
              ? "Please wait…"
              : step === "password"
                ? "Log in"
                : "Continue"}
            <Icon name="arrow" size={16} />
          </button>
        </fieldset>
      </form>
      <div className="form-links">
        <Link to="/reset-password" state={{ email }}>
          Forgot your password?
        </Link>
        <br />
        New to EnergyDemo? <Link to="/register">Create an account</Link>
        <br />
        <Link to="/verify" state={{ email }}>
          Verify your email
        </Link>
      </div>
    </AuthPanel>
  );
}

export function RegisterPage() {
  const { configured, profile } = useAuth();
  const action = useAction();
  const navigate = useNavigate();
  if (profile) return <Navigate to="/dashboard" replace />;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = String(data.get("password"));
    const email = String(data.get("email")).trim();
    const name = String(data.get("name")).trim();
    const validation = !name
      ? "Enter your name."
      : passwordError(password) ||
        (password !== data.get("confirmPassword")
          ? "The passwords do not match."
          : "");
    if (validation) {
      action.setError(validation);
      return;
    }
    clearPasswords(form);
    void action.run(async () => {
      const result = await signUp({
        username: email,
        password,
        options: { userAttributes: { email, name }, autoSignIn: false },
      });
      navigate(result.isSignUpComplete ? "/login" : "/verify", {
        state: { email },
      });
    });
  }
  return (
    <AuthPanel
      title="Make room for better energy."
      subtitle="Create your account. Start with a clearer perspective."
    >
      <form className="form" onSubmit={submit}>
        <fieldset disabled={!configured || action.busy}>
          <Field
            name="name"
            label="Your name"
            autoComplete="name"
            required
            maxLength={64}
            placeholder="How should we call you?"
          />
          <Field
            name="email"
            label="Email address"
            type="email"
            autoComplete="email"
            required
            maxLength={254}
            placeholder="you@example.com"
          />
          <PasswordField newPassword />
          <PasswordField
            name="confirmPassword"
            label="Confirm password"
            newPassword
          />
          <Feedback {...action} />
          <button className="button primary">
            {action.busy ? "Creating account…" : "Create account"}
            <Icon name="arrow" size={16} />
          </button>
        </fieldset>
      </form>
      <p className="form-links">
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </AuthPanel>
  );
}

export function VerifyPage() {
  const location = useLocation();
  const [email, setEmail] = useState(location.state?.email ?? "");
  const { configured } = useAuth();
  const navigate = useNavigate();
  const action = useAction();
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code")).trim();
    void action.run(async () => {
      await confirmSignUp({ username: email.trim(), confirmationCode: code });
      navigate("/login", { replace: true, state: { email, verified: true } });
    });
  }
  return (
    <AuthPanel
      title="Check your inbox."
      subtitle="Enter the verification code sent to your email address."
    >
      <form className="form" onSubmit={submit}>
        <fieldset disabled={!configured || action.busy}>
          <Field
            name="email"
            label="Email address"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Field
            name="code"
            label="Verification code"
            autoComplete="one-time-code"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            required
          />
          <Feedback {...action} />
          <button className="button primary">
            {action.busy ? "Verifying…" : "Verify email"}
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={!email.trim() || action.busy}
            onClick={() =>
              void action.run(async () => {
                await resendSignUpCode({ username: email.trim() });
                action.setSuccess(
                  "A new code has been requested. Check your inbox and spam folder.",
                );
              })
            }
          >
            Resend code
          </button>
        </fieldset>
      </form>
      <p className="form-links">
        <Link to="/login">Back to login</Link>
      </p>
    </AuthPanel>
  );
}

export function ResetPasswordPage() {
  const location = useLocation();
  const [email, setEmail] = useState(location.state?.email ?? "");
  const [step, setStep] = useState<"request" | "confirm" | "done">("request");
  const { configured } = useAuth();
  const action = useAction();
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = String(data.get("password") ?? "");
    if (step === "confirm" && passwordError(password)) {
      action.setError(passwordError(password));
      return;
    }
    clearPasswords(form);
    void action.run(async () => {
      if (step === "request") {
        await resetPassword({ username: email.trim() });
        setStep("confirm");
        action.setSuccess(
          "If an eligible account exists, a recovery code has been sent to its verified email.",
        );
      } else {
        await confirmResetPassword({
          username: email.trim(),
          confirmationCode: String(data.get("code")).trim(),
          newPassword: password,
        });
        setStep("done");
      }
    });
  }
  return (
    <AuthPanel
      title={step === "done" ? "A fresh start." : "Reset your password."}
      subtitle={
        step === "done"
          ? "Your password has been updated. Sign in with your new password."
          : "We’ll help you get back to your workspace."
      }
    >
      {step === "done" ? (
        <Link to="/login" className="button primary" state={{ email }}>
          Back to login
        </Link>
      ) : (
        <form className="form" onSubmit={submit}>
          <fieldset disabled={!configured || action.busy}>
            <Field
              label="Email address"
              name="email"
              type="email"
              autoComplete="email"
              required
              readOnly={step === "confirm"}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {step === "confirm" && (
              <>
                <Field
                  label="Recovery code"
                  name="code"
                  autoComplete="one-time-code"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  required
                  maxLength={6}
                />
                <PasswordField newPassword label="New password" />
              </>
            )}
            <Feedback {...action} />
            <button className="button primary">
              {action.busy
                ? "Please wait…"
                : step === "request"
                  ? "Send recovery code"
                  : "Update password"}
            </button>
            {step === "confirm" && (
              <button
                className="link-button"
                type="button"
                onClick={() => {
                  setStep("request");
                  action.setError("");
                  action.setSuccess("");
                }}
              >
                Request another code
              </button>
            )}
          </fieldset>
        </form>
      )}
      <p className="form-links">
        <Link to="/login">Back to login</Link>
      </p>
    </AuthPanel>
  );
}
