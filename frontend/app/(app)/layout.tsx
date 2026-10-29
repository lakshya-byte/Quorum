import { AuthProvider } from "../_lib/auth";
import AppShell from "../_components/shell/AppShell";
import { ToastProvider } from "../_ui";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <ToastProvider>
        <AppShell>{children}</AppShell>
      </ToastProvider>
    </AuthProvider>
  );
}
