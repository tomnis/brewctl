import React, { useEffect, useState, useId, createContext, useContext } from "react";
import {
  Box,
  Button,
  Container,
  Flex,
  Input,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogRoot,
  DialogTitle,
  DialogTrigger,
  Stack,
  Text,
  DialogActionTrigger,
} from "@chakra-ui/react";
const apiUrl = import.meta.env.COLDBREW_FRONTEND_API_URL;


interface BrewInProgress {
    brew_id: string;
    current_flow_rate: string
}

const BrewContext = createContext({
  brewInProgress: null, fetchBrewInProgress: () => {}
})

export default function Brew() {
  const [brewInProgress, setBrewInProgress] = useState([])

  const fetchBrewInProgress = async () => {
    const response = await fetch(`${apiUrl}/brew/status`)
    const brewInProgress = await response.json()
    console.log(brewInProgress)
    setBrewInProgress(brewInProgress)
  }

  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

  const backgroundRefreshBrewInProgress = async () => {
      fetchBrewInProgress()
      await delay(4000); // Waits for a few seconds
      console.log("recursive call")
      backgroundRefreshBrewInProgress()
  }

//   useEffect(() => {
      // TODO somehow call this repeatedly to update brew in progress
//     fetchBrewInProgress()
//   }, [])
  useEffect(() => {
      // TODO somehow call this repeatedly to update brew in progress
    backgroundRefreshBrewInProgress()
  }, [])


  // TODO should only show this if there is currently a brew in progress
  return (
    <BrewContext.Provider value={{brewInProgress, fetchBrewInProgress}}>
      <Container maxW="container.xl" pt="100px">
        <Stack gap={5}>
    Brew in Progress:
             <b key={brewInProgress.brew_id}>[id={brewInProgress.brew_id}]   [flow_rate={brewInProgress.current_flow_rate}]   [weight={brewInProgress.current_weight}]</b>
        </Stack>
        <CancelBrew fetchBrewInProgress={fetchBrewInProgress} />
        <StartBrew />
      </Container>
    </BrewContext.Provider>
  )
}


const CancelBrew = ({fetchBrewInProgress}) => {
   const cancelBrew = async() => {
       await fetch(`${apiUrl}/brew/kill`, {
           method: "POST"
       })
       await fetchBrewInProgress()
   }

    return (
        <Button h="1.5rem" onClick={cancelBrew}>cancel_brew</Button>
    )
}


function StartBrew() {
    const [startBrewRequest, setStartBrewRequest] = React.useState("")
    const {brewInProgress, fetchBrewInProgress} = React.useContext(BrewContext)

     const handleInput = (event: React.ChangeEvent<HTMLInputElement>) => {
       setBrewRequest(event.target.value)
     }

    // handle "brew start buttonw" TODO on error
     const handleSubmit =(event: React.FormEvent<HTMLFormElement>) => {
         event.preventDefault()
         console.log(startBrewRequest)
         const newBrewRequest = {
           "target_flow_rate": startBrewRequest.target_flow_rate,
           "valve_interval": startBrewRequest.valve_interval,
           "epsilon": startBrewRequest.epsilon,
         }

         fetch(`${apiUrl}/brew/start`, {
           method: "POST",
           headers: { "Content-Type": "application/json" },
           body: JSON.stringify(newBrewRequest)
         }).then(fetchBrewInProgress)
     }

   const targetFlowRateInputId = useId();
   const valveIntervalInputId = useId();
   const epsilonInputId = useId();

   return (
     <BrewContext.Provider value={{startBrewRequest, fetchBrewInProgress}}>
       <Container maxW="container.xl" pt="100px">
           <form onSubmit={handleSubmit}>
               <label htmlFor={targetFlowRateInputId}>target_flow_rate:</label>
               <Input type="text" id={targetFlowRateInputId} placeholder="0.05" aria-label="target_flow_rate"/>

               <label htmlFor={valveIntervalInputId}>valve_interval:</label>
               <Input type="text" id={valveIntervalInputId} placeholder="60" aria-label="valve_interval"/>

               <label htmlFor={epsilonInputId}>epsilon:</label>
               <Input type="text" id={epsilonInputId} placeholder="0.08" aria-label="epsilon"/>
               <button type="submit">start_brew</button>
           </form>
       </Container>
     </BrewContext.Provider>
   )
}