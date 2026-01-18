// typescript
import React, { useEffect, useState, useRef, useId, createContext } from "react";
import {
  Button,
  Container,
  Input,
  Stack,
  Text,
} from "@chakra-ui/react";
// TODO this doesnt work override at docker build time
const apiUrl = (import.meta.env.COLDBREW_FRONTEND_API_URL as string) || "http://localhost:8000/api";
console.log("apiUrl: " + apiUrl);

interface BrewInProgress {
  brew_id: string;
  current_flow_rate: string;
  current_weight: string;
}

type BrewContextShape = {
  brewInProgress: BrewInProgress | null;
  fetchBrewInProgress: () => Promise<void>;
  stopPolling: () => void;
};

const BrewContext = createContext<BrewContextShape>({
  brewInProgress: null,
  fetchBrewInProgress: async () => {},
  stopPolling: () => {},
});

export default function Brew() {
  const [brewInProgress, setBrewInProgress] = useState<BrewInProgress | null>(null);

  // ref to hold polling state, timeout id and abort controller
  const pollRef = useRef<{
    active: boolean;
    timeoutId: number | null;
    controller: AbortController | null;
  }>({ active: false, timeoutId: null, controller: null });

  const fetchBrewInProgress = async () => {
    // abort previous fetch if still running
    if (pollRef.current.controller) {
      try {
        pollRef.current.controller.abort();
      } catch {}
    }
    const controller = new AbortController();
    pollRef.current.controller = controller;

    try {
      const response = await fetch(`${apiUrl}/brew/status`, { signal: controller.signal });
      if (!response.ok) return;
      const data = await response.json();
      setBrewInProgress(data);
    } catch (e) {
      if ((e as any).name === "AbortError") {
        // fetch was aborted; ignore
      } else {
        console.error("fetch error", e);
      }
    } finally {
      pollRef.current.controller = null;
    }
  };

  const backgroundRefreshBrewInProgress = async () => {
    await fetchBrewInProgress();
    if (!pollRef.current.active) return;
    const id = window.setTimeout(() => backgroundRefreshBrewInProgress(), 4000);
    pollRef.current.timeoutId = id;
  };

  const startPolling = () => {
    if (pollRef.current.active) return;
    pollRef.current.active = true;
    backgroundRefreshBrewInProgress();
  };

  const stopPolling = () => {
    pollRef.current.active = false;
    if (pollRef.current.timeoutId != null) {
      clearTimeout(pollRef.current.timeoutId);
      pollRef.current.timeoutId = null;
    }
    if (pollRef.current.controller) {
      try {
        pollRef.current.controller.abort();
      } catch {}
      pollRef.current.controller = null;
    }
  };

  useEffect(() => {
    startPolling();
    return () => {
      stopPolling();
    };
    // run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <BrewContext.Provider value={{ brewInProgress, fetchBrewInProgress, stopPolling }}>
      <Container maxW="container.xl" pt="100px">
        <Stack gap={5}>
          Brew in Progress:
          <b key={brewInProgress?.brew_id}>
            [id={brewInProgress?.brew_id}] [flow_rate={brewInProgress?.current_flow_rate}] [weight={brewInProgress?.current_weight}]
          </b>
        </Stack>
        <CancelBrew />
        <StartBrew />
      </Container>
    </BrewContext.Provider>
  );
}

const CancelBrew: React.FC = () => {
  const { fetchBrewInProgress, stopPolling } = React.useContext(BrewContext);

  const cancelBrew = async () => {
    try {
      await fetch(`${apiUrl}/brew/kill`, {
        method: "POST",
      });
    } catch (e) {
      console.error("cancel failed", e);
    } finally {
      // stop polling immediately and refresh state once
      stopPolling();
      await fetchBrewInProgress();
    }
  };

  return <Button h="1.5rem" onClick={cancelBrew}>cancel_brew</Button>;
};

function StartBrew() {
  const DEFAULT_FLOW = "0.05";
  const DEFAULT_VALVE_INTERVAL = "60";
  const DEFAULT_EPSILON = "0.08";

  const [targetFlowRate, setTargetFlowRate] = React.useState("");
  const [valveInterval, setValveInterval] = React.useState("");
  const [epsilon, setEpsilon] = React.useState("");
  const [targetFlowError, setTargetFlowError] = React.useState<string | null>(null);
  const [valveIntervalError, setValveIntervalError] = React.useState<string | null>(null);
  const [epsilonError, setEpsilonError] = React.useState<string | null>(null);
  const { fetchBrewInProgress } = React.useContext(BrewContext);

  const validateTargetFlowInput = (value: string): string | null => {
    const trimmed = value.trim();
    if (!trimmed) return null; // empty -> will use default (valid)
    const n = Number(trimmed);
    if (Number.isNaN(n)) return "target_flow_rate must be a number";
    if (n < 0.02 || n > 0.08) return "target_flow_rate must be between 0.02 and 0.08";
    return null;
  };

  const validateValveIntervalInput = (value: string): string | null => {
    const trimmed = value.trim();
    if (!trimmed) return null; // empty -> will use default (valid)
    const n = Number(trimmed);
    if (Number.isNaN(n)) return "valve_interval must be a number";
    if (n < 4 || n > 1024) return "valve_interval must be between 4 and 1024";
    return null;
  };

  const validateEpsilonInput = (value: string): string | null => {
    const trimmed = value.trim();
    if (!trimmed) return null; // empty -> will use default (valid)
    const n = Number(trimmed);
    if (Number.isNaN(n)) return "epsilon must be a number";
    if (n <= 0) return "epsilon must be greater than 0.0";
    if (n >= 4) return "epsilon must be less than 4.0";
    return null;
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const effectiveTargetFlow = targetFlowRate.trim() || DEFAULT_FLOW;
    const effectiveValveInterval = valveInterval.trim() || DEFAULT_VALVE_INTERVAL;
    const effectiveEpsilon = epsilon.trim() || DEFAULT_EPSILON;

    const targetErr = validateTargetFlowInput(effectiveTargetFlow);
    if (targetErr) {
      setTargetFlowError(targetErr);
      return;
    }

    const valveErr = validateValveIntervalInput(effectiveValveInterval);
    if (valveErr) {
      setValveIntervalError(valveErr);
      return;
    }

    const epsErr = validateEpsilonInput(effectiveEpsilon);
    if (epsErr) {
      setEpsilonError(epsErr);
      return;
    }

    const newBrewRequest = {
      target_flow_rate: effectiveTargetFlow,
      valve_interval: effectiveValveInterval,
      epsilon: effectiveEpsilon,
    };

    try {
      await fetch(`${apiUrl}/brew/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newBrewRequest),
      });
      await fetchBrewInProgress();
    } catch (e) {
      console.error("start failed", e);
    }
  };

  const targetFlowRateInputId = useId();
  const valveIntervalInputId = useId();
  const epsilonInputId = useId();

  return (
    <Container maxW="container.xl" pt="100px">
      <form onSubmit={handleSubmit}>
        <label htmlFor={targetFlowRateInputId}>target_flow_rate (g/sec):</label>
        <Input
          value={targetFlowRate}
          onChange={(e: any) => {
            setTargetFlowRate(e.target.value);
            setTargetFlowError(validateTargetFlowInput(e.target.value));
          }}
          type="text"
          id={targetFlowRateInputId}
          placeholder={DEFAULT_FLOW}
          aria-label="target_flow_rate"
          aria-invalid={!!targetFlowError}
        />
        {targetFlowError && (
          <Text color="red.500" fontSize="sm" mt={1}>
            {targetFlowError}
          </Text>
        )}

        <label htmlFor={valveIntervalInputId}>valve_interval (sec):</label>
        <Input
          value={valveInterval}
          onChange={(e: any) => {
            setValveInterval(e.target.value);
            setValveIntervalError(validateValveIntervalInput(e.target.value));
          }}
          type="text"
          id={valveIntervalInputId}
          placeholder={DEFAULT_VALVE_INTERVAL}
          aria-label="valve_interval"
          aria-invalid={!!valveIntervalError}
        />
        {valveIntervalError && (
          <Text color="red.500" fontSize="sm" mt={1}>
            {valveIntervalError}
          </Text>
        )}

        <label htmlFor={epsilonInputId}>epsilon (g/sec):</label>
        <Input
          value={epsilon}
          onChange={(e: any) => {
            setEpsilon(e.target.value);
            setEpsilonError(validateEpsilonInput(e.target.value));
          }}
          type="text"
          id={epsilonInputId}
          placeholder={DEFAULT_EPSILON}
          aria-label="epsilon"
          aria-invalid={!!epsilonError}
        />
        {epsilonError && (
          <Text color="red.500" fontSize="sm" mt={1}>
            {epsilonError}
          </Text>
        )}

        <Button type="submit" disabled={!!targetFlowError || !!valveIntervalError || !!epsilonError}>start_brew</Button>
      </form>
    </Container>
  );
}