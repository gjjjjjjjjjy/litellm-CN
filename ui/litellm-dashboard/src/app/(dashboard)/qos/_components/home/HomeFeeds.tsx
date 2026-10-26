"use client";

import React from "react";
import {
  Activity,
  CircleCheck,
  ExternalLink,
  FlaskConical,
  Megaphone,
  Newspaper,
  PackagePlus,
  Plus,
  ServerCrash,
  Trash2,
} from "lucide-react";

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
import { Logo } from "@/components/molecules/logo/Logo";
import type { QosActivityEvent } from "@/app/(dashboard)/hooks/qos/useQosHome";
import { activityLine, newsLogoProvider, relativeTimeLabel, type ActivityTone } from "./homeData";

const FeedPanel = ({
  icon: Icon,
  title,
  action,
  className,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) => (
  <section
    className={cn(
      "flex max-h-72 min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-xs lg:max-h-none",
      className,
    )}
  >
    <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b px-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Icon className="size-4 text-muted-foreground" />
        {title}
      </h3>
      {action}
    </header>
    {children !== null && (
      <div
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3"
        role="region"
        aria-label={title}
        tabIndex={0}
      >
        {children}
      </div>
    )}
  </section>
);

const EmptyLine = ({ text }: { text: string }) => (
  <p className="py-3 text-center text-xs text-muted-foreground">{text}</p>
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
  const empty = announcements === undefined || announcements.length === 0;

  return (
    <>
      <FeedPanel
        icon={Megaphone}
        title="Announcements"
        className="max-h-40 lg:max-h-32"
        action={
          <div className="flex items-center gap-2">
            {empty && <span className="text-xs text-muted-foreground">No announcements</span>}
            {canManage && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs text-primary"
                onClick={() => setPosting(true)}
              >
                <Plus className="size-3.5" />
                Post
              </Button>
            )}
          </div>
        }
      >
        {empty ? null : (
          <ul className="flex flex-col gap-3">
            {announcements.map((announcement) => (
              <li key={announcement.id} className="rounded-lg border border-primary/10 bg-primary/5 p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 break-words text-sm font-medium">{announcement.title}</p>
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
                  <p className="mt-1 text-xs leading-relaxed whitespace-pre-line break-words text-muted-foreground">
                    {announcement.body}
                  </p>
                )}
                <p className="mt-2 break-words text-[11px] text-muted-foreground">
                  {`${announcement.author} · ${relativeTimeLabel(announcement.created_at, now)}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </FeedPanel>
      <PostAnnouncementDialog accessToken={accessToken} open={posting} onOpenChange={setPosting} />
    </>
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
            <li
              key={item.link}
              className="flex gap-2.5 py-2.5 first:pt-0 last:pb-0 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-500"
            >
              <Logo
                provider={newsLogoProvider(item.source)}
                label={item.source}
                className="mt-0.5 size-4 shrink-0 rounded-sm"
              />
              <div className="min-w-0 flex-1">
                <a
                  href={item.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-start gap-1.5 text-xs leading-relaxed font-medium transition-colors hover:text-primary"
                >
                  <span className="line-clamp-2 break-words">{item.title}</span>
                  <ExternalLink className="mt-0.5 size-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-hover:text-primary" />
                </a>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {item.published_at === null
                    ? item.source
                    : `${item.source} · ${relativeTimeLabel(item.published_at, now)}`}
                </p>
              </div>
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

const TONE_BADGE: Readonly<Record<ActivityTone, string>> = {
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  error: "bg-destructive/10 text-destructive",
  info: "bg-primary/10 text-primary",
};

const ACTIVITY_ICON: Readonly<Record<QosActivityEvent["kind"], typeof Activity>> = {
  node_down: ServerCrash,
  node_recovered: CircleCheck,
  benchmark: FlaskConical,
  model_added: PackagePlus,
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
        <ol className="flex flex-col gap-3">
          {activity.events.map((event, index) => {
            const line = activityLine(event);
            const Icon = ACTIVITY_ICON[event.kind];
            return (
              <li
                key={`${event.kind}-${event.at}-${index}`}
                className="flex gap-2.5 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-right-2 motion-safe:duration-500"
              >
                <span
                  className={cn("flex size-6 shrink-0 items-center justify-center rounded-lg", TONE_BADGE[line.tone])}
                >
                  <Icon className="size-3.5" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="break-words text-xs leading-relaxed font-medium">{line.title}</p>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground" title={line.description}>
                    {`${relativeTimeLabel(event.at, now)} · ${line.description}`}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </FeedPanel>
  );
};
