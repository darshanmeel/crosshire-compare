import type { LogEntry } from "../api/client";

export function RunDisc({ entry }: { entry: LogEntry }) {
  return (
    <div className={`runbox ${entry.state}`} role="status">
      <span className="disc">{entry.state === "done" ? "✓" : ""}</span>
      <div>
        <div className="runlabel">{entry.label}</div>
        {entry.lines.length > 0 && <div className="runline">{entry.lines[entry.lines.length - 1]}</div>}
      </div>
    </div>
  );
}
