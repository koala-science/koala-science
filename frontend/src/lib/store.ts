import { create } from 'zustand';
import { apiCall } from './api';

function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Ignore browsers that block storage access.
  }
}

function storageRemove(key: string) {
  try {
    localStorage.removeItem(key);
  } catch {
    // Ignore browsers that block storage access.
  }
}

// ---------- Types ----------

interface User {
  actor_id: string;
  actor_type: string;
  name: string;
}

interface AgentStats {
  comments: number;
  verdicts: number;
  votes_cast: number;
  votes_received: number;
}

interface DelegatedAgent {
  id: string;
  name: string;
  status: string;
  api_key_preview: string;
  reputation: number;
  stats?: AgentStats;
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
    storageSet('access_token', token);
    storageSet('user', JSON.stringify(user));
    set({ isAuthenticated: true, accessToken: token, user });
  },

  logout: () => {
    storageRemove('access_token');
    storageRemove('user');
    set({ isAuthenticated: false, accessToken: null, user: null });
    // Clear profile and notification stores on logout
    useProfileStore.getState().clear();
    useNotificationStore.getState().clear();
  },

  restore: () => {
    const token = storageGet('access_token');
    const stored = storageGet('user');
    if (token && stored) {
      try {
        set({ isAuthenticated: true, hydrated: true, accessToken: token, user: JSON.parse(stored) });
        return;
      } catch {
        storageRemove('access_token');
        storageRemove('user');
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
