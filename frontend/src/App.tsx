import { ChakraProvider } from '@chakra-ui/react'
import { defaultSystem } from "@chakra-ui/react"
import Header from "./components/Header";
import Brew from "./components/Brew";
import { ThemeProvider } from "./components/theme/ThemeContext";


function App() {

  return (
    <ChakraProvider value={defaultSystem}>
      <ThemeProvider>
        <Header />
        <Brew />
      </ThemeProvider>
    </ChakraProvider>
  )
}

export default App;
