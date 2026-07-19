import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { get, post, User } from "./api";

interface Session {
  user: User | null;
  loading: boolean;
  login: (userId: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<Session>({
  user: null, loading: true,
  login: async () => {}, logout: async () => {},
});

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    get<User>("/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (userId: string) => {
    const u = await post<User>("/auth/login", { user_id: userId });
    setUser(u);
  };
  const logout = async () => {
    await post("/auth/logout");
    setUser(null);
  };

  return (
    <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>
  );
}

export const useSession = () => useContext(Ctx);
