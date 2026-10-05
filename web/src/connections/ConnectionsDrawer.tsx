// SPEC §02: the Connections drawer, over any page. Esc, the scrim and the × close it.
import { useCallback, useRef } from "react";
import type { Meta } from "../api/client";
import { Drawer } from "../ui/kit";
import { ConnectionsManager } from "./ConnectionsManager";

export function ConnectionsDrawer({ meta, onClose }: { meta?: Meta; onClose: () => void }) {
  // The Drawer moves focus into itself whenever its onClose changes; App passes a new arrow on every
  // render, so hand it one that never changes - focus then stays in the box being typed in.
  const latest = useRef(onClose);
  latest.current = onClose;
  const close = useCallback(() => latest.current(), []);
  return <Drawer title="Connections" onClose={close}><ConnectionsManager meta={meta} /></Drawer>;
}
