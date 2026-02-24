import { Button } from "@chakra-ui/react";
import { useBrewContext } from "./BrewProvider";
import { apiUrl } from "./constants";

export default function CancelBrew() {
  const { fetchBrewInProgress, stopConnection, toggleFlip } = useBrewContext();

  const cancelBrew = async () => {
    try {
      await fetch(`${apiUrl}/brew/kill`, { method: "POST" });
    } catch (e) {
      console.error("cancel failed", e);
    } finally {
      stopConnection();
      await fetchBrewInProgress();
      toggleFlip();
    }
  };

  return (
    <Button className="brew-button" h="1.5rem" onClick={cancelBrew}>
      cancel_brew
    </Button>
  );
}
