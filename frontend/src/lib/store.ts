import { create } from 'zustand';
import { apiCall } from './api';

// ---------- Types ----------

interface User {
  actor_id: string;
  actor_type: string;
  name: string;
}

interface DelegatedAgent {
  id: string;
  name: string;
  status: string;
  api_key_preview: string;
  reputation: number;
}

interface UserProfile {
  id: string;
  name: string;
  auth_method: string;
  reputation_score: number;
  voting_weight: number;
  delegated_agents: DelegatedAgent[];
  orcid_id?: string | null;
  google_scholar_id?: string | null;
}

interface DomainAuthority {
  id: string;
  domain_name: string;
  authority_score: number;
  total_comments: number;
}

// ---------- Auth Store ----------

interface AuthState {
  isAuthenticated: boolean;
  hydrated: boolean;
  user: User | null;
  accessToken: string | null;
  login: (token: string, user: User) => void;
  logout: () => void;
  restore: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  hydrated: false,
  user: null,
  accessToken: null,

  login: (token, user) => {
    localStorage.setItem('access_token', token);
    localStorage.setItem('user', JSON.stringify(user));
    set({ isAuthenticated: true, accessToken: token, user });
  },

  logout: () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
    set({ isAuthenticated: false, accessToken: null, user: null });
    // Clear profile store on logout
    useProfileStore.getState().clear();
  },

  restore: () => {
    const token = localStorage.getItem('access_token');
    const stored = localStorage.getItem('user');
    if (token && stored) {
      try {
        set({ isAuthenticated: true, hydrated: true, accessToken: token, user: JSON.parse(stored) });
        return;
      } catch {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
      }
    }
    set({ hydrated: true });
  },
}));

// ---------- Profile Store ----------
// Cached user profile + reputation, shared across all pages.

interface ProfileState {
  profile: UserProfile | null;
  reputation: DomainAuthority[];
  loading: boolean;
  fetchProfile: () => Promise<void>;
  addAgent: (agent: DelegatedAgent) => void;
  removeAgent: (agentId: string) => void;
  clear: () => void;
}

export const useProfileStore = create<ProfileState>((set, get) => ({
  profile: null,
  reputation: [],
  loading: false,

  fetchProfile: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const [profile, reputation] = await Promise.all([
        apiCall<UserProfile>('/users/me'),
        apiCall<DomainAuthority[]>('/reputation/me'),
      ]);
      set({ profile, reputation, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  addAgent: (agent) => {
    const profile = get().profile;
    if (profile) {
      set({
        profile: {
          ...profile,
          delegated_agents: [...profile.delegated_agents, agent],
        },
      });
    }
  },

  removeAgent: (agentId) => {
    const profile = get().profile;
    if (profile) {
      set({
        profile: {
          ...profile,
          delegated_agents: profile.delegated_agents.map((a) =>
            a.id === agentId ? { ...a, status: 'Suspended' } : a
          ),
        },
      });
    }
  },

  clear: () => set({ profile: null, reputation: [], loading: false }),
}));

// ---------- UI Store ----------

interface UIState {
  isAgentView: boolean;
  toggleAgentView: () => void;
}

export const useUIStore = create<UIState>((set) => ({
  isAgentView: false,
  toggleAgentView: () => set((s) => ({ isAgentView: !s.isAgentView })),
}));
