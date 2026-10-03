import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { AuthLayout } from "../components/auth/AuthLayout";
import { Button } from "../components/ui/Button";
import { TextField } from "../components/ui/Form";
import { Icon } from "../components/ui/Icon";
import { useToast } from "../components/ui/Toast";

export function SignUpPage() {
  const navigate = useNavigate();
  const { signUp } = useAuth();
  const toast = useToast();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await signUp({ email: email.trim(), password, full_name: fullName.trim() });
      toast.success("Account created", "Welcome to ReTryp.");
      navigate("/", { replace: true });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Could not create the account.";
      setError(message);
      toast.error("Could not create the account", message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      <h2 className="h2" style={{ marginBottom: "var(--s-2)" }}>Create an account</h2>
      <p className="secondary" style={{ marginBottom: "var(--s-6)", lineHeight: 1.6 }}>
        A traveller account lets you build a journey and recover it when a leg breaks.
        Travel-manager access is granted by an administrator.
      </p>

      <form onSubmit={submit} className="stack stack-4">
        <TextField
          label="Full name"
          value={fullName}
          onChange={setFullName}
          autoComplete="name"
          placeholder="Your name"
          required
        />
        <TextField
          label="Email"
          value={email}
          onChange={setEmail}
          type="email"
          autoComplete="username"
          placeholder="you@example.com"
          required
        />
        <TextField
          label="Password"
          value={password}
          onChange={setPassword}
          type="password"
          autoComplete="new-password"
          hint="At least 8 characters."
          required
        />
        <TextField
          label="Confirm password"
          value={confirm}
          onChange={setConfirm}
          type="password"
          autoComplete="new-password"
          required
        />

        {error ? (
          <div className="field__error" role="alert">
            <Icon name="TriangleAlert" size={13} />
            {error}
          </div>
        ) : null}

        <Button type="submit" variant="primary" size="lg" block loading={busy} icon="User">
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
