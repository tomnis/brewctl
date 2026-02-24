import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { useBrewStatus } from "./useBrewStatus";
import { BrewContextShape } from "./types";
import { pauseBrew, resumeBrew, nudgeOpen, nudgeClose } from "./constants";

const BrewContext = createContext<BrewContextShape>({
  brewInProgress: null,
  brewError: null,
  isFlipped: false,
  fetchBrewInProgress: async () => {},
  stopConnection: () => {},
  toggleFlip: () => {},
  handlePause: async () => {},
  handleResume: async () => {},
  handleNudgeOpen: async () => {},
  handleNudgeClose: async () => {},
  dismissError: () => {},
});

export const useBrewContext = () => useContext(BrewContext);

export const BrewProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { brewInProgress, brewError, fetchBrewInProgress, startConnection, stopConnection } = useBrewStatus();
  const [isFlipped, setIsFlipped] = useState(false);

  useEffect(() => {
    startConnection();
    return () => stopConnection();
  }, [startConnection, stopConnection]);

  // When brewInProgress changes, update isFlipped to show correct side of card
  useEffect(() => {
    if (brewInProgress !== null && (brewInProgress.brew_state === "brewing" || brewInProgress.brew_state === "paused" || brewInProgress.brew_state === "error")) {
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

  const handleNudgeOpen = useCallback(async () => {
    await nudgeOpen();
    await fetchBrewInProgress();
  }, [fetchBrewInProgress]);

  const handleNudgeClose = useCallback(async () => {
    await nudgeClose();
    await fetchBrewInProgress();
  }, [fetchBrewInProgress]);

  const dismissError = useCallback(() => {
    // Error is managed by useBrewStatus, so this is a no-op
    // The error will be cleared when the brew state changes
  }, []);

  return (
    <BrewContext.Provider value={{ 
      brewInProgress, 
      brewError,
      isFlipped, 
      fetchBrewInProgress, 
      stopConnection, 
      toggleFlip, 
      handlePause, 
      handleResume,
      handleNudgeOpen,
      handleNudgeClose,
      dismissError 
    }}>
      {children}
    </BrewContext.Provider>
  );
};
