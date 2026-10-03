import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { UserProfile } from "../api/types";

interface AuthContextValue {
  user: UserProfile | null;
  loading: boolean;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (input: {
    email: string;
    password: string;
    full_name: string;
  }) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (user: UserProfile) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  const signInMutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      api.signin(email, password),
    onSuccess: (data) => {
      queryClient.setQueryData(["me"], data);
      void queryClient.invalidateQueries();
    },
  });

  const signUpMutation = useMutation({
    mutationFn: (input: { email: string; password: string; full_name: string }) =>
      api.signup({ ...input, role: "traveller" }),
    onSuccess: (data) => {
      queryClient.setQueryData(["me"], data);
      void queryClient.invalidateQueries();
    },
  });

  const signOutMutation = useMutation({
    mutationFn: api.signout,
    onSuccess: () => {
      queryClient.setQueryData(["me"], undefined);
      queryClient.clear();
    },
  });

  const signIn = useCallback(
    async (email: string, password: string) => {
      await signInMutation.mutateAsync({ email, password });
    },
    [signInMutation],
  );

  const signUp = useCallback(
    async (input: { email: string; password: string; full_name: string }) => {
      await signUpMutation.mutateAsync(input);
    },
    [signUpMutation],
  );

  const signOut = useCallback(async () => {
    await signOutMutation.mutateAsync();
  }, [signOutMutation]);

  const refresh = useCallback(async () => {
    await meQuery.refetch();
  }, [meQuery]);

  const setUser = useCallback(
    (user: UserProfile) => {
      queryClient.setQueryData(["me"], { user });
    },
    [queryClient],
  );

  const value = useMemo<AuthContextValue>(() => {
    const error =
      meQuery.error instanceof ApiError && meQuery.error.status !== 401
        ? meQuery.error.detail
        : null;
    return {
      user: meQuery.data?.user ?? null,
      loading: meQuery.isLoading,
      error,
      signIn,
      signUp,
      signOut,
      refresh,
      setUser,
    };
  }, [
    meQuery.data,
    meQuery.isLoading,
    meQuery.error,
    signIn,
    signUp,
    signOut,
    refresh,
    setUser,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
