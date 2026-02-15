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
  
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  
  if (minutes === 0) {
    return `~${remainingSeconds}s remaining`;
  }
  return `~${minutes}m ${remainingSeconds}s remaining`;
}

function formatETA(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "";
  
  const etaDate = new Date(Date.now() + seconds * 1000);
  const hours = etaDate.getHours();
  const minutes = etaDate.getMinutes();
  const ampm = hours >= 12 ? "PM" : "AM";
  const displayHours = hours % 12 || 12;
  const displayMinutes = minutes.toString().padStart(2, "0");
  
  return `ETA: ${displayHours}:${displayMinutes} ${ampm}`;
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

  const front = (
    <>
      Brew parameters:
      <StartBrew />
    </>
  );

  const back = (
    <>
      Brew in Progress:
      <b key={brewInProgress?.brew_id}>
        [id={brewInProgress?.brew_id?.substring(0, 8)}] [state={brewInProgress?.brew_state}] [started={formatStartedTime(brewInProgress?.time_started)}] [flow_rate={brewInProgress?.current_flow_rate ? parseFloat(brewInProgress.current_flow_rate).toFixed(3) + 'g/s' : 'N/A'}] [weight={brewInProgress?.current_weight ? parseFloat(brewInProgress.current_weight).toFixed(1) + 'g' : 'N/A'}]
      </b>
      {etaString && remainingString && (
        <div>
          {etaString} ({remainingString})
        </div>
      )}
      <PauseResumeButton />
      <CancelBrew />
    </>
  );

  return <FlipCard isFlipped={isFlipped} front={front} back={back} />;
}
