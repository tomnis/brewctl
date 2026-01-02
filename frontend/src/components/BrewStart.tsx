import React, { useEffect, useId, useState, createContext, useContext } from "react";
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

const BrewStartContext = createContext({
    brewRequest: null, fetchBrew: () => {}
})

export default function BrewStart() {
      const [brew, setBrew] = useState([])
  const [brewRequest, setBrewRequest] = useState([])
  const {brews, fetchBrews} = React.useContext(BrewStartContext)

 const fetchBrew = async () => {
      const response = await fetch("http://localhost:8000/brew/status")
      const brew = await response.json()
      console.log("in fetchBrew: " + brew)
      setBrew(brew)
    }

  const handleInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    setBrewReqRequest(event.target.value)
  }

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    console.log(brewRequest)
    const newBrewRequest = {
      "target_flow_rate": brewRequest.target_flow_rate,
      "valve_interval": brewRequest.valve_interval,
      "epsilon": brewRequest.epsilon,
    }

    fetch("http://localhost:8000/brew/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(newBrewRequest)
    }).then(fetchBrew)
  }

//   return (
//     <form onSubmit={handleSubmit}>
//       <Input
//         pr="4.5rem"
//         type="text"
//         placeholder="Add a todo item"
//         aria-label="Add a todo item"
//         onChange={handleInput}
//       />
//     </form>
//   )
  const targetFlowRateInputId = useId();
  const valveIntervalInputId = useId();
  const epsilonInputId = useId();



  return (
    <BrewStartContext.Provider value={{brewRequest, fetchBrew}}>
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
    </BrewStartContext.Provider>
  )
}