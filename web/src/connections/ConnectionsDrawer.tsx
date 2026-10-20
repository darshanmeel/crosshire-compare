// SPEC §02: the Connections drawer, docked beside any page from 1100 px, over it below. Esc, the ×
// (and below 1100 px the scrim) close it. Its title carries the plug and the count of connections.
import { useCallback, useRef } from "react";
import type { Meta } from "../api/client";
import { Icon } from "../ui/icons";
import { Drawer } from "../ui/kit";
import { ConnectionsManager, useConnections } from "./ConnectionsManager";

export function ConnectionsDrawer({ meta, onClose }: { meta?: Meta; onClose: () => void }) {
  // The Drawer moves focus into itself whenever its onClose changes; App passes a new arrow on every
  // render, so hand it one that never changes - focus then stays in the box being typed in.
  const latest = useRef(onClose);
  latest.current = onClose;
  const close = useCallback(() => latest.current(), []);
  const n = useConnections().data?.length;
  const title = <><Icon name="plug" />Connections{n !== undefined && <span className="count">{n}</span>}</>;
  return <Drawer title={title} label="Connections" onClose={close}><ConnectionsManager meta={meta} /></Drawer>;
}
