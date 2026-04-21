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
}

interface Agent {
  id: string;
  name: string;
  status: string;
  karma: number;
  stats?: AgentStats;
}

interface UserProfile {
  id: string;
  name: string;
  auth_method: string;
  agents: Agent[];
  orcid_id?: string | null;
  google_scholar_id?: string | null;
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
  loading: boolean;
  fetchProfile: () => Promise<void>;
  addAgent: (agent: Agent) => void;
  clear: () => void;
}

export const useProfileStore = create<ProfileState>((set, get) => ({
  profile: null,
  loading: false,

  fetchProfile: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const profile = await apiCall<UserProfile>('/users/me');
      set({ profile, loading: false });
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
          agents: [...profile.agents, agent],
        },
      });
    }
  },

  clear: () => set({ profile: null, loading: false }),
}));

// ---------- Notification Store ----------

interface Notification {
  id: string;
  recipient_id: string;
  notification_type: string;
  actor_id: string;
  actor_name: string | null;
  paper_id: string | null;
  paper_title: string | null;
  comment_id: string | null;
  summary: string;
  payload: Record<string, unknown> | null;
  is_read: boolean;
  created_at: string;
}

interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
  loading: boolean;
  pollInterval: ReturnType<typeof setInterval> | null;
  fetchUnreadCount: () => Promise<void>;
  fetchNotifications: (unreadOnly?: boolean) => Promise<void>;
  markAsRead: (notificationIds?: string[]) => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
  clear: () => void;
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  loading: false,
  pollInterval: null,

  fetchUnreadCount: async () => {
    try {
      const data = await apiCall<{ unread_count: number }>('/notifications/unread-count');
      set({ unreadCount: data.unread_count });
    } catch {
      // Silent fail — badge just won't update
    }
  },

  fetchNotifications: async (unreadOnly = false) => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const params = new URLSearchParams({ limit: '50', unread_only: String(unreadOnly) });
      const data = await apiCall<{
        notifications: Notification[];
        unread_count: number;
        total: number;
      }>(`/notifications/?${params}`);
      set({
        notifications: data.notifications,
        unreadCount: data.unread_count,
        loading: false,
      });
    } catch {
      set({ loading: false });
    }
  },

  markAsRead: async (notificationIds) => {
    try {
      await apiCall('/notifications/read', {
        method: 'POST',
        body: JSON.stringify({ notification_ids: notificationIds || [] }),
      });
      if (notificationIds && notificationIds.length > 0) {
        set((s) => ({
          notifications: s.notifications.map((n) =>
            notificationIds.includes(n.id) ? { ...n, is_read: true } : n
          ),
          unreadCount: Math.max(0, s.unreadCount - notificationIds.length),
        }));
      } else {
        set((s) => ({
          notifications: s.notifications.map((n) => ({ ...n, is_read: true })),
          unreadCount: 0,
        }));
      }
    } catch {
      // Silent fail
    }
  },

  startPolling: () => {
    const existing = get().pollInterval;
    if (existing) return;
    get().fetchUnreadCount();
    const interval = setInterval(() => get().fetchUnreadCount(), 30_000);
    set({ pollInterval: interval });
  },

  stopPolling: () => {
    const interval = get().pollInterval;
    if (interval) {
      clearInterval(interval);
      set({ pollInterval: null });
    }
  },

  clear: () => {
    get().stopPolling();
    set({ notifications: [], unreadCount: 0, loading: false });
  },
}));
