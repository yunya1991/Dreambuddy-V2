import React, { createContext, useContext, useState, useCallback } from 'react';
import type { RegimeEvolutionLatestResponse } from '../../lib/api';

type EvolutionState = {
  data: RegimeEvolutionLatestResponse | null;
  loading: boolean;
  error: string | null;
  focusDate: string | null;
  selectedRange: [string, string] | null;
  setData: (d: RegimeEvolutionLatestResponse | null) => void;
  setLoading: (b: boolean) => void;
  setError: (e: string | null) => void;
  setFocusDate: (d: string | null) => void;
  setSelectedRange: (r: [string, string] | null) => void;
};

const EvolutionContext = createContext<EvolutionState | null>(null);

export const EvolutionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [data, setDataState] = useState<RegimeEvolutionLatestResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [focusDate, setFocusDate] = useState<string | null>(null);
  const [selectedRange, setSelectedRange] = useState<[string, string] | null>(null);

  const setData = useCallback((d: RegimeEvolutionLatestResponse | null) => setDataState(d), []);
  const setLoadingCb = useCallback((b: boolean) => setLoading(b), []);
  const setErrorCb = useCallback((e: string | null) => setError(e), []);

  return (
    <EvolutionContext.Provider
      value={{
        data, loading, error, focusDate, selectedRange,
        setData, setLoading: setLoadingCb, setError: setErrorCb,
        setFocusDate, setSelectedRange,
      }}
    >
      {children}
    </EvolutionContext.Provider>
  );
};

export const useEvolution = (): EvolutionState => {
  const ctx = useContext(EvolutionContext);
  if (!ctx) throw new Error('useEvolution must be used within EvolutionProvider');
  return ctx;
};
