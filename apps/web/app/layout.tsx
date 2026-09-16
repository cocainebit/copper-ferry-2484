import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Agent Desktop — A computer for your ideas",
  description:
    "Give your agent a persistent cloud computer. Watch it work, step in when needed, and pick up where you left off.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
