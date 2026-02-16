import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { Theme, themes, defaultTheme } from "./themes";

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  themeId: string;
  setThemeId: (id: string) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEY = "coldbrewer-theme";

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const found = themes.find((t) => t.id === stored);
      if (found) return found;
    }
  } catch {
    // localStorage not available
  }
  return defaultTheme;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  useEffect(() => {
    // Apply CSS variables when theme changes
    const root = document.documentElement;
    root.style.setProperty("--theme-primary", theme.colors.primary);
    root.style.setProperty("--theme-primary-glow", theme.colors.primaryGlow);
    root.style.setProperty("--theme-bg", theme.colors.bg);
    root.style.setProperty("--theme-bg-secondary", theme.colors.bgSecondary);
    root.style.setProperty("--theme-border", theme.colors.border);
    root.style.setProperty("--theme-input-placeholder", theme.colors.inputPlaceholder);
    
    // Also update legacy variables for compatibility
    root.style.setProperty("--chakra-colors-green-500", theme.colors.primary);
  }, [theme]);

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
    try {
      localStorage.setItem(STORAGE_KEY, newTheme.id);
    } catch {
      // localStorage not available
    }
  };

  const setThemeId = (id: string) => {
    const found = themes.find((t) => t.id === id);
    if (found) {
      setTheme(found);
    }
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme, themeId: theme.id, setThemeId }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
