import { createContext, useContext, useState, type ReactNode } from "react";

interface BrowserContextValue {
  url: string | null;
  openUrl: (url: string) => void;
  close: () => void;
}

const BrowserContext = createContext<BrowserContextValue>({
  url: null,
  openUrl: () => {},
  close: () => {},
});

export function BrowserProvider({ children }: { children: ReactNode }) {
  const [url, setUrl] = useState<string | null>(null);

  return (
    <BrowserContext.Provider value={{ url, openUrl: setUrl, close: () => setUrl(null) }}>
      {children}
    </BrowserContext.Provider>
  );
}

export function useBrowser() {
  return useContext(BrowserContext);
}
