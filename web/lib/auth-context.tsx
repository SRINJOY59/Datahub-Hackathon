"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { User, Session, AuthError } from "@supabase/supabase-js";
import { getSupabaseClient, isSupabaseConfigured } from "./supabase";

export interface AuthContextType {
  user: User | null;
  session: Session | null;
  username: string;
  email: string;
  loading: boolean;
  isConfigured: boolean;
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  signUp: (
    username: string,
    email: string,
    password: string
  ) => Promise<{ error: string | null; needsEmailConfirmation?: boolean }>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const LOCAL_STORAGE_DEV_USER = "sentinel_dev_user";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = getSupabaseClient();

    if (!supabase) {
      // If Supabase is not yet configured, check for local simulated session
      if (typeof window !== "undefined") {
        const saved = localStorage.getItem(LOCAL_STORAGE_DEV_USER);
        if (saved) {
          try {
            const parsed = JSON.parse(saved);
            setUser(parsed.user);
            setSession(parsed.session);
          } catch {
            localStorage.removeItem(LOCAL_STORAGE_DEV_USER);
          }
        }
      }
      setLoading(false);
      return;
    }

    // 1. Get initial session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
    });

    // 2. Listen to auth changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
    });

    return () => {
      subscription.unsubscribe();
    };
  }, []);

  const username =
    (user?.user_metadata?.username as string) ||
    (user?.user_metadata?.full_name as string) ||
    (user?.email ? user.email.split("@")[0] : "Operator");

  const email = user?.email || "";

  const signIn = async (
    emailInput: string,
    passwordInput: string
  ): Promise<{ error: string | null }> => {
    const supabase = getSupabaseClient();

    if (!supabase) {
      // Mock login for offline / unconfigured development
      if (!emailInput || !passwordInput) {
        return { error: "Please enter both email and password." };
      }
      const mockUser = {
        id: "dev-user-" + Date.now(),
        app_metadata: {},
        user_metadata: {
          username: emailInput.split("@")[0],
          full_name: emailInput.split("@")[0],
        },
        aud: "authenticated",
        created_at: new Date().toISOString(),
        email: emailInput,
        phone: "",
        role: "authenticated",
        updated_at: new Date().toISOString(),
      } as unknown as User;

      const mockSession = {
        access_token: "mock-token",
        refresh_token: "mock-refresh-token",
        expires_in: 3600,
        token_type: "bearer",
        user: mockUser,
      } as unknown as Session;

      setUser(mockUser);
      setSession(mockSession);
      if (typeof window !== "undefined") {
        localStorage.setItem(
          LOCAL_STORAGE_DEV_USER,
          JSON.stringify({ user: mockUser, session: mockSession })
        );
      }
      return { error: null };
    }

    try {
      const { error } = await supabase.auth.signInWithPassword({
        email: emailInput.trim(),
        password: passwordInput,
      });

      if (error) {
        return { error: error.message };
      }

      return { error: null };
    } catch (err: unknown) {
      const authErr = err as AuthError;
      return { error: authErr.message || "An unexpected error occurred during login." };
    }
  };

  const signUp = async (
    usernameInput: string,
    emailInput: string,
    passwordInput: string
  ): Promise<{ error: string | null; needsEmailConfirmation?: boolean }> => {
    const supabase = getSupabaseClient();

    if (!supabase) {
      // Mock signup for unconfigured dev environment
      if (!usernameInput.trim() || !emailInput.trim() || !passwordInput) {
        return { error: "Please fill in all fields." };
      }
      const mockUser = {
        id: "dev-user-" + Date.now(),
        app_metadata: {},
        user_metadata: {
          username: usernameInput.trim(),
          full_name: usernameInput.trim(),
        },
        aud: "authenticated",
        created_at: new Date().toISOString(),
        email: emailInput.trim(),
        phone: "",
        role: "authenticated",
        updated_at: new Date().toISOString(),
      } as unknown as User;

      const mockSession = {
        access_token: "mock-token",
        refresh_token: "mock-refresh-token",
        expires_in: 3600,
        token_type: "bearer",
        user: mockUser,
      } as unknown as Session;

      setUser(mockUser);
      setSession(mockSession);
      if (typeof window !== "undefined") {
        localStorage.setItem(
          LOCAL_STORAGE_DEV_USER,
          JSON.stringify({ user: mockUser, session: mockSession })
        );
      }
      return { error: null, needsEmailConfirmation: false };
    }

    try {
      const { data, error } = await supabase.auth.signUp({
        email: emailInput.trim(),
        password: passwordInput,
        options: {
          data: {
            username: usernameInput.trim(),
            full_name: usernameInput.trim(),
          },
        },
      });

      if (error) {
        return { error: error.message };
      }

      // Check if email confirmation is required by Supabase project settings
      const needsEmailConfirmation = Boolean(
        data.user && !data.session && !data.user.confirmed_at
      );

      return { error: null, needsEmailConfirmation };
    } catch (err: unknown) {
      const authErr = err as AuthError;
      return { error: authErr.message || "An unexpected error occurred during signup." };
    }
  };

  const signOut = async () => {
    const supabase = getSupabaseClient();
    if (supabase) {
      try {
        await supabase.auth.signOut();
      } catch (err) {
        console.error("Error signing out from Supabase:", err);
      }
    }
    setUser(null);
    setSession(null);
    if (typeof window !== "undefined") {
      localStorage.removeItem(LOCAL_STORAGE_DEV_USER);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        username,
        email,
        loading,
        isConfigured: isSupabaseConfigured,
        signIn,
        signUp,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
