"use client";

import React from "react";
import { Activity, ExternalLink, Megaphone, Newspaper, Plus, Trash2 } from "lucide-react";

import {
  useDeleteAnnouncement,
  usePostAnnouncement,
  useQosActivity,
  useQosAnnouncements,
  useQosNews,
} from "@/app/(dashboard)/hooks/qos/useQosHome";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/cva.config";
import { extractErrorMessage } from "@/utils/errorUtils";
import { activityLine, relativeTimeLabel, type ActivityTone } from "./homeData";

const FeedPanel = ({
  icon: Icon,
  title,
  action,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) => (
  <section className="flex min-h-0 flex-col rounded-xl border bg-card shadow-xs">
    <header className="flex items-center justify-between gap-2 px-4 pt-4 pb-2">
      <h3 className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <Icon className="size-4" />
        {title}
      </h3>
      {action}
    </header>
    <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{children}</div>
  </section>
);

const EmptyLine = ({ text }: { text: string }) => (
  <p className="py-6 text-center text-sm text-muted-foreground">{text}</p>
);

const PostAnnouncementDialog = ({
  accessToken,
  open,
  onOpenChange,
}: {
  accessToken: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const [title, setTitle] = React.useState("");
  const [body, setBody] = React.useState("");
  const post = usePostAnnouncement(accessToken);

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    post.mutate(
      { title, body },
      {
        onSuccess: () => {
          setTitle("");
          setBody("");
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Post an announcement</DialogTitle>
            <DialogDescription>Everyone sees it at the top of the home dashboard.</DialogDescription>
          </DialogHeader>
          <label htmlFor="announcement-title" className="flex flex-col gap-1.5 text-sm font-medium">
            Title
            <Input
              id="announcement-title"
              value={title}
              maxLength={120}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label htmlFor="announcement-body" className="flex flex-col gap-1.5 text-sm font-medium">
            Details
            <Textarea
              id="announcement-body"
              value={body}
              maxLength={2000}
              rows={4}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          {post.error !== null && (
            <Alert variant="destructive">
              <AlertDescription>{extractErrorMessage(post.error)}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={title.trim() === "" || post.isPending}>
              Post
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export const AnnouncementsPanel = ({
  accessToken,
  canManage,
  now,
}: {
  accessToken: string | null;
  canManage: boolean;
  now: Date;
}) => {
  const announcements = useQosAnnouncements(accessToken).data;
  const remove = useDeleteAnnouncement(accessToken);
  const [posting, setPosting] = React.useState(false);

  return (
    <FeedPanel
      icon={Megaphone}
      title="Announcements"
      action={
        canManage && (
          <Button size="sm" variant="outline" onClick={() => setPosting(true)}>
            <Plus className="size-4" />
            Post
          </Button>
        )
      }
    >
      {announcements === undefined || announcements.length === 0 ? (
        <EmptyLine text="No announcements" />
      ) : (
        <ul className="flex flex-col gap-3">
          {announcements.map((announcement) => (
            <li key={announcement.id} className="rounded-lg border border-primary/30 bg-primary/10 p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium">{announcement.title}</p>
                {canManage && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-6 shrink-0 text-muted-foreground hover:text-destructive"
                    aria-label="Delete announcement"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(announcement.id)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                )}
              </div>
              {announcement.body !== "" && (
                <p className="mt-1 text-sm whitespace-pre-line text-muted-foreground">{announcement.body}</p>
              )}
              <p className="mt-2 text-xs text-muted-foreground">
                {`${announcement.author} · ${relativeTimeLabel(announcement.created_at, now)}`}
              </p>
            </li>
          ))}
        </ul>
      )}
      <PostAnnouncementDialog accessToken={accessToken} open={posting} onOpenChange={setPosting} />
    </FeedPanel>
  );
};

export const NewsPanel = ({ accessToken, now }: { accessToken: string | null; now: Date }) => {
  const news = useQosNews(accessToken).data;
  const failed = news === undefined ? [] : news.sources.filter((source) => source.error !== null);

  return (
    <FeedPanel icon={Newspaper} title="AI news">
      {news === undefined || news.items.length === 0 ? (
        <EmptyLine text="No news yet" />
      ) : (
        <ul className="flex flex-col divide-y divide-border/60">
          {news.items.map((item) => (
            <li key={item.link} className="py-2.5">
              <a
                href={item.link}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex items-start gap-1.5 text-sm font-medium hover:text-primary"
              >
                <span className="line-clamp-2">{item.title}</span>
                <ExternalLink className="mt-0.5 size-3 shrink-0 opacity-0 group-hover:opacity-100" />
              </a>
              <p className="mt-1 text-xs text-muted-foreground">
                {item.published_at === null
                  ? item.source
                  : `${item.source} · ${relativeTimeLabel(item.published_at, now)}`}
              </p>
            </li>
          ))}
        </ul>
      )}
      {failed.length > 0 && (
        <p
          className="mt-2 text-xs text-warning"
          title={failed.map((source) => `${source.name}: ${source.error}`).join("\n")}
        >
          {`Could not reach ${failed.map((source) => source.name).join(", ")}`}
        </p>
      )}
    </FeedPanel>
  );
};

const TONE_DOT: Readonly<Record<ActivityTone, string>> = {
  success: "bg-success",
  warning: "bg-warning",
  error: "bg-destructive",
  info: "bg-primary",
};

export const ActivityPanel = ({
  accessToken,
  refreshMs,
  now,
}: {
  accessToken: string | null;
  refreshMs: number | false;
  now: Date;
}) => {
  const activity = useQosActivity(accessToken, refreshMs).data;

  return (
    <FeedPanel icon={Activity} title="Activity">
      {activity === undefined || activity.events.length === 0 ? (
        <EmptyLine text="Nothing happened in the last 7 days" />
      ) : (
        <ol className="relative flex flex-col gap-3 border-l border-border/60 pl-4">
          {activity.events.map((event, index) => {
            const line = activityLine(event);
            return (
              <li key={`${event.kind}-${event.at}-${index}`} className="relative">
                <span className={cn("absolute top-1.5 -left-[21px] size-2.5 rounded-full", TONE_DOT[line.tone])} />
                <p className="text-sm">{line.title}</p>
                <p className="truncate text-xs text-muted-foreground" title={line.description}>
                  {`${relativeTimeLabel(event.at, now)} · ${line.description}`}
                </p>
              </li>
            );
          })}
        </ol>
      )}
    </FeedPanel>
  );
};
