import React from "react";
import { Button, Container, Input, Text, Box } from "@chakra-ui/react";
import { useId } from "react";
import { useBrewContext } from "./BrewProvider";
import { 
  DEFAULT_FLOW, 
  DEFAULT_VALVE_INTERVAL, 
  DEFAULT_EPSILON, 
  DEFAULT_TARGET_WEIGHT, 
  STRATEGIES, 
  DEFAULT_STRATEGY,
  StrategyType,
  Strategy
} from "./constants";
import { apiUrl } from "./constants";
import { validateTargetFlowInput, validateValveIntervalInput, validateEpsilonInput, validateTargetWeightInput } from "./validators";

export default function StartBrew() {
  const [targetFlowRate, setTargetFlowRate] = React.useState("");
  const [valveInterval, setValveInterval] = React.useState("");
  const [targetWeight, setTargetWeight] = React.useState("");
  const [epsilon, setEpsilon] = React.useState("");
  const [strategy, setStrategy] = React.useState<StrategyType>(DEFAULT_STRATEGY);
  const [strategyParams, setStrategyParams] = React.useState<Record<string, string>>({});
  
  const [targetFlowError, setTargetFlowError] = React.useState<string | null>(null);
  const [valveIntervalError, setValveIntervalError] = React.useState<string | null>(null);
  const [targetWeightError, setTargetWeightError] = React.useState<string | null>(null);
  const [epsilonError, setEpsilonError] = React.useState<string | null>(null);
  
  const { fetchBrewInProgress } = useBrewContext();

  // Get current strategy definition
  const currentStrategy: Strategy = STRATEGIES.find(s => s.id === strategy) || STRATEGIES[0];

  // Handle strategy change - reset params
  const handleStrategyChange = (newStrategy: StrategyType) => {
    setStrategy(newStrategy);
    // Reset strategy params when strategy changes
    const newStrategyDef = STRATEGIES.find(s => s.id === newStrategy);
    if (newStrategyDef) {
      const defaults: Record<string, string> = {};
      newStrategyDef.params.forEach(param => {
        defaults[param.name] = param.defaultValue;
      });
      setStrategyParams(defaults);
    }
  };

  // Initialize default strategy params on mount
  React.useEffect(() => {
    const defaultParams: Record<string, string> = {};
    currentStrategy.params.forEach(param => {
      defaultParams[param.name] = param.defaultValue;
    });
    setStrategyParams(defaultParams);
  }, [currentStrategy]);

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

    // Build strategy params from form values
    const effectiveStrategyParams: Record<string, string> = {};
    currentStrategy.params.forEach(param => {
      const value = strategyParams[param.name];
      effectiveStrategyParams[param.name] = value?.trim() || param.defaultValue;
    });

    const newBrewRequest = {
      target_flow_rate: parseFloat(effectiveTargetFlow),
      valve_interval: parseFloat(effectiveValveInterval),
      epsilon: parseFloat(effectiveEpsilon),
      target_weight: parseFloat(effectiveTargetWeight),
      vessel_weight: 229,
      strategy: strategy,
      strategy_params: effectiveStrategyParams,
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
  const strategyInputId = useId();

  return (
    <Container maxW="container.xl">
      <form className="start-brew-form" onSubmit={handleSubmit}>
        {/* Strategy Selection */}
        <Box mb={4}>
          <label className="terminal-row" htmlFor={strategyInputId}>STRATEGY:_</label>
          <select
            value={strategy}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => handleStrategyChange(e.target.value as StrategyType)}
            id={strategyInputId}
            aria-label="strategy"
            style={{
              width: "100%",
              padding: "8px",
              borderRadius: "4px",
              border: "1px solid #4A5568",
              background: "#2D3748",
              color: "white",
            }}
          >
            {STRATEGIES.map(s => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <Text fontSize="xs" color="gray.400" mt={1}>
            {currentStrategy.description}
          </Text>
        </Box>

        {/* Dynamic Strategy Parameters */}
        {currentStrategy.params.length > 0 && (
          <Box mb={4} p={3} borderWidth="1px" borderRadius="md" borderColor="gray.600">
            <Text fontSize="sm" fontWeight="bold" mb={2}>
              {currentStrategy.name} Parameters
            </Text>
            {currentStrategy.params.map(param => (
              <Box key={param.name} mb={2}>
                <label className="terminal-row" htmlFor={`${strategyInputId}-${param.name}`}>
                  {param.label}:_
                </label>
                <Input
                  value={strategyParams[param.name] || ""}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setStrategyParams(prev => ({
                      ...prev,
                      [param.name]: e.target.value
                    }));
                  }}
                  type="text"
                  id={`${strategyInputId}-${param.name}`}
                  placeholder={param.placeholder}
                  aria-label={param.name}
                />
                {param.description && (
                  <Text fontSize="xs" color="gray.500" mt={1}>
                    {param.description}
                  </Text>
                )}
              </Box>
            ))}
          </Box>
        )}

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
