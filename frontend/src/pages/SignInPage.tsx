import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { Button } from "../components/ui/Button";
import { TextField } from "../components/ui/Form";
import { Icon } from "../components/ui/Icon";
import { useToast } from "../components/ui/Toast";
import { AuthLayout } from "../components/auth/AuthLayout";

export function SignInPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { signIn } = useAuth();
  const toast = useToast();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(from, { replace: true });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Sign-in failed.";
      setError(message);
      toast.error("Could not sign in", message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      <h2 className="h2" style={{ marginBottom: "var(--s-2)" }}>Sign in to ReTryp</h2>
      <p className="secondary" style={{ marginBottom: "var(--s-6)" }}>
        Manage your complete journey from one place.
      </p>

      <form onSubmit={submit} className="stack stack-4">
        <TextField
          label="Email"
          value={email}
          onChange={setEmail}
          type="email"
          autoComplete="username"
          placeholder="you@example.com"
          required
        />

        <div className="field">
          <label className="field__label" htmlFor="password">
            Password
          </label>
          <div style={{ position: "relative" }}>
            <input
              id="password"
              className="input"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
              style={{ paddingRight: "var(--s-8)" }}
            />
            <button
              type="button"
              className="btn btn--icon btn--ghost btn--sm"
              onClick={() => setShowPassword((value) => !value)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              style={{ position: "absolute", right: 4, top: 3 }}
            >
              <Icon name={showPassword ? "EyeOff" : "Eye"} size={15} />
            </button>
          </div>
        </div>

        {error ? (
          <div className="field__error" role="alert">
            <Icon name="TriangleAlert" size={13} />
            {error}
          </div>
        ) : null}

        <Button type="submit" variant="primary" size="lg" block loading={busy} icon="Lock">
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
