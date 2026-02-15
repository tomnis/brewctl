// typescript
import { Container, Stack } from "@chakra-ui/react";
import { BrewProvider, useBrewContext } from "./brew/BrewProvider";
import StartBrew from "./brew/StartBrew";
import CancelBrew from "./brew/CancelBrew";
import PauseResumeButton from "./brew/PauseResumeButton";
import FlipCard from "./brew/FlipCard";

function formatTimeRemaining(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "N/A";
  if (seconds === 0) return "Done!";
  
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  
  if (hours > 0) {
    return `~${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `~${minutes}m ${remainingSeconds}s`;
  }
  return `~${remainingSeconds}s`;
}

function formatETA(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "";
  
  const etaDate = new Date(Date.now() + seconds * 1000);
  const hours = etaDate.getHours();
  const minutes = etaDate.getMinutes();
  
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}`;
}

function formatStartedTime(timeStarted: string | undefined): string {
  if (!timeStarted) return "N/A";
  
  const date = new Date(timeStarted);
  const hours = date.getHours();
  const minutes = date.getMinutes();
  
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}`;
}

export default function Brew() {
  return (
    <BrewProvider>
      <Container maxW="container.xl" pt="100px">
        <Stack gap={5}>
          <BrewInner />
        </Stack>
      </Container>
    </BrewProvider>
  );
}

function BrewInner() {
  const { brewInProgress, isFlipped } = useBrewContext();

  const eta = brewInProgress?.estimated_time_remaining ? parseFloat(brewInProgress.estimated_time_remaining) : null;
  const etaString = formatETA(eta);
  const remainingString = formatTimeRemaining(eta);

  const brewId = brewInProgress?.brew_id?.substring(0, 8) || "N/A";
  const state = brewInProgress?.brew_state || "UNKNOWN";
  const started = formatStartedTime(brewInProgress?.time_started);
  const flowRate = brewInProgress?.current_flow_rate ? parseFloat(brewInProgress.current_flow_rate).toFixed(3) + " g/s" : "N/A";
  const weight = brewInProgress?.current_weight ? parseFloat(brewInProgress.current_weight).toFixed(1) + " g" : "N/A";

  const front = (
    <div className="terminal-box terminal-glow">
      <div className="terminal-header">
        <span>$ ./coldbrewer --init</span>
      </div>
      <StartBrew />
    </div>
  );

  const back = (
    <div className="terminal-box terminal-glow">
      <div className="terminal-header">
        <span>$ ./brew_monitor --verbose</span>
      </div>
      
      <div className="terminal-row">
        <span className="terminal-label">BREW_ID</span>
        <span className="terminal-value">{brewId}</span>
      </div>
      <div className="terminal-row">
        <span className="terminal-label">STATE</span>
        <span className="terminal-value">{state}</span>
      </div>
      <div className="terminal-row">
        <span className="terminal-label">STARTED</span>
        <span className="terminal-value">{started}</span>
      </div>
      <div className="terminal-row">
        <span className="terminal-label">FLOW_RATE</span>
        <span className="terminal-value">{flowRate}</span>
      </div>
      <div className="terminal-row">
        <span className="terminal-label">WEIGHT</span>
        <span className="terminal-value">{weight}</span>
      </div>
      {etaString && (
        <div className="terminal-row">
          <span className="terminal-label">ETA</span>
          <span className="terminal-value">{etaString}</span>
        </div>
      )}
      {remainingString && (
        <div className="terminal-row">
          <span className="terminal-label">REMAINING</span>
          <span className="terminal-value">{remainingString}</span>
        </div>
      )}
      
      <div className="terminal-footer">
        <PauseResumeButton />
        <CancelBrew />
      </div>
    </div>
  );

  return <FlipCard isFlipped={isFlipped} front={front} back={back} />;
}
