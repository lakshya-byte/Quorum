import { AuthProvider } from "../_lib/auth";
import AppHeader from "./_components/AppHeader";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AppHeader />
      <main className="w-full flex-1 max-w-7xl mx-auto px-4 lg:px-8 py-6 sm:py-8">{children}</main>
    </AuthProvider>
  );
}
