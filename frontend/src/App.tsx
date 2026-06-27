import { PROTOCOL_VERSION } from "@browser-agent/contracts";

export default function App() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-neutral-950 text-neutral-100">
      <div className="text-center">
        <h1 className="text-2xl font-semibold">Browser Agent — Cockpit</h1>
        <p className="mt-2 text-neutral-400">
          Scaffold. Protocol v{PROTOCOL_VERSION}.
        </p>
      </div>
    </main>
  );
}
