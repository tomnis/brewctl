import { Button } from "@chakra-ui/react";
import { useBrewContext } from "./BrewProvider";

export default function PauseResumeButton() {
  const { brewInProgress, handlePause, handleResume } = useBrewContext();

  if (!brewInProgress) {
    return null;
  }

  const isPaused = brewInProgress.brew_state === "paused";

  return isPaused ? (
    <Button
      className="brew-button"
      h="1.5rem"
      onClick={handleResume}
      colorScheme="green"
    >
      resume_brew
    </Button>
  ) : (
    <Button
      className="brew-button"
      h="1.5rem"
      onClick={handlePause}
      colorScheme="yellow"
    >
      pause_brew
    </Button>
  );
}
