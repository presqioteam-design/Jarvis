import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { onAuthStateChanged, signInWithPopup, signInWithRedirect, signOut, type User } from "firebase/auth";
import { FirebaseError } from "firebase/app";
import { auth, googleProvider } from "./firebase";

/** undefined while Firebase restores the session, null when signed out */
const AuthContext = createContext<User | null | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => onAuthStateChanged(auth, setUser), []);
  return <AuthContext.Provider value={user}>{children}</AuthContext.Provider>;
}

export const useUser = () => useContext(AuthContext);

/** Returns an error message to show, or "" on success / user cancel. */
export async function signInWithGoogle(): Promise<string> {
  try {
    await signInWithPopup(auth, googleProvider);
    return "";
  } catch (e) {
    const code = e instanceof FirebaseError ? e.code : "";
    if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") return "";
    if (code === "auth/popup-blocked" || code === "auth/operation-not-supported-in-environment") {
      await signInWithRedirect(auth, googleProvider);
      return "";
    }
    if (code === "auth/unauthorized-domain") {
      return `This domain isn't allowed to sign in. Add "${location.hostname}" in Firebase → Authentication → Settings → Authorized domains.`;
    }
    if (code === "auth/operation-not-allowed") {
      return "Google sign-in is turned off. Enable it in Firebase → Authentication → Sign-in method.";
    }
    return "Sign-in failed. Please try again.";
  }
}

export const logOut = () => signOut(auth);
