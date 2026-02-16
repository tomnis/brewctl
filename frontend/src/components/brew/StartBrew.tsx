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
    const { fetchBrewInProgress, toggleFlip } = useBrewContext();

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
        
        // Poll for brew status with retries to handle race condition
        // where the backend may not have finished persisting the brew state yet
        const maxRetries = 5;
        const retryDelayMs = 500;
        
        // Skip background polling during retry loop to prevent stale data overwriting our results
        for (let attempt = 0; attempt < maxRetries; attempt++) {
          await fetchBrewInProgress({ skipBackground: true });
          
          // Wait a bit before next retry
          await new Promise(resolve => setTimeout(resolve, retryDelayMs));
        }
        
        // Don't call toggleFlip() here - the effect in BrewProvider.tsx
        // automatically flips the card when brewInProgress has valid data
      } catch (e) {
        console.error("start failed", e);
      }
    };

  const targetFlowRateInputId = useId();
  const valveIntervalInputId = useId();
  const targetWeightInputId = useId();
  const epsilonInputId = useId();

  return (
    <Container maxW="container.xl" pt="100px">
      <form className="start-brew-form" onSubmit={handleSubmit}>
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
          <Text className="error-glow" color="red.500" fontSize="sm" mt={1}>
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
          <Text className="error-glow" color="red.500" fontSize="sm" mt={1}>
            {valveIntervalError}
          </Text>
        )}


            <label htmlFor={targetWeightInputId}>target_weight (grams):</label>
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
          <Text className="error-glow" color="red.500" fontSize="sm" mt={1}>
            {epsilonError}
          </Text>
        )}

        <Button
          className="brew-button"
          type="submit"
          disabled={!!targetFlowError || !!valveIntervalError || !!epsilonError || !!targetWeightError}
        >
          start_brew
        </Button>
      </form>
    </Container>
  );
}
