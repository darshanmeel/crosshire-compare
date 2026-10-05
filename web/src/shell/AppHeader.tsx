import type { Meta } from "../api/client";
import { useConnections } from "../connections/ConnectionsManager";
import { Logo } from "../ui/icons";
import { Button } from "../ui/kit";
import { useLog } from "./LogPanel";
import { ModeToggle } from "./ModeToggle";
import type { Page } from "./usePage";
import { setView, useView } from "./view";

/** The 56 px header: the wordmark, the Compare / Profile switch (radiogroup "Page", as the e2e runs
 *  find it), and Connections, Run from config, Log and Light / Dark on the right. */
export function AppHeader({ meta, page, setPage }: { meta?: Meta; page: Page; setPage: (p: Page) => void }) {
  const v = useView();
  const conns = useConnections().data?.length ?? 0;
  const logs = useLog().data?.entries.length ?? 0;
  const words = (meta?.app_name ?? "").split(" ");
  const flip = (p: Page) => { setPage(p); setView({ view: "setup", column: null, anchor: null }); };
  return (
    <header className="app-header">
      <a className="brand" href="#" onClick={(e) => { e.preventDefault(); flip("Compare"); }}>
        <Logo />
        <span>{words.slice(0, -1).join(" ")} <em>{words[words.length - 1]}</em></span>
      </a>
      <div className="mode" role="radiogroup" aria-label="Page">
        {(["Compare", "Profiling"] as Page[]).map((p) => (
          <label key={p} className={page === p ? "on" : undefined}>
            <input type="radio" name="page" aria-label={p} checked={page === p} onChange={() => flip(p)} />
            {p === "Profiling" ? "Profile" : p}
          </label>
        ))}
      </div>
      <span className="grow" />
      <div className="actions">
        <Button icon="plug" count={conns} aria-pressed={v.drawer === "connections"} onClick={() => setView({ drawer: "connections" })}>Connections</Button>
        {page === "Compare" && (
          <Button aria-pressed={v.view === "config"} onClick={() => setView({ view: v.view === "config" ? "setup" : "config" })}>Run from config</Button>
        )}
        <Button count={logs} aria-pressed={v.view === "log"} onClick={() => setView({ view: v.view === "log" ? "setup" : "log" })}>Log</Button>
        <ModeToggle />
      </div>
    </header>
  );
}
