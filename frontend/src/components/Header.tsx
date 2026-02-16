import { Heading, Flex } from "@chakra-ui/react";
import { useTheme } from "./theme/ThemeContext";
import { themes } from "./theme/themes";

const Header = () => {
  const { themeId, setThemeId } = useTheme();

  return (
    <Flex
      as="nav"
      align="center"
      justify="space-between"
      wrap="wrap"
      padding={{ base: "0.5rem 0.75rem", md: "0.75rem 1rem" }}
      bg="var(--theme-bg-secondary)"
      borderBottom="2px solid var(--theme-border)"
      width="100%"
      position="fixed"
      top="0"
      left="0"
      right="0"
      zIndex="1000"
      boxShadow="0 0 10px var(--theme-primary)"
      flexDirection={{ base: "column", md: "row" }}
      gap={{ base: 2, md: 0 }}
    >
      <Flex 
        align="center" 
        as="nav" 
        mr={{ base: 0, md: 5 }}
        width={{ base: "100%", md: "auto" }}
        justify={{ base: "center", md: "flex-start" }}
      >
        <Heading 
          as="h1" 
          size={{ base: "sm", md: "md" }} 
          className="terminal-glow"
          fontFamily="'VT323', 'Courier New', Courier, monospace"
        >
          COLDBREWER v1.0
        </Heading>
      </Flex>
      <Flex 
        align="center" 
        gap={{ base: 2, md: 4 }}
        width={{ base: "100%", md: "auto" }}
        justify={{ base: "center", md: "flex-end" }}
        flexWrap="wrap"
      >
        <span className="terminal-glow" style={{ fontSize: '0.9em' }} aria-hidden="true">
          [System Online]
        </span>
        <select
          className="theme-select"
          value={themeId}
          onChange={(e) => setThemeId(e.target.value)}
          aria-label="Select theme"
        >
          {themes.map((theme) => (
            <option key={theme.id} value={theme.id}>
              {theme.name}
            </option>
          ))}
        </select>
      </Flex>
    </Flex>
  );
};

export default Header;
