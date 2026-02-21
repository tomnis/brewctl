// typescript
import { Button, Container, Stack } from "@chakra-ui/react";
import { BrewProvider, useBrewContext } from "./brew/BrewProvider";
import StartBrew from "./brew/StartBrew";
import CancelBrew from "./brew/CancelBrew";
import PauseResumeButton from "./brew/PauseResumeButton";
import FlipCard from "./brew/FlipCard";
import { ValveGauge } from "./brew/ValveGauge";
import { TrendChart } from "./brew/TrendChart";
import NudgeButtons from "./brew/NudgeButtons";

function formatTimeRemaining(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "null";
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
  if (!timeStarted) return "null";
  
  const date = new Date(timeStarted);
  const hours = date.getHours();
  const minutes = date.getMinutes();
  
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}`;
}

function formatProgressBar(current: number, target: number): string {
  const percent = Math.min(100, Math.max(0, (current / target) * 100));
  const filled = Math.round(percent / 5); // 20 chars = 5% each
  const empty = 20 - filled;
  const bar = "█".repeat(filled) + "░".repeat(empty);
  return `[${bar}] ${percent.toFixed(0)}%`;
}

export default function Brew() {
  return (
    <BrewProvider>
      <Container 
        maxW="container.xl" 
        pt={{ base: "120px", md: "100px" }}
        px={{ base: 2, md: 4 }}
        pb={{ base: "80px", md: "70px" }}
      >
        <Stack gap={{ base: 3, md: 5 }}>
          <BrewInner />
        </Stack>
      </Container>
    </BrewProvider>
  );
}

function BrewInner() {
  const { brewInProgress, isFlipped, toggleFlip } = useBrewContext();

  const eta = brewInProgress?.estimated_time_remaining ? parseFloat(brewInProgress.estimated_time_remaining) : null;
  const etaString = formatETA(eta);
  const remainingString = formatTimeRemaining(eta);

  const brewId = brewInProgress?.brew_id?.substring(0, 8) || "null";
  const brewState = brewInProgress?.brew_state || "idle";
  const state = brewState.toUpperCase();
  const strategy = brewInProgress?.brew_strategy || "default";
  const started = formatStartedTime(brewInProgress?.time_started);
  const flowRate = brewInProgress?.current_flow_rate ? parseFloat(brewInProgress.current_flow_rate).toFixed(3) + " g/s" : "null";
  const weight = brewInProgress?.current_weight ? parseFloat(brewInProgress.current_weight).toFixed(1) + " g" : "null";
  const targetWeight = brewInProgress?.target_weight ? parseFloat(brewInProgress.target_weight).toFixed(1) + " g" : "null";

  const isError = brewState === "error";
  const errorMessage = brewInProgress?.error_message || "Unknown error";

  // Determine if brew is active (brewing or paused)
  const isActive = brewState === "brewing" || brewState === "paused";
  const valvePosition = brewInProgress?.valve_position ?? null;

  const front = (
    <div className="terminal-box terminal-glow">
      <div className="terminal-header terminal-row">
        <span>$ ./brewctl start</span>
      </div>
      <StartBrew />
    </div>
  );

  const back = (
    <div className="terminal-box terminal-glow">
      <div className="terminal-header terminal-row">
        <span>$ ./brewctl inspect --verbose</span>
      </div>
      
      <div className="terminal-row">
        <span className="terminal-label">BREW_ID:_</span>
        <span className="terminal-value">{brewId}</span>
      </div>
      <div className="terminal-row">
        <span className="terminal-label">TARGET_WEIGHT:_</span>
        <span className="terminal-value">{targetWeight}</span>
      </div>
      <div className="terminal-row">
        <span className="terminal-label">TIME_STARTED:_</span>
        <span className="terminal-value">{started}</span>
      </div>
      <div className="terminal-row">
        <span className="terminal-label">STRATEGY:_</span>
        <span className="terminal-value">{strategy}</span>
      </div>
      <div className="terminal-separator">............_____________________________________________............</div>
      <div className="terminal-row">
        <span className="terminal-label">STATE:_</span>
        <span className="terminal-value">{state}</span>
      </div>
      {isError ? (
        <div className="terminal-row error-glow" style={{ color: "#ff6b6b"}}>
        <span className="terminal-label">  MESSAGE:_</span>
        <span className="terminal-value">{errorMessage}</span>
        </div>
      ) : (
          <div></div>

      )}
      <div className="terminal-row">
        <span className="terminal-label">CUR_FLOW_RATE:_</span>
        <span className="terminal-value">{flowRate}</span>
      </div>
      <div className="terminal-row">
        <span className="terminal-label">CUR_WEIGHT:_</span>
        <span className="terminal-value">{weight}</span>
      </div>
      {weight !== "null" && targetWeight !== "null" && (
        <div className="terminal-row">
          <span className="terminal-label">PROGRESS:_</span>
          <span className="terminal-value">{formatProgressBar(parseFloat(weight), parseFloat(targetWeight))}</span>
        </div>
      )}
      {etaString && (
        <div className="terminal-row">
          <span className="terminal-label">ETA:_</span>
          <span className="terminal-value">{etaString}</span>
        </div>
      )}
      {remainingString && (
        <div className="terminal-row">
          <span className="terminal-label">TIME_REMAINING:_</span>
          <span className="terminal-value">{remainingString}</span>
        </div>
      )}
      
      {/* Valve Position Gauge and Trend Chart - only shown when brewing or paused */}
      {isActive && (
        <div style={{ display: "flex", justifyContent: "center", gap: "16px", padding: "8px 0", flexWrap: "wrap" }}>
          <ValveGauge position={valvePosition} isActive={isActive} />
          <TrendChart 
            flowRateHistory={brewInProgress?.flow_rate_history || []} 
            weightHistory={brewInProgress?.weight_history || []}
            targetWeight={brewInProgress?.target_weight || null}
            isActive={isActive}
          />
        </div>
      )}
      
      <div className="terminal-footer">
        {brewState === "completed" ? (
          <Button
            className="brew-button"
            h="1.5rem"
            onClick={toggleFlip}
            colorScheme="green"
          >
            ok
          </Button>
        ) : (
          <>
            <PauseResumeButton />
            <CancelBrew />
            <NudgeButtons />
          </>
        )}
      </div>
    </div>
  );

  return <FlipCard isFlipped={isFlipped} front={front} back={back} />;
}
