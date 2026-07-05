import "./globals.css";
import { V3AppShell } from "@/components/V3AppShell";

export const metadata = {
  title: "DreamBuddy v3 — AI Trading System",
  description: "WorkBuddy OS SACG Architecture Frontend",
};

export default function V3Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="v3-root">
      <V3AppShell>{children}</V3AppShell>
    </div>
  );
}
