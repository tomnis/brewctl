import React, { useEffect, useState, createContext, useContext } from "react";
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

interface Brew {
    brew_id: string;
    current_flow_rate: string
}

const BrewContext = createContext({
  brew: null, fetchBrew: () => {}
})

export default function Brew() {
  const [brew, setBrew] = useState([])
  const fetchBrew = async () => {
    const response = await fetch("http://localhost:8000/brew/status")
    const brew = await response.json()
    console.log(brew)
    setBrew(brew)
  }
  useEffect(() => {
    fetchBrew()
  }, [])

  return (
    <BrewContext.Provider value={{brew, fetchBrew}}>
      <Container maxW="container.xl" pt="100px">
        <Stack gap={5}>
             <b key={brew.brew_id}>{brew.brew_id} {brew.current_flow_rate}</b>
        </Stack>
      </Container>
    </BrewContext.Provider>
  )
}