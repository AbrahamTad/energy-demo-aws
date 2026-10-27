import { useId, useState } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";
import { useAuth } from "../auth/context";
import { Icon } from "./Icon";

export function Field({
  label,
  hint,
  id,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  return (
    <div className="field">
      <label htmlFor={fieldId}>{label}</label>
      <input
        {...props}
        id={fieldId}
        aria-describedby={hint ? `${fieldId}-hint` : undefined}
      />
      {hint && <small id={`${fieldId}-hint`}>{hint}</small>}
    </div>
  );
}
export function PasswordField({
  label = "Password",
  name = "password",
  newPassword = false,
}: {
  label?: string;
  name?: string;
  newPassword?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <span className="password-field">
        <input
          id={id}
          name={name}
          required
          type={visible ? "text" : "password"}
          autoComplete={newPassword ? "new-password" : "current-password"}
          minLength={newPassword ? 12 : 1}
          maxLength={128}
          aria-describedby={newPassword ? `${id}-hint` : undefined}
        />
        <button
          type="button"
          onClick={() => setVisible(!visible)}
          aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </span>
      {newPassword && (
        <small id={`${id}-hint`}>
          12 or more characters, with uppercase, lowercase, a number, and a
          symbol.
        </small>
      )}
    </div>
  );
}
export function AuthPanel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  const { configured } = useAuth();
  return (
    <div className="auth-layout">
      <aside className="auth-story">
        <span className="brand-icon">
          <Icon name="bolt" size={38} />
        </span>
        <p className="eyebrow">A MORE CONNECTED PERSPECTIVE</p>
        <h2>
          Your energy.
          <br />A brighter outlook.
        </h2>
        <p>
          One thoughtful space to understand your energy and manage your
          account.
        </p>
        <ul>
          <li>
            <Icon name="check" size={17} /> Your sources, clearly visualized
          </li>
          <li>
            <Icon name="check" size={17} /> Your account, securely connected
          </li>
          <li>
            <Icon name="check" size={17} /> Built for wherever you are
          </li>
        </ul>
      </aside>
      <section className="auth-form-wrap">
        <h1>{title}</h1>
        <p className="muted">{subtitle}</p>
        {!configured && (
          <div className="notice" role="status">
            Account access isn’t available yet. You can still explore the energy
            dashboard.
          </div>
        )}
        {children}
        <p className="auth-note">
          <Icon name="shield" size={16} />
          Sessions stay in this page’s memory. After a reload or closing the
          tab, sign in again.
        </p>
      </section>
    </div>
  );
}
