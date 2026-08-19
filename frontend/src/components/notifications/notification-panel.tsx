"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Bell, FileText, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNotificationStore } from "@/lib/store";
import { timeAgo } from "@/lib/utils";

const TYPE_ICON: Record<string, typeof Bell> = {
  PAPER_IN_DOMAIN: FileText,
};

type StoreNotification = {
  id: string;
  recipient_id: string;
  notification_type: string;
  actor_id: string;
  actor_name: string | null;
  paper_id: string | null;
  paper_title: string | null;
  argument_id: string | null;
  summary: string;
  payload: Record<string, unknown> | null;
  is_read: boolean;
  created_at: string;
};

export function NotificationPanel() {
  const notifications = useNotificationStore((s) => s.notifications);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const loading = useNotificationStore((s) => s.loading);
  const fetchNotifications = useNotificationStore((s) => s.fetchNotifications);
  const markAsRead = useNotificationStore((s) => s.markAsRead);

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  const rows = notifications as StoreNotification[];

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between mb-4 border-b pb-2">
        <h2 className="text-2xl font-semibold flex items-center gap-2">
          Notifications
          {unreadCount > 0 && (
            <span className="inline-flex items-center justify-center bg-primary text-primary-foreground text-[10px] font-bold rounded-full min-w-[18px] h-[18px] px-1">
              {unreadCount}
            </span>
          )}
        </h2>
        {unreadCount > 0 && (
          <Button
            variant="ghost"
            size="xs"
            onClick={() => markAsRead()}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            <Check className="h-3 w-3 mr-1" />
            Mark all read
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && notifications.length === 0 ? (
          <div className="p-4 space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="animate-pulse flex gap-3">
                <div className="h-8 w-8 rounded-full bg-muted" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 bg-muted rounded w-3/4" />
                  <div className="h-3 bg-muted rounded w-1/2" />
                </div>
              </div>
            ))}
          </div>
        ) : notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-muted-foreground text-sm">
            <Bell className="h-8 w-8 mb-2 opacity-30" />
            <p>No notifications yet</p>
            <p className="text-xs mt-1">Activity on your papers will appear here</p>
          </div>
        ) : (
          <ul className="divide-y">
            {rows.map((n) => {
              const Icon = TYPE_ICON[n.notification_type] ?? Bell;
              const unread = !n.is_read;

              return (
                <li key={n.id}>
                  <Link href={`/p/${n.paper_id}`}>
                    <div
                      data-testid="notification-row"
                      className={`flex gap-3 px-4 py-3 transition-colors hover:bg-muted/50 ${unread ? 'bg-primary/5' : ''}`}
                    >
                      <div className={`mt-0.5 flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center ${unread ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}`}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm leading-snug ${unread ? 'font-medium' : 'text-muted-foreground'}`}>
                          {n.summary}
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {timeAgo(n.created_at)}
                        </p>
                      </div>
                      {unread && (
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            markAsRead([n.id]);
                          }}
                          className="flex-shrink-0 mt-1 text-muted-foreground hover:text-foreground"
                          title="Mark as read"
                        >
                          <Check className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
