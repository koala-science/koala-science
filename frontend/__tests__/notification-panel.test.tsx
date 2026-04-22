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
  comment_id: string | null;
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
    comment_id: null,
    summary: partial.summary ?? 'a summary',
    payload: null,
    is_read: partial.is_read ?? false,
    created_at: partial.created_at ?? '2026-04-22T10:00:00Z',
    ...partial,
  };
}

describe('NotificationPanel grouping', () => {
  beforeEach(() => {
    useNotificationStore.setState({
      notifications: [],
      unreadCount: 0,
      loading: false,
      pollInterval: null,
    } as any);
  });

  it('groups 3 unread COMMENT_ON_PAPER on the same paper into one row with count and actor names', () => {
    seedNotifications([
      makeNotification({
        id: 'n1',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-x',
        paper_title: 'Paper X',
        actor_name: 'alice',
        created_at: '2026-04-22T10:00:00Z',
      }),
      makeNotification({
        id: 'n2',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-x',
        paper_title: 'Paper X',
        actor_name: 'bob',
        created_at: '2026-04-22T10:01:00Z',
      }),
      makeNotification({
        id: 'n3',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-x',
        paper_title: 'Paper X',
        actor_name: 'carol',
        created_at: '2026-04-22T10:02:00Z',
      }),
    ]);

    render(<NotificationPanel />);

    const groups = screen.getAllByTestId('notification-row');
    expect(groups).toHaveLength(1);
    expect(groups[0]).toHaveTextContent('3 new comments');
    expect(groups[0]).toHaveTextContent('alice');
    expect(groups[0]).toHaveTextContent('bob');
    expect(groups[0]).toHaveTextContent('carol');
  });

  it('renders three separate groups for mixed types/papers in chronological order', () => {
    seedNotifications([
      makeNotification({
        id: 'n1',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-x',
        actor_name: 'alice',
        created_at: '2026-04-22T10:00:00Z',
      }),
      makeNotification({
        id: 'n2',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-x',
        actor_name: 'bob',
        created_at: '2026-04-22T10:01:00Z',
      }),
      makeNotification({
        id: 'n3',
        notification_type: 'REPLY',
        paper_id: 'paper-x',
        comment_id: 'c-reply',
        actor_name: 'dana',
        summary: 'dana replied to your comment',
        created_at: '2026-04-22T10:02:00Z',
      }),
      makeNotification({
        id: 'n4',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-y',
        actor_name: 'erin',
        summary: 'erin commented on Paper Y',
        created_at: '2026-04-22T10:03:00Z',
      }),
    ]);

    render(<NotificationPanel />);

    const groups = screen.getAllByTestId('notification-row');
    expect(groups).toHaveLength(3);
    expect(groups[0]).toHaveTextContent('2 new comments');
    expect(groups[1]).toHaveTextContent('dana');
    expect(groups[2]).toHaveTextContent('erin');
  });

  it('does not group read notifications', () => {
    seedNotifications([
      makeNotification({
        id: 'n1',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-x',
        actor_name: 'alice',
        is_read: true,
        created_at: '2026-04-22T10:00:00Z',
      }),
      makeNotification({
        id: 'n2',
        notification_type: 'COMMENT_ON_PAPER',
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

  it('links a grouped COMMENT_ON_PAPER to /p/{paper_id} (no comment anchor)', () => {
    seedNotifications([
      makeNotification({
        id: 'n1',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-x',
        comment_id: 'c-1',
        actor_name: 'alice',
        created_at: '2026-04-22T10:00:00Z',
      }),
      makeNotification({
        id: 'n2',
        notification_type: 'COMMENT_ON_PAPER',
        paper_id: 'paper-x',
        comment_id: 'c-2',
        actor_name: 'bob',
        created_at: '2026-04-22T10:01:00Z',
      }),
    ]);

    render(<NotificationPanel />);

    const link = screen.getByTestId('notification-row').closest('a');
    expect(link).toHaveAttribute('href', '/p/paper-x');
  });

  it('links a REPLY to /p/{paper_id}#comment-{comment_id}', () => {
    seedNotifications([
      makeNotification({
        id: 'n1',
        notification_type: 'REPLY',
        paper_id: 'paper-x',
        comment_id: 'c-reply-1',
        actor_name: 'dana',
        created_at: '2026-04-22T10:02:00Z',
      }),
    ]);

    render(<NotificationPanel />);

    const link = screen.getByTestId('notification-row').closest('a');
    expect(link).toHaveAttribute('href', '/p/paper-x#comment-c-reply-1');
  });
});
