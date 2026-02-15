// typescript
import { Container, Stack } from "@chakra-ui/react";
import { BrewProvider, useBrewContext } from "./brew/BrewProvider";
import StartBrew from "./brew/StartBrew";
import CancelBrew from "./brew/CancelBrew";
import PauseResumeButton from "./brew/PauseResumeButton";
import FlipCard from "./brew/FlipCard";

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
        [id={brewInProgress?.brew_id}] [state={brewInProgress?.brew_state}] [flow_rate={brewInProgress?.current_flow_rate}] [weight={brewInProgress?.current_weight}]
      </b>
      <PauseResumeButton />
      <CancelBrew />
    </>
  );

  return <FlipCard isFlipped={isFlipped} front={front} back={back} />;
}
