import { useState } from "react";
import { ServerForm } from "@/components/native/ServerGate";
import { isNative, serverBase } from "@/lib/native";

/** Android app only: shows which server the app uses and lets the person change it. Renders nothing in a browser. */
export default function ServerNote() {
  const [editing, setEditing] = useState(false);
  if (!isNative()) return null;
  if (editing)
    return (
      <div className="mt-4 flex justify-center">
        <ServerForm onSaved={() => window.location.reload()} onCancel={() => setEditing(false)} />
      </div>
    );
  return (
    <p className="mt-3 text-center text-[11px] text-muted-foreground" data-testid="server-note">
      Server: {serverBase().replace(/^https?:\/\//, "")} ·{" "}
      <button type="button" className="underline underline-offset-2" onClick={() => setEditing(true)} data-testid="server-change">
        change
      </button>
    </p>
  );
}
