import React from "react";
import { Box, Button, HStack, Input, Text } from "@chakra-ui/react";
import { useId } from "react";
import { useBrewContext } from "./BrewProvider";
import { STRATEGIES, StrategyType, Strategy } from "./constants";
import { switchStrategy } from "./brewService";

/**
 * Swap the running brew's control strategy without stopping it.
 *
 * Stopping and restarting returns the valve to start and throws away the operating
 * point, so this is the only way to try a different controller on the same batch.
 */
export default function SwitchStrategyControl() {
  const { brewInProgress, fetchBrewInProgress } = useBrewContext();

  const current = (brewInProgress?.brew_strategy || "default") as StrategyType;
  const [strategy, setStrategy] = React.useState<StrategyType>(current);
  const [strategyParams, setStrategyParams] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  const selected: Strategy = STRATEGIES.find(s => s.id === strategy) || STRATEGIES[0];
  const inputId = useId();

  // Params are per-strategy, so a change invalidates whatever was typed for the old one.
  React.useEffect(() => {
    const defaults: Record<string, string> = {};
    selected.params.forEach(param => {
      defaults[param.name] = param.defaultValue;
    });
    setStrategyParams(defaults);
  }, [selected]);

  const isActive =
    brewInProgress?.brew_state === "brewing" ||
    brewInProgress?.brew_state === "paused" ||
    brewInProgress?.brew_state === "error";

  if (!isActive) {
    return null;
  }

  const handleSwitch = async () => {
    setError(null);
    setBusy(true);
    try {
      const effective: Record<string, string> = {};
      selected.params.forEach(param => {
        effective[param.name] = strategyParams[param.name]?.trim() || param.defaultValue;
      });
      await switchStrategy(strategy, effective);
      await fetchBrewInProgress();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "switch failed");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <Button
        className="brew-button"
        h="1.5rem"
        size="sm"
        colorScheme="purple"
        onClick={() => setOpen(true)}
      >
        Switch Strategy
      </Button>
    );
  }

  return (
    <Box mt={2} p={3} borderWidth="1px" borderRadius="md" borderColor="gray.600">
      <label className="terminal-row" htmlFor={inputId}>SWITCH_STRATEGY:_</label>
      <select
        value={strategy}
        onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
          setStrategy(e.target.value as StrategyType)
        }
        id={inputId}
        aria-label="switch strategy"
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
      <Text fontSize="xs" color="gray.400" mt={1}>{selected.description}</Text>

      {selected.params.map(param => (
        <Box key={param.name} mt={2}>
          <label className="terminal-row" htmlFor={`${inputId}-${param.name}`}>
            {param.label}:_
          </label>
          <Input
            value={strategyParams[param.name] || ""}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setStrategyParams(prev => ({ ...prev, [param.name]: e.target.value }))
            }
            type="text"
            id={`${inputId}-${param.name}`}
            placeholder={param.placeholder}
            aria-label={param.name}
          />
        </Box>
      ))}

      {error && (
        <Text fontSize="xs" color="red.400" mt={2} aria-label="switch strategy error">
          {error}
        </Text>
      )}

      <HStack gap={2} mt={3}>
        <Button
          className="brew-button"
          h="1.5rem"
          size="sm"
          colorScheme="purple"
          loading={busy}
          onClick={handleSwitch}
        >
          Apply
        </Button>
        <Button
          className="brew-button"
          h="1.5rem"
          size="sm"
          onClick={() => { setOpen(false); setError(null); }}
        >
          Cancel
        </Button>
      </HStack>
    </Box>
  );
}
