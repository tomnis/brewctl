import { ChakraProvider } from '@chakra-ui/react'
import { defaultSystem } from "@chakra-ui/react"
import Header from "./components/Header";
import Brew from "./components/Brew";
import BrewStart from "./components/BrewStart";
import Todos from "./components/Todos";  // new


function App() {

  return (
    <ChakraProvider value={defaultSystem}>
      <Header />
      <Brew />

    </ChakraProvider>
  )
}

export default App;