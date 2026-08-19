import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import React from 'react';

import { NotificationPanel } from '../src/components/notifications/notification-panel';
import { useNotificationStore } from '../src/lib/store';

type StoredNotification = {
  id: string;
  recipient_id: string;
  notification_type: string;
  actor_id: string;
  actor_name: string | null;
  paper_id: string | null;
  paper_title: string | null;
  argument_id: string | null;
  summary: string;
  payload: null;
  is_read: boolean;
  created_at: string;
};

function seedNotifications(notifications: StoredNotification[], unreadCount = notifications.filter((n) => !n.is_read).length) {
  useNotificationStore.setState({
    notifications,
    unreadCount,
    loading: false,
    pollInterval: null,
    fetchUnreadCount: async () => {},
    fetchNotifications: async () => {},
    markAsRead: async () => {},
    startPolling: () => {},
    stopPolling: () => {},
    clear: () => {},
  } as any);
}

function makeNotification(partial: Partial<StoredNotification> & { id: string; notification_type: string; paper_id: string | null }): StoredNotification {
  return {
    recipient_id: 'r1',
    actor_id: `actor-${partial.id}`,
    actor_name: partial.actor_name ?? 'someone',
    paper_title: 'Some paper',
    argument_id: null,
    summary: partial.summary ?? 'a summary',
    payload: null,
    is_read: partial.is_read ?? false,
    created_at: partial.created_at ?? '2026-04-22T10:00:00Z',
    ...partial,
  };
}

describe('NotificationPanel', () => {
  beforeEach(() => {
    useNotificationStore.setState({
      notifications: [],
      unreadCount: 0,
      loading: false,
      pollInterval: null,
    } as any);
  });

  it('does not group read notifications', () => {
    seedNotifications([
      makeNotification({
        id: 'n1',
        notification_type: 'PAPER_IN_DOMAIN',
        paper_id: 'paper-x',
        actor_name: 'alice',
        is_read: true,
        created_at: '2026-04-22T10:00:00Z',
      }),
      makeNotification({
        id: 'n2',
        notification_type: 'PAPER_IN_DOMAIN',
        paper_id: 'paper-x',
        actor_name: 'bob',
        is_read: true,
        created_at: '2026-04-22T10:01:00Z',
      }),
    ]);

    render(<NotificationPanel />);

    const groups = screen.getAllByTestId('notification-row');
    expect(groups).toHaveLength(2);
  });

});
