import React from "react";
import { Button, Container, Input, Text } from "@chakra-ui/react";
import { useId } from "react";
import { useBrewContext } from "./BrewProvider";
import { DEFAULT_FLOW, DEFAULT_VALVE_INTERVAL, DEFAULT_EPSILON, DEFAULT_TARGET_WEIGHT } from "./constants";
import { apiUrl } from "./constants";
import { validateTargetFlowInput, validateValveIntervalInput, validateEpsilonInput, validateTargetWeightInput } from "./validators";

export default function StartBrew() {
  const [targetFlowRate, setTargetFlowRate] = React.useState("");
  const [valveInterval, setValveInterval] = React.useState("");
  const [targetWeight, setTargetWeight] = React.useState("");
  const [epsilon, setEpsilon] = React.useState("");
  const [targetFlowError, setTargetFlowError] = React.useState<string | null>(null);
  const [valveIntervalError, setValveIntervalError] = React.useState<string | null>(null);
  const [targetWeightError, setTargetWeightError] = React.useState<string | null>(null);

  const [epsilonError, setEpsilonError] = React.useState<string | null>(null);
    const { fetchBrewInProgress } = useBrewContext();

    const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();

      const effectiveTargetFlow = targetFlowRate.trim() || DEFAULT_FLOW;
      const effectiveValveInterval = valveInterval.trim() || DEFAULT_VALVE_INTERVAL;
      const effectiveEpsilon = epsilon.trim() || DEFAULT_EPSILON;
      const effectiveTargetWeight = targetWeight.trim() || DEFAULT_TARGET_WEIGHT;


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

      const targetWeightErr = validateTargetWeightInput(effectiveTargetWeight);
      if (targetWeightErr) {
        setTargetWeightError(targetWeightErr);
        return;
      }

      const newBrewRequest = {
        target_flow_rate: effectiveTargetFlow,
        valve_interval: effectiveValveInterval,
        epsilon: effectiveEpsilon,
        target_weight: effectiveTargetWeight,
      };

      try {
        await fetch(`${apiUrl}/brew/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newBrewRequest),
        });
        
        // Wait for backend to persist state, then fetch
        // Background polling is already running and will pick up the new state
        await new Promise(resolve => setTimeout(resolve, 1500));
        await fetchBrewInProgress();
      } catch (e) {
        console.error("start failed", e);
      }
    };

  const targetFlowRateInputId = useId();
  const valveIntervalInputId = useId();
  const targetWeightInputId = useId();
  const epsilonInputId = useId();

  return (
    <Container maxW="container.xl">
      <form className="start-brew-form" onSubmit={handleSubmit}>
        <label className="terminal-row" htmlFor={targetFlowRateInputId}>[g/s] TARGET_FLOW_RATE:_</label>
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
          <Text className="error-glow" color="red.500" fontSize="sm" mt={1}>
            {targetFlowError}
          </Text>
        )}

        <label className="terminal-row" htmlFor={valveIntervalInputId}>[sec] VALVE_INTERVAL:_</label>
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
          <Text className="error-glow" color="red.500" fontSize="sm" mt={1}>
            {valveIntervalError}
          </Text>
        )}


            <label className="terminal-row" htmlFor={targetWeightInputId}>[g] TARGET_WEIGHT:_</label>
            <Input
              value={targetWeight}
              onChange={(e: any) => {
                setTargetWeight(e.target.value);
                setTargetWeightError(validateTargetWeightInput(e.target.value));
              }}
              type="text"
              id={targetWeightInputId}
              placeholder={DEFAULT_TARGET_WEIGHT}
              aria-label="target_weight"
              aria-invalid={!!targetWeightError}
            />
            {targetWeightError && (
              <Text className="error-glow" color="red.500" fontSize="sm" mt={1}>
                {targetWeightError}
              </Text>
            )}

        <label className="terminal-row" htmlFor={epsilonInputId}>[g/s] EPSILON:_</label>
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
          <Text className="error-glow" color="red.500" fontSize="sm" mt={1}>
            {epsilonError}
          </Text>
        )}

        <div className="terminal-footer">
          <Button
            className="brew-button"
            type="submit"
            disabled={!!targetFlowError || !!valveIntervalError || !!epsilonError || !!targetWeightError}
          >
            start_brew
          </Button>
        </div>
      </form>
    </Container>
  );
}
