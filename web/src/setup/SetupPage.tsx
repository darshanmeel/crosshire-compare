import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSideForm } from "../sources/formStore";
import { useSources } from "../sources/useSources";
import { refreshSetup, SETUP_KEY, type SetupView } from "./api";

/** What the setup keeps in step with the sides, mounted once on the Compare page whatever view is
 *  on screen: the Name boxes name the table's columns, and a side loaded reads the table again. */
export function useSetupSync() {
  const qc = useQueryClient();
  const [fa] = useSideForm("A");
  const [fb] = useSideForm("B");
  const sources = useSources();
  useEffect(() => {                      // the Name boxes name the table's columns and the card
    const t = setTimeout(() => {
      api.send<SetupView>("PUT", "/api/setup/names", { A: fa.name, B: fb.name })
        .then((v) => qc.setQueryData(SETUP_KEY, v)).catch(() => undefined);
    }, 300);
    return () => clearTimeout(t);
  }, [fa.name, fb.name]);
  useEffect(() => { refreshSetup(qc); }, [sources.dataUpdatedAt]);   // a side loaded, a config read: the table again
}

export function SetupSync() {
  useSetupSync();
  return null;
}
