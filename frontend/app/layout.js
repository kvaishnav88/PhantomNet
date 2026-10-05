import "./globals.css";

export const metadata = {
  title: "PhantomNet | Generative Cyber-Deception",
  description: "An LLM honeypot with a live analyst dashboard.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}