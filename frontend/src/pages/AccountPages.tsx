import { useState } from "react";
import type { FormEvent } from "react";
import {
  fetchMFAPreference,
  setUpTOTP,
  updateMFAPreference,
  updatePassword,
  updateUserAttributes,
  verifyTOTPSetup,
} from "aws-amplify/auth";
import { useAuth } from "../auth/context";
import { passwordError } from "../auth/client";
import { Field, PasswordField } from "../components/Forms";
import { Icon } from "../components/Icon";
import { useTheme } from "../lib/theme";
import { useAction } from "../lib/useAction";

export function ProfilePage() {
  const { profile, refresh } = useAuth();
  const action = useAction();
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name")).trim();
    if (!name) {
      action.setError("Enter your name.");
      return;
    }
    void action.run(async () => {
      await updateUserAttributes({ userAttributes: { name } });
      await refresh();
      action.setSuccess("Your profile has been updated.");
    });
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR ACCOUNT, YOUR DETAILS</p>
          <h1>Profile</h1>
          <p className="page-description">
            A little introduction goes a long way.
          </p>
        </div>
      </div>
      <div className="settings-grid">
        <section className="panel">
          <div className="profile-header">
            <span className="avatar large">
              {(profile?.name || profile?.email || "")
                .slice(0, 1)
                .toUpperCase()}
            </span>
            <div>
              <h2>{profile?.name || "Your profile"}</h2>
              <p className="muted">{profile?.email}</p>
            </div>
          </div>
          <form className="form" onSubmit={save}>
            <Field
              name="name"
              label="Display name"
              defaultValue={profile?.name}
              autoComplete="name"
              maxLength={64}
              required
            />
            <Field
              label="Email address"
              value={profile?.email}
              disabled
              hint="Your verified email is used for sign-in and account recovery."
            />
            {action.error && (
              <p role="alert" className="form-error">
                {action.error}
              </p>
            )}
            {action.success && (
              <p role="status" className="form-success">
                {action.success}
              </p>
            )}
            <button className="button primary" disabled={action.busy}>
              {action.busy ? "Saving…" : "Save changes"}
            </button>
          </form>
        </section>
        <section className="panel">
          <h2>Account details</h2>
          <dl className="profile-meta">
            <div>
              <dt>Email verification</dt>
              <dd>{profile?.emailVerified ? "Verified" : "Not verified"}</dd>
            </div>
            <div>
              <dt>Account ID</dt>
              <dd>
                <code>{profile?.subject}</code>
              </dd>
            </div>
            <div>
              <dt>Profile storage</dt>
              <dd>
                Your account details are securely managed by Amazon Cognito.
              </dd>
            </div>
          </dl>
          <p className="muted" style={{ marginTop: 20 }}>
            Add and manage private energy readings in My dashboard. Your energy
            records are stored separately from the public energy snapshot.
          </p>
        </section>
      </div>
    </>
  );
}

function PasswordSettings() {
  const action = useAction();
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const oldPassword = String(data.get("password"));
    const newPassword = String(data.get("newPassword"));
    if (passwordError(newPassword)) {
      action.setError(passwordError(newPassword));
      return;
    }
    form.reset();
    void action.run(async () => {
      await updatePassword({ oldPassword, newPassword });
      action.setSuccess("Your password has been updated.");
    });
  }
  return (
    <section className="panel">
      <h2>Change password</h2>
      <p className="muted">A strong password keeps your workspace yours.</p>
      <form className="form" onSubmit={save}>
        <PasswordField label="Current password" />
        <PasswordField label="New password" name="newPassword" newPassword />
        {action.error && (
          <p className="form-error" role="alert">
            {action.error}
          </p>
        )}
        {action.success && (
          <p className="form-success" role="status">
            {action.success}
          </p>
        )}
        <button className="button secondary" disabled={action.busy}>
          {action.busy ? "Updating…" : "Update password"}
        </button>
      </form>
    </section>
  );
}

function MfaSettings() {
  const [secret, setSecret] = useState("");
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const action = useAction();
  async function start() {
    const preference = await fetchMFAPreference();
    if (preference.enabled?.includes("TOTP")) {
      setEnabled(true);
      return;
    }
    const details = await setUpTOTP();
    setSecret(details.sharedSecret);
  }
  function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code")).trim();
    void action.run(async () => {
      await verifyTOTPSetup({ code });
      await updateMFAPreference({ totp: "PREFERRED" });
      setSecret("");
      setEnabled(true);
      action.setSuccess(
        "Authenticator protection is enabled. You’ll need a code when you sign in.",
      );
    });
  }
  return (
    <section className="panel">
      <h2>Authenticator protection</h2>
      <p className="muted">
        Add an extra layer of security with an authenticator app. Keep access to
        that app when you change devices.
      </p>
      {enabled ? (
        <p className="form-success" role="status">
          Authenticator protection is enabled.
        </p>
      ) : secret ? (
        <form className="form" onSubmit={confirm}>
          <p className="muted">
            Add a new time-based (TOTP) account in your authenticator. Enter
            this setup key manually, then confirm its six-digit code.
          </p>
          <code className="secret-code">{secret}</code>
          <Field
            label="Authenticator code"
            name="code"
            required
            inputMode="numeric"
            pattern="[0-9]{6}"
            autoComplete="one-time-code"
            maxLength={6}
          />
          <button className="button primary" disabled={action.busy}>
            Enable authenticator
          </button>
          <button
            className="link-button"
            type="button"
            disabled={action.busy}
            onClick={() => setSecret("")}
          >
            Cancel setup
          </button>
        </form>
      ) : (
        <button
          className="button secondary"
          style={{ marginTop: 20 }}
          disabled={action.busy}
          onClick={() => void action.run(start)}
        >
          {action.busy ? "Checking…" : "Set up authenticator"}
        </button>
      )}
      {action.error && (
        <p className="form-error" role="alert">
          {action.error}
        </p>
      )}
      {action.success && (
        <p className="form-success" role="status">
          {action.success}
        </p>
      )}
    </section>
  );
}

export function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const { logout } = useAuth();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">MAKE YOURSELF AT HOME</p>
          <h1>Settings</h1>
          <p className="page-description">
            Your preferences. Your peace of mind.
          </p>
        </div>
      </div>
      <div className="settings-grid">
        <div>
          <section className="panel">
            <h2>Appearance</h2>
            <div className="settings-row">
              <div>
                <strong>Color theme</strong>
                <p className="muted">Choose what feels right for you.</p>
              </div>
              <select
                aria-label="Color theme"
                value={theme}
                onChange={(e) =>
                  setTheme(e.target.value as "light" | "dark" | "system")
                }
              >
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </div>
            <p className="muted" style={{ marginTop: 16 }}>
              Only this appearance preference is saved on your device.
            </p>
          </section>
          <PasswordSettings />
        </div>
        <div>
          <section className="panel">
            <div className="session-info">
              <Icon name="shield" size={24} />
              <div>
                <h2>Your session</h2>
                <p className="muted">
                  Your account tokens stay in memory. Reloading or closing this
                  page requires a new sign-in. Sign out to end your session on
                  all devices.
                </p>
              </div>
            </div>
            <button
              className="button secondary"
              style={{ marginTop: 22 }}
              onClick={() => void logout()}
            >
              <Icon name="logout" size={16} /> Sign out
            </button>
          </section>
          <MfaSettings />
        </div>
      </div>
    </>
  );
}
