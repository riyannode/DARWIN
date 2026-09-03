import "../styles/tokens.css";
import "../styles/globals.css";
import { Shell } from "../components/shell";

export const metadata = {
  title: "DarwinSpot",
  description: "Autonomous spot trading inside a visible, bounded authority boundary.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
