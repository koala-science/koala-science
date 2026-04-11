"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Bell, MessageSquare, ThumbsUp, ThumbsDown, FileText, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNotificationStore } from "@/lib/store";
import { timeAgo } from "@/lib/utils";

const TYPE_CONFIG: Record<string, { icon: typeof Bell; label: string }> = {
  REPLY: { icon: MessageSquare, label: "Reply" },
  COMMENT_ON_PAPER: { icon: MessageSquare, label: "Comment" },
  VOTE_ON_PAPER: { icon: ThumbsUp, label: "Vote" },
  VOTE_ON_COMMENT: { icon: ThumbsUp, label: "Vote" },
  PAPER_IN_DOMAIN: { icon: FileText, label: "New paper" },
};

function getNotificationIcon(type: string, payload: Record<string, unknown> | null) {
  if ((type === "VOTE_ON_PAPER" || type === "VOTE_ON_COMMENT") && payload?.vote_value === -1) {
    return ThumbsDown;
  }
  return TYPE_CONFIG[type]?.icon || Bell;
}

function getNotificationHref(n: { notification_type: string; paper_id: string | null; comment_id: string | null }): string | null {
  if (n.paper_id) {
    return `/paper/${n.paper_id}`;
  }
  return null;
}

export function NotificationPanel() {
  const notifications = useNotificationStore((s) => s.notifications);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const loading = useNotificationStore((s) => s.loading);
  const fetchNotifications = useNotificationStore((s) => s.fetchNotifications);
  const markAsRead = useNotificationStore((s) => s.markAsRead);

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Bell className="h-4 w-4" />
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
            <p className="text-xs mt-1">Activity on your papers and comments will appear here</p>
          </div>
        ) : (
          <ul className="divide-y">
            {notifications.map((n) => {
              const Icon = getNotificationIcon(n.notification_type, n.payload);
              const href = getNotificationHref(n);
              const content = (
                <div
                  className={`flex gap-3 px-4 py-3 transition-colors hover:bg-muted/50 ${!n.is_read ? 'bg-primary/5' : ''}`}
                >
                  <div className={`mt-0.5 flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center ${!n.is_read ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}`}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm leading-snug ${!n.is_read ? 'font-medium' : 'text-muted-foreground'}`}>
                      {n.summary}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {timeAgo(n.created_at)}
                    </p>
                  </div>
                  {!n.is_read && (
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
              );

              return (
                <li key={n.id}>
                  {href ? (
                    <Link href={href}>{content}</Link>
                  ) : (
                    content
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
