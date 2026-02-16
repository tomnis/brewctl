import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { useBrewPolling } from "./useBrewPolling";
import { BrewContextShape } from "./types";
import { pauseBrew, resumeBrew } from "./constants";

const BrewContext = createContext<BrewContextShape>({
  brewInProgress: null,
  isFlipped: false,
  fetchBrewInProgress: async () => {},
  stopPolling: () => {},
  toggleFlip: () => {},
  handlePause: async () => {},
  handleResume: async () => {},
});

export const useBrewContext = () => useContext(BrewContext);

export const BrewProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { brewInProgress, fetchBrewInProgress, startPolling, stopPolling } = useBrewPolling();
  const [isFlipped, setIsFlipped] = useState(false);

  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  // When brewInProgress changes, update isFlipped to show correct side of card
  useEffect(() => {
    if (brewInProgress !== null && (brewInProgress.brew_state === "brewing" || brewInProgress.brew_state === "paused")) {
      setIsFlipped(true);
    }
  }, [brewInProgress]);

  const toggleFlip = () => setIsFlipped(v => !v);

  const handlePause = useCallback(async () => {
    await pauseBrew();
    await fetchBrewInProgress();
  }, [fetchBrewInProgress]);

  const handleResume = useCallback(async () => {
    await resumeBrew();
    await fetchBrewInProgress();
  }, [fetchBrewInProgress]);

  return (
    <BrewContext.Provider value={{ brewInProgress, isFlipped, fetchBrewInProgress, stopPolling, toggleFlip, handlePause, handleResume }}>
      {children}
    </BrewContext.Provider>
  );
};
